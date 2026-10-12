"""Run the production C++ guards, plus the existing fail-closed patch contracts."""
import ctypes.util
import hashlib
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest

from scripts import native_policy, patch_firefox


@unittest.skipUnless(shutil.which("g++"), "g++ required")
class NativeHardeningTests(unittest.TestCase):
    def compile_and_run(self, directory, source, *flags):
        path = Path(directory) / "check.cpp"
        path.write_text(source)
        binary = Path(directory) / "check"
        subprocess.run(["g++", "-std=c++17", "-Wall", "-Wextra", "-Werror",
                        "-I", directory, "-I", str(native_policy.NATIVE),
                        str(path), *flags, "-o", str(binary)], check=True)
        subprocess.run([str(binary)], check=True)

    @unittest.skipUnless(ctypes.util.find_library("nss3"), "system NSS required")
    def test_ca_identity_uses_real_nss_sha256(self):
        # Thin declarations for NSS's stable C ABI let this host check run
        # without Gecko or NSS development headers. There is no fake hash.
        der = patch_firefox.load_verified_certificate()
        expected = ",".join(str(byte) for byte in hashlib.sha256(der).digest())
        cache_fragment = native_policy.token_cache('''#include "SSLTokensCache.h"
  if (!readChain(aInfo.mHandshakeCertificatesBytes)) return false;''').partition(
            "if (!readChain(aInfo.mHandshakeCertificatesBytes)) return false;")[2]
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "RutheniumRoot.h").write_text(patch_firefox.generated_header(der))
            (root / "pk11pub.h").write_text('''#include <cstdint>
constexpr int SECSuccess = 0;
constexpr int SEC_OID_SHA256 = 191;
extern "C" int PK11_HashBuf(int, unsigned char*, const unsigned char*, int32_t);
extern "C" int NSS_NoDB_Init(const char*);
extern "C" int NSS_Shutdown();
''')
            self.compile_and_run(directory, '''#include "RufoxCAIdentity.h"
#include <cassert>
#include <vector>
#include <optional>
using namespace mozilla::psm::rufox;
struct Bytes {
  std::vector<uint8_t> value;
  const uint8_t* Elements() const { return value.data(); }
  size_t Length() const { return value.size(); }
};
struct Chain : std::vector<Bytes> {
  using std::vector<Bytes>::vector;
  bool IsEmpty() const { return empty(); }
};
struct Info { std::optional<Chain> mSucceededCertChainBytes; };
struct Token { bool cleared = false; void Clear() { cleared = true; } };
bool MayResume(Info& aInfo, Token& aToken) {
''' + cache_fragment + '''
  return true;
}
int main() {
  assert(IdentifyCA(nullptr, 0) == CAIdentity::Unavailable);
  assert(IdentifyCA(kRutheniumRussianRootDER, sizeof(kRutheniumRussianRootDER)) == CAIdentity::Root);
  assert(NSS_NoDB_Init(nullptr) == SECSuccess);
  uint8_t digest[32];
  assert(PK11_HashBuf(SEC_OID_SHA256, digest, kRutheniumRussianRootDER,
                     sizeof(kRutheniumRussianRootDER)) == SECSuccess);
  const uint8_t expected[] = {''' + expected + '''};
  assert(memcmp(digest, expected, sizeof(expected)) == 0);
  std::vector<uint8_t> changed(kRutheniumRussianRootDER,
                             kRutheniumRussianRootDER + sizeof(kRutheniumRussianRootDER));
  changed[changed.size() - 1] ^= 1;
  assert(IdentifyCA(changed.data(), changed.size()) == CAIdentity::Other);
  assert(!IsProtectedIntermediateHash(digest, sizeof(digest)));
  Info info; Token token;
  assert(!MayResume(info, token) && token.cleared);
  info.mSucceededCertChainBytes = Chain{}; token = Token{};
  assert(!MayResume(info, token) && token.cleared);
  info.mSucceededCertChainBytes = Chain{Bytes{{kRutheniumRussianRootDER,
      kRutheniumRussianRootDER + sizeof(kRutheniumRussianRootDER)}}};
  token = Token{};
  assert(!MayResume(info, token) && token.cleared);
  info.mSucceededCertChainBytes = Chain{Bytes{changed}}; token = Token{};
  assert(MayResume(info, token) && !token.cleared);
  assert(NSS_Shutdown() == SECSuccess);
}
''', "-lnss3")

    def test_actual_https_guard_preserves_http_only_recovery(self):
        # Compile the actual helper inserted into Gecko, not a second Python
        # implementation. Only the channel/IPC-facing interfaces are fakes.
        fixture = '''#include "nsHTTPSOnlyUtils.h"
#include "mozilla/BasePrincipal.h"
/* static */
nsHTTPSOnlyUtils::UpgradeMode nsHTTPSOnlyUtils::GetUpgradeMode(
    bool aFromPrivateWindow,
  nsCOMPtr<nsIChannel> channel = aDocumentLoadListener->GetChannel();
  nsCOMPtr<nsILoadInfo> loadInfo = channel->LoadInfo();
  uint32_t httpsOnlyStatus = loadInfo->GetHttpsOnlyStatus();
  // Only downgrade
  // If HTTPS-Only Mode is not enabled, then there is nothing to do here.
  nsCOMPtr<nsILoadInfo> loadInfo = aChannel->LoadInfo();
'''
        result = native_policy.https_only(fixture)
        self.assertEqual(native_policy.https_only(result), result)
        self.assertIn("if (RufoxBlocksHTTPSDowngrade(channel)) return nullptr;", result)
        self.assertIn("if (RufoxBlocksHTTPSDowngrade(aChannel)) return false;", result)
        helper = re.search(r"static bool RufoxBlocksHTTPSDowngrade[\s\S]*?\n}", result).group()
        with tempfile.TemporaryDirectory() as directory:
            self.compile_and_run(directory, '''#include <cassert>
#include <cstdint>
#include <string>
#define NS_FAILED(value) ((value) < 0)
struct nsAutoCString : std::string { bool IsEmpty() const { return empty(); } };
template<class T> struct nsCOMPtr {
  T* pointer = nullptr;
  T* operator->() { return pointer; }
  explicit operator bool() const { return pointer != nullptr; }
};
template<class T> T** getter_AddRefs(nsCOMPtr<T>& pointer) { return &pointer.pointer; }
struct nsITransportSecurityInfo {
  int32_t error = 0;
  int errorResult = 0, policyResult = 0;
  const char* policy = "";
  int GetErrorCode(int32_t* value) { *value = error; return errorResult; }
  int GetRufoxPolicy(nsAutoCString& value) { value.assign(policy); return policyResult; }
};
struct nsIChannel {
  nsITransportSecurityInfo* info = nullptr;
  int result = 0;
  int GetSecurityInfo(nsITransportSecurityInfo** value) { *value = info; return result; }
};
''' + helper + '''
int main() {
  assert(RufoxBlocksHTTPSDowngrade(nullptr));
  nsIChannel channel;
  assert(!RufoxBlocksHTTPSDowngrade(&channel));
  nsITransportSecurityInfo info;
  channel.info = &info;
  assert(!RufoxBlocksHTTPSDowngrade(&channel));
  info.policy = "{\\"state\\":\\"allowed\\"}";
  assert(RufoxBlocksHTTPSDowngrade(&channel));
  info.policy = "{\\"state\\":\\"blocked\\"}";
  assert(RufoxBlocksHTTPSDowngrade(&channel));
  info.policy = ""; info.error = -8181;
  assert(RufoxBlocksHTTPSDowngrade(&channel));
  info.error = 0; info.errorResult = -1;
  assert(RufoxBlocksHTTPSDowngrade(&channel));
  info.errorResult = 0; info.policyResult = -1;
  assert(RufoxBlocksHTTPSDowngrade(&channel));
  channel.result = -1;
  assert(RufoxBlocksHTTPSDowngrade(&channel));
}
''')

    def test_https_default_preserves_explicit_user_preferences(self):
        source = '''appContext.getPreferenceKey(R.string.pref_key_https_only),
            default = false,'''
        result = native_policy.fenix_settings(source)
        self.assertIn("default = true", result)
        self.assertEqual(native_policy.fenix_settings(result), result)
        with self.assertRaises(ValueError):
            native_policy.fenix_settings("upstream preference key changed")

    def test_shared_ca_identity_is_installed_in_all_three_native_paths(self):
        for transform in (native_policy.verifier_cpp, native_policy.common_socket,
                          native_policy.token_cache, native_policy.https_only):
            with self.subTest(transform=transform.__name__):
                with self.assertRaises(ValueError):
                    transform("upstream anchors changed")
        generated = native_policy.generated_files()
        self.assertIn(Path("security/certverifier/RufoxCAIdentity.h"), generated)
        build = native_policy.cert_build("# upstream build\n")
        self.assertIn('"RufoxCAIdentity.h"', build)
        self.assertIn('"RufoxPolicyHelpers.h"', build)
        self.assertEqual(native_policy.cert_build(build), build)


if __name__ == "__main__":
    unittest.main()
