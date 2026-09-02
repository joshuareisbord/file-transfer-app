#include "work_transfer/config.hpp"

#include <filesystem>
#include <fstream>
#include <random>
#include <stdexcept>
#include <string>
#include <string_view>

namespace {

void require(bool condition, std::string_view message = "requirement failed") {
  if (!condition) {
    throw std::runtime_error(std::string(message));
  }
}

template <typename Function>
void require_config_error(Function&& function) {
  bool caught = false;
  try {
    function();
  } catch (const work_transfer::ConfigError&) {
    caught = true;
  }
  require(caught, "expected ConfigError");
}

}  // namespace

int main() {
  const auto destinations = work_transfer::parse_update_destinations(R"(
[destinations]
library_update = "~/alpha//./beta"
software_update = "/srv/releases"
)");
  require(destinations.library_update == "~/alpha/beta");
  require(destinations.software_update == "/srv/releases");

  require_config_error([] {
    static_cast<void>(work_transfer::parse_update_destinations(R"(
[destinations]
library_update = "relative/path"
software_update = "/srv/releases"
)"));
  });
  require_config_error([] {
    static_cast<void>(work_transfer::parse_update_destinations(
        "[destinations]\nlibrary_update = \"/safe\\u0000tail\"\n"
        "software_update = \"/srv/releases\"\n"));
  });

  const auto definitions = work_transfer::parse_mock_tests(R"(
[[tests]]
id = "first-check"
name = "First check"

[[tests]]
id = "second_check"
name = "Second check"
)");
  require(definitions.size() == 2);
  require(definitions.front().id == "first-check");
  require(definitions.back().name == "Second check");

  require_config_error([] {
    static_cast<void>(work_transfer::parse_mock_tests(
        "[[tests]]\nid = \"safe-id\"\nname = \"bad\\u0000name\"\n"));
  });
  require_config_error([] {
    static_cast<void>(work_transfer::parse_mock_tests(R"(
[[tests]]
id = "duplicate"
name = "First"
[[tests]]
id = "duplicate"
name = "Second"
)"));
  });

  std::mt19937 random_source(42);
  const auto plans = work_transfer::plan_mock_tests(64, random_source);
  require(plans.size() == 64);
  for (std::size_t index = 0; index < plans.size(); ++index) {
    require(plans[index].test_index == index);
    require(plans[index].delay.count() >= 1000);
    require(plans[index].delay.count() <= 5000);
  }

  const auto temporary_directory =
      std::filesystem::temp_directory_path() /
      ("work-transfer-cpp-settings-test-" +
       std::to_string(std::random_device{}()));
  std::filesystem::create_directories(temporary_directory);
  const auto temporary = temporary_directory / "settings.json";
  work_transfer::SettingsStore store(temporary);
  require(store.load_language() == "en");
  store.save_language("sample-Language_2");
  require(store.load_language() == "sample-Language_2");
  require_config_error([&store] { store.save_language("../unsafe"); });

  const auto protected_file = temporary_directory / "protected.txt";
  {
    std::ofstream protected_stream(protected_file,
                                   std::ios::binary | std::ios::trunc);
    protected_stream << "do-not-overwrite\n";
  }
  auto predictable_temporary = temporary;
  predictable_temporary.replace_extension(".tmp");
  std::filesystem::create_symlink(protected_file, predictable_temporary);
  store.save_language("symlink-safe");
  {
    std::ifstream protected_stream(protected_file, std::ios::binary);
    std::string protected_contents;
    std::getline(protected_stream, protected_contents);
    require(protected_contents == "do-not-overwrite",
            "settings save followed a predictable temporary-file symlink");
  }
  require(store.load_language() == "symlink-safe");

  {
    std::ofstream invalid(temporary, std::ios::binary | std::ios::trunc);
    invalid << "{not-json}";
  }
  require(store.load_language() == "en");
  require(!store.warnings().empty());
  std::filesystem::remove_all(temporary_directory);
}
