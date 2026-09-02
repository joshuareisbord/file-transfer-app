#ifndef _GNU_SOURCE
#define _GNU_SOURCE
#endif

#include "work_transfer/logo.hpp"

#include <FL/Fl_BMP_Image.H>
#include <FL/Fl_GIF_Image.H>
#include <FL/Fl_Image.H>
#include <FL/Fl_JPEG_Image.H>
#include <FL/Fl_PNG_Image.H>
#include <FL/Fl_RGB_Image.H>
#include <cairo/cairo.h>
#include <librsvg/rsvg.h>

#include <algorithm>
#include <bit>
#include <cerrno>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fcntl.h>
#include <memory>
#include <regex>
#include <string>
#include <string_view>
#include <sys/mman.h>
#include <sys/stat.h>
#include <system_error>
#include <unistd.h>
#include <utility>

namespace work_transfer {
namespace {

constexpr std::uintmax_t kMaximumLogoBytes = 5U * 1024U * 1024U;
constexpr std::uint64_t kMaximumLogoPixels = 16'000'000U;
constexpr std::uint32_t kMaximumLogoSide = 4096U;

class FileDescriptor final {
 public:
  explicit FileDescriptor(int value) noexcept : value_(value) {}

  ~FileDescriptor() {
    if (value_ >= 0) {
      static_cast<void>(::close(value_));
    }
  }

  FileDescriptor(const FileDescriptor&) = delete;
  FileDescriptor& operator=(const FileDescriptor&) = delete;

  FileDescriptor(FileDescriptor&& other) noexcept
      : value_(std::exchange(other.value_, -1)) {}
  FileDescriptor& operator=(FileDescriptor&&) = delete;

  [[nodiscard]] int get() const noexcept { return value_; }

 private:
  int value_;
};

FileDescriptor immutable_backing_file(std::string_view contents) {
  FileDescriptor descriptor(
      ::memfd_create("work-transfer-logo", MFD_CLOEXEC | MFD_ALLOW_SEALING));
  if (descriptor.get() < 0) {
    throw LogoError("Unable to create private logo backing file.");
  }

  std::size_t offset = 0;
  while (offset < contents.size()) {
    const ssize_t written =
        ::write(descriptor.get(), contents.data() + offset,
                contents.size() - offset);
    if (written < 0) {
      if (errno == EINTR) {
        continue;
      }
      throw LogoError("Unable to populate private logo backing file.");
    }
    if (written == 0) {
      throw LogoError("Unable to populate private logo backing file.");
    }
    offset += static_cast<std::size_t>(written);
  }

  constexpr int seals =
      F_SEAL_SEAL | F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE;
  if (::fcntl(descriptor.get(), F_ADD_SEALS, seals) != 0) {
    throw LogoError("Unable to make private logo bytes immutable.");
  }
  return descriptor;
}

std::string lowercase(std::string text) {
  std::transform(text.begin(), text.end(), text.begin(), [](unsigned char value) {
    return static_cast<char>(std::tolower(value));
  });
  return text;
}

std::string read_bounded_file(const std::filesystem::path& path) {
  FileDescriptor descriptor(
      ::open(path.c_str(), O_RDONLY | O_CLOEXEC | O_NONBLOCK | O_NOFOLLOW));
  struct stat before {};
  if (descriptor.get() < 0 || ::fstat(descriptor.get(), &before) != 0 ||
      !S_ISREG(before.st_mode)) {
    throw LogoError("Logo path must reference a regular file.");
  }
  if (before.st_size <= 0 ||
      static_cast<std::uintmax_t>(before.st_size) > kMaximumLogoBytes) {
    throw LogoError("Logo must be non-empty and no larger than 5 MiB.");
  }

  std::string contents(static_cast<std::size_t>(before.st_size), '\0');
  off_t offset = 0;
  while (offset < before.st_size) {
    const auto count = ::pread(
        descriptor.get(), contents.data() + static_cast<std::size_t>(offset),
        static_cast<std::size_t>(before.st_size - offset), offset);
    if (count < 0 && errno == EINTR) {
      continue;
    }
    if (count <= 0) {
      throw LogoError("Logo changed while it was being read.");
    }
    offset += count;
  }

  char extra = 0;
  ssize_t extra_count = -1;
  do {
    extra_count = ::pread(descriptor.get(), &extra, 1, before.st_size);
  } while (extra_count < 0 && errno == EINTR);
  struct stat after {};
  const bool unchanged =
      ::fstat(descriptor.get(), &after) == 0 &&
      before.st_dev == after.st_dev && before.st_ino == after.st_ino &&
      before.st_mode == after.st_mode && before.st_size == after.st_size &&
      before.st_mtim.tv_sec == after.st_mtim.tv_sec &&
      before.st_mtim.tv_nsec == after.st_mtim.tv_nsec &&
      before.st_ctim.tv_sec == after.st_ctim.tv_sec &&
      before.st_ctim.tv_nsec == after.st_ctim.tv_nsec;
  if (extra_count != 0 || !unchanged) {
    throw LogoError("Logo changed while it was being read.");
  }
  return contents;
}

void reject_active_svg(std::string_view source) {
  const std::string normalized = lowercase(std::string(source));
  for (const std::string_view token : {"<!doctype", "<!entity", "<script",
                                       "<foreignobject", "@import"}) {
    if (normalized.find(token) != std::string::npos) {
      throw LogoError("SVG logo contains unsupported active content.");
    }
  }
  static const std::regex href(
      R"((?:href|xlink:href)\s*=\s*["']\s*([^"']+))",
      std::regex::icase);
  for (std::sregex_iterator match(normalized.begin(), normalized.end(), href), end;
       match != end; ++match) {
    if ((*match)[1].str().empty() || (*match)[1].str().front() != '#') {
      throw LogoError("SVG logo cannot load external resources.");
    }
  }
  static const std::regex url(R"(url\(\s*["']?\s*([^\s"')]+))",
                              std::regex::icase);
  for (std::sregex_iterator match(normalized.begin(), normalized.end(), url), end;
       match != end; ++match) {
    if ((*match)[1].str().empty() || (*match)[1].str().front() != '#') {
      throw LogoError("SVG logo cannot load external resources.");
    }
  }
}

