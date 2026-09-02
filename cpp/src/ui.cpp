#include "work_transfer/ui.hpp"
#include "ui_internal.hpp"

#include <FL/Fl.H>
#include <FL/Fl_Box.H>
#include <FL/Fl_Button.H>
#include <FL/Fl_Choice.H>
#include <FL/Fl_Group.H>
#include <FL/Fl_Hold_Browser.H>
#include <FL/Fl_Image.H>
#include <FL/Fl_Input.H>
#include <FL/Fl_Native_File_Chooser.H>
#include <FL/Fl_Progress.H>
#include <FL/Fl_Scroll.H>
#include <FL/Fl_Shared_Image.H>
#include <FL/fl_ask.H>

#include "work_transfer/logo.hpp"
#include "work_transfer/transfer.hpp"

#include <algorithm>
#include <array>
#include <atomic>
#include <charconv>
#include <cmath>
#include <cstddef>
#include <cstdint>
#include <deque>
#include <filesystem>
#include <iomanip>
#include <limits>
#include <map>
#include <memory>
#include <mutex>
#include <random>
#include <regex>
#include <sstream>
#include <string>
#include <string_view>
#include <utility>
#include <variant>
#include <vector>

namespace work_transfer {
using namespace ui_internal;

void WorkTransferWindow::Impl::build() {
  Fl::scheme("gtk+");
  Fl::set_font(FL_HELVETICA, "DejaVu Sans");
  Fl::set_font(FL_HELVETICA_BOLD, "DejaVu Sans Bold");
  fl_register_images();
  window->color(fl_color(configuration.theme, "canvas"));
  window->size_range(kMinimumWidth, kMinimumHeight);
  window->callback(close_callback, this);
  window->begin();
  build_header();
  build_tabs();
  build_status();
  window->end();
  window->resizable(pages[0]);
  select_tab(0);
  set_connection_health(ConnectionHealth::disconnected);
  show_idle();
  refresh_action_buttons();
}

void WorkTransferWindow::Impl::build_header() {
  header = new Fl_Group(0, 0, window->w(), kHeaderHeight);
  header->box(FL_FLAT_BOX);
  header->color(fl_color(configuration.theme, "header"));
  header->begin();

  int text_x = 20;
  if (configuration.logo_path.has_value()) {
    logo_image = load_header_logo(*configuration.logo_path);
    auto* logo = new Fl_Box(18, 16, 50, 50);
    logo->box(FL_FLAT_BOX);
    logo->color(fl_color(configuration.theme, "header"));
    logo->image(logo_image.get());
    logo->align(FL_ALIGN_CENTER | FL_ALIGN_INSIDE);
    text_x = 80;
  }

  auto* title = new Fl_Box(text_x, 13, 530, 30);
  style_box(title, fl_color(configuration.theme, "header"),
            fl_color(configuration.theme, "header_text"));
  title->labelfont(FL_HELVETICA_BOLD);
  title->labelsize(20);
  title->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(title, t("app.title"));

  auto* subtitle = new Fl_Box(text_x, 43, 620, 24);
  style_box(subtitle, fl_color(configuration.theme, "header"),
            fl_color(configuration.theme, "header_muted"));
  subtitle->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(subtitle, t("app.subtitle"));

  auto* spacer = new Fl_Box(620, 0, 100, kHeaderHeight);
  spacer->box(FL_NO_BOX);
  auto* health_label = new Fl_Box(window->w() - 330, 24, 160, 32);
  style_box(health_label, fl_color(configuration.theme, "header"),
            fl_color(configuration.theme, "header_muted"));
  health_label->align(FL_ALIGN_RIGHT | FL_ALIGN_INSIDE);
  set_widget_label(health_label, t("connection_health.label"));
  connection_health = new Fl_Box(window->w() - 158, 22, 138, 36);
  connection_health->box(FL_BORDER_BOX);
  connection_health->labelfont(FL_HELVETICA_BOLD);
  connection_health->labelsize(13);
  header->resizable(spacer);
  header->end();
}

void WorkTransferWindow::Impl::build_tabs() {
  constexpr std::array<std::string_view, 5> labels = {
      "tabs.library_update", "tabs.software_update", "tabs.test",
      "tabs.connection", "tabs.settings"};
  const int tab_width = window->w() / static_cast<int>(labels.size());
  for (std::size_t index = 0; index < labels.size(); ++index) {
    auto* button = new Fl_Button(static_cast<int>(index) * tab_width,
                                 kHeaderHeight, tab_width, kTabsHeight);
    button->box(FL_BORDER_BOX);
    button->down_box(FL_BORDER_BOX);
    button->color(fl_color(configuration.theme, "header"));
    button->selection_color(fl_color(configuration.theme, "tab_active"));
    button->labelcolor(fl_color(configuration.theme, "header_text"));
    button->labelfont(FL_HELVETICA_BOLD);
    button->labelsize(14);
    button->callback(tab_callback, this);
    set_widget_label(button, t(labels[index]));
    tab_buttons[index] = button;
  }

  library_page = build_update_page(UpdateKind::library, "library_update",
                                   configuration.destinations.library_update, 0);
  software_page = build_update_page(UpdateKind::software, "software_update",
                                    configuration.destinations.software_update, 1);
  build_test_page(2);
  build_connection_page(3);
  build_settings_page(4);
}

std::unique_ptr<WorkTransferWindow::Impl::UpdatePage>
WorkTransferWindow::Impl::build_update_page(UpdateKind kind, std::string prefix,
                                            std::string destination,
                                            int page_index) {
  auto page = std::make_unique<UpdatePage>();
  page->owner = this;
  page->kind = kind;
  page->prefix = std::move(prefix);
  page->destination = std::move(destination);
  const int top = kHeaderHeight + kTabsHeight;
  const int height = window->h() - top - kStatusHeight;
  page->group = new Fl_Group(0, top, window->w(), height);
  pages[static_cast<std::size_t>(page_index)] = page->group;
  page->group->box(FL_FLAT_BOX);
  page->group->color(fl_color(configuration.theme, "canvas"));
  page->group->begin();

  auto text = [&](std::string_view suffix) {
    return t(page->prefix + "." + std::string(suffix));
  };
  auto* heading = new Fl_Box(22, top + 15, window->w() - 44, 30);
  style_box(heading, fl_color(configuration.theme, "canvas"),
            fl_color(configuration.theme, "ink"));
  heading->labelfont(FL_HELVETICA_BOLD);
  heading->labelsize(19);
  heading->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(heading, text("heading"));
  auto* description = new Fl_Box(22, top + 45, window->w() - 44, 34);
  style_box(description, fl_color(configuration.theme, "canvas"),
            fl_color(configuration.theme, "muted"));
  description->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE | FL_ALIGN_WRAP);
  set_widget_label(description, text("description"));

