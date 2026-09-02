#pragma once

#include <map>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace work_transfer {

class LocalizationError : public std::runtime_error {
 public:
  using std::runtime_error::runtime_error;
};

struct LanguageMetadata {
  std::string code;
  std::string name;
};

struct LocalizationWarning {
  std::string code;
  std::string translation_key;
  std::map<std::string, std::string> values;
};

struct CatalogSource {
  std::string filename;
  std::string_view json;
};

class Translator {
 public:
  explicit Translator(std::string language_code,
                      std::vector<CatalogSource> catalogs);

  [[nodiscard]] static Translator embedded(
      std::string_view language_code = "en");
  [[nodiscard]] const std::string& language_code() const noexcept;
  [[nodiscard]] const std::vector<LanguageMetadata>& languages() const noexcept;
  [[nodiscard]] const std::vector<LocalizationWarning>& warnings() const noexcept;
  [[nodiscard]] std::string translate(
      std::string_view key,
      const std::map<std::string, std::string>& values = {}) const;

 private:
  struct Catalog {
    LanguageMetadata metadata;
    std::map<std::string, std::string> strings;
  };

  [[nodiscard]] const std::string* template_for(std::string_view key) const;
  void add_warning(LocalizationWarning warning) const;

  std::map<std::string, Catalog> catalogs_;
  const Catalog* english_ = nullptr;
  const Catalog* selected_ = nullptr;
  std::string language_code_;
  std::vector<LanguageMetadata> languages_;
  std::vector<std::string> invalid_placeholders_;
  mutable std::vector<LocalizationWarning> warnings_;
};

}  // namespace work_transfer
