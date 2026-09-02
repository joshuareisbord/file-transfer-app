function(embed_work_transfer_resources output_source)
    set(resource_root "${CMAKE_CURRENT_SOURCE_DIR}")
    file(GLOB language_resource_files
        CONFIGURE_DEPENDS
        RELATIVE "${resource_root}"
        "${resource_root}/work_transfer_app/localization/languages/*.json"
    )
    list(SORT language_resource_files)
    set(resource_files
        ${language_resource_files}
        "work_transfer_app/config/tests.toml"
        "work_transfer_app/config/updates.toml"
        "work_transfer_app/ui/theme.toml"
    )
    list(LENGTH language_resource_files language_resource_count)

    set_property(
        DIRECTORY APPEND PROPERTY CMAKE_CONFIGURE_DEPENDS
        ${resource_files}
    )

    file(WRITE "${output_source}"
        "#include \"work_transfer/resources.hpp\"\n\n"
        "#include <array>\n"
        "#include <cstddef>\n\n"
        "namespace work_transfer {\n"
        "namespace {\n"
    )

    set(resource_index 0)
    foreach(resource_path IN LISTS resource_files)
        file(READ "${resource_root}/${resource_path}" resource_hex HEX)
        string(REGEX REPLACE "(..)" "0x\\1," resource_bytes "${resource_hex}")
        file(APPEND "${output_source}"
            "constexpr unsigned char resource_${resource_index}[] = {${resource_bytes}};\n"
        )
        math(EXPR resource_index "${resource_index} + 1")
    endforeach()

    file(APPEND "${output_source}"
        "\nconst std::array<EmbeddedResource, ${language_resource_count}> language_catalogs{{\n"
    )
    set(language_index 0)
    foreach(language_path IN LISTS language_resource_files)
        file(APPEND "${output_source}"
            "    EmbeddedResource{\"${language_path}\", "
            "{reinterpret_cast<const char*>(resource_${language_index}), "
            "sizeof(resource_${language_index})}},\n"
        )
        math(EXPR language_index "${language_index} + 1")
    endforeach()
    file(APPEND "${output_source}"
        "}};\n"
        "}  // namespace\n\n"
        "std::string_view embedded_resource(std::string_view logical_path) noexcept {\n"
    )

    set(resource_index 0)
    foreach(resource_path IN LISTS resource_files)
        file(APPEND "${output_source}"
            "    if (logical_path == \"${resource_path}\") {\n"
            "        return {reinterpret_cast<const char*>(resource_${resource_index}), "
            "sizeof(resource_${resource_index})};\n"
            "    }\n"
        )
        math(EXPR resource_index "${resource_index} + 1")
    endforeach()

    file(APPEND "${output_source}"
        "    return {};\n"
        "}\n\n"
        "std::span<const EmbeddedResource> embedded_language_catalogs() noexcept {\n"
        "    return language_catalogs;\n"
        "}\n\n"
        "}  // namespace work_transfer\n"
    )
endfunction()