  const int panel_top = top + 92;
  const int panel_height = std::max(230, height - 112);
  const int panel_width = (window->w() - 60) / 2;
  auto* form_panel = new Fl_Box(22, panel_top, panel_width, panel_height);
  style_box(form_panel, fl_color(configuration.theme, "surface"),
            fl_color(configuration.theme, "ink"), FL_BORDER_BOX);
  auto* form_heading = new Fl_Box(40, panel_top + 16, panel_width - 36, 26);
  style_box(form_heading, fl_color(configuration.theme, "surface"),
            fl_color(configuration.theme, "ink"));
  form_heading->labelfont(FL_HELVETICA_BOLD);
  form_heading->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(form_heading, text("source_label"));
  page->source_display =
      new Fl_Input(40, panel_top + 54, panel_width - 36, 36);
  page->source_display->readonly(1);
  page->source_display->textsize(13);
  page->source_display->value(text("source_placeholder").c_str());
  page->browse_button = new Fl_Button(40, panel_top + 102, 130, 38);
  style_button(page->browse_button, configuration.theme, false);
  set_widget_label(page->browse_button, t("common.browse"));
  page->browse_button->callback(browse_callback, page.get());
  page->start_button = new Fl_Button(40, panel_top + 162, 230, 42);
  style_button(page->start_button, configuration.theme, true);
  set_widget_label(page->start_button, text("start_transfer"));
  page->start_button->callback(start_callback, page.get());
  page->error = new Fl_Box(40, panel_top + 212, panel_width - 36,
                           std::max(30, panel_height - 226));
  style_box(page->error, fl_color(configuration.theme, "surface"),
            fl_color(configuration.theme, "danger"));
  page->error->align(FL_ALIGN_LEFT | FL_ALIGN_TOP | FL_ALIGN_INSIDE |
                     FL_ALIGN_WRAP);

