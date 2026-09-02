#include "work_transfer/localization.hpp"

#include <nlohmann/json.hpp>

#include <algorithm>
#include <cctype>
#include <set>
#include <sstream>
#include <utility>

#include "work_transfer/resources.hpp"

namespace work_transfer {
namespace {

std::vector<std::string> placeholders(std::string_view text) {
  std::vector<std::string> fields;
  for (std::size_t index = 0; index < text.size();) {
    if (text[index] == '{') {
      if (index + 1 < text.size() && text[index + 1] == '{') {
        index += 2;
        continue;
      }
      const std::size_t end = text.find('}', index + 1);
      if (end == std::string_view::npos) {
        throw LocalizationError("translation contains an unmatched '{'");
      }
      const std::string field(text.substr(index + 1, end - index - 1));
      if (field.empty() ||
          !(std::isalpha(static_cast<unsigned char>(field.front())) != 0 ||
            field.front() == '_') ||
          !std::all_of(field.begin() + 1, field.end(), [](unsigned char value) {
            return std::isalnum(value) != 0 || value == '_';
          })) {
        throw LocalizationError("translation has an invalid placeholder");
      }
      fields.push_back(field);
      index = end + 1;
      continue;
    }
    if (text[index] == '}') {
      if (index + 1 < text.size() && text[index + 1] == '}') {
        index += 2;
        continue;
      }
      throw LocalizationError("translation contains an unmatched '}'");
    }
    ++index;
  }
  std::sort(fields.begin(), fields.end());
  fields.erase(std::unique(fields.begin(), fields.end()), fields.end());
  return fields;
}

std::string render(std::string_view text,
                   const std::map<std::string, std::string>& values) {
  std::string result;
  result.reserve(text.size());
  for (std::size_t index = 0; index < text.size();) {
    if (text[index] == '{' && index + 1 < text.size() &&
        text[index + 1] == '{') {
      result.push_back('{');
      index += 2;
      continue;
    }
    if (text[index] == '}' && index + 1 < text.size() &&
        text[index + 1] == '}') {
      result.push_back('}');
      index += 2;
      continue;
    }
    if (text[index] == '{') {
      const std::size_t end = text.find('}', index + 1);
      if (end == std::string_view::npos) {
        throw LocalizationError("translation contains an unmatched '{'");
      }
      const std::string key(text.substr(index + 1, end - index - 1));
      const auto value = values.find(key);
      if (value == values.end()) {
        throw LocalizationError("missing placeholder value: " + key);
      }
      result.append(value->second);
      index = end + 1;
      continue;
    }
    result.push_back(text[index]);
    ++index;
  }
  return result;
}

std::string filename_only(std::string_view path) {
  const std::size_t slash = path.find_last_of("/\\");
  return std::string(slash == std::string_view::npos ? path
                                                      : path.substr(slash + 1));
}

}  // namespace

Translator::Translator(std::string language_code,
                       std::vector<CatalogSource> sources) {
  for (const auto& source : sources) {
    try {
      const nlohmann::json document = nlohmann::json::parse(source.json);
      if (!document.is_object() || !document.contains("metadata") ||
          !document.contains("strings") ||
          !document.at("metadata").is_object() ||
          !document.at("strings").is_object()) {
        throw LocalizationError(
            "catalog must contain metadata and strings objects");
      }
      const auto& metadata = document.at("metadata");
      if (!metadata.contains("code") || !metadata.at("code").is_string() ||
          !metadata.contains("name") || !metadata.at("name").is_string()) {
        throw LocalizationError("catalog metadata requires code and name");
      }
      Catalog catalog;
      catalog.metadata.code = metadata.at("code").get<std::string>();
      catalog.metadata.name = metadata.at("name").get<std::string>();
      if (catalog.metadata.code.empty() || catalog.metadata.name.empty()) {
        throw LocalizationError("catalog metadata values must be non-empty");
      }
      if (filename_only(source.filename) != catalog.metadata.code + ".json") {
        throw LocalizationError(
            "metadata code must match the catalog filename");
      }
      for (const auto& [key, value] : document.at("strings").items()) {
        if (!value.is_string()) {
          throw LocalizationError("translation values must be strings");
        }
        std::string translated = value.get<std::string>();
        static_cast<void>(placeholders(translated));
        catalog.strings.emplace(key, std::move(translated));
      }
      catalogs_.insert_or_assign(catalog.metadata.code, std::move(catalog));
    } catch (const LocalizationError& error) {
      add_warning({"invalid_catalog", "warnings.invalid_catalog",
                   {{"filename", source.filename}, {"detail", error.what()}}});
    } catch (const nlohmann::json::exception& error) {
      add_warning({"invalid_catalog", "warnings.invalid_catalog",
                   {{"filename", source.filename}, {"detail", error.what()}}});
    }
  }

  const auto english = catalogs_.find("en");
  if (english == catalogs_.end()) {
    throw LocalizationError("the English language catalog is missing or invalid");
  }
  english_ = &english->second;
  const auto selected = catalogs_.find(language_code);
  if (selected == catalogs_.end()) {
    selected_ = english_;
    language_code_ = "en";
    add_warning({"language_not_found", "warnings.language_not_found",
                 {{"language", std::move(language_code)}}});
  } else {
    selected_ = &selected->second;
    language_code_ = selected_->metadata.code;
  }

  for (const auto& [code, catalog] : catalogs_) {
    static_cast<void>(code);
    languages_.push_back(catalog.metadata);
  }

  if (selected_ != english_) {
    for (const auto& [key, selected_text] : selected_->strings) {
      const auto english_text = english_->strings.find(key);
      if (english_text == english_->strings.end()) {
        continue;
      }
      if (placeholders(selected_text) != placeholders(english_text->second)) {
        invalid_placeholders_.push_back(key);
        add_warning({"placeholder_mismatch", "warnings.placeholder_mismatch",
                     {{"translation", key}}});
      }
    }
  }
}

Translator Translator::embedded(std::string_view language_code) {
  std::vector<CatalogSource> catalogs;
  for (const auto& resource : embedded_language_catalogs()) {
    catalogs.push_back(
        {filename_only(resource.logical_path), resource.contents});
  }
  return Translator(std::string(language_code), std::move(catalogs));
}

const std::string& Translator::language_code() const noexcept {
  return language_code_;
}

const std::vector<LanguageMetadata>& Translator::languages() const noexcept {
  return languages_;
}

const std::vector<LocalizationWarning>& Translator::warnings() const noexcept {
  return warnings_;
}

std::string Translator::translate(
    std::string_view key,
    const std::map<std::string, std::string>& values) const {
  const std::string* text = template_for(key);
  if (text == nullptr) {
    add_warning({"missing_key", "warnings.missing_key",
                 {{"translation", std::string(key)}}});
    return std::string(key);
  }
  try {
    return render(*text, values);
  } catch (const LocalizationError& error) {
    add_warning({"format_error", "warnings.format_error",
                 {{"translation", std::string(key)}, {"detail", error.what()}}});
    return *text;
  }
}

const std::string* Translator::template_for(std::string_view key) const {
  const std::string owned_key(key);
  const bool mismatched =
      std::find(invalid_placeholders_.begin(), invalid_placeholders_.end(),
                owned_key) != invalid_placeholders_.end();
  if (!mismatched) {
    const auto selected = selected_->strings.find(owned_key);
    if (selected != selected_->strings.end()) {
      return &selected->second;
    }
  }

  const auto english = english_->strings.find(owned_key);
  if (english == english_->strings.end()) {
    return nullptr;
  }
  if (selected_ != english_ &&
      selected_->strings.find(owned_key) == selected_->strings.end()) {
    add_warning({"missing_translation", "warnings.missing_translation",
                 {{"language", selected_->metadata.code},
                  {"translation", owned_key}}});
  }
  return &english->second;
}

void Translator::add_warning(LocalizationWarning warning) const {
  const auto duplicate = std::find_if(
      warnings_.begin(), warnings_.end(), [&](const LocalizationWarning& existing) {
        if (existing.code != warning.code) {
          return false;
        }
        const auto existing_translation = existing.values.find("translation");
        const auto new_translation = warning.values.find("translation");
        if (existing_translation == existing.values.end() ||
            new_translation == warning.values.end()) {
          return existing_translation == existing.values.end() &&
                 new_translation == warning.values.end();
        }
        return existing_translation->second == new_translation->second;
      });
  if (duplicate == warnings_.end()) {
    warnings_.push_back(std::move(warning));
  }
}

}  // namespace work_transfer
