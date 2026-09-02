cmake_minimum_required(VERSION 3.22)

project(work_transfer LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

include(CTest)
include(GNUInstallDirs)
include(cmake/EmbedResources.cmake)

find_package(Threads REQUIRED)
find_package(PkgConfig REQUIRED)
find_package(nlohmann_json CONFIG REQUIRED)
find_package(tomlplusplus CONFIG REQUIRED)
pkg_check_modules(RSVG REQUIRED IMPORTED_TARGET librsvg-2.0 cairo)
find_program(FLTK_CONFIG_EXECUTABLE NAMES fltk-config REQUIRED)

execute_process(
    COMMAND "${FLTK_CONFIG_EXECUTABLE}" --cxxflags
    OUTPUT_VARIABLE FLTK_COMPILE_FLAGS
    OUTPUT_STRIP_TRAILING_WHITESPACE
    COMMAND_ERROR_IS_FATAL ANY
)
execute_process(
    COMMAND "${FLTK_CONFIG_EXECUTABLE}" --use-images --ldstaticflags
    OUTPUT_VARIABLE FLTK_LINK_FLAGS
    OUTPUT_STRIP_TRAILING_WHITESPACE
    COMMAND_ERROR_IS_FATAL ANY
)
separate_arguments(FLTK_COMPILE_OPTIONS UNIX_COMMAND "${FLTK_COMPILE_FLAGS}")
separate_arguments(FLTK_LINK_OPTIONS UNIX_COMMAND "${FLTK_LINK_FLAGS}")

set(WORK_TRANSFER_SOURCES
    cpp/src/config.cpp
    cpp/src/localization.cpp
    cpp/src/logo.cpp
    cpp/src/theme.cpp
    cpp/src/transfer.cpp
    cpp/src/transfer_process.cpp
    cpp/src/ui.cpp
    cpp/src/ui_events.cpp
)

set(generated_resource_source "${CMAKE_CURRENT_BINARY_DIR}/generated/resources.cpp")
file(MAKE_DIRECTORY "${CMAKE_CURRENT_BINARY_DIR}/generated")
embed_work_transfer_resources("${generated_resource_source}")

add_library(work_transfer_core STATIC
    ${WORK_TRANSFER_SOURCES}
    "${generated_resource_source}"
)
target_include_directories(work_transfer_core PUBLIC cpp/include)
target_compile_options(work_transfer_core PRIVATE
    ${FLTK_COMPILE_OPTIONS}
    -Wall
    -Wextra
    -Wpedantic
    -Werror
    -fstack-protector-strong
    -D_FORTIFY_SOURCE=3
)
target_link_libraries(work_transfer_core PUBLIC
    Threads::Threads
    PkgConfig::RSVG
    nlohmann_json::nlohmann_json
    util
    ${FLTK_LINK_OPTIONS}
)

add_executable(work-transfer cpp/src/main.cpp)
target_link_libraries(work-transfer PRIVATE work_transfer_core)
target_compile_options(work-transfer PRIVATE
    -Wall
    -Wextra
    -Wpedantic
    -Werror
    -fstack-protector-strong
    -D_FORTIFY_SOURCE=3
)
target_link_options(work-transfer PRIVATE -Wl,-z,relro,-z,now)

install(TARGETS work-transfer RUNTIME DESTINATION "${CMAKE_INSTALL_BINDIR}")

if(BUILD_TESTING)
    file(GLOB WORK_TRANSFER_TEST_SOURCES CONFIGURE_DEPENDS cpp/tests/test_*.cpp)
    foreach(test_source IN LISTS WORK_TRANSFER_TEST_SOURCES)
        get_filename_component(test_name "${test_source}" NAME_WE)
        add_executable("${test_name}" "${test_source}")
        target_link_libraries("${test_name}" PRIVATE work_transfer_core)
        target_compile_options("${test_name}" PRIVATE
            -UNDEBUG
            -Wall
            -Wextra
            -Wpedantic
            -Werror
        )
        add_test(NAME "${test_name}" COMMAND "${test_name}")
    endforeach()

    add_test(NAME packaged_self_check COMMAND work-transfer --self-check)
endif()
