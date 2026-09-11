/* MPL-2.0. Inputs are canonical ASCII hosts from Gecko, without a trailing dot. */
#ifndef RufoxPolicyHelpers_h
#define RufoxPolicyHelpers_h

#include <string_view>

namespace mozilla::psm::rufox {
inline bool AllowedZone(std::string_view host) {
  for (auto suffix : {std::string_view(".ru"), std::string_view(".su"),
                      std::string_view(".xn--p1ai")}) {
    if (host.size() > suffix.size() &&
        host.substr(host.size() - suffix.size()) == suffix) {
      return true;
    }
  }
  return false;
}

inline bool HasException(std::string_view entries, std::string_view host,
                         std::string_view scope) {
  if (host.empty() || host.find_first_of("|, \t\r\n") != std::string_view::npos) {
    return false;
  }
  while (!entries.empty()) {
    auto separator = entries.find(',');
    auto entry = entries.substr(0, separator);
    auto divider = entry.find('|');
    if (divider != std::string_view::npos && entry.substr(0, divider) == host) {
      auto allowed = entry.substr(divider + 1);
      if (allowed == "all" || allowed == scope) return true;
    }
    if (separator == std::string_view::npos) break;
    entries.remove_prefix(separator + 1);
  }
  return false;
}
}  // namespace mozilla::psm::rufox
#endif