std::pair<double, double> svg_dimensions(RsvgHandle* handle) {
  double width = 0.0;
  double height = 0.0;
  if (rsvg_handle_get_intrinsic_size_in_pixels(handle, &width, &height) == 0) {
    gboolean has_viewbox = 0;
    RsvgRectangle viewbox {};
    rsvg_handle_get_intrinsic_dimensions(handle, nullptr, nullptr, nullptr,
                                         nullptr, &has_viewbox, &viewbox);
    if (has_viewbox == 0) {
      throw LogoError("SVG logo has no usable intrinsic dimensions.");
    }
    width = viewbox.width;
    height = viewbox.height;
  }
  return {width, height};
}

unsigned char unpremultiply(unsigned char channel, unsigned char alpha) {
  if (alpha == 0U) {
    return 0U;
  }
  const auto expanded =
      (static_cast<unsigned int>(channel) * 255U + alpha / 2U) / alpha;
  return static_cast<unsigned char>(std::min(expanded, 255U));
}

std::unique_ptr<unsigned char[]> copy_cairo_pixels(cairo_surface_t* surface,
                                                   int width, int height) {
  cairo_surface_flush(surface);
  const unsigned char* source = cairo_image_surface_get_data(surface);
  const int stride = cairo_image_surface_get_stride(surface);
  if (source == nullptr || stride < width * 4) {
    throw LogoError("Unable to read rendered SVG pixels.");
  }

  auto result = std::make_unique<unsigned char[]>(
      static_cast<std::size_t>(width) * static_cast<std::size_t>(height) * 4U);
  for (int y = 0; y < height; ++y) {
    const unsigned char* row = source + static_cast<std::size_t>(y) * stride;
    for (int x = 0; x < width; ++x) {
      const unsigned char* input = row + static_cast<std::size_t>(x) * 4U;
      unsigned char* output =
          result.get() +
          (static_cast<std::size_t>(y) * static_cast<std::size_t>(width) +
           static_cast<std::size_t>(x)) *
              4U;
      unsigned char alpha = 0U;
      unsigned char red = 0U;
      unsigned char green = 0U;
      unsigned char blue = 0U;
      // Cairo stores premultiplied ARGB32 in native byte order, while FLTK
      // expects straight-alpha RGBA bytes for a four-channel Fl_RGB_Image.
      if constexpr (std::endian::native == std::endian::little) {
        blue = input[0];
        green = input[1];
        red = input[2];
        alpha = input[3];
      } else {
        alpha = input[0];
        red = input[1];
        green = input[2];
        blue = input[3];
      }
      output[0] = unpremultiply(red, alpha);
      output[1] = unpremultiply(green, alpha);
      output[2] = unpremultiply(blue, alpha);
      output[3] = alpha;
    }
  }
  return result;
}

