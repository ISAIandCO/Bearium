"""One navigation permission, delivered by a parent-only channel capability."""
from pathlib import Path

# The high TLS-provider bit is reserved by this fork. Public tlsFlags setters
# strip it; only GrantRufoxOneShot can activate it on a parent HTTP channel.
BIT = '0x80000000U'


def transform(path, s, once):
    name = Path(path).name
    def edit(old, new):
        nonlocal s
        s = once(s, old, new)
    if name == 'nsIHttpChannelInternal.idl':
        edit('4e28263d-1e03-46f4-aa5c-9512f91957f9', '37382421-43c0-475c-806a-2efb94a108ee')
        edit('    [must_use] attribute unsigned long tlsFlags;', '''    [must_use] attribute unsigned long tlsFlags;

    /** Browser chrome only: permit this top-level HTTPS request under Rufox CA policy. */
    [must_use, implicit_jscontext] void grantRufoxOneShot();''')
    elif name == 'HttpBaseChannel.h':
        edit('  NS_IMETHOD SetTlsFlags(uint32_t aTlsFlags) override;', '''  NS_IMETHOD SetTlsFlags(uint32_t aTlsFlags) override;
  NS_IMETHOD GrantRufoxOneShot(JSContext* aCx) override;''')
        edit('  uint32_t mTlsFlags{0};', '''  uint32_t mTlsFlags{0};
  // Intentionally absent from redirect/replacement and child IPC serialization.
  bool mRufoxOneShot = false;''')
    elif name == 'HttpBaseChannel.cpp':
        edit('#include "nsContentUtils.h"', '#include "nsContentUtils.h"\n#include "nsXULAppAPI.h"')
        edit('  mTlsFlags = aTlsFlags;', f'  mTlsFlags = aTlsFlags & ~{BIT};')
        edit('HttpBaseChannel::GetApiRedirectToURI(nsIURI** aResult) {', '''HttpBaseChannel::GrantRufoxOneShot(JSContext* aCx) {
  if (!aCx || !XRE_IsParentProcess() || !nsContentUtils::IsSystemCaller(aCx)) {
    return NS_ERROR_DOM_SECURITY_ERR;
  }
  if (!mURI || !mURI->SchemeIs("https") || mConnectionInfo ||
      mLoadInfo->GetExternalContentPolicyType() != ExtContentPolicy::TYPE_DOCUMENT) {
    return NS_ERROR_NOT_AVAILABLE;
  }
  mRufoxOneShot = true;
  mLoadFlags |= LOAD_FRESH_CONNECTION | LOAD_BYPASS_CACHE | INHIBIT_CACHING;
  return NS_OK;
}

NS_IMETHODIMP
HttpBaseChannel::GetApiRedirectToURI(nsIURI** aResult) {''')
    elif name == 'nsHttpChannel.cpp':
        edit('  // Construct connection info object', '''  // Notify before choosing an Alt-Svc route, cache policy or connection pool.
  if (nsCOMPtr<nsIObserverService> observers = services::GetObserverService()) {
    observers->NotifyObservers(static_cast<nsIHttpChannel*>(this),
                               "http-on-rufox-request", nullptr);
  }
  // One user-authorized navigation gets its own non-reusable HTTP/1 connection.
  // Neither another path on this host nor a redirect may borrow the permission.
  if (mRufoxOneShot) {
    StoreAllowSpdy(false);
    StoreAllowHttp3(false);
    StoreAllowAltSvc(false);
    mCaps |= NS_HTTP_DISALLOW_SPDY | NS_HTTP_DISALLOW_HTTP3 |
             NS_HTTP_DISALLOW_HTTP2_PROXY;
    mCaps &= ~(NS_HTTP_ALLOW_KEEPALIVE | NS_HTTP_ALLOW_SPDY_WITHOUT_KEEPALIVE);
  }

  // Construct connection info object''')
        edit('  mConnectionInfo->SetTlsFlags(mTlsFlags);', f'''  if (mRufoxOneShot) mTlsFlags |= {BIT};
  mConnectionInfo->SetTlsFlags(mTlsFlags);''')
    elif name == 'nsSocketTransport2.cpp':
        edit('          mOriginAttributes, controlFlags, mTlsFlags, &fd,', f'''          mOriginAttributes, controlFlags,
          mHttpsProxy ? (mTlsFlags & ~{BIT}) : mTlsFlags, &fd,''')
    elif name == 'nsNSSIOLayer.cpp':
        edit('  if (providerTlsFlags) {', f'  if (providerTlsFlags & ~{BIT}) {{')
        edit('new nsSSLIOLayerHelpers(PublicOrPrivate::Public, providerTlsFlags);', f'new nsSSLIOLayerHelpers(PublicOrPrivate::Public, providerTlsFlags & ~{BIT});')
    elif name == 'SSLServerCertVerification.cpp':
        edit('  // Get DC information', f'''  if (socketInfo->GetProviderTlsFlags() & {BIT}) {{
    certVerifierFlags |= CertVerifier::FLAG_RUFOX_ONE_SHOT;
  }}

  // Get DC information''')
    elif name == 'CertVerifier.h':
        edit('  static const Flags FLAG_TLS_IGNORE_STATUS_REQUEST;', '''  static const Flags FLAG_TLS_IGNORE_STATUS_REQUEST;
  static const Flags FLAG_RUFOX_ONE_SHOT;''')
        edit('const OriginAttributes& originAttributes);', 'const OriginAttributes& originAttributes, bool rufoxOneShot);')
        edit('const char* hostname, const OriginAttributes& originAttributes,\n      CertificateTransparencyInfo* ctInfo);', 'const char* hostname, const OriginAttributes& originAttributes,\n      CertificateTransparencyInfo* ctInfo, bool rufoxOneShot);')
    elif name == 'CertVerifier.cpp':
        edit('const CertVerifier::Flags CertVerifier::FLAG_TLS_IGNORE_STATUS_REQUEST = 4;', '''const CertVerifier::Flags CertVerifier::FLAG_TLS_IGNORE_STATUS_REQUEST = 4;
const CertVerifier::Flags CertVerifier::FLAG_RUFOX_ONE_SHOT = 8;''')
        edit('const OriginAttributes& originAttributes) {', 'const OriginAttributes& originAttributes, bool rufoxOneShot) {')
        edit('time, hostname, originAttributes, ctInfo);', 'time, hostname, originAttributes, ctInfo, rufoxOneShot);')
        if s.count('ctInfo, originAttributes);') != 2:
            raise ValueError('expected two TLS CT policy call sites')
        s = s.replace('ctInfo, originAttributes);', 'ctInfo, originAttributes, flags & FLAG_RUFOX_ONE_SHOT);')
    else:
        raise ValueError(path)
    return '// Rufox one-shot channel capability\n' + s


def install(transforms, once):
    paths = ['netwerk/protocol/http/' + p for p in (
        'nsIHttpChannelInternal.idl', 'HttpBaseChannel.h', 'HttpBaseChannel.cpp', 'nsHttpChannel.cpp')]
    paths += ['netwerk/base/nsSocketTransport2.cpp', 'security/manager/ssl/nsNSSIOLayer.cpp',
              'security/manager/ssl/SSLServerCertVerification.cpp',
              'security/certverifier/CertVerifier.h', 'security/certverifier/CertVerifier.cpp']
    for path in paths:
        previous = transforms.get(Path(path), lambda source: source)
        transforms[Path(path)] = lambda source, p=path, prev=previous: source if '// Rufox one-shot channel capability' in source else transform(p, prev(source), once)
