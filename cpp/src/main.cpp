#include <FL/Fl.H>

#include <unistd.h>

#include <atomic>
#include <cstdint>
#include <cstdlib>
#include <filesystem>
#include <iostream>
#include <memory>
#include <mutex>
#include <optional>
#include <stdexcept>
#include <string>
#include <string_view>
#include <thread>
#include <utility>

#include "work_transfer/config.hpp"
#include "work_transfer/localization.hpp"
#include "work_transfer/resources.hpp"
#include "work_transfer/theme.hpp"
#include "work_transfer/transfer.hpp"
#include "work_transfer/ui.hpp"

namespace {

constexpr std::string_view kVersion = "0.1.0";

struct CommandLine {
  bool self_check = false;
  bool show_version = false;
  std::optional<std::filesystem::path> logo;
};

[[nodiscard]] CommandLine parse_command_line(int argc, char* argv[]) {
  CommandLine result;
  for (int index = 1; index < argc; ++index) {
    const std::string_view argument(argv[index]);
    if (argument == "--self-check") {
      result.self_check = true;
    } else if (argument == "--version") {
      result.show_version = true;
    } else if (argument == "--logo") {
      if (++index >= argc || argv[index][0] == '\0') {
        throw std::invalid_argument("--logo requires a file path");
      }
      result.logo = std::filesystem::path(argv[index]);
    } else {
      throw std::invalid_argument("unrecognized argument: " +
                                  std::string(argument));
    }
  }
  if (result.self_check && result.show_version) {
    throw std::invalid_argument(
        "--self-check and --version cannot be used together");
  }
  if (result.logo.has_value() &&
      (result.self_check || result.show_version)) {
    throw std::invalid_argument(
        "--logo is only valid when launching the application");
  }
  return result;
}

[[nodiscard]] std::filesystem::path default_known_hosts_path() {
  const char* home = std::getenv("HOME");
  if (home == nullptr || *home == '\0') {
    throw std::runtime_error(
        "HOME is unavailable; the default known_hosts path is unknown");
  }
  return std::filesystem::path(home) / ".ssh" / "known_hosts";
}

void require_executable(const std::filesystem::path& path) {
  std::error_code error;
  if (!std::filesystem::is_regular_file(path, error) || error ||
      ::access(path.c_str(), X_OK) != 0) {
    throw std::runtime_error(path.string() +
                             " is missing or is not executable");
  }
}

void validate_embedded_resources() {
  const auto resources = work_transfer::embedded_language_catalogs();
  if (resources.empty()) {
    throw std::runtime_error("no embedded language catalogs were found");
  }
  for (const auto& resource : resources) {
    if (resource.logical_path.empty() || resource.contents.empty()) {
      throw std::runtime_error("an embedded language catalog is empty");
    }
  }

  const auto english = work_transfer::Translator::embedded("en");
  if (english.languages().size() != resources.size()) {
    throw std::runtime_error(
        "one or more embedded language catalogs are invalid");
  }
  for (const auto& language : english.languages()) {
    const auto loaded = work_transfer::Translator::embedded(language.code);
    if (loaded.language_code() != language.code) {
      throw std::runtime_error("unable to load embedded language catalog: " +
                               language.code);
    }
  }

  static_cast<void>(work_transfer::load_embedded_update_destinations());
  static_cast<void>(work_transfer::load_embedded_mock_tests());
  static_cast<void>(work_transfer::load_embedded_theme());
}

[[nodiscard]] int run_self_check() {
  validate_embedded_resources();
  require_executable("/usr/bin/ssh");
  require_executable("/usr/bin/scp");
  std::cout
      << "work-transfer: ready (SCP transport, language, branding, and "
         "application config resources loaded)\n";
  return 0;
}

[[nodiscard]] std::string ui_detail(
    std::string message, work_transfer::TransferErrorKind error_kind) {
  if (error_kind == work_transfer::TransferErrorKind::authentication) {
    return "authentication";
  }
  if (error_kind == work_transfer::TransferErrorKind::host_key) {
    return "host_key";
  }
  return message;
}

[[nodiscard]] bool degrades_connection(
    work_transfer::TransferErrorKind error_kind) noexcept {
  return error_kind == work_transfer::TransferErrorKind::authentication ||
         error_kind == work_transfer::TransferErrorKind::host_key ||
         error_kind == work_transfer::TransferErrorKind::connection;
}

class ApplicationController final {
 public:
  explicit ApplicationController(std::filesystem::path known_hosts)
      : known_hosts_(std::move(known_hosts)) {}

