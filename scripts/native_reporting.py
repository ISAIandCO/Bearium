"""Carry CA policy diagnostics with the TLS result, including socket-process IPC."""
from pathlib import Path


def transform(path, source):
    # Called after the base overlay; this marker makes the additions idempotent.
    if '// Rufox diagnostics transport' in source:
        return source
    def replace(old, new, count=1):
        nonlocal source
        if source.count(old) != count:
            raise ValueError(f'{path}: expected {count} reporting anchors: {old!r}')
        source = source.replace(old, new)
    name = Path(path).name
    if name == 'CertVerifier.h':
        replace('  bool enabled;', '  nsCString rufoxPolicy;\n  bool enabled;')
        replace('const char* hostname, const OriginAttributes& originAttributes);', 'const char* hostname, const OriginAttributes& originAttributes,\n      CertificateTransparencyInfo* ctInfo);')
    elif name == 'CertVerifier.cpp':
        replace('  enabled = false;', '  rufoxPolicy.Truncate();\n  enabled = false;')
        replace('time, hostname, originAttributes);', 'time, hostname, originAttributes, ctInfo);')
    elif name in ('SSLServerCertVerification.h', 'VerifySSLServerCertParent.h', 'VerifySSLServerCertParent.cpp'):
        # Only verification-result methods have this trailing argument.
        count = source.count('bool aMadeOCSPRequests)')
        replace('bool aMadeOCSPRequests)', 'bool aMadeOCSPRequests, const nsACString& aRufoxPolicy)', count)
        if name == 'SSLServerCertVerification.h':
            replace('  bool mMadeOCSPRequests;', '  bool mMadeOCSPRequests;\n  nsCString mRufoxPolicy;')
        if name == 'VerifySSLServerCertParent.cpp':
            replace('aMadeOCSPRequests);', 'aMadeOCSPRequests, aRufoxPolicy);', 2)
            replace('aMadeOCSPRequests]()', 'aMadeOCSPRequests, aRufoxPolicy = nsCString(aRufoxPolicy)]()')
    elif name == 'SSLServerCertVerification.cpp':
        replace('    bool aMadeOCSPRequests) {', '    bool aMadeOCSPRequests, const nsACString& aRufoxPolicy) {')
        replace('mProviderFlags, madeOCSPRequests);', 'mProviderFlags, madeOCSPRequests, certificateTransparencyInfo.rufoxPolicy);', 2)
        replace('  mMadeOCSPRequests = aMadeOCSPRequests;', '  mMadeOCSPRequests = aMadeOCSPRequests;\n  mRufoxPolicy = aRufoxPolicy;')
        replace('  mSocketControl->SetMadeOCSPRequests(mMadeOCSPRequests);', '  mSocketControl->SetRufoxPolicy(mRufoxPolicy);\n  mSocketControl->SetMadeOCSPRequests(mMadeOCSPRequests);')
    elif name in ('VerifySSLServerCertChild.h', 'VerifySSLServerCertChild.cpp'):
        replace('const bool& aMadeOCSPRequests)', 'const bool& aMadeOCSPRequests, const nsACString& aRufoxPolicy)')
        if name.endswith('.cpp'):
            replace('mProviderFlags, aMadeOCSPRequests);', 'mProviderFlags, aMadeOCSPRequests, aRufoxPolicy);')
    elif name == 'PVerifySSLServerCert.ipdl':
        replace('bool aMadeOCSPRequests);', 'bool aMadeOCSPRequests, nsCString aRufoxPolicy);')
    elif name == 'CommonSocketControl.h':
        replace('  void SetCertificateTransparencyStatus(', '''  void SetRufoxPolicy(const nsACString& aPolicy) {
    COMMON_SOCKET_CONTROL_ASSERT_ON_OWNING_THREAD();
    mRufoxPolicy = aPolicy;
  }
  void SetCertificateTransparencyStatus(''')
        replace('  uint16_t mCertificateTransparencyStatus;', '  uint16_t mCertificateTransparencyStatus;\n  nsCString mRufoxPolicy;')
    elif name == 'CommonSocketControl.cpp':
        replace('mIsBuiltCertChainRootBuiltInRoot, mPeerId));', 'mIsBuiltCertChainRootBuiltInRoot, mPeerId, mRufoxPolicy));')
    elif name == 'TransportSecurityInfo.h':
        replace('const nsCString& aPeerId);', 'const nsCString& aPeerId,\n      const nsCString& aRufoxPolicy = nsCString());')
        replace('  const nsCString mPeerId;', '  const nsCString mPeerId;\n  const nsCString mRufoxPolicy;')
    elif name == 'TransportSecurityInfo.cpp':
        replace('const nsCString& aPeerId)', 'const nsCString& aPeerId, const nsCString& aRufoxPolicy)')
        replace('mPeerId(aPeerId) {}', 'mPeerId(aPeerId), mRufoxPolicy(aRufoxPolicy) {}')
        replace('NS_IMPL_ISUPPORTS(TransportSecurityInfo, nsITransportSecurityInfo)', '''NS_IMPL_ISUPPORTS(TransportSecurityInfo, nsITransportSecurityInfo)

NS_IMETHODIMP TransportSecurityInfo::GetRufoxPolicy(nsACString& aResult) {
  aResult = mRufoxPolicy;
  return NS_OK;
}''')
        replace('NS_ConvertUTF8toUTF16("9")', 'NS_ConvertUTF8toUTF16("10")')
        replace('  rv = stream->Finish(aResult);', '''  rv = objStream->WriteStringZ(mRufoxPolicy.get());
  NS_ENSURE_SUCCESS(rv, rv);
  rv = stream->Finish(aResult);''')
        replace('  nsCString aPeerId;', '  nsCString aPeerId;\n  nsCString aRufoxPolicy;', 2)
        anchor = '  RefPtr<nsITransportSecurityInfo> securityInfo(new TransportSecurityInfo('
        pos = source.index(anchor)
        source = source[:pos] + '''  if (serVersionParsedToInt >= 10) {
    rv = objStream->ReadCString(aRufoxPolicy);
    NS_ENSURE_SUCCESS(rv, rv);
  }

''' + source[pos:]
        replace('aResumed, aIsBuiltCertChainRootBuiltInRoot, aPeerId));', 'aResumed, aIsBuiltCertChainRootBuiltInRoot, aPeerId, aRufoxPolicy));', 2)
        replace('  WriteParam(aWriter, mPeerId);', '  WriteParam(aWriter, mPeerId);\n  WriteParam(aWriter, mRufoxPolicy);')
        replace('!ReadParam(aReader, &aPeerId))', '!ReadParam(aReader, &aPeerId) ||\n      !ReadParam(aReader, &aRufoxPolicy))')
    elif name == 'nsITransportSecurityInfo.idl':
        replace('216112d3-28bc-4671-b057-f98cc09ba1ea', '1c52d5a2-45ad-43e8-938d-5756a366c1cd')
        replace('  readonly attribute unsigned long securityState;', '''  // JSON from the CA policy verifier, empty when that policy did not run.
  readonly attribute AUTF8String rufoxPolicy;
  readonly attribute unsigned long securityState;''')
    elif name == 'FuzzySecurityInfo.cpp':
        source += '''\nNS_IMETHODIMP mozilla::net::FuzzySecurityInfo::GetRufoxPolicy(nsACString& aResult) {
  aResult.Truncate();
  return NS_OK;
}
'''
    else:
        raise ValueError(path)
    return '// Rufox diagnostics transport\n' + source


PATHS = [
    'security/certverifier/CertVerifier.h', 'security/certverifier/CertVerifier.cpp',
    *('security/manager/ssl/' + name for name in (
        'SSLServerCertVerification.h', 'SSLServerCertVerification.cpp',
        'VerifySSLServerCertParent.h', 'VerifySSLServerCertParent.cpp',
        'VerifySSLServerCertChild.h', 'VerifySSLServerCertChild.cpp',
        'PVerifySSLServerCert.ipdl', 'CommonSocketControl.h', 'CommonSocketControl.cpp',
        'TransportSecurityInfo.h', 'TransportSecurityInfo.cpp', 'nsITransportSecurityInfo.idl')),
    'netwerk/base/FuzzySecurityInfo.cpp',
]


def install(transforms):
    for path in PATHS:
        previous = transforms.get(Path(path), lambda s: s)
        transforms[Path(path)] = lambda s, p=path, prev=previous: s if "// Rufox diagnostics transport" in s else transform(p, prev(s))
