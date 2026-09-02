#include "work_transfer/localization.hpp"

#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

namespace {

void require(bool condition, std::string_view message = "requirement failed") {
  if (!condition) {
    throw std::runtime_error(std::string(message));
  }
}

}  // namespace

int main() {
  constexpr std::string_view english = R"({
    "metadata": {"code": "en", "name": "English"},
    "strings": {
      "plain": "English value",
      "formatted": "Hello {name}",
      "braces": "Use {{value}}",
      "warnings.missing_key": "missing {translation}",
      "warnings.missing_translation": "missing {translation}",
      "warnings.placeholder_mismatch": "mismatch {translation}",
      "warnings.format_error": "format {translation} {detail}",
      "warnings.language_not_found": "language {language}",
      "warnings.invalid_catalog": "catalog {filename} {detail}"
    }
  })";
  constexpr std::string_view alternate = R"({
    "metadata": {"code": "xx", "name": "Example"},
    "strings": {
      "formatted": "Alternate {different}",
      "braces": "Literal {{value}}"
    }
  })";

  work_transfer::Translator translator(
      "xx", {{"en.json", english}, {"xx.json", alternate}});
  require(translator.language_code() == "xx");
  require(translator.languages().size() == 2);
  require(translator.translate("plain") == "English value");
  require(translator.translate("formatted", {{"name", "Ada"}}) == "Hello Ada");
  require(translator.translate("braces") == "Literal {value}");
  require(translator.translate("unknown") == "unknown");
  const auto warning_count = translator.warnings().size();
  require(translator.translate("unknown") == "unknown");
  require(translator.warnings().size() == warning_count);
  require(!translator.warnings().empty());

  work_transfer::Translator fallback("not-installed", {{"en.json", english}});
  require(fallback.language_code() == "en");
  require(fallback.translate("formatted", {{"name", "Grace"}}) ==
         "Hello Grace");
}
