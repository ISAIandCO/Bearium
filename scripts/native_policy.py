"""Rufox native policy overlay; exact anchors fail closed on upstream changes."""
from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NATIVE = ROOT / "native"


def once(source: str, old: str, new: str) -> str:
    if new in source:
        return source
    if source.count(old) != 1:
        raise ValueError(f"native policy: expected one anchor: {old[:100]!r}")
    return source.replace(old, new, 1)


def log_header() -> str:
    data = json.loads((NATIVE / "ct-log-list.json").read_text())
    rows = []
    def timestamp(value):
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    def byte_list(value):
        return ", ".join(f"0x{x:02x}" for x in value)
    seen = set()
    for operator_id, operator in enumerate(data["operators"]):
        for log in operator["logs"]:
            key = base64.b64decode(log["key"], validate=True)
            identity = base64.b64decode(log["log_id"], validate=True)
            if hashlib.sha256(key).digest() != identity or identity in seen:
                raise ValueError("invalid or duplicate CT log identity")
            seen.add(identity)
            if len(log["state"]) != 1:
                raise ValueError("ambiguous CT state")
            state, detail = next(iter(log["state"].items()))
            if state not in ("usable", "readonly", "retired"):
                continue  # Rejected/unknown logs never attest certificates.
            interval = log["temporal_interval"]
            start = timestamp(interval["start_inclusive"])
            end = timestamp(interval["end_exclusive"])
            if start >= end or len(key) > 512:
                raise ValueError("invalid CT log interval or key")
            rows.append("{{%s}, {%s}, %d, %d, %dULL, %dULL, %dULL, %s, %s}" % (
                byte_list(identity), byte_list(key), len(key), operator_id,
                start, end, timestamp(detail["timestamp"]),
                str(state != "usable").lower(), str(operator["name"] == "Yandex").lower()))
    if not rows:
        raise ValueError("empty CT log policy")
    return """// Generated from the reviewed CAnttRUst CT log snapshot. MPL-2.0.
#ifndef RufoxCTLogs_h
#define RufoxCTLogs_h
struct RufoxCTLog {
  uint8_t id[32];
  uint8_t key[512];
  size_t keyLength;
  int16_t operatorId;
  uint64_t start, end, since;
  bool retired, yandex;
};
inline constexpr RufoxCTLog kRufoxCTLogs[] = {
""" + ",\n".join(rows) + "\n};\n#endif\n"


def verifier_h(source: str) -> str:
    source = once(source, "  nsTArray<mozilla::pkix::Input> mThirdPartyIntermediateInputs;", """  nsTArray<mozilla::pkix::Input> mThirdPartyIntermediateInputs;
  // Rufox: immutable policy snapshot, rebuilt when preferences change.
  nsTArray<mozilla::pkix::Input> mTLSServerRootInputs;
  mozilla::pkix::Input mRutheniumRootInput;
  mozilla::UniquePtr<mozilla::ct::MultiLogCTVerifier> mRufoxCTVerifier;
  nsCString mRufoxExceptions;
  nsCString mRufoxPrivateExceptions;
  bool mRufoxHardened = false;
  Result VerifyRufoxPolicy(NSSCertDBTrustDomain& trustDomain,
      const nsTArray<nsTArray<uint8_t>>& builtChain,
      mozilla::pkix::Input sctsFromTLS, mozilla::pkix::Time time,
      const char* hostname, const OriginAttributes& originAttributes);
""")
    # Only the outer CT policy gets origin attributes; the upstream CT checker
    # and its trust list remain untouched.
    start = source.index("  mozilla::pkix::Result VerifyCertificateTransparencyPolicy(")
    end = source.index(";", start) + 1
    part = source[start:end]
    if "const OriginAttributes& originAttributes" not in part:
        part = part.replace("CertificateTransparencyInfo* ctInfo)",
                            "CertificateTransparencyInfo* ctInfo,\n      const OriginAttributes& originAttributes)")
        source = source[:start] + part + source[end:]
    return source


