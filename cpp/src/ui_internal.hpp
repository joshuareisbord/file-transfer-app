#pragma once

#include "work_transfer/ui.hpp"

#include <FL/Fl.H>
#include <FL/Fl_Box.H>
#include <FL/Fl_Button.H>
#include <FL/Fl_Choice.H>
#include <FL/Fl_Group.H>
#include <FL/Fl_Hold_Browser.H>
#include <FL/Fl_Image.H>
#include <FL/Fl_Input.H>
#include <FL/Fl_Progress.H>
#include <FL/fl_draw.H>

#include <array>
#include <cstddef>
#include <deque>
#include <filesystem>
#include <map>
#include <memory>
#include <mutex>
#include <string>
#include <string_view>
#include <type_traits>
#include <utility>
#include <variant>
#include <vector>

namespace work_transfer {
namespace ui_internal {

inline constexpr int kInitialWidth = 1080;
inline constexpr int kInitialHeight = 760;
inline constexpr int kMinimumWidth = 900;
inline constexpr int kMinimumHeight = 650;
inline constexpr int kHeaderHeight = 82;
inline constexpr int kTabsHeight = 44;
inline constexpr int kStatusHeight = 118;

inline Fl_Color fl_color(const ColorTheme& theme, std::string_view role) {
  const auto color = theme.color(role);
  return fl_rgb_color(color.red, color.green, color.blue);
}

inline void set_widget_label(Fl_Widget* widget, const std::string& text) {
  widget->copy_label(text.c_str());
}

inline void style_box(Fl_Box* box, Fl_Color background, Fl_Color foreground,
                      Fl_Boxtype box_type = FL_FLAT_BOX) {
  box->box(box_type);
  box->color(background);
  box->labelcolor(foreground);
  box->labelfont(FL_HELVETICA);
  box->labelsize(14);
}

inline void style_button(Fl_Button* button, const ColorTheme& theme,
                         bool primary) {
  button->box(FL_BORDER_BOX);
  button->down_box(FL_BORDER_BOX);
  button->color(fl_color(theme, primary ? "primary_action" : "surface"));
  button->selection_color(
      fl_color(theme, primary ? "primary_action_active" : "button_active"));
  button->labelcolor(
      fl_color(theme, primary ? "primary_action_text" : "ink"));
  button->labelfont(FL_HELVETICA_BOLD);
  button->labelsize(14);
}

}  // namespace ui_internal

struct WorkTransferWindow::Impl {
  struct ConnectionEvent {
    bool successful;
    bool degraded;
    std::string detail;
  };
  struct ProgressEvent {
    TransferProgressView progress;
  };
  struct FinishedEvent {
    TransferOutcome outcome;
    std::string detail;
  };
  struct MockEvent {
    std::size_t generation;
    std::size_t index;
    bool passes;
  };
  using Event = std::variant<ConnectionEvent, ProgressEvent, FinishedEvent,
                             MockEvent>;

  struct AsyncState {
    std::mutex mutex;
    std::deque<Event> events;
    Impl* owner = nullptr;
    bool wake_pending = false;
  };

  struct UpdatePage {
    Impl* owner = nullptr;
    UpdateKind kind;
    std::string prefix;
    std::string destination;
    Fl_Group* group = nullptr;
    Fl_Input* source_display = nullptr;
    Fl_Button* browse_button = nullptr;
    Fl_Button* start_button = nullptr;
    Fl_Box* error = nullptr;
    Fl_Hold_Browser* history = nullptr;
    std::filesystem::path source;
    bool history_has_entries = false;
  };

  struct TestRow {
    Fl_Box* color = nullptr;
    Fl_Box* result = nullptr;
  };

