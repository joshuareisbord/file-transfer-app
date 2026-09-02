#include "work_transfer/transfer.hpp"
#include "transfer_process.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <cerrno>
#include <chrono>
#include <cctype>
#include <cstdlib>
#include <fcntl.h>
#include <mutex>
#include <stdexcept>
#include <string>
#include <utility>
#include <vector>

#include <signal.h>
#include <sys/stat.h>
#include <sys/types.h>
#include <unistd.h>

namespace work_transfer {
namespace {

using Clock = std::chrono::steady_clock;
constexpr auto kStallThreshold = std::chrono::seconds(5);
constexpr auto kStallEmitInterval = std::chrono::seconds(1);
constexpr auto kMinimumProgressEmitInterval = std::chrono::milliseconds(100);
using internal::ProcessResult;
using internal::ProcessSpec;
using internal::run_process;

struct FileDescriptor {
    int value{-1};

    FileDescriptor() = default;
    explicit FileDescriptor(int descriptor) : value(descriptor) {}
    ~FileDescriptor() {
        if (value >= 0) {
            ::close(value);
        }
    }

    FileDescriptor(const FileDescriptor&) = delete;
    FileDescriptor& operator=(const FileDescriptor&) = delete;
    FileDescriptor(FileDescriptor&& other) noexcept
        : value(std::exchange(other.value, -1)) {}
    FileDescriptor& operator=(FileDescriptor&& other) noexcept {
        if (this != &other) {
            if (value >= 0) {
                ::close(value);
            }
            value = std::exchange(other.value, -1);
        }
        return *this;
    }
};

struct ValidationError {
    std::string message;
    TransferErrorKind kind;
};

[[nodiscard]] std::string trim(std::string_view value) {
    const auto first = value.find_first_not_of(" \t\r\n");
    if (first == std::string_view::npos) {
        return {};
    }
    return std::string(value.substr(first, value.find_last_not_of(" \t\r\n") -
                                               first + 1));
}

[[nodiscard]] bool has_control_or_nul(std::string_view value) {
    return std::any_of(value.begin(), value.end(), [](unsigned char character) {
        return character == 0 || character < 0x20 || character == 0x7f;
    });
}

[[nodiscard]] bool valid_host(std::string_view host) {
    if (host.empty() || host.front() == '-' || has_control_or_nul(host)) {
        return false;
    }
    return std::all_of(host.begin(), host.end(), [](unsigned char character) {
        return std::isalnum(character) != 0 || character == '.' ||
               character == '-' || character == '_' || character == ':' ||
               character == '%';
    });
}

[[nodiscard]] bool valid_username(std::string_view username) {
    if (username.empty() || username.front() == '-' ||
        has_control_or_nul(username)) {
        return false;
    }
    return std::all_of(username.begin(), username.end(),
                       [](unsigned char character) {
                           return std::isalnum(character) != 0 ||
                                  character == '.' || character == '-' ||
                                  character == '_';
                       });
}

[[nodiscard]] std::filesystem::path expand_user_path(
    const std::filesystem::path& path) {
    const auto native = path.string();
    if (native == "~" || native.rfind("~/", 0) == 0) {
        if (const char* home = std::getenv("HOME"); home != nullptr && *home != 0) {
            return std::filesystem::path(home) /
                   (native == "~" ? std::string{} : native.substr(2));
        }
    }
    return path;
}

[[nodiscard]] std::filesystem::path absolute_normalized(
    const std::filesystem::path& path) {
    std::error_code error;
    auto result = std::filesystem::absolute(expand_user_path(path), error);
    if (error) {
        return expand_user_path(path);
    }
    return result.lexically_normal();
}

[[nodiscard]] FileDescriptor open_without_symlinks(
    const std::filesystem::path& absolute_path) {
    FileDescriptor directory(
        ::open("/", O_PATH | O_DIRECTORY | O_CLOEXEC));
    if (directory.value < 0) {
        return {};
    }

    std::vector<std::filesystem::path> components;
    for (const auto& component : absolute_path.relative_path()) {
        if (component.empty() || component == "." || component == "..") {
            return {};
        }
        components.push_back(component);
    }
    if (components.empty()) {
        return {};
    }

    for (std::size_t index = 0; index < components.size(); ++index) {
        const bool final_component = index + 1 == components.size();
        const int flags = final_component
                              ? O_RDONLY | O_CLOEXEC | O_NONBLOCK | O_NOFOLLOW
                              : O_PATH | O_DIRECTORY | O_CLOEXEC | O_NOFOLLOW;
        FileDescriptor opened(::openat(directory.value,
                                       components[index].c_str(), flags));
        if (opened.value < 0) {
            return {};
        }
        directory = std::move(opened);
    }
    return directory;
}

[[nodiscard]] bool regular_file_exists(const std::filesystem::path& path) {
    std::error_code error;
    return std::filesystem::is_regular_file(path, error) && !error;
}

[[nodiscard]] std::optional<ValidationError> validate_config(
    const ConnectionConfig& config) {
    if (!valid_host(trim(config.host))) {
        return ValidationError{"invalid_host", TransferErrorKind::connection};
    }
    if (!valid_username(trim(config.username))) {
        return ValidationError{"invalid_username",
                               TransferErrorKind::authentication};
    }
    if (config.port == 0) {
        return ValidationError{"invalid_port", TransferErrorKind::connection};
    }
    const auto identity = absolute_normalized(config.identity_file);
    if (!regular_file_exists(identity)) {
        return ValidationError{"identity_file_missing",
                               TransferErrorKind::authentication};
    }
    const auto known_hosts = absolute_normalized(config.known_hosts);
    if (!regular_file_exists(known_hosts)) {
        return ValidationError{"known_hosts_missing", TransferErrorKind::host_key};
    }
    if (has_control_or_nul(identity.string()) ||
        has_control_or_nul(known_hosts.string()) ||
        identity.string().find('%') != std::string::npos ||
        known_hosts.string().find('%') != std::string::npos) {
        return ValidationError{"invalid_key_path",
                               TransferErrorKind::authentication};
    }
    return std::nullopt;
}

class ProgressStreamParser {
  public:
    ProgressStreamParser(std::string filename, std::uint64_t total,
                         const ProgressCallback& callback)
        : filename_(std::move(filename)), total_(total), callback_(callback) {
        last_progress_ = TransferProgress{
            .filename = filename_,
            .transferred_bytes = 0,
            .total_bytes = total_,
            .percent = total_ == 0 ? 100.0 : 0.0,
            .bytes_per_second = std::nullopt,
            .eta_seconds = std::nullopt,
            .is_stalled = false,
        };
    }

