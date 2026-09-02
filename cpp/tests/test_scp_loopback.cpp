#include <cstdlib>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <stdexcept>
#include <string>
#include <string_view>

#include "work_transfer/transfer.hpp"

namespace {

constexpr auto kLoopbackRoot = "/tmp/work-transfer-scp-loopback";

void require(bool condition, const std::string& message) {
  if (!condition) {
    throw std::runtime_error(message);
  }
}

std::string read_file(const std::filesystem::path& path) {
  std::ifstream stream(path, std::ios::binary);
  require(static_cast<bool>(stream), "unable to read " + path.string());
  return {std::istreambuf_iterator<char>(stream),
          std::istreambuf_iterator<char>()};
}

void write_file(const std::filesystem::path& path, std::string_view contents) {
  std::ofstream stream(path, std::ios::binary | std::ios::trunc);
  require(static_cast<bool>(stream), "unable to write " + path.string());
  stream << contents;
  require(static_cast<bool>(stream), "unable to write " + path.string());
}

}  // namespace

int main() {
  if (std::getenv("WORK_TRANSFER_RUN_SCP_LOOPBACK") == nullptr) {
    std::cout << "SCP loopback skipped outside the packaging environment\n";
    return 0;
  }

  try {
    const std::filesystem::path root(kLoopbackRoot);
    const std::filesystem::path source = root / "source.bin";
    const std::filesystem::path approved = root / "approved.bin";
    const std::filesystem::path received =
        root / "received path;safe" / "source.bin";
    const std::filesystem::path symlink_source = root / "symlink-source.bin";
    const std::filesystem::path symlink_target = root / "private-target.bin";
    const std::filesystem::path symlink_received =
        root / "received path;safe" / "symlink-source.bin";
    const std::filesystem::path mutable_source = root / "mutable-source.bin";
    const std::filesystem::path mutable_received =
        root / "received path;safe" / "mutable-source.bin";
    work_transfer::ConnectionConfig connection{
        .host = "127.0.0.1",
        .username = "work-transfer-e2e",
        .identity_file = root / "client_key",
        .known_hosts = root / "known_hosts",
        .port = 2222,
    };

    work_transfer::ScpTransport transport;
    const auto connection_result = transport.test_connection(connection);
    require(connection_result.success,
            "connection test failed: " + connection_result.message);

    constexpr std::string_view approved_mutable_payload =
        "approved bytes before in-place mutation\n";
    write_file(mutable_source, approved_mutable_payload);
    auto prepared_mutable = transport.prepare_source(mutable_source);
    require(prepared_mutable != nullptr,
            "Start-boundary source preparation rejected a regular file");
    bool source_was_mutated = false;
    const auto mutable_result = transport.transfer(
        connection, prepared_mutable,
        root.string() + "/received path;safe",
        [&](const work_transfer::TransferProgress& progress) {
          if (!source_was_mutated && progress.transferred_bytes == 0) {
            write_file(mutable_source, "unapproved same-inode replacement\n");
            source_was_mutated = true;
          }
        });
    require(mutable_result.success(),
            "snapshot transfer failed: " + mutable_result.message);
    require(source_was_mutated,
            "SCP did not emit its initial snapshot progress event");
    require(read_file(mutable_received) == approved_mutable_payload,
            "receiver observed an in-place mutation of the selected file");

    write_file(symlink_target, "private target that was not selected\n");
    std::filesystem::create_symlink(symlink_target, symlink_source);
    const auto symlink_result = transport.transfer(
        connection,
        {.source = symlink_source,
         .remote_directory = root.string() + "/received path;safe"});
    require(!symlink_result.success(),
            "transfer followed a selected symbolic link");
    require(!std::filesystem::exists(symlink_received),
            "symbolic-link target bytes reached the receiver");

    bool source_was_swapped = false;
    const auto transfer_result = transport.transfer(
        connection,
        {.source = source,
         .remote_directory = root.string() + "/received path;safe"},
        [&](const work_transfer::TransferProgress& progress) {
          if (!source_was_swapped && progress.transferred_bytes == 0) {
            std::filesystem::rename(source, approved);
            write_file(source, "unapproved replacement payload\n");
            source_was_swapped = true;
          }
        });
    require(transfer_result.success(),
            "SCP transfer failed: " + transfer_result.message);
    require(source_was_swapped,
            "SCP did not emit its initial pinned-source progress event");
    require(read_file(approved) == read_file(received),
            "received file differs from the descriptor-pinned source");
    require(read_file(source) != read_file(received),
            "SCP followed the replaced source pathname");
    std::cout << "SCP loopback passed\n";
    return 0;
  } catch (const std::exception& error) {
    std::cerr << error.what() << '\n';
    return 1;
  }
}
