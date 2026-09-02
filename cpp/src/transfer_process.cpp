#include "transfer_process.hpp"

#include "work_transfer/transfer.hpp"

#include <algorithm>
#include <array>
#include <cerrno>
#include <cmath>
#include <fcntl.h>
#include <limits>
#include <stdexcept>
#include <utility>

#include <poll.h>
#include <signal.h>
#include <sys/wait.h>
#include <unistd.h>

#if defined(__linux__)
#include <pty.h>
#include <sys/random.h>
#else
#include <util.h>
#endif

namespace work_transfer {
namespace {

using Clock = std::chrono::steady_clock;
constexpr std::size_t kMaximumDiagnosticBytes = 16384;
constexpr auto kTerminationGrace = std::chrono::seconds(2);

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

[[nodiscard]] std::optional<double> parse_decimal(std::string_view text) {
    if (text.empty()) {
        return std::nullopt;
    }
    double whole = 0.0;
    double fraction = 0.0;
    double divisor = 1.0;
    bool after_decimal = false;
    bool saw_digit = false;
    for (const unsigned char character : text) {
        if (character == '.' && !after_decimal) {
            after_decimal = true;
            continue;
        }
        if (character < '0' || character > '9') {
            return std::nullopt;
        }
        saw_digit = true;
        if (after_decimal) {
            divisor *= 10.0;
            fraction += static_cast<double>(character - '0') / divisor;
        } else {
            whole = whole * 10.0 + static_cast<double>(character - '0');
        }
        if (!std::isfinite(whole)) {
            return std::nullopt;
        }
    }
    return saw_digit ? std::optional<double>(whole + fraction) : std::nullopt;
}

[[nodiscard]] std::optional<double> parse_scaled_bytes(std::string_view token) {
    if (token.ends_with("/s")) {
        token.remove_suffix(2);
    }
    double multiplier = 1.0;
    constexpr std::array<std::pair<std::string_view, double>, 5> suffixes{{
        {"TB", 1024.0 * 1024.0 * 1024.0 * 1024.0},
        {"GB", 1024.0 * 1024.0 * 1024.0},
        {"MB", 1024.0 * 1024.0},
        {"KB", 1024.0},
        {"B", 1.0},
    }};
    for (const auto& [suffix, scale] : suffixes) {
        if (token.ends_with(suffix)) {
            token.remove_suffix(suffix.size());
            multiplier = scale;
            break;
        }
    }
    const auto number = parse_decimal(token);
    if (!number || *number >
                       static_cast<double>(std::numeric_limits<std::uint64_t>::max()) /
                           multiplier) {
        return std::nullopt;
    }
    return *number * multiplier;
}

[[nodiscard]] std::optional<double> parse_eta(std::string_view token) {
    const auto first_separator = token.find(':');
    if (first_separator == std::string_view::npos) {
        return std::nullopt;
    }
    const auto second_separator = token.find(':', first_separator + 1);
    const auto first = parse_decimal(token.substr(0, first_separator));
    const auto middle = parse_decimal(token.substr(
        first_separator + 1,
        (second_separator == std::string_view::npos ? token.size()
                                                    : second_separator) -
            first_separator - 1));
    if (!first || !middle || *middle >= 60.0) {
        return std::nullopt;
    }
    if (second_separator == std::string_view::npos) {
        return *first * 60.0 + *middle;
    }
    if (token.find(':', second_separator + 1) != std::string_view::npos) {
        return std::nullopt;
    }
    const auto seconds = parse_decimal(token.substr(second_separator + 1));
    if (!seconds || *seconds >= 60.0) {
        return std::nullopt;
    }
    return *first * 3600.0 + *middle * 60.0 + *seconds;
}

[[nodiscard]] std::vector<std::string_view> split_fields(std::string_view line) {
    std::vector<std::string_view> fields;
    std::size_t position = 0;
    while (position < line.size() && fields.size() < 32) {
        position = line.find_first_not_of(" \t", position);
        if (position == std::string_view::npos) {
            break;
        }
        const auto end = line.find_first_of(" \t", position);
        fields.emplace_back(line.substr(position, end - position));
        position = end == std::string_view::npos ? line.size() : end;
    }
    return fields;
}

void set_close_on_exec(int descriptor) {
    const int flags = ::fcntl(descriptor, F_GETFD);
    if (flags >= 0) {
        static_cast<void>(::fcntl(descriptor, F_SETFD, flags | FD_CLOEXEC));
    }
}

void set_nonblocking(int descriptor) {
    const int flags = ::fcntl(descriptor, F_GETFL);
    if (flags >= 0) {
        static_cast<void>(::fcntl(descriptor, F_SETFL, flags | O_NONBLOCK));
    }
}

void close_child_descriptor(int descriptor, int preserved) {
    if (descriptor > STDERR_FILENO && descriptor != preserved) {
        ::close(descriptor);
    }
}

void append_bounded(std::string& output, std::string_view chunk) {
    const auto remaining = kMaximumDiagnosticBytes - output.size();
    output.append(chunk.substr(0, remaining));
}

}  // namespace

namespace internal {

void terminate_group(pid_t process, int signal_number) noexcept {
    if (process > 0) {
        static_cast<void>(::kill(-process, signal_number));
    }
}

ProcessResult run_process(const ProcessSpec& spec,
                          std::atomic<pid_t>& active_process,
                          const std::atomic_bool* cancellation,
                          const ProcessOutputCallback& on_output,
                          const ProcessTickCallback& on_tick) {
    ProcessResult result;
    if (cancellation != nullptr && cancellation->load()) {
        result.cancelled = true;
        return result;
    }

    int read_descriptor = -1;
    int write_descriptor = -1;
    int master = -1;
    int slave = -1;
    if (spec.use_pty) {
        if (::openpty(&master, &slave, nullptr, nullptr, nullptr) != 0) {
            return result;
        }
        read_descriptor = master;
        write_descriptor = slave;
        set_close_on_exec(master);
        set_close_on_exec(slave);
    } else {
        int descriptors[2]{-1, -1};
        if (::pipe(descriptors) != 0) {
            return result;
        }
        read_descriptor = descriptors[0];
        write_descriptor = descriptors[1];
        set_close_on_exec(read_descriptor);
        set_close_on_exec(write_descriptor);
    }
    FileDescriptor read_end(read_descriptor);
    FileDescriptor write_end(write_descriptor);
    set_nonblocking(read_end.value);
    FileDescriptor null_input(::open("/dev/null", O_RDONLY | O_CLOEXEC));
    if (null_input.value < 0) {
        return result;
    }

    std::vector<char*> arguments;
    arguments.reserve(spec.arguments.size() + 2);
    arguments.push_back(const_cast<char*>(spec.executable.c_str()));
    for (const auto& argument : spec.arguments) {
        arguments.push_back(const_cast<char*>(argument.c_str()));
    }
    arguments.push_back(nullptr);

    const pid_t process = ::fork();
    if (process < 0) {
        return result;
    }
    if (process == 0) {
        static_cast<void>(::setpgid(0, 0));
        if (::dup2(null_input.value, STDIN_FILENO) < 0 ||
            ::dup2(write_end.value, STDOUT_FILENO) < 0 ||
            ::dup2(write_end.value, STDERR_FILENO) < 0) {
            ::_exit(126);
        }
        if (spec.inherited_source >= 0) {
            if (spec.inherited_source != kPinnedSourceDescriptor) {
                if (::dup2(spec.inherited_source, kPinnedSourceDescriptor) < 0) {
                    ::_exit(126);
                }
            } else {
                static_cast<void>(
                    ::fcntl(kPinnedSourceDescriptor, F_SETFD, 0));
            }
        }
        close_child_descriptor(read_end.value, kPinnedSourceDescriptor);
        close_child_descriptor(write_end.value, kPinnedSourceDescriptor);
        close_child_descriptor(null_input.value, kPinnedSourceDescriptor);
        if (spec.inherited_source > STDERR_FILENO &&
            spec.inherited_source != kPinnedSourceDescriptor) {
            ::close(spec.inherited_source);
        }
        ::execv(arguments.front(), arguments.data());
        ::_exit(127);
    }

    static_cast<void>(::setpgid(process, process));
    write_end = FileDescriptor{};
    null_input = FileDescriptor{};
    if (spec.cancellable) {
        active_process.store(process);
    }

    const auto started = Clock::now();
    std::optional<Clock::time_point> termination_started;
    bool process_done = false;
    int wait_status = 0;
    std::array<char, 4096> buffer{};
    while (!process_done) {
        pollfd descriptor{.fd = read_end.value, .events = POLLIN, .revents = 0};
        static_cast<void>(::poll(&descriptor, 1, 100));
        while (true) {
            const auto count = ::read(read_end.value, buffer.data(), buffer.size());
            if (count > 0) {
                const std::string_view chunk(buffer.data(),
                                             static_cast<std::size_t>(count));
                append_bounded(result.diagnostic, chunk);
                if (on_output) {
                    on_output(chunk);
                }
                continue;
            }
            if (count < 0 && errno == EINTR) {
                continue;
            }
            break;
        }
        if (on_tick) {
            on_tick();
        }

        // Withdraw the externally signalable PID before waitpid can reap it.
        // A concurrent cancel still sets the cancellation flag, which this
        // loop observes and delivers to the known-live local PID if needed.
        if (spec.cancellable) {
            pid_t expected = process;
            static_cast<void>(
                active_process.compare_exchange_strong(expected, 0));
        }
        const auto wait_result = ::waitpid(process, &wait_status, WNOHANG);
        process_done = wait_result == process ||
                       (wait_result < 0 && errno == ECHILD);
        if (spec.cancellable && !process_done) {
            active_process.store(process);
        }
        const auto now = Clock::now();
        if (!process_done && !termination_started && cancellation != nullptr &&
            cancellation->load()) {
            result.cancelled = true;
            termination_started = now;
            terminate_group(process, SIGTERM);
        }
        if (!process_done && !termination_started && spec.timeout &&
            now - started >= *spec.timeout) {
            result.timed_out = true;
            termination_started = now;
            terminate_group(process, SIGTERM);
        }
        if (!process_done && termination_started &&
            now - *termination_started >= kTerminationGrace) {
            terminate_group(process, SIGKILL);
        }
    }

    // The cancellable PID remains withdrawn after reaping. Deliver final bytes
    // only now, so a callback cannot signal a recycled process identifier.
    while (true) {
        const auto count = ::read(read_end.value, buffer.data(), buffer.size());
        if (count > 0) {
            const std::string_view chunk(buffer.data(),
                                         static_cast<std::size_t>(count));
            append_bounded(result.diagnostic, chunk);
            if (on_output) {
                on_output(chunk);
            }
            continue;
        }
        if (count < 0 && errno == EINTR) {
            continue;
        }
        break;
    }
    if (WIFEXITED(wait_status)) {
        result.exit_code = WEXITSTATUS(wait_status);
    } else if (WIFSIGNALED(wait_status)) {
        result.exit_code = 128 + WTERMSIG(wait_status);
    }
    return result;
}

std::string random_identifier() {
    std::array<unsigned char, 16> bytes{};
#if defined(__linux__)
    std::size_t offset = 0;
    while (offset < bytes.size()) {
        const auto count = ::getrandom(bytes.data() + offset, bytes.size() - offset,
                                       0);
        if (count > 0) {
            offset += static_cast<std::size_t>(count);
        } else if (count < 0 && errno != EINTR) {
            throw std::runtime_error("random_source_unavailable");
        }
    }
#else
    ::arc4random_buf(bytes.data(), bytes.size());
#endif
    constexpr char hexadecimal[] = "0123456789abcdef";
    std::string result;
    result.reserve(bytes.size() * 2);
    for (const auto byte : bytes) {
        result.push_back(hexadecimal[byte >> 4]);
        result.push_back(hexadecimal[byte & 0x0f]);
    }
    return result;
}

}  // namespace internal

namespace detail {

std::optional<TransferProgress> parse_scp_progress_line(
    std::string_view line, std::string_view filename,
    std::uint64_t total_bytes) {
    if (line.empty() || line.size() > internal::kMaximumProgressRecord) {
        return std::nullopt;
    }
    const auto fields = split_fields(line);
    const auto percent_field = std::find_if(
        fields.begin(), fields.end(), [](std::string_view field) {
            return field.size() > 1 && field.ends_with('%');
        });
    if (percent_field == fields.end()) {
        return std::nullopt;
    }
    const auto index = static_cast<std::size_t>(percent_field - fields.begin());
    auto percent_token = *percent_field;
    percent_token.remove_suffix(1);
    const auto parsed_percent = parse_decimal(percent_token);
    if (!parsed_percent || *parsed_percent > 100.0) {
        return std::nullopt;
    }

    std::uint64_t transferred = static_cast<std::uint64_t>(std::llround(
        static_cast<long double>(total_bytes) * *parsed_percent / 100.0L));
    if (index + 1 < fields.size()) {
        if (const auto parsed_bytes = parse_scaled_bytes(fields[index + 1])) {
            transferred = static_cast<std::uint64_t>(std::llround(*parsed_bytes));
        }
    }
    if (*parsed_percent >= 100.0) {
        transferred = total_bytes;
    }
    transferred = std::min(transferred, total_bytes);

    std::optional<double> rate;
    if (index + 2 < fields.size()) {
        rate = parse_scaled_bytes(fields[index + 2]);
    }
    std::optional<double> eta;
    if (index + 3 < fields.size()) {
        eta = parse_eta(fields[index + 3]);
    }
    if (!eta && rate && *rate > 0.0) {
        eta = static_cast<double>(total_bytes - transferred) / *rate;
    }
    return TransferProgress{
        .filename = std::string(filename),
        .transferred_bytes = transferred,
        .total_bytes = total_bytes,
        .percent = *parsed_percent,
        .bytes_per_second = rate,
        .eta_seconds = eta,
        .is_stalled = false,
    };
}

std::string quote_posix_shell_token(std::string_view value) {
    if (value.find('\0') != std::string_view::npos) {
        throw std::invalid_argument("NUL cannot be represented in a shell token");
    }
    std::string result{"'"};
    result.reserve(value.size() + 2);
    for (const char character : value) {
        if (character == '\'') {
            result.append("'\\''");
        } else {
            result.push_back(character);
        }
    }
    result.push_back('\'');
    return result;
}

}  // namespace detail
}  // namespace work_transfer
