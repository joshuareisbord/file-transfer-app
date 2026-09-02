#pragma once

#include <span>
#include <string_view>

namespace work_transfer {

struct EmbeddedResource {
    std::string_view logical_path;
    std::string_view contents;
};

/** Return an embedded application resource, or an empty view when unknown. */
[[nodiscard]] std::string_view embedded_resource(std::string_view logical_path) noexcept;

/** Return every language catalog discovered when CMake configured the build. */
[[nodiscard]] std::span<const EmbeddedResource> embedded_language_catalogs() noexcept;

}  // namespace work_transfer
