#include "work_transfer/config.hpp"

#include <nlohmann/json.hpp>
#include <toml++/toml.hpp>

#include <algorithm>
#include <cerrno>
#include <cstdlib>
#include <fcntl.h>
#include <fstream>
#include <regex>
#include <set>
#include <sstream>
#include <system_error>
#include <unistd.h>

#include "work_transfer/resources.hpp"

namespace work_transfer {
namespace {

constexpr std::string_view kUpdatesResource =
    "work_transfer_app/config/updates.toml";
constexpr std::string_view kTestsResource =
    "work_transfer_app/config/tests.toml";
constexpr std::string_view kSettingsWarning = "warnings.settings_invalid";

void require_exact_keys(const toml::table& table,
                        const std::set<std::string>& expected,
                        std::string_view context) {
  std::set<std::string> actual;
  for (const auto& [key, value] : table) {
    static_cast<void>(value);
    actual.emplace(key.str());
  }
  if (actual == expected) {
    return;
  }

  std::ostringstream message;
  message << context << " must contain exactly";
  for (const auto& key : expected) {
    message << " '" << key << "'";
  }
  throw ConfigError(message.str());
}

std::string require_string(const toml::table& table, std::string_view key,
                           std::string_view context) {
  const auto value = table[key].value<std::string>();
  if (!value.has_value()) {
    throw ConfigError(std::string(context) + "." + std::string(key) +
                      " must be a string");
  }
  return *value;
}

std::string normalize_remote_path(std::string_view raw,
                                  std::string_view field_name) {
  if (raw.empty() ||
      std::all_of(raw.begin(), raw.end(), [](unsigned char character) {
        return std::isspace(character) != 0;
      })) {
    throw ConfigError("'" + std::string(field_name) +
                      "' must be a nonblank string");
  }
  if (raw.find('\0') != std::string_view::npos ||
      raw.find('\n') != std::string_view::npos ||
      raw.find('\r') != std::string_view::npos) {
    throw ConfigError("'" + std::string(field_name) +
                      "' must not contain control characters");
  }

  const bool home_relative = raw.starts_with("~/");
  if (!home_relative && !raw.starts_with('/')) {
    throw ConfigError("'" + std::string(field_name) +
                      "' must be an absolute POSIX path or start with '~/'");
  }

  const std::string_view body = home_relative ? raw.substr(2) : raw.substr(1);
  std::vector<std::string> components;
  std::size_t begin = 0;
  while (begin <= body.size()) {
    const std::size_t end = body.find('/', begin);
    const std::string_view component =
        body.substr(begin, end == std::string_view::npos ? body.size() - begin
                                                        : end - begin);
    if (component == "..") {
      throw ConfigError("'" + std::string(field_name) +
                        "' must not contain '..'");
    }
    if (!component.empty() && component != ".") {
      components.emplace_back(component);
    }
    if (end == std::string_view::npos) {
      break;
    }
    begin = end + 1;
  }

  std::ostringstream normalized;
  normalized << (home_relative ? "~/" : "/");
  for (std::size_t index = 0; index < components.size(); ++index) {
    if (index > 0) {
      normalized << '/';
    }
    normalized << components[index];
  }
  return normalized.str();
}

toml::table parse_toml(std::string_view document,
                       std::string_view description) {
  try {
    return toml::parse(document);
  } catch (const toml::parse_error& error) {
    throw ConfigError(std::string(description) + " is invalid TOML: " +
                      error.description().data());
  }
}

bool valid_language_code(std::string_view code) {
  static const std::regex safe_code("^[A-Za-z0-9][A-Za-z0-9_-]*$");
  return std::regex_match(code.begin(), code.end(), safe_code);
}

std::string read_text_file(const std::filesystem::path& path) {
  std::ifstream stream(path, std::ios::binary);
  if (!stream) {
    throw std::filesystem::filesystem_error(
        "unable to open settings file", path,
        std::make_error_code(std::errc::io_error));
  }
  return {std::istreambuf_iterator<char>(stream),
          std::istreambuf_iterator<char>()};
}

}  // namespace

UpdateDestinations parse_update_destinations(std::string_view document) {
  toml::table root = parse_toml(document, "update configuration");
  require_exact_keys(root, {"destinations"}, "update configuration");
  const auto* destinations = root["destinations"].as_table();
  if (destinations == nullptr) {
    throw ConfigError("'destinations' must be a TOML table");
  }
  require_exact_keys(*destinations, {"library_update", "software_update"},
                     "destinations");

  return {
      normalize_remote_path(
          require_string(*destinations, "library_update", "destinations"),
          "library_update"),
      normalize_remote_path(
          require_string(*destinations, "software_update", "destinations"),
          "software_update"),
  };
}

std::vector<MockTestDefinition> parse_mock_tests(std::string_view document) {
  toml::table root = parse_toml(document, "mock-test configuration");
  require_exact_keys(root, {"tests"}, "mock-test configuration");
  const auto* entries = root["tests"].as_array();
  if (entries == nullptr || entries->empty()) {
    throw ConfigError(
        "'tests' must contain at least one ordered [[tests]] entry");
  }

  static const std::regex safe_id("^[A-Za-z0-9][A-Za-z0-9_-]*$");
  std::set<std::string> seen_ids;
  std::vector<MockTestDefinition> definitions;
  definitions.reserve(entries->size());
  for (std::size_t index = 0; index < entries->size(); ++index) {
    const auto* entry = entries->get(index)->as_table();
    if (entry == nullptr) {
      throw ConfigError("mock-test entries must be TOML tables");
    }
    require_exact_keys(*entry, {"id", "name"}, "mock-test entry");
    std::string id = require_string(*entry, "id", "mock-test entry");
    std::string name = require_string(*entry, "name", "mock-test entry");
    if (!std::regex_match(id, safe_id)) {
      throw ConfigError("mock-test id must be a safe identifier");
    }
    if (name.empty() ||
        std::all_of(name.begin(), name.end(), [](unsigned char character) {
          return std::isspace(character) != 0;
        }) ||
        name.find('\0') != std::string::npos ||
        name.find('\n') != std::string::npos ||
        name.find('\r') != std::string::npos) {
      throw ConfigError("mock-test name must be nonblank and single-line");
    }
    if (!seen_ids.emplace(id).second) {
      throw ConfigError("mock-test id '" + id + "' is duplicate");
    }
    definitions.push_back({std::move(id), std::move(name)});
  }
  return definitions;
}

UpdateDestinations load_embedded_update_destinations() {
  return parse_update_destinations(embedded_resource(kUpdatesResource));
}

std::vector<MockTestDefinition> load_embedded_mock_tests() {
  return parse_mock_tests(embedded_resource(kTestsResource));
}

std::vector<MockTestPlan> plan_mock_tests(std::size_t count,
                                         std::mt19937& random_source) {
  std::uniform_int_distribution<int> delay(1000, 5000);
  std::bernoulli_distribution passes(0.90);
  std::vector<MockTestPlan> plans;
  plans.reserve(count);
  for (std::size_t index = 0; index < count; ++index) {
    plans.push_back(
        {index, std::chrono::milliseconds(delay(random_source)),
         passes(random_source)});
  }
  return plans;
}

std::filesystem::path default_settings_path() {
  if (const char* xdg_home = std::getenv("XDG_CONFIG_HOME");
      xdg_home != nullptr && *xdg_home != '\0') {
    return std::filesystem::path(xdg_home) / "work-transfer" / "settings.json";
  }
  if (const char* home = std::getenv("HOME"); home != nullptr && *home != '\0') {
    return std::filesystem::path(home) / ".config" / "work-transfer" /
           "settings.json";
  }
  throw ConfigError(
      "HOME and XDG_CONFIG_HOME are unavailable; settings path is unknown");
}

SettingsStore::SettingsStore(std::filesystem::path path)
    : path_(std::move(path)) {}

const std::filesystem::path& SettingsStore::path() const noexcept {
  return path_;
}

std::string SettingsStore::load_language() {
  warnings_.clear();
  std::error_code error;
  if (!std::filesystem::exists(path_, error)) {
    if (error) {
      warnings_.emplace_back(kSettingsWarning);
    }
    return "en";
  }

  try {
    const nlohmann::json document = nlohmann::json::parse(read_text_file(path_));
    if (!document.is_object() || document.size() != 1 ||
        !document.contains("language") ||
        !document.at("language").is_string()) {
      throw ConfigError("invalid settings schema");
    }
    const std::string code = document.at("language").get<std::string>();
    if (!valid_language_code(code)) {
      throw ConfigError("invalid language code");
    }
    return code;
  } catch (const std::exception&) {
    warnings_.emplace_back(kSettingsWarning);
    return "en";
  }
}

void SettingsStore::save_language(std::string_view language_code) {
  if (!valid_language_code(language_code)) {
    throw ConfigError(
        "language code may contain only letters, digits, '-' or '_'");
  }
  warnings_.clear();
  std::filesystem::create_directories(path_.parent_path());
  const std::string document =
      nlohmann::json{{"language", language_code}}.dump(2) + '\n';
  const std::string template_path =
      (path_.parent_path() / (path_.filename().string() + ".tmp.XXXXXX"))
          .string();
  std::vector<char> template_buffer(template_path.begin(), template_path.end());
  template_buffer.push_back('\0');

  int descriptor = ::mkstemp(template_buffer.data());
  if (descriptor < 0) {
    throw std::filesystem::filesystem_error(
        "unable to create temporary settings file", path_.parent_path(),
        std::error_code(errno, std::generic_category()));
  }
  const std::filesystem::path temporary(template_buffer.data());
  const auto cleanup = [&]() noexcept {
    if (descriptor >= 0) {
      static_cast<void>(::close(descriptor));
      descriptor = -1;
    }
    std::error_code ignored;
    static_cast<void>(std::filesystem::remove(temporary, ignored));
  };

  try {
    if (::fcntl(descriptor, F_SETFD, FD_CLOEXEC) != 0) {
      throw std::filesystem::filesystem_error(
          "unable to secure temporary settings file", temporary,
          std::error_code(errno, std::generic_category()));
    }
    std::size_t written = 0;
    while (written < document.size()) {
      const auto result =
          ::write(descriptor, document.data() + written, document.size() - written);
      if (result < 0 && errno == EINTR) {
        continue;
      }
      if (result <= 0) {
        throw std::filesystem::filesystem_error(
            "unable to write temporary settings file", temporary,
            std::error_code(result < 0 ? errno : EIO, std::generic_category()));
      }
      written += static_cast<std::size_t>(result);
    }
    if (::fsync(descriptor) != 0) {
      throw std::filesystem::filesystem_error(
          "unable to write temporary settings file", temporary,
          std::error_code(errno, std::generic_category()));
    }
    const int close_result = ::close(descriptor);
    descriptor = -1;
    if (close_result != 0) {
      throw std::filesystem::filesystem_error(
          "unable to write temporary settings file", temporary,
          std::error_code(errno, std::generic_category()));
    }
    std::filesystem::rename(temporary, path_);
  } catch (...) {
    cleanup();
    throw;
  }
}

const std::vector<std::string>& SettingsStore::warnings() const noexcept {
  return warnings_;
}

}  // namespace work_transfer
