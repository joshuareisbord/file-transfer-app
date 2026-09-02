#include "work_transfer/theme.hpp"

#include <toml++/toml.hpp>

#include <set>
#include <sstream>
#include <utility>

#include "work_transfer/resources.hpp"

namespace work_transfer {
namespace {

constexpr std::string_view kThemeResource = "work_transfer_app/ui/theme.toml";

const std::set<std::string> kRequiredRoles = {
    "active_accent",
    "active_accent_text",
    "border",
    "button_active",
    "button_active_text",
    "canvas",
    "connection_connected",
    "connection_connected_text",
    "connection_degraded",
    "connection_degraded_text",
    "connection_disconnected",
    "connection_disconnected_text",
    "danger",
    "danger_active",
    "danger_active_text",
    "disabled",
    "disabled_text",
    "header",
    "header_muted",
    "header_text",
    "ink",
    "muted",
    "notice",
    "primary_action",
    "primary_action_active",
    "primary_action_text",
    "progress",
    "selection",
    "selection_text",
    "status_ink",
    "status_meta",
    "status_state",
    "status_surface",
    "success",
    "surface",
    "tab_active",
    "tab_active_text",
    "tab_selected",
    "tab_selected_text",
    "test_fail",
    "test_fail_text",
    "test_not_run",
    "test_not_run_text",
    "test_pass",
    "test_pass_text",
    "test_running",
    "test_running_text",
};

toml::table parse_toml(std::string_view document) {
  try {
    return toml::parse(document);
  } catch (const toml::parse_error& error) {
    throw ThemeError("theme is invalid TOML: " +
                     std::string(error.description()));
  }
}

RgbColor parse_rgb(const toml::node& node, std::string_view name) {
  const auto* values = node.as_array();
  if (values == nullptr || values->size() != 3) {
    throw ThemeError("palette." + std::string(name) +
                     " must contain exactly three RGB integers");
  }
  RgbColor color{};
  std::uint8_t* components[] = {&color.red, &color.green, &color.blue};
  for (std::size_t index = 0; index < 3; ++index) {
    const auto value = values->get(index)->value<std::int64_t>();
    if (!value.has_value() || *value < 0 || *value > 255) {
      throw ThemeError("palette." + std::string(name) +
                       " RGB values must be integers from 0 to 255");
    }
    *components[index] = static_cast<std::uint8_t>(*value);
  }
  return color;
}

}  // namespace

ColorTheme::ColorTheme(std::map<std::string, RgbColor> palette,
                       std::map<std::string, RgbColor> roles)
    : palette_(std::move(palette)), roles_(std::move(roles)) {}

const RgbColor& ColorTheme::color(std::string_view role) const {
  const auto found = roles_.find(std::string(role));
  if (found == roles_.end()) {
    throw ThemeError("unknown theme role: " + std::string(role));
  }
  return found->second;
}

const std::map<std::string, RgbColor>& ColorTheme::palette() const noexcept {
  return palette_;
}

const std::map<std::string, RgbColor>& ColorTheme::roles() const noexcept {
  return roles_;
}

ColorTheme parse_theme(std::string_view document) {
  toml::table root = parse_toml(document);
  const auto* palette_table = root["palette"].as_table();
  const auto* roles_table = root["roles"].as_table();
  if (palette_table == nullptr || roles_table == nullptr) {
    throw ThemeError("theme must contain palette and roles tables");
  }

  std::map<std::string, RgbColor> palette;
  for (const auto& [group_name, group_node] : *palette_table) {
    const auto* group = group_node.as_table();
    if (group == nullptr) {
      throw ThemeError("palette." + std::string(group_name.str()) +
                       " must be a TOML table");
    }
    for (const auto& [color_name, color_node] : *group) {
      const std::string qualified = std::string(group_name.str()) + "." +
                                    std::string(color_name.str());
      palette.emplace(qualified, parse_rgb(color_node, qualified));
    }
  }
  if (palette.empty()) {
    throw ThemeError("palette must define at least one color");
  }

  std::set<std::string> present_roles;
  std::map<std::string, RgbColor> roles;
  for (const auto& [role_name, reference_node] : *roles_table) {
    const auto reference = reference_node.value<std::string>();
    if (!reference.has_value()) {
      throw ThemeError("roles." + std::string(role_name.str()) +
                       " must reference a palette color");
    }
    const auto color = palette.find(*reference);
    if (color == palette.end()) {
      throw ThemeError("roles." + std::string(role_name.str()) +
                       " references unknown palette color: " + *reference);
    }
    present_roles.emplace(role_name.str());
    roles.emplace(role_name.str(), color->second);
  }

  std::vector<std::string> missing;
  for (const auto& required : kRequiredRoles) {
    if (!present_roles.contains(required)) {
      missing.push_back(required);
    }
  }
  if (!missing.empty()) {
    std::ostringstream message;
    message << "roles table is missing required roles:";
    for (const auto& role : missing) {
      message << ' ' << role;
    }
    throw ThemeError(message.str());
  }
  return ColorTheme(std::move(palette), std::move(roles));
}

ColorTheme load_embedded_theme() {
  return parse_theme(embedded_resource(kThemeResource));
}

}  // namespace work_transfer