  const int history_x = 38 + panel_width;
  auto* history_panel =
      new Fl_Box(history_x, panel_top, panel_width, panel_height);
  style_box(history_panel, fl_color(configuration.theme, "surface"),
            fl_color(configuration.theme, "ink"), FL_BORDER_BOX);
  auto* history_heading =
      new Fl_Box(history_x + 18, panel_top + 16, panel_width - 36, 26);
  style_box(history_heading, fl_color(configuration.theme, "surface"),
            fl_color(configuration.theme, "ink"));
  history_heading->labelfont(FL_HELVETICA_BOLD);
  history_heading->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(history_heading, text("history_title"));
  auto* columns =
      new Fl_Box(history_x + 18, panel_top + 50, panel_width - 36, 30);
  style_box(columns, fl_color(configuration.theme, "header"),
            fl_color(configuration.theme, "header_text"), FL_BORDER_BOX);
  columns->labelfont(FL_HELVETICA_BOLD);
  columns->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(columns,
             text("history_file") + "                              " +
                 text("history_status"));
  page->history = new Fl_Hold_Browser(history_x + 18, panel_top + 80,
                                      panel_width - 36, panel_height - 98);
  page->history->box(FL_BORDER_BOX);
  page->history->color(fl_color(configuration.theme, "surface"));
  page->history->textcolor(fl_color(configuration.theme, "ink"));
  page->history->selection_color(fl_color(configuration.theme, "selection"));
  page->history->textsize(13);
  page->history->add(text("history_empty").c_str());
  page->group->resizable(page->history);
  page->group->end();
  page->group->hide();
  return page;
}

void WorkTransferWindow::Impl::build_test_page(int page_index) {
  const int top = kHeaderHeight + kTabsHeight;
  const int height = window->h() - top - kStatusHeight;
  auto* group = new Fl_Group(0, top, window->w(), height);
  pages[static_cast<std::size_t>(page_index)] = group;
  group->box(FL_FLAT_BOX);
  group->color(fl_color(configuration.theme, "canvas"));
  group->begin();
  auto* heading = new Fl_Box(22, top + 15, window->w() - 44, 30);
  style_box(heading, fl_color(configuration.theme, "canvas"),
            fl_color(configuration.theme, "ink"));
  heading->labelfont(FL_HELVETICA_BOLD);
  heading->labelsize(19);
  heading->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(heading, t("test.heading"));
  auto* description = new Fl_Box(22, top + 45, window->w() - 44, 30);
  style_box(description, fl_color(configuration.theme, "canvas"),
            fl_color(configuration.theme, "muted"));
  description->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(description, t("test.description"));
  run_tests_button = new Fl_Button(22, top + 82, 150, 40);
  style_button(run_tests_button, configuration.theme, true);
  set_widget_label(run_tests_button, t("test.run"));
  run_tests_button->callback(run_tests_callback, this);

  auto* scroll =
      new Fl_Scroll(22, top + 136, window->w() - 44, height - 156);
  scroll->box(FL_BORDER_BOX);
  scroll->color(fl_color(configuration.theme, "surface"));
  scroll->begin();
  if (configuration.mock_tests.empty()) {
    auto* empty = new Fl_Box(40, top + 156, window->w() - 80, 36);
    style_box(empty, fl_color(configuration.theme, "surface"),
              fl_color(configuration.theme, "muted"));
    empty->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
    set_widget_label(empty, t("test.no_tests"));
    run_tests_button->deactivate();
  } else {
    test_rows.reserve(configuration.mock_tests.size());
    for (std::size_t index = 0; index < configuration.mock_tests.size(); ++index) {
      const int row_y = top + 154 + static_cast<int>(index) * 52;
      auto* status_color = new Fl_Box(40, row_y + 9, 28, 28);
      style_box(status_color, fl_color(configuration.theme, "test_not_run"),
                fl_color(configuration.theme, "test_not_run_text"),
                FL_BORDER_BOX);
      auto* result = new Fl_Box(80, row_y, 105, 46);
      style_box(result, fl_color(configuration.theme, "surface"),
                fl_color(configuration.theme, "ink"));
      result->labelfont(FL_HELVETICA_BOLD);
      result->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
      set_widget_label(result, t("test.not_run"));
      auto* name = new Fl_Box(195, row_y, window->w() - 250, 46);
      style_box(name, fl_color(configuration.theme, "surface"),
                fl_color(configuration.theme, "ink"));
      name->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE | FL_ALIGN_WRAP);
      set_widget_label(name, configuration.mock_tests[index].name);
      test_rows.push_back({status_color, result});
    }
  }
  scroll->end();
  group->resizable(scroll);
  group->end();
  group->hide();
}