  WorkTransferWindow* window;
  UiConfiguration configuration;
  UiCallbacks callbacks;
  std::shared_ptr<AsyncState> async = std::make_shared<AsyncState>();
  Fl_Group* header = nullptr;
  Fl_Box* connection_health = nullptr;
  std::array<Fl_Button*, 5> tab_buttons{};
  std::array<Fl_Group*, 5> pages{};
  std::unique_ptr<UpdatePage> library_page;
  std::unique_ptr<UpdatePage> software_page;
  std::vector<TestRow> test_rows;
  Fl_Button* run_tests_button = nullptr;
  std::size_t test_generation = 0;
  std::size_t remaining_tests = 0;
  Fl_Input* host_input = nullptr;
  Fl_Input* username_input = nullptr;
  Fl_Input* port_input = nullptr;
  Fl_Input* key_input = nullptr;
  Fl_Box* connection_detail = nullptr;
  Fl_Button* test_connection_button = nullptr;
  Fl_Choice* language_choice = nullptr;
  Fl_Box* settings_notice = nullptr;
  Fl_Group* status_group = nullptr;
  Fl_Box* status_filename = nullptr;
  Fl_Box* status_state = nullptr;
  Fl_Progress* status_progress = nullptr;
  Fl_Box* status_metrics = nullptr;
  Fl_Button* abort_button = nullptr;
  std::unique_ptr<Fl_Image> logo_image;
  UpdatePage* active_page = nullptr;
  std::string active_filename;
  bool connection_ready = false;
  bool connection_test_active = false;
  bool transfer_active = false;

  Impl(WorkTransferWindow* owner, UiConfiguration config, UiCallbacks actions)
      : window(owner),
        configuration(std::move(config)),
        callbacks(std::move(actions)) {
    async->owner = this;
    build();
  }

  ~Impl() {
    std::lock_guard lock(async->mutex);
    async->owner = nullptr;
    async->events.clear();
  }

  [[nodiscard]] std::string t(
      std::string_view key,
      const std::map<std::string, std::string>& values = {}) const {
    return configuration.translator.translate(key, values);
  }

  void build();
  void build_header();
  void build_tabs();
  std::unique_ptr<UpdatePage> build_update_page(UpdateKind kind,
                                                std::string prefix,
                                                std::string destination,
                                                int page_index);
  void build_test_page(int page_index);
  void build_connection_page(int page_index);
  void build_settings_page(int page_index);
  void build_status();
  void layout(int width, int height);
  void select_tab(int index);
  void set_connection_health(ConnectionHealth health);
  void refresh_action_buttons();
  void choose_source(UpdatePage& page);
  void start_transfer(UpdatePage& page);
  void run_mock_tests();
  void apply_mock_result(const MockEvent& event);
  void set_test_state(std::size_t index, std::string_view state);
  void connection_changed();
  void choose_key();
  void test_connection();
  void save_language();
  void abort_transfer();
  void close_requested();
  void show_idle();
  void show_connecting(std::string_view filename);
  void apply(const ConnectionEvent& event);
  void apply(const ProgressEvent& event);
  void apply(const FinishedEvent& event);
  void apply(const MockEvent& event);
  void drain_events();

  template <typename Value>
  static void post_event(const std::shared_ptr<AsyncState>& state, Value value) {
    bool schedule_wake = false;
    {
      std::lock_guard lock(state->mutex);
      if (state->owner == nullptr) {
        return;
      }
      if constexpr (std::is_same_v<std::decay_t<Value>, ProgressEvent>) {
        if (!state->events.empty() &&
            std::holds_alternative<ProgressEvent>(state->events.back())) {
          state->events.back() = std::move(value);
        } else {
          state->events.emplace_back(std::move(value));
        }
      } else {
        state->events.emplace_back(std::move(value));
      }
      if (!state->wake_pending) {
        state->wake_pending = true;
        schedule_wake = true;
      }
    }
    if (!schedule_wake) {
      return;
    }
    auto* keep_alive = new std::shared_ptr<AsyncState>(state);
    Fl::awake(
        [](void* data) {
          std::unique_ptr<std::shared_ptr<AsyncState>> holder(
              static_cast<std::shared_ptr<AsyncState>*>(data));
          Impl* owner = nullptr;
          {
            std::lock_guard lock((*holder)->mutex);
            owner = (*holder)->owner;
          }
          if (owner != nullptr) {
            owner->drain_events();
          }
        },
        keep_alive);
  }

  static void tab_callback(Fl_Widget* widget, void* data);
  static void browse_callback(Fl_Widget*, void* data);
  static void start_callback(Fl_Widget*, void* data);
  static void run_tests_callback(Fl_Widget*, void* data);
  static void input_changed_callback(Fl_Widget*, void* data);
  static void choose_key_callback(Fl_Widget*, void* data);
  static void test_connection_callback(Fl_Widget*, void* data);
  static void language_callback(Fl_Widget*, void* data);
  static void abort_callback(Fl_Widget*, void* data);
  static void close_callback(Fl_Widget*, void* data);
};

}  // namespace work_transfer