def verifier_cpp(source: str) -> str:
    source = once(source, '#include "CertVerifier.h"', '#include "CertVerifier.h"\n#include "RutheniumRoot.h"\n#include "RufoxCTLogs.h"\n#include "RufoxPolicyHelpers.h"\n#include "mozilla/Preferences.h"\n#include "prtime.h"\n#include "nsReadableUtils.h"\n#include <cstring>')
    init = """
  // Rufox extra trust is limited to TLS servers; policy is checked below.
  mTLSServerRootInputs = mThirdPartyRootInputs.Clone();
  if (mRutheniumRootInput.Init(kRutheniumRussianRootDER,
                             sizeof(kRutheniumRussianRootDER)) == Success) {
    mTLSServerRootInputs.AppendElement(mRutheniumRootInput);
  }
  Preferences::GetCString("security.rufox.exceptions", mRufoxExceptions);
  Preferences::GetCString("security.rufox.private_exceptions", mRufoxPrivateExceptions);
  if (!mRufoxExceptions.IsEmpty()) mRufoxExceptions.Append(',');
  nsAutoCString sessionExceptions;
  Preferences::GetCString("security.rufox.session_exceptions", sessionExceptions);
  mRufoxExceptions.Append(sessionExceptions);
  mRufoxHardened = Preferences::GetBool("security.rufox.hardened", false);
  mRufoxCTVerifier = MakeUnique<MultiLogCTVerifier>();
  for (const auto& log : kRufoxCTLogs) {
    Input key;
    CTLogVerifier verifier(log.operatorId, CTLogState::Admissible,
                           CTLogFormat::RFC6962, log.since);
    if (key.Init(log.key, log.keyLength) != Success || verifier.Init(key) != Success) {
      mRufoxCTVerifier.reset();
      break;
    }
    mRufoxCTVerifier->AddLog(std::move(verifier));
  }
"""
    if "// Rufox extra trust" not in source:
        end = source.index("\nCertVerifier::~CertVerifier()")
        close = source.rfind("\n}", 0, end)
        source = source[:close] + init + source[close:]
    start = source.index("    case VerifyUsage::TLSServer: {")
    end = source.index("    case VerifyUsage::EmailCA:", start)
    part = source[start:end]
    if "mTLSServerRootInputs" not in part:
        if part.count("originAttributes, mThirdPartyRootInputs,") != 2:
            raise ValueError("unexpected TLS trust domain callers")
        part = part.replace("originAttributes, mThirdPartyRootInputs,", "originAttributes, mTLSServerRootInputs,")
        # Every outer CT policy invocation must carry the privacy partition.
        import re
        part, count = re.subn(r"(VerifyCertificateTransparencyPolicy\([\s\S]*?ctInfo)\);", r"\1, originAttributes);", part)
        if count != 2:
            raise ValueError("unexpected CT policy callers")
        source = source[:start] + part + source[end:]
    start = source.index("Result CertVerifier::VerifyCertificateTransparencyPolicy(")
    end = source.index("Result CertVerifier::VerifyCertificateTransparencyPolicyInner(", start)
    part = source[start:end]
    if "VerifyRufoxPolicy(trustDomain" not in part:
        part = once(part, "CertificateTransparencyInfo* ctInfo) {", "CertificateTransparencyInfo* ctInfo,\n    const OriginAttributes& originAttributes) {")
        part = once(part, "  if (mCTConfig.mMode", """  Result rufoxResult = VerifyRufoxPolicy(trustDomain, builtChain, sctsFromTLS,
                                          time, hostname, originAttributes);
  if (rufoxResult != Success) {
    return rufoxResult;
  }
  if (mCTConfig.mMode""")
        source = source[:start] + part + source[end:]
    implementation = (NATIVE / "RufoxPolicy.inc").read_text()
    if implementation not in source:
        source = once(source, "void CertVerifier::LoadKnownCTLogs() {", implementation + "\nvoid CertVerifier::LoadKnownCTLogs() {")
    return source


def nss_component(source: str) -> str:
    return once(source, '        prefName.EqualsLiteral("security.pki.cert_short_lifetime_in_days") ||', '        StringBeginsWith(prefName, "security.rufox."_ns) ||\n        prefName.EqualsLiteral("security.pki.cert_short_lifetime_in_days") ||')


def about_redirector(source):
    return once(source, '    {"about", "chrome://global/content/aboutAbout.html", 0},', '''    {"about", "chrome://global/content/aboutAbout.html", 0},
    {"bearium-protection", "chrome://global/content/rufoxProtection.html",
     nsIAboutModule::ALLOW_SCRIPT | nsIAboutModule::IS_SECURE_CHROME_UI},''')


def about_components(source):
    return once(source, "about_pages = [", "about_pages = [\n    'bearium-protection',")


def jar(source):
    return once(source, "   content/global/aboutAbout.js", """   content/global/rufoxProtection.html
   content/global/rufoxLogMetadata.js
   content/global/rufoxProtection.js
   content/global/rufoxProtection.css
   content/global/aboutAbout.js""")


def trust_panel(source):
    source = once(source, "                            ProtectionPanel(", """                            androidx.compose.foundation.layout.Column {
                            RufoxProtectionSummary(
                                engine = sessionState?.engineState?.engineSession,
                                onOpen = {
                                components.useCases.sessionUseCases.loadUrl(
                                    "about:bearium-protection#url=" + Uri.encode(args.url),
                                    sessionId = args.sessionId,
                                )
                                dismiss()
                            })
                            ProtectionPanel(""")
    return once(source, """                        }

                        Route.TrackersPanel -> {""", """                            }
                        }

                        Route.TrackersPanel -> {""")