    void feed(std::string_view chunk) {
        for (const char character : chunk) {
            if (character == '\r' || character == '\n') {
                finish_record();
                dropping_ = false;
            } else if (!dropping_ &&
                       record_.size() < internal::kMaximumProgressRecord) {
                record_.push_back(character);
            } else {
                record_.clear();
                dropping_ = true;
            }
        }
    }

    void tick() {
        if (!last_progress_) {
            return;
        }
        const auto now = Clock::now();
        if (now - last_advanced_ < kStallThreshold ||
            now - last_stall_emit_ < kStallEmitInterval) {
            return;
        }
        auto stalled = *last_progress_;
        stalled.is_stalled = true;
        stalled.eta_seconds.reset();
        last_stall_emit_ = now;
        emit(stalled);
    }

    void finish() { finish_record(); }

  private:
    void finish_record() {
        if (!record_.empty() && !dropping_) {
            if (auto progress = detail::parse_scp_progress_line(
                    record_, filename_, total_)) {
                const auto now = Clock::now();
                const bool advanced =
                    !last_progress_ || progress->transferred_bytes >
                                           last_progress_->transferred_bytes;
                if (advanced) {
                    progress->is_stalled = false;
                    last_progress_ = *progress;
                    last_advanced_ = now;
                    const bool complete = progress->transferred_bytes >= total_;
                    if (complete || now - last_emit_ >=
                                        kMinimumProgressEmitInterval) {
                        last_emit_ = now;
                        emit(*progress);
                    }
                }
            }
        }
        record_.clear();
    }

