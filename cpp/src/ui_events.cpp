#include "ui_internal.hpp"

#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <deque>
#include <iomanip>
#include <map>
#include <memory>
#include <mutex>
#include <regex>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>

namespace work_transfer {
using namespace ui_internal;
namespace {

std::string format_bytes(std::uint64_t value, const Translator& translator) {
  struct Unit {
    std::uint64_t divisor;
    std::string_view key;
  };
  constexpr std::array<Unit, 4> units = {{{1ULL << 30U, "units.gibibytes"},
                                          {1ULL << 20U, "units.mebibytes"},
                                          {1ULL << 10U, "units.kibibytes"},
                                          {1, "units.bytes"}}};
  for (const auto& unit : units) {
    if (value >= unit.divisor || unit.divisor == 1) {
      std::ostringstream formatted;
      if (unit.divisor == 1) {
        formatted << value;
      } else {
        formatted << std::fixed << std::setprecision(1)
                  << static_cast<double>(value) / unit.divisor;
      }
      return translator.translate(unit.key, {{"value", formatted.str()}});
    }
  }
  return {};
}

std::string format_eta(std::optional<double> seconds, bool stalled,
                       const Translator& translator) {
  if (stalled) {
    return translator.translate("status.eta_stalled");
  }
  if (!seconds.has_value() || !std::isfinite(*seconds)) {
    return translator.translate("status.eta_calculating");
  }
  const long long rounded =
      std::max(0LL, static_cast<long long>(std::ceil(*seconds)));
  if (rounded < 60) {
    return translator.translate("units.duration_seconds",
                                {{"value", std::to_string(rounded)}});
  }
  if (rounded < 3600) {
    return translator.translate(
        "units.duration_minutes",
        {{"minutes", std::to_string(rounded / 60)},
         {"seconds", std::to_string(rounded % 60)}});
  }
  return translator.translate(
      "units.duration_hours",
      {{"hours", std::to_string(rounded / 3600)},
       {"minutes", std::to_string((rounded % 3600) / 60)}});
}

std::string localized_backend_message(const Translator& translator,
                                      std::string message,
                                      bool connection_context) {
  const auto first = message.find_first_not_of(" \t\r\n");
  const auto last = message.find_last_not_of(" \t\r\n");
  message = first == std::string::npos
                ? std::string{}
                : message.substr(first, last - first + 1);
  static const std::map<std::string, std::string_view> translations = {
      {"authentication", "errors.authentication"},
      {"host_key", "errors.host_key"},
      {"source_file_missing", "errors.source_file_missing"},
      {"destination_file_exists", "errors.remote_file_exists"},
      {"identity_file_missing", "errors.identity_file_missing"},
      {"known_hosts_missing", "errors.known_hosts_missing"},
      {"connection_not_tested", "connection.test_required"},
      {"transfer_active", "errors.transfer_active"},
      {"invalid_remote_directory", "errors.remote_directory_invalid"},
      {"invalid_host", "validation.host_required"},
      {"invalid_username", "validation.username_required"},
      {"invalid_port", "validation.port_range"},
  };
  if (const auto known = translations.find(message); known != translations.end()) {
    return translator.translate(known->second);
  }
  static const std::regex stable_token("^[a-z][a-z0-9_]*$");
  if (std::regex_match(message, stable_token)) {
    return translator.translate("errors.unexpected");
  }
  const std::string detail =
      message.empty() ? translator.translate("common.unavailable") : message;
  return connection_context
             ? translator.translate("errors.connection_failed", {{"detail", detail}})
             : translator.translate("errors.transfer", {{"message", detail}});
}

}  // namespace

void WorkTransferWindow::Impl::apply(const ConnectionEvent& event) {
  if (event.degraded) {
    connection_ready = false;
    set_connection_health(ConnectionHealth::degraded);
    set_widget_label(connection_detail,
                     localized_backend_message(configuration.translator,
                                               event.detail, true));
  } else {
    if (!connection_test_active) {
      return;
    }
    connection_test_active = false;
    if (event.successful) {
      connection_ready = true;
      set_connection_health(ConnectionHealth::connected);
      set_widget_label(connection_detail, t("connection.status_tested"));
    } else {
      connection_ready = false;
      set_connection_health(ConnectionHealth::disconnected);
      set_widget_label(connection_detail,
                       localized_backend_message(configuration.translator,
                                                 event.detail, true));
    }
  }
  refresh_action_buttons();
}

void WorkTransferWindow::Impl::apply(const ProgressEvent& event) {
  if (!transfer_active) {
    return;
  }
  const auto& progress = event.progress;
  const double percent =
      progress.total_bytes == 0
          ? 0.0
          : 100.0 * static_cast<double>(progress.transferred_bytes) /
                static_cast<double>(progress.total_bytes);
  const double bounded = std::clamp(percent, 0.0, 100.0);
  status_progress->value(bounded);
  std::ostringstream percent_text;
  percent_text << std::fixed << std::setprecision(1) << bounded;
  set_widget_label(
      status_state,
      t("status.progress", {{"percent", percent_text.str()}}));
  const std::string transferred = t(
      "status.transferred",
      {{"sent", format_bytes(progress.transferred_bytes,
                             configuration.translator)},
       {"total", format_bytes(progress.total_bytes, configuration.translator)}});
  const std::string rate = t(
      "units.per_second",
      {{"value",
        format_bytes(static_cast<std::uint64_t>(
                         std::max(0.0, std::floor(progress.bytes_per_second))),
                     configuration.translator)}});
  const std::string eta = t(
      "status.eta",
      {{"eta", format_eta(progress.eta_seconds, progress.is_stalled,
                           configuration.translator)}});
  set_widget_label(status_metrics, transferred + "     " + rate + "     " + eta);
  abort_button->activate();
}

void WorkTransferWindow::Impl::apply(const FinishedEvent& event) {
  if (!transfer_active) {
    return;
  }
  UpdatePage* owner = active_page;
  transfer_active = false;
  active_page = nullptr;
  abort_button->deactivate();
  set_widget_label(status_metrics, "");
  switch (event.outcome) {
    case TransferOutcome::completed:
      set_widget_label(status_state, t("state.completed"));
      status_progress->value(100.0);
      if (owner != nullptr) {
        if (!owner->history_has_entries) {
          owner->history->clear();
          owner->history_has_entries = true;
        }
        owner->history->add(
            (active_filename + "     " + t("state.completed")).c_str());
      }
      break;
    case TransferOutcome::aborted:
      set_widget_label(status_state, t("state.aborted"));
      break;
    case TransferOutcome::failed:
      set_widget_label(status_state, t("state.failed"));
      if (owner != nullptr) {
        set_widget_label(owner->error,
                         localized_backend_message(configuration.translator,
                                                   event.detail, false));
      }
      break;
  }
  active_filename.clear();
  refresh_action_buttons();
}

void WorkTransferWindow::Impl::apply(const MockEvent& event) {
  apply_mock_result(event);
}

void WorkTransferWindow::Impl::drain_events() {
  std::deque<Event> queued;
  {
    std::lock_guard lock(async->mutex);
    queued.swap(async->events);
    async->wake_pending = false;
  }
  for (const auto& event : queued) {
    std::visit([this](const auto& value) { apply(value); }, event);
  }
  window->redraw();
}

void WorkTransferWindow::Impl::tab_callback(Fl_Widget* widget, void* data) {
  auto* self = static_cast<Impl*>(data);
  const auto found =
      std::find(self->tab_buttons.begin(), self->tab_buttons.end(), widget);
  if (found != self->tab_buttons.end()) {
    self->select_tab(static_cast<int>(found - self->tab_buttons.begin()));
  }
}

void WorkTransferWindow::Impl::browse_callback(Fl_Widget*, void* data) {
  auto* page = static_cast<UpdatePage*>(data);
  page->owner->choose_source(*page);
}

void WorkTransferWindow::Impl::start_callback(Fl_Widget*, void* data) {
  auto* page = static_cast<UpdatePage*>(data);
  page->owner->start_transfer(*page);
}

void WorkTransferWindow::Impl::run_tests_callback(Fl_Widget*, void* data) {
  static_cast<Impl*>(data)->run_mock_tests();
}

void WorkTransferWindow::Impl::input_changed_callback(Fl_Widget*, void* data) {
  static_cast<Impl*>(data)->connection_changed();
}

void WorkTransferWindow::Impl::choose_key_callback(Fl_Widget*, void* data) {
  static_cast<Impl*>(data)->choose_key();
}

void WorkTransferWindow::Impl::test_connection_callback(Fl_Widget*, void* data) {
  static_cast<Impl*>(data)->test_connection();
}

void WorkTransferWindow::Impl::language_callback(Fl_Widget*, void* data) {
  static_cast<Impl*>(data)->save_language();
}

void WorkTransferWindow::Impl::abort_callback(Fl_Widget*, void* data) {
  static_cast<Impl*>(data)->abort_transfer();
}

void WorkTransferWindow::Impl::close_callback(Fl_Widget*, void* data) {
  static_cast<Impl*>(data)->close_requested();
}

WorkTransferWindow::WorkTransferWindow(UiConfiguration configuration,
                                       UiCallbacks callbacks)
    : Fl_Double_Window(kInitialWidth, kInitialHeight),
      impl_(std::make_unique<Impl>(this, std::move(configuration),
                                  std::move(callbacks))) {
  set_widget_label(this, impl_->t("app.title"));
}

WorkTransferWindow::~WorkTransferWindow() = default;

void WorkTransferWindow::resize(int x, int y, int width, int height) {
  Fl_Double_Window::resize(x, y, width, height);
  if (impl_ != nullptr) {
    impl_->layout(width, height);
  }
}

int WorkTransferWindow::handle(int event) {
  if (event == FL_SHORTCUT && (Fl::event_state() & FL_CTRL) != 0) {
    const int key = Fl::event_key();
    if (key >= '1' && key <= '5') {
      impl_->select_tab(key - '1');
      return 1;
    }
  }
  return Fl_Double_Window::handle(event);
}

void WorkTransferWindow::post_connection_result(bool successful,
                                                std::string detail) {
  Impl::post_event(impl_->async,
                   Impl::ConnectionEvent{successful, false, std::move(detail)});
}

void WorkTransferWindow::post_connection_degraded(std::string detail) {
  Impl::post_event(impl_->async,
                   Impl::ConnectionEvent{false, true, std::move(detail)});
}

void WorkTransferWindow::post_transfer_progress(TransferProgressView progress) {
  Impl::post_event(impl_->async, Impl::ProgressEvent{std::move(progress)});
}

void WorkTransferWindow::post_transfer_finished(TransferOutcome outcome,
                                                std::string detail) {
  Impl::post_event(impl_->async,
                   Impl::FinishedEvent{outcome, std::move(detail)});
}

}  // namespace work_transfer
