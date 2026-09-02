#include "work_transfer/transfer.hpp"

#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <stop_token>
#include <string>

#include <unistd.h>

namespace {

void require(bool condition, std::string_view message) {
    if (!condition) {
        throw std::runtime_error(std::string(message));
    }
}

class TemporaryDirectory {
  public:
    TemporaryDirectory() {
        std::string pattern = "/tmp/work-transfer-test-XXXXXX";
        pattern.push_back('\0');
        const char* created = ::mkdtemp(pattern.data());
        require(created != nullptr, "unable to create temporary directory");
        path_ = created;
    }

    ~TemporaryDirectory() {
        std::error_code ignored;
        std::filesystem::remove_all(path_, ignored);
    }

    [[nodiscard]] const std::filesystem::path& path() const { return path_; }

  private:
    std::filesystem::path path_;
};

void write_file(const std::filesystem::path& path, std::string_view value) {
    std::ofstream stream(path, std::ios::binary);
    stream << value;
    require(stream.good(), "unable to write test file");
}

void test_progress_parser_reports_bytes_rate_and_eta() {
    constexpr std::uint64_t total = 2U * 1024U * 1024U;
    const auto progress = work_transfer::detail::parse_scp_progress_line(
        "update package.bin        50% 1024KB   2.0MB/s   00:03 ETA",
        "update package.bin", total);

    require(progress.has_value(), "valid progress record was rejected");
    require(progress->filename == "update package.bin", "filename changed");
    require(progress->transferred_bytes == 1024U * 1024U,
            "transferred byte count was parsed incorrectly");
    require(progress->total_bytes == total, "total byte count changed");
    require(std::abs(progress->percent - 50.0) < 0.001,
            "percentage was parsed incorrectly");
    require(progress->bytes_per_second.has_value(), "rate was not parsed");
    require(std::abs(*progress->bytes_per_second - 2.0 * 1024.0 * 1024.0) <
                0.001,
            "rate was parsed incorrectly");
    require(progress->eta_seconds == 3.0, "ETA was parsed incorrectly");

    const auto long_eta = work_transfer::detail::parse_scp_progress_line(
        "update.bin 25% 512KB 1.0KB/s 01:02:03 ETA", "update.bin", total);
    require(long_eta.has_value() && long_eta->eta_seconds == 3723.0,
            "hour-scale ETA was parsed incorrectly");
}

void test_progress_parser_rejects_malformed_and_oversized_records() {
    require(!work_transfer::detail::parse_scp_progress_line("not progress", "x", 1)
                 .has_value(),
            "malformed progress was accepted");
    require(!work_transfer::detail::parse_scp_progress_line(std::string(9000, 'x'),
                                                            "x", 1)
                 .has_value(),
            "oversized progress was accepted");
}

void test_remote_shell_quoting_contains_hostile_text_in_one_token() {
    const auto quoted = work_transfer::detail::quote_posix_shell_token(
        "report;$(touch PWN)' data.bin");
    require(quoted == "'report;$(touch PWN)'\\'' data.bin'",
            "remote shell token was not safely quoted");
}

void test_connection_validation_happens_before_process_launch() {
    TemporaryDirectory directory;
    const auto identity = directory.path() / "identity";
    const auto known_hosts = directory.path() / "known_hosts";
    write_file(identity, "key");
    write_file(known_hosts, "host key");

    work_transfer::ScpTransport transport;
    const work_transfer::ConnectionConfig config{
        .host = "-oProxyCommand=touch PWN",
        .username = "transfer",
        .identity_file = identity,
        .known_hosts = known_hosts,
        .port = 22,
    };

    const auto result = transport.test_connection(config);
    require(!result.success, "host option injection was accepted");
    require(result.message == "invalid_host", "wrong host validation error");
    require(result.error_kind == work_transfer::TransferErrorKind::connection,
            "wrong host validation category");
}

void test_transfer_rejects_remote_control_characters() {
    TemporaryDirectory directory;
    const auto source = directory.path() / "update.bin";
    const auto identity = directory.path() / "identity";
    const auto known_hosts = directory.path() / "known_hosts";
    write_file(source, "payload");
    write_file(identity, "key");
    write_file(known_hosts, "host key");

    work_transfer::ScpTransport transport;
    const work_transfer::ConnectionConfig config{
        .host = "192.0.2.2",
        .username = "transfer",
        .identity_file = identity,
        .known_hosts = known_hosts,
        .port = 22,
    };
    const auto result = transport.transfer(
        config,
        {.source = source, .remote_directory = "/srv/incoming\nmalicious"});

    require(result.state == work_transfer::TransferState::failed,
            "remote control characters were accepted");
    require(result.message == "invalid_remote_directory",
            "wrong remote path validation error");
    require(result.error_kind == work_transfer::TransferErrorKind::file,
            "wrong remote path validation category");
    require(!transport.is_active(), "rejected transfer remained active");
    require(!transport.cancel(), "inactive transfer reported cancellation");
}

void test_transfer_rejects_non_regular_source() {
    TemporaryDirectory directory;
    const auto identity = directory.path() / "identity";
    const auto known_hosts = directory.path() / "known_hosts";
    write_file(identity, "key");
    write_file(known_hosts, "host key");

    work_transfer::ScpTransport transport;
    const work_transfer::ConnectionConfig config{
        .host = "192.0.2.2",
        .username = "transfer",
        .identity_file = identity,
        .known_hosts = known_hosts,
        .port = 22,
    };
    const auto result = transport.transfer(
        config, {.source = directory.path(), .remote_directory = "/srv/incoming"});

    require(result.state == work_transfer::TransferState::failed,
            "directory source was accepted");
    require(result.message == "source_file_missing",
            "wrong source validation error");
    require(result.error_kind == work_transfer::TransferErrorKind::file,
            "wrong source validation category");
}

void test_prelaunch_cancellation_prevents_network_operations() {
    TemporaryDirectory directory;
    const auto source_path = directory.path() / "update.bin";
    const auto identity = directory.path() / "identity";
    const auto known_hosts = directory.path() / "known_hosts";
    write_file(source_path, "payload");
    write_file(identity, "key");
    write_file(known_hosts, "host key");

    work_transfer::ScpTransport transport;
    const work_transfer::ConnectionConfig config{
        .host = "192.0.2.2",
        .username = "transfer",
        .identity_file = identity,
        .known_hosts = known_hosts,
        .port = 22,
    };
    std::stop_source cancellation;
    cancellation.request_stop();

    const auto connection =
        transport.test_connection(config, cancellation.get_token());
    require(!connection.success && connection.message == "operation_cancelled",
            "prelaunch connection cancellation was lost");

    const auto transfer = transport.transfer(
        config,
        {.source = source_path, .remote_directory = "/srv/incoming"},
        cancellation.get_token());
    require(transfer.state == work_transfer::TransferState::aborted,
            "prelaunch transfer cancellation was lost");
    require(!transport.is_active(), "cancelled operation remained active");
}

}  // namespace

int main() {
    try {
        test_progress_parser_reports_bytes_rate_and_eta();
        test_progress_parser_rejects_malformed_and_oversized_records();
        test_remote_shell_quoting_contains_hostile_text_in_one_token();
        test_connection_validation_happens_before_process_launch();
        test_transfer_rejects_remote_control_characters();
        test_transfer_rejects_non_regular_source();
        test_prelaunch_cancellation_prevents_network_operations();
        return 0;
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
