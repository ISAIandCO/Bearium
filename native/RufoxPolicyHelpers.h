/* MPL-2.0. Inputs are canonical ASCII hosts from Gecko, without a trailing dot. */
#ifndef RufoxPolicyHelpers_h
#define RufoxPolicyHelpers_h

#include <string_view>
#include <cstdint>
#include <limits>
#include <cstring>

namespace mozilla::psm::rufox {
// Restriction-only identities, not additional trust anchors. Exact DER SHA-256
// pins for Russian Trusted Sub CA RSA 2022 and RSA 2024, also reviewed in
// Goudron/good-bear 6845f1e, generate_good_bear_russian_pki_anchors.py.
inline bool IsProtectedIntermediateHash(const uint8_t* digest, size_t length) {
  static constexpr uint8_t hashes[][32] = {
    {0xbb,0xbd,0xe2,0x10,0x3e,0x79,0x0b,0x99,0x9e,0xc6,0x2b,0xd0,0x3c,0xf6,0x25,0xa5,
     0xa2,0xe7,0xc3,0x16,0xe1,0x0a,0xfe,0x6a,0x49,0x0e,0xed,0xea,0xd8,0xb3,0xfd,0x9b},
    {0x21,0x55,0x78,0x50,0x36,0xc9,0x00,0xdb,0xb5,0xf1,0xbb,0x2a,0x15,0x69,0xc8,0x0c,
     0x55,0x59,0x5b,0xd6,0xbf,0x94,0x86,0x7a,0x29,0xbb,0xdd,0xbc,0x7d,0x88,0xa3,0xf2},
  };
  if (!digest || length != 32) return false;
  for (const auto& hash : hashes) {
    if (memcmp(digest, hash, sizeof(hash)) == 0) return true;
  }
  return false;
}

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