  ~ApplicationController() { shutdown(); }

  ApplicationController(const ApplicationController&) = delete;
  ApplicationController& operator=(const ApplicationController&) = delete;

  [[nodiscard]] work_transfer::UiCallbacks callbacks() {
    return {
        .test_connection =
            [this](work_transfer::ConnectionRequest request) {
              test_connection(std::move(request));
            },
        .connection_invalidated = [this] { invalidate_connection(); },
        .start_transfer =
            [this](work_transfer::TransferStartRequest request) {
              start_transfer(std::move(request));
            },
        .abort_transfer = [this] { request_cancel(); },
        .shutdown = [this] { shutdown(); },
    };
  }

  void attach(work_transfer::WorkTransferWindow& window) noexcept {
    window_.store(&window, std::memory_order_release);
  }

  void shutdown() noexcept {
    if (shutting_down_.exchange(true, std::memory_order_acq_rel)) {
      return;
    }
    window_.store(nullptr, std::memory_order_release);
    generation_.fetch_add(1, std::memory_order_acq_rel);
    {
      std::lock_guard lock(state_mutex_);
      tested_connection_.reset();
    }
    request_cancel();
    join_worker();
  }

 private:
  [[nodiscard]] work_transfer::ConnectionConfig make_connection(
      work_transfer::ConnectionRequest request) const {
    return {
        .host = std::move(request.host),
        .username = std::move(request.username),
        .identity_file = std::move(request.identity_file),
        .known_hosts = known_hosts_,
        .port = request.port,
    };
  }

  void test_connection(work_transfer::ConnectionRequest request) {
    if (shutting_down_.load(std::memory_order_acquire)) {
      return;
    }
    if (transport_.is_active()) {
      throw std::runtime_error("transfer_active");
    }
    join_worker();
    const std::uint64_t generation =
        generation_.fetch_add(1, std::memory_order_acq_rel) + 1;
    auto connection = make_connection(std::move(request));
    worker_ = std::jthread(
        [this, generation, connection = std::move(connection)](
            std::stop_token stop) mutable {
          const auto result = transport_.test_connection(connection, stop);
          if (stop.stop_requested() ||
              shutting_down_.load(std::memory_order_acquire)) {
            return;
          }

          const bool current =
              generation_.load(std::memory_order_acquire) == generation;
          if (current) {
            std::lock_guard lock(state_mutex_);
            if (result.success) {
              tested_connection_ = connection;
            } else {
              tested_connection_.reset();
            }
          }
          if (auto* window = window_.load(std::memory_order_acquire);
              window != nullptr) {
            window->post_connection_result(
                current && result.success,
                current ? ui_detail(result.message, result.error_kind)
                        : "connection_not_tested");
          }
        });
  }

  void invalidate_connection() noexcept {
    generation_.fetch_add(1, std::memory_order_acq_rel);
    std::lock_guard lock(state_mutex_);
    tested_connection_.reset();
  }

