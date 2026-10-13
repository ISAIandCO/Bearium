/* MPL-2.0. Classify verifier-selected certificates; never grant trust. */
#ifndef RufoxCAIdentity_h
#define RufoxCAIdentity_h

#include <climits>
#include <cstring>
#include "RutheniumRoot.h"
#include "RufoxPolicyHelpers.h"
#include "pk11pub.h"

namespace mozilla::psm::rufox {
enum class CAIdentity { Other, Root, Intermediate, Unavailable };

inline CAIdentity IdentifyCA(const uint8_t* der, size_t length) {
  if (!der || !length || length > INT_MAX) return CAIdentity::Unavailable;
  if (length == sizeof(kRutheniumRussianRootDER) &&
      memcmp(der, kRutheniumRussianRootDER, length) == 0) {
    return CAIdentity::Root;
  }
  uint8_t digest[32];
  if (PK11_HashBuf(SEC_OID_SHA256, digest, der, static_cast<int32_t>(length)) !=
      SECSuccess) {
    return CAIdentity::Unavailable;
  }
  return IsProtectedIntermediateHash(digest, sizeof(digest))
             ? CAIdentity::Intermediate : CAIdentity::Other;
}
}  // namespace mozilla::psm::rufox
#endif