def common_socket(source):
    source = once(source, '#include "CommonSocketControl.h"', '#include "CommonSocketControl.h"\n#include "RutheniumRoot.h"\n#include <cstring>')
    return once(source, "  // See where CheckCertHostname() is called in", """  // Rufox: an exception for one host must not authorize another SAN via H2/H3.
  // A separate connection runs the complete policy for the requested host.
  for (const auto& chainCert : mSucceededCertChain) {
    nsTArray<uint8_t> der;
    if (NS_FAILED(chainCert->GetRawDER(der))) {
      return NS_OK;
    }
    if (der.Length() == sizeof(kRutheniumRussianRootDER) &&
        memcmp(der.Elements(), kRutheniumRussianRootDER, der.Length()) == 0) {
      return NS_OK;
    }
  }

  // See where CheckCertHostname() is called in""")


def token_cache(source):
    source = once(source, '#include "SSLTokensCache.h"', '#include "SSLTokensCache.h"\n#include "RutheniumRoot.h"\n#include <cstring>')
    return once(source, "  if (!readChain(aInfo.mHandshakeCertificatesBytes)) return false;", """  if (!readChain(aInfo.mHandshakeCertificatesBytes)) return false;
  // Rufox: never resume protected-CA sessions (including persisted tokens from
  // older builds). This also prevents 0-RTT before the current policy is checked.
  if (aInfo.mSucceededCertChainBytes) {
    for (const auto& der : *aInfo.mSucceededCertChainBytes) {
      if (der.Length() == sizeof(kRutheniumRussianRootDER) &&
          memcmp(der.Elements(), kRutheniumRussianRootDER, der.Length()) == 0) {
        aToken.Clear();
        return false;
      }
    }
  }""")


def cert_build(source):
    line = '\nEXPORTS += ["RutheniumRoot.h"]\n'
    return source if line in source else source + line


def install(transforms):
    transforms[Path("security/certverifier/CertVerifier.cpp")] = verifier_cpp
    transforms[Path("security/certverifier/CertVerifier.h")] = verifier_h
    transforms.pop(Path("security/certverifier/NSSCertDBTrustDomain.cpp"), None)
    transforms.pop(Path("security/certverifier/NSSCertDBTrustDomain.h"), None)
    transforms[Path("security/manager/ssl/nsNSSComponent.cpp")] = nss_component
    transforms[Path("docshell/base/nsAboutRedirector.cpp")] = about_redirector
    transforms[Path("docshell/build/components.conf")] = about_components
    transforms[Path("toolkit/content/jar.mn")] = jar
    transforms[Path("mobile/android/fenix/app/src/main/java/org/mozilla/fenix/settings/trustpanel/TrustPanelFragment.kt")] = trust_panel
    transforms[Path("security/manager/ssl/CommonSocketControl.cpp")] = common_socket
    transforms[Path("netwerk/base/SSLTokensCache.cpp")] = token_cache
    transforms[Path("security/certverifier/moz.build")] = cert_build
    try:
        from . import native_reporting, native_frontend, native_one_shot
    except ImportError:
        import native_reporting, native_frontend, native_one_shot
    native_reporting.install(transforms)
    native_frontend.install(transforms, once)
    native_one_shot.install(transforms, once)


def generated_files():
    result = {Path("security/certverifier/RufoxCTLogs.h"): log_header()}
    logs = json.loads((NATIVE / "ct-log-list.json").read_text())
    metadata = {"version": logs["version"], "timestamp": logs["log_list_timestamp"], "logs": {}}
    for operator in logs["operators"]:
        for log in operator["logs"]:
            identity = base64.b64decode(log["log_id"]).hex()
            metadata["logs"][identity] = {"name": log["description"], "operator": operator["name"],
                "state": next(iter(log["state"])), "interval": log["temporal_interval"]}
    result[Path("toolkit/content/rufoxLogMetadata.js")] = "const RufoxLogMetadata = " + json.dumps(metadata, ensure_ascii=True) + ";\n"

    result[Path("security/certverifier/RufoxPolicyHelpers.h")] = (NATIVE / "RufoxPolicyHelpers.h").read_text()
    for name in ("rufoxProtection.html", "rufoxProtection.js", "rufoxProtection.css"):
        result[Path("toolkit/content") / name] = (NATIVE / name).read_text()
    result[Path("mobile/shared/modules/geckoview/RufoxProtection.sys.mjs")] = (NATIVE / "RufoxProtection.sys.mjs").read_text()
    result[Path("mobile/android/fenix/app/src/main/java/org/mozilla/fenix/settings/trustpanel/RufoxProtectionSummary.kt")] = (NATIVE / "RufoxProtectionSummary.kt").read_text()
    return result