void WorkTransferWindow::Impl::build_connection_page(int page_index) {
  const int top = kHeaderHeight + kTabsHeight;
  const int height = window->h() - top - kStatusHeight;
  auto* group = new Fl_Group(0, top, window->w(), height);
  pages[static_cast<std::size_t>(page_index)] = group;
  group->box(FL_FLAT_BOX);
  group->color(fl_color(configuration.theme, "canvas"));
  group->begin();
  auto* heading = new Fl_Box(22, top + 15, window->w() - 44, 30);
  style_box(heading, fl_color(configuration.theme, "canvas"),
            fl_color(configuration.theme, "ink"));
  heading->labelfont(FL_HELVETICA_BOLD);
  heading->labelsize(19);
  heading->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(heading, t("connection.heading"));
  auto* description = new Fl_Box(22, top + 45, window->w() - 44, 34);
  style_box(description, fl_color(configuration.theme, "canvas"),
            fl_color(configuration.theme, "muted"));
  description->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE | FL_ALIGN_WRAP);
  set_widget_label(description, t("connection.description"));

  auto* panel = new Fl_Group(22, top + 92, window->w() - 44,
                             std::min(350, height - 112));
  panel->box(FL_BORDER_BOX);
  panel->color(fl_color(configuration.theme, "surface"));
  panel->begin();
  constexpr int margin = 22;
  constexpr int column_gap = 28;
  constexpr int row_height = 64;
  const int column_width = (panel->w() - margin * 2 - column_gap) / 2;
  const int left_x = panel->x() + margin;
  const int right_x = left_x + column_width + column_gap;
  const int fields_y = panel->y() + 12;
  auto add_field = [&](int column, int row, std::string_view key,
                       bool secret = false) -> Fl_Input* {
    const int x = column == 0 ? left_x : right_x;
    const int y = fields_y + row * row_height;
    auto* label = new Fl_Box(x, y, column_width, 20);
    style_box(label, fl_color(configuration.theme, "surface"),
              fl_color(configuration.theme, "ink"));
    label->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
    set_widget_label(label, t(key));
    Fl_Input* input = secret
                          ? static_cast<Fl_Input*>(
                                new Fl_Secret_Input(x, y + 22, column_width, 34))
                          : new Fl_Input(x, y + 22, column_width, 34);
    input->textsize(14);
    input->when(FL_WHEN_CHANGED);
    input->callback(input_changed_callback, this);
    return input;
  };

  host_input = add_field(0, 0, "connection.host");
  username_input = add_field(0, 1, "connection.username");
  password_input = static_cast<Fl_Secret_Input*>(
      add_field(0, 2, "connection.password", true));
  password_input->maximum_size(1024);
  port_input = add_field(1, 0, "connection.port");
  port_input->value("22");
  library_destination_input =
      add_field(1, 1, "connection.library_destination");
  library_destination_input->value(
      configuration.destinations.library_update.c_str());
  software_destination_input =
      add_field(1, 2, "connection.software_destination");
  software_destination_input->value(
      configuration.destinations.software_update.c_str());

  const int action_y = panel->y() + panel->h() - 54;
  connection_detail = new Fl_Box(panel->x() + margin, action_y,
                                 panel->w() - margin * 2 - 192, 40);
  style_box(connection_detail, fl_color(configuration.theme, "surface"),
            fl_color(configuration.theme, "muted"));
  connection_detail->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE | FL_ALIGN_WRAP);
  set_widget_label(connection_detail, t("connection.status_untested"));
  test_connection_button = new Fl_Button(panel->x() + panel->w() - margin - 176,
                                         action_y, 176, 40);
  style_button(test_connection_button, configuration.theme, true);
  set_widget_label(test_connection_button, t("connection.test"));
  test_connection_button->callback(test_connection_callback, this);
  panel->end();
  panel->resizable(software_destination_input);
  group->resizable(panel);
  group->end();
  group->hide();
}

