"""Compile the injected method against the relevant typed Gecko API contract."""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from scripts import native_one_shot, native_policy


class OneShotApiTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which('g++'), 'g++ required')
    def test_context_and_typed_document_policy(self):
        original = '''#include "nsContentUtils.h"
  mTlsFlags = aTlsFlags;
NS_IMETHODIMP
HttpBaseChannel::GetApiRedirectToURI(nsIURI** aResult) {
'''
        patched = native_one_shot.transform('HttpBaseChannel.cpp', original, native_policy.once)
        method = patched[patched.index('HttpBaseChannel::GrantRufoxOneShot('):]
        method = method[:method.index('\nNS_IMETHODIMP')]
        idl = native_one_shot.transform('nsIHttpChannelInternal.idl',
            '4e28263d-1e03-46f4-aa5c-9512f91957f9\n    [must_use] attribute unsigned long tlsFlags;',
            native_policy.once)
        self.assertIn('[must_use, implicit_jscontext] void grantRufoxOneShot();', idl)
        header = native_one_shot.transform('HttpBaseChannel.h',
            '  NS_IMETHOD SetTlsFlags(uint32_t aTlsFlags) override;\n  uint32_t mTlsFlags{0};',
            native_policy.once)
        self.assertIn('GrantRufoxOneShot(JSContext* aCx) override;', header)
        code = r'''
#include <cassert>
struct JSContext { bool system; };
static bool parent = true;
bool XRE_IsParentProcess() { return parent; }
namespace nsContentUtils { bool IsSystemCaller(JSContext* cx) { return cx->system; } }
enum class ExtContentPolicy { TYPE_DOCUMENT, TYPE_SCRIPT };
struct URI { bool https = true; bool SchemeIs(const char*) { return https; } };
struct LoadInfo {
  ExtContentPolicy type = ExtContentPolicy::TYPE_DOCUMENT;
  ExtContentPolicy GetExternalContentPolicyType() { return type; }
};
constexpr int NS_ERROR_DOM_SECURITY_ERR = 1, NS_ERROR_NOT_AVAILABLE = 2, NS_OK = 0;
constexpr unsigned LOAD_FRESH_CONNECTION = 1, LOAD_BYPASS_CACHE = 2, INHIBIT_CACHING = 4;
struct HttpBaseChannel {
  URI uri; LoadInfo info;
  URI* mURI = &uri; LoadInfo* mLoadInfo = &info;
  bool mConnectionInfo = false, mRufoxOneShot = false;
  unsigned mLoadFlags = 0;
  int GrantRufoxOneShot(JSContext* aCx);
};
''' + 'int ' + method + r'''
int main() {
  JSContext trusted{true}, content{false}; HttpBaseChannel channel;
  assert(channel.GrantRufoxOneShot(nullptr) == NS_ERROR_DOM_SECURITY_ERR);
  assert(channel.GrantRufoxOneShot(&content) == NS_ERROR_DOM_SECURITY_ERR);
  parent = false;
  assert(channel.GrantRufoxOneShot(&trusted) == NS_ERROR_DOM_SECURITY_ERR);
  parent = true; channel.info.type = ExtContentPolicy::TYPE_SCRIPT;
  assert(channel.GrantRufoxOneShot(&trusted) == NS_ERROR_NOT_AVAILABLE);
  assert(!channel.mRufoxOneShot && channel.mLoadFlags == 0);
  channel.info.type = ExtContentPolicy::TYPE_DOCUMENT;
  assert(channel.GrantRufoxOneShot(&trusted) == NS_OK);
  assert(channel.mRufoxOneShot && channel.mLoadFlags == 7);
}
'''
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / 'method.cpp'
            binary = Path(tmp) / 'method'
            source.write_text(code)
            subprocess.run(['g++', '-std=c++17', '-Wall', '-Wextra', '-Werror',
                            str(source), '-o', str(binary)], check=True)
            subprocess.run([str(binary)], check=True)
