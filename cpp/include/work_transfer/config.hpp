#pragma once

#include <chrono>
#include <cstddef>
#include <filesystem>
#include <random>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace work_transfer {

class ConfigError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

struct UpdateDestinations {
  std::string library_update;
  std::string software_update;
};

struct MockTestDefinition {
  std::string id;
  std::string name;
};

struct MockTestPlan {
  std::size_t test_index;
  std::chrono::milliseconds delay;
  bool passes;
};

[[nodiscard]] UpdateDestinations parse_update_destinations(
    std::string_view document);
[[nodiscard]] std::vector<MockTestDefinition> parse_mock_tests(
    std::string_view document);
[[nodiscard]] UpdateDestinations load_embedded_update_destinations();
[[nodiscard]] std::vector<MockTestDefinition> load_embedded_mock_tests();
[[nodiscard]] std::vector<MockTestPlan> plan_mock_tests(
    std::size_t count, std::mt19937& random_source);

[[nodiscard]] std::filesystem::path default_settings_path();

class SettingsStore {
 public:
  explicit SettingsStore(
      std::filesystem::path path = default_settings_path());

  [[nodiscard]] const std::filesystem::path& path() const noexcept;
  [[nodiscard]] std::string load_language();
  void save_language(std::string_view language_code);
  [[nodiscard]] const std::vector<std::string>& warnings() const noexcept;

 private:
  std::filesystem::path path_;
  std::vector<std::string> warnings_;
};

}  // namespace work_transfer