    void emit(const TransferProgress& progress) const noexcept {
        if (!callback_) {
            return;
        }
        try {
            callback_(progress);
        } catch (...) {
            // UI callback failures cannot be allowed to strand an SCP child.
        }
    }

    std::string filename_;
    std::uint64_t total_;
    const ProgressCallback& callback_;
    std::string record_;
    bool dropping_{false};
    std::optional<TransferProgress> last_progress_;
    Clock::time_point last_advanced_{Clock::now()};
    Clock::time_point last_emit_{Clock::now() - kMinimumProgressEmitInterval};
    Clock::time_point last_stall_emit_{Clock::now() - kStallEmitInterval};
};

[[nodiscard]] std::string bracket_host(std::string_view host) {
    return host.find(':') == std::string_view::npos
               ? std::string(host)
               : "[" + std::string(host) + "]";
}

[[nodiscard]] std::string quote_ssh_config_value(std::string_view value) {
    std::string result{"\""};
    result.reserve(value.size() + 2);
    for (const char character : value) {
        if (character == '\\' || character == '"') {
            result.push_back('\\');
        }
        result.push_back(character);
    }
    result.push_back('"');
    return result;
}

[[nodiscard]] std::vector<std::string> strict_ssh_options(
    const ConnectionConfig& config) {
    const auto identity = absolute_normalized(config.identity_file).string();
    const auto known_hosts = absolute_normalized(config.known_hosts).string();
    return {
        "-F", "/dev/null",
        "-o", "BatchMode=yes",
        "-o", "PreferredAuthentications=publickey",
        "-o", "PubkeyAuthentication=yes",
        "-o", "PasswordAuthentication=no",
        "-o", "KbdInteractiveAuthentication=no",
        "-o", "ChallengeResponseAuthentication=no",
        "-o", "HostbasedAuthentication=no",
        "-o", "GSSAPIAuthentication=no",
        "-o", "IdentitiesOnly=yes",
        "-o", "IdentityAgent=none",
        "-o", "StrictHostKeyChecking=yes",
        "-o", "UserKnownHostsFile=" + quote_ssh_config_value(known_hosts),
        "-o", "GlobalKnownHostsFile=/dev/null",
        "-o", "ConnectTimeout=10",
        "-o", "ConnectionAttempts=1",
        "-o", "ServerAliveInterval=5",
        "-o", "ServerAliveCountMax=2",
        "-o", "ClearAllForwardings=yes",
        "-o", "ForwardAgent=no",
        "-o", "ForwardX11=no",
        "-o", "PermitLocalCommand=no",
        "-o", "RequestTTY=no",
        "-o", "LogLevel=ERROR",
        "-i", identity,
    };
}

[[nodiscard]] std::string normalized_remote_directory(std::string_view input) {
    std::string prefix;
    std::string_view remainder;
    if (input == "~") {
        return "~";
    }
    if (input.starts_with("~/")) {
        prefix = "~/";
        remainder = input.substr(2);
    } else if (input.starts_with('/')) {
        prefix = "/";
        remainder = input.substr(1);
    } else {
        return {};
    }

    std::vector<std::string_view> parts;
    std::size_t position = 0;
    while (position <= remainder.size()) {
        const auto end = remainder.find('/', position);
        const auto part = remainder.substr(position, end - position);
        if (!part.empty() && part != ".") {
            if (part == "..") {
                if (!parts.empty()) {
                    parts.pop_back();
                }
            } else {
                parts.push_back(part);
            }
        }
        if (end == std::string_view::npos) {
            break;
        }
        position = end + 1;
    }
    std::string result = prefix;
    for (std::size_t index = 0; index < parts.size(); ++index) {
        if (!result.ends_with('/')) {
            result.push_back('/');
        }
        result.append(parts[index]);
    }
    if (result == "~/") {
        return "~";
    }
    return result;
}

[[nodiscard]] std::string join_remote(std::string_view directory,
                                      std::string_view filename) {
    return std::string(directory) + (directory.ends_with('/') ? "" : "/") +
           std::string(filename);
}

[[nodiscard]] std::string remote_shell_path(std::string_view path) {
    if (path == "~") {
        return R"("${HOME}")";
    }
    if (path.starts_with("~/")) {
        return R"("${HOME}")" +
               detail::quote_posix_shell_token(path.substr(1));
    }
    return detail::quote_posix_shell_token(path);
}

[[nodiscard]] TransferErrorKind classify_ssh_error(std::string_view diagnostic,
                                                    bool connected) {
    if (diagnostic.find("Permission denied") != std::string_view::npos) {
        return TransferErrorKind::authentication;
    }
    if (diagnostic.find("Host key verification failed") !=
            std::string_view::npos ||
        diagnostic.find("REMOTE HOST IDENTIFICATION HAS CHANGED") !=
            std::string_view::npos ||
        diagnostic.find("host key is known") != std::string_view::npos) {
        return TransferErrorKind::host_key;
    }
    constexpr std::array<std::string_view, 7> connection_messages{
        "Could not resolve hostname", "Connection refused", "No route to host",
        "Connection timed out", "Operation timed out", "Connection reset",
        "Connection closed"};
    if (std::any_of(connection_messages.begin(), connection_messages.end(),
                    [diagnostic](std::string_view message) {
                        return diagnostic.find(message) != std::string_view::npos;
                    })) {
        return TransferErrorKind::connection;
    }
    return connected ? TransferErrorKind::file : TransferErrorKind::connection;
}

[[nodiscard]] std::string generic_failure_message(TransferErrorKind kind,
                                                  bool transfer) {
    switch (kind) {
        case TransferErrorKind::authentication:
            return "SSH authentication failed";
        case TransferErrorKind::host_key:
            return "SSH host key verification failed";
        case TransferErrorKind::connection:
            return "SSH connection failed";
        case TransferErrorKind::file:
            return transfer ? "OpenSSH file transfer failed"
                            : "OpenSSH remote operation failed";
        default:
            return "OpenSSH operation failed";
    }
}

}  // namespace

class PreparedSource::Impl {
  public:
    Impl(FileDescriptor descriptor, std::filesystem::path path,
         const struct stat& metadata)
        : descriptor(std::move(descriptor)),
          path(std::move(path)),
          metadata(metadata) {}