std::unique_ptr<Fl_Image> load_svg_logo(const std::filesystem::path& path) {
  const std::string source = read_bounded_file(path);
  reject_active_svg(source);

  GError* parse_error = nullptr;
  RsvgHandle* parsed = rsvg_handle_new_from_data(
      reinterpret_cast<const guint8*>(source.data()), source.size(),
      &parse_error);
  if (parse_error != nullptr) {
    g_error_free(parse_error);
  }
  if (parsed == nullptr) {
    throw LogoError("SVG logo is malformed or unsupported.");
  }
  const auto release_handle = [](RsvgHandle* handle) { g_object_unref(handle); };
  std::unique_ptr<RsvgHandle, decltype(release_handle)> handle(parsed,
                                                              release_handle);
  rsvg_handle_set_dpi(handle.get(), 96.0);
  const auto [intrinsic_width, intrinsic_height] = svg_dimensions(handle.get());
  if (!std::isfinite(intrinsic_width) || !std::isfinite(intrinsic_height) ||
      intrinsic_width <= 0.0 || intrinsic_height <= 0.0 ||
      intrinsic_width > kMaximumLogoSide ||
      intrinsic_height > kMaximumLogoSide ||
      intrinsic_width * intrinsic_height > kMaximumLogoPixels) {
    throw LogoError("SVG logo dimensions exceed the safe limit.");
  }

  constexpr int target = 48;
  const double scale =
      std::min(target / intrinsic_width, target / intrinsic_height);
  const int width =
      std::max(1, static_cast<int>(std::round(intrinsic_width * scale)));
  const int height =
      std::max(1, static_cast<int>(std::round(intrinsic_height * scale)));

  cairo_surface_t* raw_surface =
      cairo_image_surface_create(CAIRO_FORMAT_ARGB32, width, height);
  const auto release_surface = [](cairo_surface_t* surface) {
    cairo_surface_destroy(surface);
  };
  std::unique_ptr<cairo_surface_t, decltype(release_surface)> surface(
      raw_surface, release_surface);
  if (cairo_surface_status(surface.get()) != CAIRO_STATUS_SUCCESS) {
    throw LogoError("Unable to initialize SVG rendering surface.");
  }

  cairo_t* raw_context = cairo_create(surface.get());
  const auto release_context = [](cairo_t* context) { cairo_destroy(context); };
  std::unique_ptr<cairo_t, decltype(release_context)> context(raw_context,
                                                             release_context);
  if (cairo_status(context.get()) != CAIRO_STATUS_SUCCESS) {
    throw LogoError("Unable to initialize SVG renderer.");
  }
  cairo_set_operator(context.get(), CAIRO_OPERATOR_CLEAR);
  cairo_paint(context.get());
  cairo_set_operator(context.get(), CAIRO_OPERATOR_OVER);

  const RsvgRectangle viewport{0.0, 0.0, static_cast<double>(width),
                               static_cast<double>(height)};
  GError* render_error = nullptr;
  const gboolean rendered = rsvg_handle_render_document(
      handle.get(), context.get(), &viewport, &render_error);
  if (render_error != nullptr) {
    g_error_free(render_error);
  }
  if (rendered == 0 || cairo_status(context.get()) != CAIRO_STATUS_SUCCESS ||
      cairo_surface_status(surface.get()) != CAIRO_STATUS_SUCCESS) {
    throw LogoError("Unable to render SVG logo.");
  }

  auto pixels = copy_cairo_pixels(surface.get(), width, height);
  auto result = std::make_unique<Fl_RGB_Image>(pixels.release(), width, height, 4);
  result->alloc_array = 1;
  if (result->fail() != 0) {
    throw LogoError("Unable to create rendered SVG image.");
  }
  return result;
}