void WorkTransferWindow::Impl::build_settings_page(int page_index) {
  const int top = kHeaderHeight + kTabsHeight;
  const int height = window->h() - top - kStatusHeight;
  auto* group = new Fl_Group(0, top, window->w(), height);
  pages[static_cast<std::size_t>(page_index)] = group;
  group->box(FL_FLAT_BOX);
  group->color(fl_color(configuration.theme, "canvas"));
  group->begin();
  auto* heading = new Fl_Box(22, top + 15, window->w() - 44, 30);
  style_box(heading, fl_color(configuration.theme, "canvas"),
            fl_color(configuration.theme, "ink"));
  heading->labelfont(FL_HELVETICA_BOLD);
  heading->labelsize(19);
  heading->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(heading, t("settings.heading"));
  auto* description = new Fl_Box(22, top + 45, window->w() - 44, 34);
  style_box(description, fl_color(configuration.theme, "canvas"),
            fl_color(configuration.theme, "muted"));
  description->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(description, t("settings.description"));

  auto* panel = new Fl_Group(22, top + 92, window->w() - 44,
                             std::min(330, height - 112));
  panel->box(FL_BORDER_BOX);
  panel->color(fl_color(configuration.theme, "surface"));
  panel->begin();
  auto make_label = [&](int y, std::string_view key) {
    auto* label = new Fl_Box(44, y, 190, 36);
    style_box(label, fl_color(configuration.theme, "surface"),
              fl_color(configuration.theme, "ink"));
    label->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
    set_widget_label(label, t(key));
  };
  make_label(top + 112, "settings.language");
  language_choice = new Fl_Choice(250, top + 112, window->w() - 300, 36);
  int selected_index = -1;
  for (std::size_t index = 0; index < configuration.translator.languages().size();
       ++index) {
    const auto& language = configuration.translator.languages()[index];
    language_choice->add(language.name.c_str());
    if (language.code == configuration.current_language) {
      selected_index = static_cast<int>(index);
    }
  }
  if (selected_index >= 0) {
    language_choice->value(selected_index);
  }
  language_choice->callback(language_callback, this);
  settings_notice = new Fl_Box(250, top + 154, window->w() - 300, 42);
  style_box(settings_notice, fl_color(configuration.theme, "surface"),
            fl_color(configuration.theme, "notice"));
  settings_notice->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE | FL_ALIGN_WRAP);
  make_label(top + 214, "settings.version");
  auto* version = new Fl_Box(250, top + 214, window->w() - 300, 36);
  style_box(version, fl_color(configuration.theme, "surface"),
            fl_color(configuration.theme, "ink"));
  version->labelfont(FL_HELVETICA_BOLD);
  version->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(version, configuration.version);
  make_label(top + 258, "settings.build");
  auto* build = new Fl_Box(250, top + 258, window->w() - 300, 36);
  style_box(build, fl_color(configuration.theme, "surface"),
            fl_color(configuration.theme, "ink"));
  build->labelfont(FL_HELVETICA_BOLD);
  build->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  set_widget_label(build, t("settings.build_packaged"));

  std::vector<std::string> warning_lines;
  for (const auto& warning : configuration.translator.warnings()) {
    warning_lines.push_back(t(warning.translation_key, warning.values));
  }
  if (configuration.settings != nullptr) {
    for (const auto& warning_key : configuration.settings->warnings()) {
      warning_lines.push_back(t(warning_key));
    }
  }
  if (!warning_lines.empty()) {
    std::ostringstream message;
    for (std::size_t index = 0; index < warning_lines.size(); ++index) {
      if (index > 0) {
        message << '\n';
      }
      message << warning_lines[index];
    }
    auto* warnings = new Fl_Box(44, top + 306, window->w() - 88, 60);
    style_box(warnings, fl_color(configuration.theme, "surface"),
              fl_color(configuration.theme, "danger"));
    warnings->align(FL_ALIGN_LEFT | FL_ALIGN_TOP | FL_ALIGN_INSIDE |
                    FL_ALIGN_WRAP);
    set_widget_label(warnings, message.str());
  }
  panel->end();
  panel->resizable(language_choice);
  group->resizable(panel);
  group->end();
  group->hide();
}