    FileDescriptor descriptor;
    std::filesystem::path path;
    struct stat metadata {};
};

PreparedSource::PreparedSource(std::unique_ptr<Impl> impl)
    : impl_(std::move(impl)) {}

PreparedSource::~PreparedSource() = default;

namespace {

struct SnapshotResult {
    FileDescriptor descriptor;
    bool cancelled{false};
};

[[nodiscard]] bool same_source_metadata(const struct stat& left,
                                        const struct stat& right) noexcept {
    return left.st_dev == right.st_dev && left.st_ino == right.st_ino &&
           left.st_mode == right.st_mode && left.st_size == right.st_size &&
           left.st_mtim.tv_sec == right.st_mtim.tv_sec &&
           left.st_mtim.tv_nsec == right.st_mtim.tv_nsec &&
           left.st_ctim.tv_sec == right.st_ctim.tv_sec &&
           left.st_ctim.tv_nsec == right.st_ctim.tv_nsec;
}

[[nodiscard]] SnapshotResult snapshot_source(
    int source_descriptor, const struct stat& expected,
    const std::atomic_bool& cancellation_requested) {
    struct stat before {};
    if (::fstat(source_descriptor, &before) != 0 ||
        !same_source_metadata(before, expected)) {
        return {};
    }

    std::string pattern = "/tmp/work-transfer-source-XXXXXX";
    pattern.push_back('\0');
    FileDescriptor writable(::mkstemp(pattern.data()));
    if (writable.value < 0) {
        return {};
    }
    static_cast<void>(::unlink(pattern.data()));
    if (::fcntl(writable.value, F_SETFD, FD_CLOEXEC) != 0) {
        return {};
    }

    std::array<char, 64U * 1024U> buffer{};
    off_t offset = 0;
    while (offset < expected.st_size) {
        if (cancellation_requested.load()) {
            return {.descriptor = {}, .cancelled = true};
        }
        const off_t remaining = expected.st_size - offset;
        const auto requested = static_cast<std::size_t>(
            std::min<off_t>(static_cast<off_t>(buffer.size()), remaining));
        const auto count =
            ::pread(source_descriptor, buffer.data(), requested, offset);
        if (count < 0 && errno == EINTR) {
            continue;
        }
        if (count <= 0) {
            return {};
        }
        std::size_t written = 0;
        const auto count_size = static_cast<std::size_t>(count);
        while (written < count_size) {
            const auto result = ::write(writable.value, buffer.data() + written,
                                        count_size - written);
            if (result < 0 && errno == EINTR) {
                continue;
            }
            if (result <= 0) {
                return {};
            }
            written += static_cast<std::size_t>(result);
        }
        offset += count;
    }

    struct stat after {};
    if (::fstat(source_descriptor, &after) != 0 ||
        !same_source_metadata(after, expected) ||
        ::fchmod(writable.value, S_IRUSR) != 0) {
        return {};
    }
    const std::string descriptor_path =
        "/proc/self/fd/" + std::to_string(writable.value);
    FileDescriptor readonly(
        ::open(descriptor_path.c_str(), O_RDONLY | O_CLOEXEC));
    if (readonly.value < 0) {
        return {};
    }
    writable = FileDescriptor{};
    return {.descriptor = std::move(readonly), .cancelled = false};
}

}  // namespace

class ScpTransport::Impl {
  public:
    [[nodiscard]] ConnectionTestResult test_connection(
        const ConnectionConfig& original_config, std::stop_token stop) {
        std::unique_lock operation(operation_mutex_, std::try_to_lock);
        if (!operation.owns_lock()) {
            return {false, "transfer_active", TransferErrorKind::unknown};
        }
        if (stop.stop_requested()) {
            return {false, "operation_cancelled", TransferErrorKind::none};
        }
        if (const auto error = validate_config(original_config)) {
            return {false, error->message, error->kind};
        }
        cancellation_requested_.store(false);
        operation_active_.store(true);
        struct OperationGuard {
            std::atomic_bool& active;
            ~OperationGuard() { active.store(false); }
        } operation_guard{operation_active_};
        if (stop.stop_requested()) {
            cancellation_requested_.store(true);
            return {false, "operation_cancelled", TransferErrorKind::none};
        }
        const auto config = normalized_config(original_config);
        auto arguments = strict_ssh_options(config);
        arguments.insert(arguments.end(), {"-p", std::to_string(config.port),
                                           "--", ssh_target(config), "true"});
        const auto process = run_process(
            {.executable = "/usr/bin/ssh",
             .arguments = std::move(arguments),
             .use_pty = false,
             .cancellable = true,
             .inherited_source = -1,
             .timeout = std::chrono::seconds(15)},
            active_process_, &cancellation_requested_);
        if (process.cancelled) {
            return {false, "operation_cancelled", TransferErrorKind::none};
        }
        if (process.exit_code == 0) {
            return {true, {}, TransferErrorKind::none};
        }
        const auto kind = classify_ssh_error(process.diagnostic, false);
        return {false, generic_failure_message(kind, false), kind};
    }

