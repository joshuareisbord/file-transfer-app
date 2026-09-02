#pragma once

#include <atomic>
#include <chrono>
#include <functional>
#include <optional>
#include <string>
#include <string_view>
#include <vector>

#include <sys/types.h>

namespace work_transfer::internal {

inline constexpr std::size_t kMaximumProgressRecord = 8192;
inline constexpr int kPinnedSourceDescriptor = 197;

struct ProcessSpec {
    std::string executable;
    std::vector<std::string> arguments;
    std::string_view password;
    bool use_pty{false};
    bool cancellable{false};
    int inherited_source{-1};
    std::optional<std::chrono::seconds> timeout;
};

struct ProcessResult {
    int exit_code{127};
    bool cancelled{false};
    bool timed_out{false};
    std::string diagnostic;
};

using ProcessOutputCallback = std::function<void(std::string_view)>;
using ProcessTickCallback = std::function<void()>;

[[nodiscard]] ProcessResult run_process(
    const ProcessSpec& spec, std::atomic<pid_t>& active_process,
    const std::atomic_bool* cancellation,
    const ProcessOutputCallback& on_output = {},
    const ProcessTickCallback& on_tick = {});

void terminate_group(pid_t process, int signal_number) noexcept;

[[nodiscard]] std::string random_identifier();

}  // namespace work_transfer::internal