void WorkTransferWindow::Impl::build_status() {
  const int top = window->h() - kStatusHeight;
  status_group = new Fl_Group(0, top, window->w(), kStatusHeight);
  status_group->box(FL_BORDER_BOX);
  status_group->color(fl_color(configuration.theme, "status_surface"));
  status_group->begin();
  status_filename = new Fl_Box(18, top + 10, window->w() - 220, 24);
  style_box(status_filename, fl_color(configuration.theme, "status_surface"),
            fl_color(configuration.theme, "status_ink"));
  status_filename->labelfont(FL_HELVETICA_BOLD);
  status_filename->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  status_state = new Fl_Box(window->w() - 198, top + 10, 180, 24);
  style_box(status_state, fl_color(configuration.theme, "status_surface"),
            fl_color(configuration.theme, "status_state"));
  status_state->labelfont(FL_HELVETICA_BOLD);
  status_state->align(FL_ALIGN_RIGHT | FL_ALIGN_INSIDE);
  status_progress = new Fl_Progress(18, top + 43, window->w() - 178, 22);
  status_progress->minimum(0.0);
  status_progress->maximum(100.0);
  status_progress->value(0.0);
  status_progress->color(fl_color(configuration.theme, "surface"));
  status_progress->selection_color(fl_color(configuration.theme, "progress"));
  abort_button = new Fl_Button(window->w() - 146, top + 38, 128, 34);
  style_button(abort_button, configuration.theme, false);
  abort_button->labelcolor(fl_color(configuration.theme, "danger"));
  set_widget_label(abort_button, t("common.abort"));
  abort_button->callback(abort_callback, this);
  status_metrics = new Fl_Box(18, top + 75, window->w() - 36, 28);
  style_box(status_metrics, fl_color(configuration.theme, "status_surface"),
            fl_color(configuration.theme, "status_meta"));
  status_metrics->align(FL_ALIGN_LEFT | FL_ALIGN_INSIDE);
  status_group->resizable(status_progress);
  status_group->end();
}

void WorkTransferWindow::Impl::layout(int width, int height) {
  if (header == nullptr) {
    return;
  }
  header->resize(0, 0, width, kHeaderHeight);
  const int tab_width = width / static_cast<int>(tab_buttons.size());
  for (std::size_t index = 0; index < tab_buttons.size(); ++index) {
    const int x = static_cast<int>(index) * tab_width;
    const int next_x = index + 1 == tab_buttons.size()
                           ? width
                           : static_cast<int>(index + 1) * tab_width;
    tab_buttons[index]->resize(x, kHeaderHeight, next_x - x, kTabsHeight);
  }
  const int body_top = kHeaderHeight + kTabsHeight;
  const int body_height = std::max(1, height - body_top - kStatusHeight);
  for (auto* page : pages) {
    if (page != nullptr) {
      page->resize(0, body_top, width, body_height);
    }
  }
  status_group->resize(0, height - kStatusHeight, width, kStatusHeight);
}

void WorkTransferWindow::Impl::select_tab(int index) {
  if (index < 0 || index >= static_cast<int>(pages.size())) {
    return;
  }
  for (std::size_t position = 0; position < pages.size(); ++position) {
    const bool selected = static_cast<int>(position) == index;
    if (selected) {
      pages[position]->show();
      tab_buttons[position]->color(
          fl_color(configuration.theme, "tab_selected"));
      tab_buttons[position]->labelcolor(
          fl_color(configuration.theme, "tab_selected_text"));
    } else {
      pages[position]->hide();
      tab_buttons[position]->color(fl_color(configuration.theme, "header"));
      tab_buttons[position]->labelcolor(
          fl_color(configuration.theme, "header_text"));
    }
    tab_buttons[position]->redraw();
  }
  window->redraw();
}

void WorkTransferWindow::Impl::set_connection_health(ConnectionHealth health) {
  std::string_view state;
  std::string_view background;
  std::string_view foreground;
  switch (health) {
    case ConnectionHealth::connected:
      state = "connected";
      background = "connection_connected";
      foreground = "connection_connected_text";
      break;
    case ConnectionHealth::degraded:
      state = "degraded";
      background = "connection_degraded";
      foreground = "connection_degraded_text";
      break;
    case ConnectionHealth::disconnected:
      state = "disconnected";
      background = "connection_disconnected";
      foreground = "connection_disconnected_text";
      break;
  }
  connection_health->color(fl_color(configuration.theme, background));
  connection_health->labelcolor(fl_color(configuration.theme, foreground));
  set_widget_label(connection_health,
             t("connection_health." + std::string(state)));
  connection_health->redraw();
}

void WorkTransferWindow::Impl::refresh_action_buttons() {
  for (auto* page : {library_page.get(), software_page.get()}) {
    if (page == nullptr) {
      continue;
    }
    if (connection_ready && !connection_test_active && !transfer_active) {
      page->start_button->activate();
    } else {
      page->start_button->deactivate();
    }
  }
  if (!connection_test_active && !transfer_active) {
    test_connection_button->activate();
  } else {
    test_connection_button->deactivate();
  }
}