    [[nodiscard]] TransferResult transfer(
        const ConnectionConfig& original_config,
        const std::filesystem::path& source_path, int source_descriptor,
        const struct stat& source_metadata, std::string_view remote_path,
        std::stop_token stop, ProgressCallback on_progress) {
        std::unique_lock operation(operation_mutex_, std::try_to_lock);
        if (!operation.owns_lock()) {
            return {TransferState::failed, "transfer_active",
                    TransferErrorKind::unknown, {}};
        }
        if (stop.stop_requested()) {
            return {TransferState::aborted, {}, TransferErrorKind::none, {}};
        }
        if (const auto error = validate_config(original_config)) {
            return {TransferState::failed, error->message, error->kind, {}};
        }
        if (has_control_or_nul(remote_path)) {
            return {TransferState::failed, "invalid_remote_directory",
                    TransferErrorKind::file, {}};
        }
        const auto remote_directory =
            normalized_remote_directory(trim(remote_path));
        if (remote_directory.empty()) {
            return {TransferState::failed, "invalid_remote_directory",
                    TransferErrorKind::file, {}};
        }

        if (source_descriptor < 0 || !S_ISREG(source_metadata.st_mode) ||
            source_metadata.st_size < 0) {
            return {TransferState::failed, "source_file_missing",
                    TransferErrorKind::file, {}};
        }
        const auto filename = source_path.filename().string();
        if (filename.empty() || filename == "." || filename == ".." ||
            has_control_or_nul(filename)) {
            return {TransferState::failed, "source_file_missing",
                    TransferErrorKind::file, {}};
        }

        const auto config = normalized_config(original_config);
        std::string staging;
        try {
            staging = join_remote(remote_directory,
                                  ".work-transfer-" +
                                      internal::random_identifier() + ".part");
        } catch (const std::exception&) {
            return {TransferState::failed, "random_source_unavailable",
                    TransferErrorKind::unknown, {}};
        }
        const auto final_path = join_remote(remote_directory, filename);

        cancellation_requested_.store(false);
        operation_active_.store(true);
        transfer_active_.store(true);
        struct ActiveGuard {
            std::atomic_bool& operation;
            std::atomic_bool& active;
            ~ActiveGuard() {
                active.store(false);
                operation.store(false);
            }
        } active_guard{operation_active_, transfer_active_};

        if (stop.stop_requested()) {
            cancellation_requested_.store(true);
            return {TransferState::aborted, {}, TransferErrorKind::none,
                    final_path};
        }

        auto snapshot = snapshot_source(source_descriptor, source_metadata,
                                        cancellation_requested_);
        if (snapshot.cancelled || cancellation_requested_.load()) {
            return {TransferState::aborted, {}, TransferErrorKind::none,
                    final_path};
        }
        if (snapshot.descriptor.value < 0) {
            return {TransferState::failed, "source_file_missing",
                    TransferErrorKind::file, final_path};
        }

        const auto total = static_cast<std::uint64_t>(source_metadata.st_size);
        emit_noexcept(on_progress,
                      {.filename = filename,
                       .transferred_bytes = 0,
                       .total_bytes = total,
                       .percent = total == 0 ? 100.0 : 0.0,
                       .bytes_per_second = std::nullopt,
                       .eta_seconds = std::nullopt,
                       .is_stalled = false});
        auto scp_arguments = strict_ssh_options(config);
        scp_arguments.insert(scp_arguments.end(),
                             {"-O", "-P", std::to_string(config.port), "--",
                              "/proc/self/fd/" +
                                  std::to_string(
                                      internal::kPinnedSourceDescriptor),
                              scp_target(config, remote_shell_path(staging))});
        ProgressStreamParser parser(filename, total, on_progress);
        const auto uploaded = run_process(
            {.executable = "/usr/bin/scp",
             .arguments = std::move(scp_arguments),
             .use_pty = true,
             .cancellable = true,
             .inherited_source = snapshot.descriptor.value,
             .timeout = std::nullopt},
            active_process_, &cancellation_requested_,
            [&parser](std::string_view output) { parser.feed(output); },
            [&parser] { parser.tick(); });
        parser.finish();

        if (uploaded.exit_code != 0 || cancellation_requested_.load()) {
            cleanup(config, staging);
            if (uploaded.cancelled || cancellation_requested_.load()) {
                return {TransferState::aborted, {}, TransferErrorKind::none,
                        final_path};
            }
            const auto kind = classify_ssh_error(uploaded.diagnostic, true);
            return {TransferState::failed, generic_failure_message(kind, true), kind,
                    final_path};
        }

        if (cancellation_requested_.load()) {
            cleanup(config, staging);
            return {TransferState::aborted, {}, TransferErrorKind::none, final_path};
        }
        const auto committed = finalize(config, staging, final_path);
        if (committed.cancelled) {
            cleanup(config, staging);
            return {TransferState::aborted, {}, TransferErrorKind::none, final_path};
        }
        if (committed.exit_code != 0) {
            cleanup(config, staging);
            if (committed.exit_code == 17) {
                return {TransferState::failed, "destination_file_exists",
                        TransferErrorKind::file, final_path};
            }
            const auto kind = classify_ssh_error(committed.diagnostic, true);
            return {TransferState::failed, generic_failure_message(kind, false),
                    kind, final_path};
        }

        emit_noexcept(on_progress,
                      {.filename = filename,
                       .transferred_bytes = total,
                       .total_bytes = total,
                       .percent = 100.0,
                       .bytes_per_second = std::nullopt,
                       .eta_seconds = 0.0,
                       .is_stalled = false});
        return {TransferState::completed, {}, TransferErrorKind::none, final_path};
    }

