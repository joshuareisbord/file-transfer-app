#pragma once

#include <cstdint>
#include <map>
#include <stdexcept>
#include <string>
#include <string_view>

namespace work_transfer {

class ThemeError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

struct RgbColor {
  std::uint8_t red;
  std::uint8_t green;
  std::uint8_t blue;

  [[nodiscard]] bool operator==(const RgbColor&) const = default;
};

class ColorTheme {
 public:
  ColorTheme(std::map<std::string, RgbColor> palette,
             std::map<std::string, RgbColor> roles);

  [[nodiscard]] const RgbColor& color(std::string_view role) const;
  [[nodiscard]] const std::map<std::string, RgbColor>& palette() const noexcept;
  [[nodiscard]] const std::map<std::string, RgbColor>& roles() const noexcept;

 private:
  std::map<std::string, RgbColor> palette_;
  std::map<std::string, RgbColor> roles_;
};

[[nodiscard]] ColorTheme parse_theme(std::string_view document);
[[nodiscard]] ColorTheme load_embedded_theme();

}  // namespace work_transfer
