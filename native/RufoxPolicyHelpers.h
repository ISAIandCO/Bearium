/* MPL-2.0. Inputs are canonical ASCII hosts from Gecko, without a trailing dot. */
#ifndef RufoxPolicyHelpers_h
#define RufoxPolicyHelpers_h

#include <string_view>
#include <cstdint>
#include <limits>

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
                         std::string_view scope, uint64_t nowSeconds = 0) {
  if (host.empty() || host.find_first_of("|, \t\r\n") != std::string_view::npos) {
    return false;
  }
  while (!entries.empty()) {
    auto separator = entries.find(',');
    auto entry = entries.substr(0, separator);
    auto divider = entry.find('|');
    if (divider != std::string_view::npos && entry.substr(0, divider) == host) {
      auto allowed = entry.substr(divider + 1);
      auto expiryDivider = allowed.find('|');
      bool current = true;
      if (expiryDivider != std::string_view::npos) {
        auto expiry = allowed.substr(expiryDivider + 1);
        allowed = allowed.substr(0, expiryDivider);
        uint64_t until = 0;
        current = !expiry.empty() && nowSeconds != 0;
        for (char c : expiry) {
          if (c < '0' || c > '9' || until > (std::numeric_limits<uint64_t>::max() - 9) / 10) {
            current = false;
            break;
          }
          until = until * 10 + (c - '0');
        }
        current = current && nowSeconds < until;
      }
      if (current && (allowed == "all" || allowed == scope)) return true;
    }
    if (separator == std::string_view::npos) break;
    entries.remove_prefix(separator + 1);
  }
  return false;
}
}  // namespace mozilla::psm::rufox
#endif
