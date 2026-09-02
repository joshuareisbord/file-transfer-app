#pragma once

#include <cstdint>
#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <stop_token>
#include <string>
#include <string_view>

namespace work_transfer {

enum class TransferState { completed, aborted, failed };

enum class TransferErrorKind {
    none,
    file,
    authentication,
    host_key,
    connection,
    unknown,
};

struct ConnectionConfig {
    std::string host;
    std::string username;
    std::string password;
    std::filesystem::path known_hosts;
    std::uint16_t port{22};
};

struct ConnectionTestResult {
    bool success{false};
    std::string message;
    TransferErrorKind error_kind{TransferErrorKind::none};
};

struct TransferRequest {
    std::filesystem::path source;
    std::string remote_directory;
};

struct TransferProgress {
    std::string filename;
    std::uint64_t transferred_bytes{0};
    std::uint64_t total_bytes{0};
    double percent{0.0};
    std::optional<double> bytes_per_second;
    std::optional<double> eta_seconds;
    bool is_stalled{false};
};

struct TransferResult {
    TransferState state{TransferState::failed};
    std::string message;
    TransferErrorKind error_kind{TransferErrorKind::none};
    std::string remote_path;

    [[nodiscard]] bool success() const noexcept {
        return state == TransferState::completed;
    }
};

using ProgressCallback = std::function<void(const TransferProgress&)>;

/** One regular source file pinned at the operator's Start action. */
class PreparedSource final {
  public:
    ~PreparedSource();

    PreparedSource(const PreparedSource&) = delete;
    PreparedSource& operator=(const PreparedSource&) = delete;
    PreparedSource(PreparedSource&&) = delete;
    PreparedSource& operator=(PreparedSource&&) = delete;

  private:
    class Impl;
    explicit PreparedSource(std::unique_ptr<Impl> impl);

    std::unique_ptr<Impl> impl_;
    friend class ScpTransport;
};

/** Run strict, password-authenticated OpenSSH operations without a local shell. */
class ScpTransport final {
  public:
    ScpTransport();
    ~ScpTransport();

    ScpTransport(const ScpTransport&) = delete;
    ScpTransport& operator=(const ScpTransport&) = delete;
    ScpTransport(ScpTransport&&) = delete;
    ScpTransport& operator=(ScpTransport&&) = delete;

    /** Test strict host verification and password authentication synchronously. */
    [[nodiscard]] ConnectionTestResult test_connection(
        const ConnectionConfig& config);

    /** Test a connection while honoring cancellation requested before launch. */
    [[nodiscard]] ConnectionTestResult test_connection(
        const ConnectionConfig& config, std::stop_token stop);

    /**
     * Open one source at the Start boundary without following symbolic links.
     *
     * The returned handle pins file identity for asynchronous handoff. A null
     * result means the path was unsafe, missing, or not a regular file.
     */
    [[nodiscard]] std::shared_ptr<PreparedSource> prepare_source(
        const std::filesystem::path& source) const;

    /**
     * Transfer one pinned regular file synchronously.
     *
     * Call this from a worker thread. Progress callbacks execute on that same
     * worker thread and must marshal UI work to the FLTK thread with Fl::awake.
     */
    [[nodiscard]] TransferResult transfer(const ConnectionConfig& config,
                                          const TransferRequest& request,
                                          ProgressCallback on_progress = {});

    /** Transfer while honoring cancellation requested before worker launch. */
    [[nodiscard]] TransferResult transfer(
        const ConnectionConfig& config, const TransferRequest& request,
        std::stop_token stop, ProgressCallback on_progress = {});

    /** Transfer an already pinned source through a private stable snapshot. */
    [[nodiscard]] TransferResult transfer(
        const ConnectionConfig& config,
        const std::shared_ptr<PreparedSource>& source,
        std::string remote_directory, ProgressCallback on_progress = {});

    /** Transfer a prepared source with a worker cancellation token. */
    [[nodiscard]] TransferResult transfer(
        const ConnectionConfig& config,
        const std::shared_ptr<PreparedSource>& source,
        std::string remote_directory, std::stop_token stop,
        ProgressCallback on_progress = {});

    /** Cancel the active connection test or transfer process group from any thread. */
    [[nodiscard]] bool cancel() noexcept;

    [[nodiscard]] bool is_active() const noexcept;

  private:
    class Impl;
    std::unique_ptr<Impl> impl_;
};

namespace detail {

/** Normalize a safe absolute or home-relative remote directory. */
[[nodiscard]] std::optional<std::string> normalize_remote_directory(
    std::string_view path);

/** Parse one bounded OpenSSH SCP progress record. */
[[nodiscard]] std::optional<TransferProgress> parse_scp_progress_line(
    std::string_view line, std::string_view filename,
    std::uint64_t total_bytes);

/** Quote one string as a single POSIX remote-shell token. */
[[nodiscard]] std::string quote_posix_shell_token(std::string_view value);

}  // namespace detail

}  // namespace work_transfer