  void start_transfer(work_transfer::TransferStartRequest request) {
    if (shutting_down_.load(std::memory_order_acquire)) {
      throw std::runtime_error("connection_not_tested");
    }
    if (transport_.is_active()) {
      throw std::runtime_error("transfer_active");
    }
    join_worker();
    std::optional<work_transfer::ConnectionConfig> connection;
    {
      std::lock_guard lock(state_mutex_);
      connection = tested_connection_;
    }
    if (!connection.has_value()) {
      throw std::runtime_error("connection_not_tested");
    }
    auto source = transport_.prepare_source(request.source);
    if (source == nullptr) {
      throw std::runtime_error("source_file_missing");
    }

    worker_ = std::jthread(
        [this, connection = std::move(*connection),
         source = std::move(source),
         remote_directory = std::move(request.remote_directory)](
            std::stop_token stop) mutable {
          const auto result = transport_.transfer(
              connection, source, std::move(remote_directory), stop,
              [this, &stop](const work_transfer::TransferProgress& progress) {
                if (stop.stop_requested() ||
                    shutting_down_.load(std::memory_order_acquire)) {
                  return;
                }
                if (auto* window = window_.load(std::memory_order_acquire);
                    window != nullptr) {
                  window->post_transfer_progress(
                      {.transferred_bytes = progress.transferred_bytes,
                       .total_bytes = progress.total_bytes,
                       .bytes_per_second =
                           progress.bytes_per_second.value_or(0.0),
                       .eta_seconds = progress.eta_seconds,
                       .is_stalled = progress.is_stalled});
                }
              });
          if (shutting_down_.load(std::memory_order_acquire)) {
            return;
          }

          const std::string detail =
              ui_detail(result.message, result.error_kind);
          if (degrades_connection(result.error_kind)) {
            {
              std::lock_guard lock(state_mutex_);
              tested_connection_.reset();
            }
            if (auto* window = window_.load(std::memory_order_acquire);
                window != nullptr) {
              window->post_connection_degraded(detail);
            }
          }
          if (auto* window = window_.load(std::memory_order_acquire);
              window != nullptr) {
            work_transfer::TransferOutcome outcome =
                work_transfer::TransferOutcome::failed;
            if (result.state == work_transfer::TransferState::completed) {
              outcome = work_transfer::TransferOutcome::completed;
            } else if (result.state == work_transfer::TransferState::aborted) {
              outcome = work_transfer::TransferOutcome::aborted;
            }
            window->post_transfer_finished(outcome, detail);
          }
        });
  }

  void join_worker() noexcept {
    if (!worker_.joinable()) {
      return;
    }
    worker_.request_stop();
    worker_.join();
  }

  void request_cancel() noexcept {
    worker_.request_stop();
    static_cast<void>(transport_.cancel());
  }

  const std::filesystem::path known_hosts_;
  work_transfer::ScpTransport transport_;
  std::atomic<work_transfer::WorkTransferWindow*> window_{nullptr};
  std::atomic_bool shutting_down_{false};
  std::atomic<std::uint64_t> generation_{0};
  std::mutex state_mutex_;
  std::optional<work_transfer::ConnectionConfig> tested_connection_;
  std::jthread worker_;
};

[[nodiscard]] int run_gui(const CommandLine& command_line) {
  auto settings = std::make_shared<work_transfer::SettingsStore>();
  const std::string language = settings->load_language();
  work_transfer::UiConfiguration configuration{
      .translator = work_transfer::Translator::embedded(language),
      .theme = work_transfer::load_embedded_theme(),
      .destinations = work_transfer::load_embedded_update_destinations(),
      .mock_tests = work_transfer::load_embedded_mock_tests(),
      .settings = settings,
      .current_language = language,
      .version = std::string(kVersion),
      .logo_path = command_line.logo,
  };

  static_cast<void>(Fl::lock());
  ApplicationController controller(default_known_hosts_path());
  work_transfer::WorkTransferWindow window(std::move(configuration),
                                           controller.callbacks());
  controller.attach(window);
  window.show();
  int result = 0;
  try {
    result = Fl::run();
  } catch (...) {
    controller.shutdown();
    throw;
  }
  controller.shutdown();
  return result;
}

}  // namespace

int main(int argc, char* argv[]) {
  try {
    const CommandLine command_line = parse_command_line(argc, argv);
    if (command_line.show_version) {
      std::cout << kVersion << '\n';
      return 0;
    }
    if (command_line.self_check) {
      return run_self_check();
    }
    return run_gui(command_line);
  } catch (const std::exception& error) {
    std::cerr << "work-transfer: " << error.what() << '\n';
    return 1;
  }
}
