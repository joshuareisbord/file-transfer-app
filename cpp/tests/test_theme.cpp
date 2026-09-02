#include "work_transfer/theme.hpp"

#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

void require(bool condition, std::string_view message = "requirement failed") {
  if (!condition) {
    throw std::runtime_error(std::string(message));
  }
}

const std::vector<std::string> kRoles = {
    "active_accent", "active_accent_text", "border", "button_active",
    "button_active_text", "canvas", "connection_connected",
    "connection_connected_text", "connection_degraded",
    "connection_degraded_text", "connection_disconnected",
    "connection_disconnected_text", "danger", "danger_active",
    "danger_active_text", "disabled", "disabled_text", "header",
    "header_muted", "header_text", "ink", "muted", "notice",
    "primary_action", "primary_action_active", "primary_action_text",
    "progress", "selection", "selection_text", "status_ink", "status_meta",
    "status_state", "status_surface", "success", "surface", "tab_active",
    "tab_active_text", "tab_selected", "tab_selected_text", "test_fail",
    "test_fail_text", "test_not_run", "test_not_run_text", "test_pass",
    "test_pass_text", "test_running", "test_running_text"};

std::string valid_theme() {
  std::string document = "[palette.sample]\ncolor = [12, 34, 56]\n[roles]\n";
  for (const auto& role : kRoles) {
    document += role + " = \"sample.color\"\n";
  }
  return document;
}

}  // namespace

int main() {
  const auto theme = work_transfer::parse_theme(valid_theme());
  require(theme.color("canvas") == (work_transfer::RgbColor{12, 34, 56}));
  require(theme.roles().size() == kRoles.size());

  bool invalid_rgb = false;
  try {
    std::string document = valid_theme();
    document.replace(document.find("[12, 34, 56]"), 12, "[12, 34, 999]");
    static_cast<void>(work_transfer::parse_theme(document));
  } catch (const work_transfer::ThemeError&) {
    invalid_rgb = true;
  }
  require(invalid_rgb);
}