std::pair<std::uint32_t, std::uint32_t> raster_dimensions(
    std::string_view bytes, std::string_view extension) {
  const auto byte = [&](std::size_t index) {
    return static_cast<std::uint8_t>(bytes[index]);
  };
  const auto big16 = [&](std::size_t index) {
    return static_cast<std::uint32_t>((byte(index) << 8U) | byte(index + 1));
  };
  const auto big32 = [&](std::size_t index) {
    return (static_cast<std::uint32_t>(byte(index)) << 24U) |
           (static_cast<std::uint32_t>(byte(index + 1)) << 16U) |
           (static_cast<std::uint32_t>(byte(index + 2)) << 8U) |
           static_cast<std::uint32_t>(byte(index + 3));
  };
  if (extension == ".png" && bytes.size() >= 24 &&
      bytes.substr(0, 8) == std::string_view("\x89PNG\r\n\x1a\n", 8)) {
    return {big32(16), big32(20)};
  }
  if (extension == ".gif" && bytes.size() >= 10 &&
      (bytes.starts_with("GIF87a") || bytes.starts_with("GIF89a"))) {
    return {static_cast<std::uint32_t>(byte(6) | (byte(7) << 8U)),
            static_cast<std::uint32_t>(byte(8) | (byte(9) << 8U))};
  }
  if (extension == ".bmp" && bytes.size() >= 26 && bytes.starts_with("BM")) {
    const auto little32 = [&](std::size_t index) {
      return static_cast<std::uint32_t>(byte(index)) |
             (static_cast<std::uint32_t>(byte(index + 1)) << 8U) |
             (static_cast<std::uint32_t>(byte(index + 2)) << 16U) |
             (static_cast<std::uint32_t>(byte(index + 3)) << 24U);
    };
    return {little32(18), little32(22) & 0x7FFFFFFFU};
  }
  if ((extension == ".jpg" || extension == ".jpeg") && bytes.size() >= 4 &&
      byte(0) == 0xFFU && byte(1) == 0xD8U) {
    std::size_t offset = 2;
    while (offset + 8 < bytes.size()) {
      if (byte(offset) != 0xFFU) {
        ++offset;
        continue;
      }
      while (offset < bytes.size() && byte(offset) == 0xFFU) {
        ++offset;
      }
      if (offset >= bytes.size()) {
        break;
      }
      const std::uint8_t marker = byte(offset++);
      if (marker == 0xD8U || marker == 0xD9U || marker == 0x01U ||
          (marker >= 0xD0U && marker <= 0xD7U)) {
        continue;
      }
      if (offset + 2 > bytes.size()) {
        break;
      }
      const std::uint32_t length = big16(offset);
      if (length < 2 || offset + length > bytes.size()) {
        break;
      }
      const bool start_of_frame =
          (marker >= 0xC0U && marker <= 0xC3U) ||
          (marker >= 0xC5U && marker <= 0xC7U) ||
          (marker >= 0xC9U && marker <= 0xCBU) ||
          (marker >= 0xCDU && marker <= 0xCFU);
      if (start_of_frame && length >= 7) {
        return {big16(offset + 5), big16(offset + 3)};
      }
      offset += length;
    }
  }
  throw LogoError("Logo has an unsupported or malformed image header.");
}

std::unique_ptr<Fl_Image> load_raster_logo(
    const std::filesystem::path& path, std::string_view extension) {
  const std::string contents = read_bounded_file(path);
  const auto [width, height] = raster_dimensions(contents, extension);
  if (width == 0 || height == 0 || width > kMaximumLogoSide ||
      height > kMaximumLogoSide ||
      static_cast<std::uint64_t>(width) * height > kMaximumLogoPixels) {
    throw LogoError("Logo dimensions exceed the safe limit.");
  }
  const double scale = std::min(48.0 / width, 48.0 / height);
  const int target_width =
      std::max(1, static_cast<int>(std::round(width * scale)));
  const int target_height =
      std::max(1, static_cast<int>(std::round(height * scale)));

  const FileDescriptor backing_file = immutable_backing_file(contents);
  const std::string backing_path =
      "/proc/self/fd/" + std::to_string(backing_file.get());
  std::unique_ptr<Fl_Image> decoded;
  if (extension == ".png") {
    decoded = std::make_unique<Fl_PNG_Image>(backing_path.c_str());
  } else if (extension == ".jpg" || extension == ".jpeg") {
    decoded = std::make_unique<Fl_JPEG_Image>(backing_path.c_str());
  } else if (extension == ".gif") {
    decoded = std::make_unique<Fl_GIF_Image>(backing_path.c_str());
  } else if (extension == ".bmp") {
    decoded = std::make_unique<Fl_BMP_Image>(backing_path.c_str());
  }
  if (decoded == nullptr || decoded->fail() != 0 || decoded->w() <= 0 ||
      decoded->h() <= 0 ||
      decoded->w() != static_cast<int>(width) ||
      decoded->h() != static_cast<int>(height)) {
    throw LogoError("Unable to decode logo image.");
  }

  std::unique_ptr<Fl_Image> image(
      decoded->copy(target_width, target_height));
  if (image == nullptr || image->fail() != 0 || image->w() != target_width ||
      image->h() != target_height) {
    throw LogoError("Unable to copy decoded logo image.");
  }
  return image;
}

}  // namespace

std::unique_ptr<Fl_Image> load_header_logo(
    const std::filesystem::path& path) {
  const std::string extension = lowercase(path.extension().string());
  if (extension == ".svg") {
    return load_svg_logo(path);
  }
  if (extension == ".png" || extension == ".jpg" || extension == ".jpeg" ||
      extension == ".gif" || extension == ".bmp") {
    return load_raster_logo(path, extension);
  }
  throw LogoError("Unsupported logo format. Use SVG, PNG, JPEG, GIF, or BMP.");
}

}  // namespace work_transfer