void WorkTransferWindow::Impl::choose_source(UpdatePage& page) {
  Fl_Native_File_Chooser chooser;
  chooser.title(t(page.prefix + ".choose_file").c_str());
  chooser.type(Fl_Native_File_Chooser::BROWSE_FILE);
  const int result = chooser.show();
  if (result == 0 && chooser.filename() != nullptr) {
    page.source = std::filesystem::absolute(chooser.filename()).lexically_normal();
    page.source_display->value(page.source.c_str());
    set_widget_label(page.error, "");
  } else if (result == -1) {
    set_widget_label(page.error, chooser.errmsg() == nullptr ? t("errors.unexpected")
                                                       : chooser.errmsg());
  }
}

void WorkTransferWindow::Impl::start_transfer(UpdatePage& page) {
  set_widget_label(page.error, "");
  if (connection_test_active) {
    set_widget_label(page.error, t("connection.status_testing"));
    return;
  }
  if (!connection_ready) {
    set_widget_label(page.error, t(page.prefix + ".connection_required"));
    return;
  }
  if (transfer_active) {
    set_widget_label(page.error, t("errors.transfer_active"));
    return;
  }
  if (page.source.empty()) {
    set_widget_label(page.error, t(page.prefix + ".source_required"));
    return;
  }
  std::error_code error;
  if (!std::filesystem::is_regular_file(page.source, error) || error) {
    set_widget_label(page.error, t(page.prefix + ".source_missing"));
    return;
  }

  const auto request = TransferStartRequest{page.kind, page.source,
                                            page.destination};
  try {
    if (!callbacks.start_transfer) {
      throw std::runtime_error("transfer callback is unavailable");
    }
    callbacks.start_transfer(request);
  } catch (const std::exception& caught) {
    set_widget_label(page.error,
               t("errors.transfer", {{"message", caught.what()}}));
    return;
  }
  active_page = &page;
  transfer_active = true;
  show_connecting(page.source.filename().string());
  page.source.clear();
  page.source_display->value(
      t(page.prefix + ".source_placeholder").c_str());
  refresh_action_buttons();
}

void WorkTransferWindow::Impl::run_mock_tests() {
  if (remaining_tests != 0 || configuration.mock_tests.empty()) {
    return;
  }
  ++test_generation;
  remaining_tests = configuration.mock_tests.size();
  run_tests_button->deactivate();
  std::random_device entropy;
  std::mt19937 random_source(entropy());
  const auto plans = plan_mock_tests(configuration.mock_tests.size(), random_source);
  for (const auto& plan : plans) {
    set_test_state(plan.test_index, "running");
    struct TimeoutPayload {
      std::shared_ptr<AsyncState> state;
      MockEvent event;
    };
    auto* payload = new TimeoutPayload{
        async, {test_generation, plan.test_index, plan.passes}};
    Fl::add_timeout(
        static_cast<double>(plan.delay.count()) / 1000.0,
        [](void* data) {
          std::unique_ptr<TimeoutPayload> payload(
              static_cast<TimeoutPayload*>(data));
          post_event(payload->state, std::move(payload->event));
        },
        payload);
  }
}

void WorkTransferWindow::Impl::apply_mock_result(const MockEvent& event) {
  if (event.generation != test_generation || remaining_tests == 0 ||
      event.index >= test_rows.size()) {
    return;
  }
  set_test_state(event.index, event.passes ? "pass" : "fail");
  --remaining_tests;
  if (remaining_tests == 0) {
    run_tests_button->activate();
  }
}

void WorkTransferWindow::Impl::set_test_state(std::size_t index,
                                              std::string_view state) {
  if (index >= test_rows.size()) {
    return;
  }
  std::string_view background;
  std::string_view foreground;
  if (state == "pass") {
    background = "test_pass";
    foreground = "test_pass_text";
  } else if (state == "fail") {
    background = "test_fail";
    foreground = "test_fail_text";
  } else if (state == "running") {
    background = "test_running";
    foreground = "test_running_text";
  } else {
    background = "test_not_run";
    foreground = "test_not_run_text";
  }
  auto& row = test_rows[index];
  row.color->color(fl_color(configuration.theme, background));
  row.color->labelcolor(fl_color(configuration.theme, foreground));
  row.color->redraw();
  set_widget_label(row.result, t("test." + std::string(state)));
}