    [[nodiscard]] bool cancel() noexcept {
        if (!operation_active_.load()) {
            return false;
        }
        cancellation_requested_.store(true);
        internal::terminate_group(active_process_.load(), SIGTERM);
        return true;
    }

    [[nodiscard]] bool is_active() const noexcept {
        return operation_active_.load();
    }

    ~Impl() { static_cast<void>(cancel()); }

  private:
    static ConnectionConfig normalized_config(const ConnectionConfig& config) {
        return {.host = trim(config.host),
                .username = trim(config.username),
                .identity_file = absolute_normalized(config.identity_file),
                .known_hosts = absolute_normalized(config.known_hosts),
                .port = config.port};
    }

    static std::string ssh_target(const ConnectionConfig& config) {
        return config.username + "@" + config.host;
    }

    static std::string scp_target(const ConnectionConfig& config,
                                  std::string_view path) {
        return config.username + "@" + bracket_host(config.host) + ":" +
               std::string(path);
    }

    static void emit_noexcept(const ProgressCallback& callback,
                              const TransferProgress& progress) noexcept {
        if (!callback) {
            return;
        }
        try {
            callback(progress);
        } catch (...) {
            // A UI callback must not escape into transport lifecycle cleanup.
        }
    }

    ProcessResult finalize(const ConnectionConfig& config,
                           std::string_view staging,
                           std::string_view final_path) {
        const auto staging_token = remote_shell_path(staging);
        const auto final_token = remote_shell_path(final_path);
        const std::string command =
            "if test -e " + final_token +
            "; then rm -f -- " + staging_token +
            "; exit 17; fi; if ln -- " + staging_token + " " + final_token +
            "; then rm -- " + staging_token +
            "; else code=$?; rm -f -- " + staging_token +
            "; exit \"$code\"; fi";
        auto arguments = strict_ssh_options(config);
        arguments.insert(arguments.end(), {"-p", std::to_string(config.port),
                                           "--", ssh_target(config), command});
        return run_process({.executable = "/usr/bin/ssh",
                            .arguments = std::move(arguments),
                            .use_pty = false,
                            .cancellable = true,
                            .inherited_source = -1,
                            .timeout = std::chrono::seconds(15)},
                           active_process_, &cancellation_requested_);
    }

