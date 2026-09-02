#pragma once

#include <FL/Fl_Double_Window.H>

#include <cstdint>
#include <filesystem>
#include <functional>
#include <memory>
#include <optional>
#include <string>

#include "work_transfer/config.hpp"
#include "work_transfer/localization.hpp"
#include "work_transfer/theme.hpp"

namespace work_transfer {

enum class UpdateKind { library, software };
enum class ConnectionHealth { disconnected, connected, degraded };
enum class TransferOutcome { completed, aborted, failed };

struct ConnectionRequest {
  std::string host;
  std::string username;
  std::uint16_t port;
  std::filesystem::path identity_file;
};

struct TransferStartRequest {
  UpdateKind kind;
  std::filesystem::path source;
  std::string remote_directory;
};

struct TransferProgressView {
  std::uint64_t transferred_bytes = 0;
  std::uint64_t total_bytes = 0;
  double bytes_per_second = 0.0;
  std::optional<double> eta_seconds;
  bool is_stalled = false;
};

struct UiCallbacks {
  std::function<void(ConnectionRequest)> test_connection;
  std::function<void()> connection_invalidated;
  std::function<void(TransferStartRequest)> start_transfer;
  std::function<void()> abort_transfer;
  std::function<void()> shutdown;
};

struct UiConfiguration {
  Translator translator;
  ColorTheme theme;
  UpdateDestinations destinations;
  std::vector<MockTestDefinition> mock_tests;
  std::shared_ptr<SettingsStore> settings;
  std::string current_language = "en";
  std::string version = "0.1.0";
  std::optional<std::filesystem::path> logo_path;
};

class WorkTransferWindow final : public Fl_Double_Window {
 public:
  WorkTransferWindow(UiConfiguration configuration, UiCallbacks callbacks);
  ~WorkTransferWindow() override;

  WorkTransferWindow(const WorkTransferWindow&) = delete;
  WorkTransferWindow& operator=(const WorkTransferWindow&) = delete;

  void resize(int x, int y, int width, int height) override;
  int handle(int event) override;

  // These post methods are safe to call from background transport threads.
  void post_connection_result(bool successful, std::string detail = {});
  void post_connection_degraded(std::string detail);
  void post_transfer_progress(TransferProgressView progress);
  void post_transfer_finished(TransferOutcome outcome,
                              std::string detail = {});

 private:
  struct Impl;
  std::unique_ptr<Impl> impl_;
};

}  // namespace work_transfer