void WorkTransferWindow::Impl::connection_changed() {
  if (connection_ready) {
    set_widget_label(connection_detail, t("connection.status_invalidated"));
  }
  connection_ready = false;
  set_connection_health(ConnectionHealth::disconnected);
  refresh_action_buttons();
  if (callbacks.connection_invalidated) {
    callbacks.connection_invalidated();
  }
}

void WorkTransferWindow::Impl::test_connection() {
  if (transfer_active || connection_test_active) {
    return;
  }
  const std::string host = host_input->value();
  const std::string username = username_input->value();
  const std::string password = password_input->value();
  const std::string port_text = port_input->value();
  const auto library_destination = detail::normalize_remote_directory(
      library_destination_input->value());
  const auto software_destination = detail::normalize_remote_directory(
      software_destination_input->value());
  if (host.empty()) {
    set_widget_label(connection_detail, t("validation.host_required"));
    return;
  }
  if (username.empty()) {
    set_widget_label(connection_detail, t("validation.username_required"));
    return;
  }
  if (password.empty()) {
    set_widget_label(connection_detail, t("validation.password_required"));
    return;
  }
  unsigned int port = 0;
  const auto parsed = std::from_chars(port_text.data(),
                                      port_text.data() + port_text.size(), port);
  if (parsed.ec != std::errc{} || parsed.ptr != port_text.data() + port_text.size()) {
    set_widget_label(connection_detail, t("validation.port_numeric"));
    return;
  }
  if (port < 1 || port > std::numeric_limits<std::uint16_t>::max()) {
    set_widget_label(connection_detail, t("validation.port_range"));
    return;
  }
  if (!library_destination.has_value()) {
    set_widget_label(connection_detail,
                     t("validation.library_destination_invalid"));
    return;
  }
  if (!software_destination.has_value()) {
    set_widget_label(connection_detail,
                     t("validation.software_destination_invalid"));
    return;
  }
  try {
    if (!callbacks.test_connection) {
      throw std::runtime_error("connection callback is unavailable");
    }
    library_page->destination = *library_destination;
    software_page->destination = *software_destination;
    callbacks.test_connection({.host = host,
                               .username = username,
                               .password = password,
                               .port = static_cast<std::uint16_t>(port)});
    connection_test_active = true;
    set_widget_label(connection_detail, t("connection.status_testing"));
    refresh_action_buttons();
  } catch (const std::exception& caught) {
    set_widget_label(connection_detail,
               t("errors.connection_failed", {{"detail", caught.what()}}));
  }
}

void WorkTransferWindow::Impl::save_language() {
  if (configuration.settings == nullptr || language_choice->value() < 0 ||
      language_choice->value() >=
          static_cast<int>(configuration.translator.languages().size())) {
    return;
  }
  const auto& language = configuration.translator.languages()[
      static_cast<std::size_t>(language_choice->value())];
  try {
    configuration.settings->save_language(language.code);
    set_widget_label(settings_notice, t("settings.restart_required"));
  } catch (const std::exception& caught) {
    set_widget_label(settings_notice,
               t("errors.settings_save_failed", {{"detail", caught.what()}}));
  }
}

void WorkTransferWindow::Impl::abort_transfer() {
  if (!transfer_active) {
    return;
  }
  abort_button->deactivate();
  set_widget_label(status_state, t("state.cancelling"));
  if (callbacks.abort_transfer) {
    callbacks.abort_transfer();
  }
}

void WorkTransferWindow::Impl::close_requested() {
  if (transfer_active &&
      fl_choice("%s", t("common.cancel").c_str(), t("common.close").c_str(),
                nullptr, t("dialogs.close_message").c_str()) != 1) {
    return;
  }
  if (transfer_active && callbacks.abort_transfer) {
    callbacks.abort_transfer();
  }
  if (callbacks.shutdown) {
    callbacks.shutdown();
  }
  window->hide();
}

void WorkTransferWindow::Impl::show_idle() {
  set_widget_label(status_filename, t("status.idle"));
  set_widget_label(status_state, "");
  set_widget_label(status_metrics, "");
  status_progress->value(0.0);
  abort_button->deactivate();
}

void WorkTransferWindow::Impl::show_connecting(std::string_view filename) {
  active_filename = filename;
  set_widget_label(status_filename,
             t("status.filename", {{"filename", std::string(filename)}}));
  set_widget_label(status_state, t("state.connecting"));
  set_widget_label(status_metrics,
             t("status.eta", {{"eta", t("status.eta_calculating")}}));
  status_progress->value(0.0);
  abort_button->activate();
}

}  // namespace work_transfer