    void cleanup(const ConnectionConfig& config, std::string_view staging) {
        auto arguments = strict_ssh_options(config);
        arguments.insert(arguments.end(),
                         {"-p", std::to_string(config.port), "--",
                          ssh_target(config),
                          "rm -f -- " + remote_shell_path(staging)});
        static_cast<void>(run_process(
            {.executable = "/usr/bin/ssh",
             .arguments = std::move(arguments),
             .use_pty = false,
             .cancellable = false,
             .inherited_source = -1,
             .timeout = std::chrono::seconds(10)},
            active_process_, nullptr));
    }

    std::mutex operation_mutex_;
    std::atomic_bool operation_active_{false};
    std::atomic_bool transfer_active_{false};
    std::atomic_bool cancellation_requested_{false};
    std::atomic<pid_t> active_process_{0};
};

ScpTransport::ScpTransport() : impl_(std::make_unique<Impl>()) {}

ScpTransport::~ScpTransport() = default;

ConnectionTestResult ScpTransport::test_connection(
    const ConnectionConfig& config) {
    return test_connection(config, {});
}

ConnectionTestResult ScpTransport::test_connection(
    const ConnectionConfig& config, std::stop_token stop) {
    return impl_->test_connection(config, stop);
}

std::shared_ptr<PreparedSource> ScpTransport::prepare_source(
    const std::filesystem::path& source) const {
    const auto normalized = absolute_normalized(source);
    const auto source_text = normalized.string();
    const auto filename = normalized.filename().string();
    if (source_text.empty() || has_control_or_nul(source_text) ||
        filename.empty() || filename == "." || filename == ".." ||
        has_control_or_nul(filename)) {
        return {};
    }

    FileDescriptor descriptor = open_without_symlinks(normalized);
    struct stat metadata {};
    if (descriptor.value < 0 || ::fstat(descriptor.value, &metadata) != 0 ||
        !S_ISREG(metadata.st_mode) || metadata.st_size < 0) {
        return {};
    }
    return std::shared_ptr<PreparedSource>(new PreparedSource(
        std::make_unique<PreparedSource::Impl>(
            std::move(descriptor), normalized, metadata)));
}

TransferResult ScpTransport::transfer(const ConnectionConfig& config,
                                      const TransferRequest& request,
                                      ProgressCallback on_progress) {
    return transfer(config, request, {}, std::move(on_progress));
}

TransferResult ScpTransport::transfer(const ConnectionConfig& config,
                                      const TransferRequest& request,
                                      std::stop_token stop,
                                      ProgressCallback on_progress) {
    if (stop.stop_requested()) {
        return {TransferState::aborted, {}, TransferErrorKind::none, {}};
    }
    auto source = prepare_source(request.source);
    if (source == nullptr) {
        return {TransferState::failed, "source_file_missing",
                TransferErrorKind::file, {}};
    }
    return transfer(config, source, request.remote_directory, stop,
                    std::move(on_progress));
}

TransferResult ScpTransport::transfer(
    const ConnectionConfig& config,
    const std::shared_ptr<PreparedSource>& source,
    std::string remote_directory, ProgressCallback on_progress) {
    return transfer(config, source, std::move(remote_directory), {},
                    std::move(on_progress));
}

TransferResult ScpTransport::transfer(
    const ConnectionConfig& config,
    const std::shared_ptr<PreparedSource>& source,
    std::string remote_directory, std::stop_token stop,
    ProgressCallback on_progress) {
    if (source == nullptr || source->impl_ == nullptr) {
        return {TransferState::failed, "source_file_missing",
                TransferErrorKind::file, {}};
    }
    return impl_->transfer(config, source->impl_->path,
                           source->impl_->descriptor.value,
                           source->impl_->metadata, remote_directory, stop,
                           std::move(on_progress));
}

bool ScpTransport::cancel() noexcept { return impl_->cancel(); }

bool ScpTransport::is_active() const noexcept { return impl_->is_active(); }

}  // namespace work_transfer
