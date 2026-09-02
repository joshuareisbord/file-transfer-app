#pragma once

#include <filesystem>
#include <memory>
#include <stdexcept>

class Fl_Image;

namespace work_transfer {

class LogoError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

/** Decode a bounded, passive SVG or raster logo into a 48px FLTK image. */
[[nodiscard]] std::unique_ptr<Fl_Image> load_header_logo(
    const std::filesystem::path& path);

}  // namespace work_transfer
