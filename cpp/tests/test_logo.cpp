#include "work_transfer/logo.hpp"

#include <FL/Fl_Image.H>
#include <FL/Fl_RGB_Image.H>

#include <array>
#include <filesystem>
#include <fstream>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {

void require(bool condition, std::string_view message = "requirement failed") {
  if (!condition) {
    throw std::runtime_error(std::string(message));
  }
}

void write_file(const std::filesystem::path& path, std::string_view contents) {
  std::ofstream stream(path, std::ios::binary | std::ios::trunc);
  stream << contents;
  if (!stream) {
    throw std::runtime_error("unable to write logo fixture");
  }
}

}  // namespace

int main() {
  const auto temporary_directory = std::filesystem::temp_directory_path();
  const auto svg_path = temporary_directory / "work-transfer-logo-test.svg";
  write_file(svg_path, R"(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 32">
<rect width="64" height="32" fill="#123456"/>
</svg>)");
  const auto logo = work_transfer::load_header_logo(svg_path);
  require(logo != nullptr);
  require(logo->w() == 48 && logo->h() == 24);
  const auto* svg_pixels = dynamic_cast<const Fl_RGB_Image*>(logo.get());
  require(svg_pixels != nullptr && svg_pixels->data() != nullptr &&
              svg_pixels->data()[0] != nullptr,
          "SVG logo must contain rendered RGBA pixels");
  const auto* center = reinterpret_cast<const unsigned char*>(
      svg_pixels->data()[0] + ((12 * 48 + 24) * 4));
  require(center[0] == 0x12U && center[1] == 0x34U && center[2] == 0x56U &&
              center[3] == 0xFFU,
          "SVG logo must render its declared fill color");

  write_file(svg_path, R"(<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 10 10">
<script>alert(1)</script>
</svg>)");
  bool rejected = false;
  try {
    static_cast<void>(work_transfer::load_header_logo(svg_path));
  } catch (const work_transfer::LogoError&) {
    rejected = true;
  }
  require(rejected, "active SVG content must be rejected");

  constexpr std::array<unsigned char, 68> png_bytes{
      0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0x00, 0x00, 0x00,
      0x0d, 0x49, 0x48, 0x44, 0x52, 0x00, 0x00, 0x00, 0x01, 0x00, 0x00,
      0x00, 0x01, 0x08, 0x04, 0x00, 0x00, 0x00, 0xb5, 0x1c, 0x0c, 0x02,
      0x00, 0x00, 0x00, 0x0b, 0x49, 0x44, 0x41, 0x54, 0x78, 0xda, 0x63,
      0x64, 0xf8, 0x0f, 0x00, 0x01, 0x05, 0x01, 0x01, 0x27, 0x18, 0xe3,
      0x66, 0x00, 0x00, 0x00, 0x00, 0x49, 0x45, 0x4e, 0x44, 0xae, 0x42,
      0x60, 0x82};
  const auto png_path = temporary_directory / "work-transfer-logo-test.png";
  write_file(png_path,
             std::string_view(reinterpret_cast<const char*>(png_bytes.data()),
                              png_bytes.size()));
  const auto raster_logo = work_transfer::load_header_logo(png_path);
  require(raster_logo != nullptr, "validated PNG bytes must decode");
  require(raster_logo->w() == 48 && raster_logo->h() == 48,
          "raster logo must be scaled from the validated image");

  const auto symlink_path =
      temporary_directory / "work-transfer-logo-test-link.png";
  std::filesystem::remove(symlink_path);
  std::filesystem::create_symlink(png_path, symlink_path);
  rejected = false;
  try {
    static_cast<void>(work_transfer::load_header_logo(symlink_path));
  } catch (const work_transfer::LogoError&) {
    rejected = true;
  }
  require(rejected, "logo ingestion must not follow a replaceable symbolic link");

  std::filesystem::remove(svg_path);
  std::filesystem::remove(symlink_path);
  std::filesystem::remove(png_path);
}
