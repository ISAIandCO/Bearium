#!/usr/bin/env python3
"""Apply the Ruthenium scoped CA and Android product patches to Firefox."""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import re
import shutil
import urllib.request
from pathlib import Path
from typing import Callable

try:
    from . import native_policy
except ImportError:
    import native_policy


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CERTIFICATE_PATH = REPOSITORY_ROOT / "certificates/russian_trusted_root_ca.pem"
CERTIFICATE_LOCK_PATH = REPOSITORY_ROOT / "certificates/ministry-ca-lock.json"

CERT_VERIFIER_CPP = Path("security/certverifier/CertVerifier.cpp")
CERT_VERIFIER_H = Path("security/certverifier/CertVerifier.h")
TRUST_DOMAIN_CPP = Path("security/certverifier/NSSCertDBTrustDomain.cpp")
TRUST_DOMAIN_H = Path("security/certverifier/NSSCertDBTrustDomain.h")
GENERATED_HEADER = Path("security/certverifier/RutheniumRoot.h")
FENIX_GRADLE = Path("mobile/android/fenix/app/build.gradle")
FENIX_STRINGS = Path(
    "mobile/android/fenix/app/src/main/res/values/static_strings.xml"
)
FENIX_RELEASE_STRINGS = Path(
    "mobile/android/fenix/app/src/release/res/values/static_strings.xml"
)
FENIX_LAUNCHER_FOREGROUND = Path(
    "mobile/android/fenix/app/src/main/res/drawable/ic_launcher_foreground.xml"
)
FENIX_RELEASE_LAUNCHER_FOREGROUND = Path(
    "mobile/android/fenix/app/src/release/res/drawable/ic_launcher_foreground.xml"
)
FENIX_ADAPTIVE_ICON = Path(
    "mobile/android/fenix/app/src/main/res/mipmap-anydpi/ic_launcher.xml"
)
FENIX_ADAPTIVE_ROUND_ICON = Path(
    "mobile/android/fenix/app/src/main/res/mipmap-anydpi/ic_launcher_round.xml"
)

ICON_SOURCE_DIR = REPOSITORY_ROOT / "branding/android"
ICON_DENSITIES = ("mdpi", "hdpi", "xhdpi", "xxhdpi", "xxxhdpi")
FENIX_LEGACY_ICONS = tuple(
    (
        ICON_SOURCE_DIR / f"bearium-{density}.webp",
        Path(
            f"mobile/android/fenix/app/src/release/res/mipmap-{density}/"
            "ic_launcher.webp"
        ),
    )
    for density in ICON_DENSITIES
) + tuple(
    (
        ICON_SOURCE_DIR / f"bearium-round-{density}.webp",
        Path(
            f"mobile/android/fenix/app/src/release/res/mipmap-{density}/"
            "ic_launcher_round.webp"
        ),
    )
    for density in ICON_DENSITIES
)
FENIX_ADAPTIVE_ICONS = tuple(
    (ICON_SOURCE_DIR / filename,
     Path(f"mobile/android/fenix/app/src/{variant}/res/drawable/{resource}.xml"))
    for variant in ("main", "release")
    for filename, resource in (("bearium-foreground.xml", "ic_launcher_foreground"),
                               ("bearium-monochrome.xml", "ic_launcher_monochrome"),
                               ("bearium-background.xml", "bearium_background"))
)

TEXT_TARGETS = (
    CERT_VERIFIER_CPP,
    CERT_VERIFIER_H,
    FENIX_GRADLE,
    FENIX_STRINGS,
    FENIX_RELEASE_STRINGS,
    FENIX_LAUNCHER_FOREGROUND,
    FENIX_RELEASE_LAUNCHER_FOREGROUND,
    FENIX_ADAPTIVE_ICON,
    FENIX_ADAPTIVE_ROUND_ICON,
)

BEGIN_MARKER = "// BEGIN Ruthenium scoped Russian CA"
END_MARKER = "// END Ruthenium scoped Russian CA"


def canonical_json(value: object) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode()


def load_certificate_lock(path: Path = CERTIFICATE_LOCK_PATH) -> dict[str, str]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8", "strict"))
    if not isinstance(value, dict) or canonical_json(value) != raw:
        raise ValueError("certificate lock must be canonical JSON")
    if set(value) != {"der_sha256", "primary_url", "secondary_url"}:
        raise ValueError("certificate lock has unexpected fields")
    if not isinstance(value["der_sha256"], str) or not re.fullmatch(
        r"[0-9a-f]{64}", value["der_sha256"]
    ):
        raise ValueError("certificate lock has an invalid SHA-256")
    for key in ("primary_url", "secondary_url"):
        if not isinstance(value[key], str) or not value[key].startswith("https://"):
            raise ValueError(f"certificate lock has an invalid {key}")
    return value  # type: ignore[return-value]


def decode_pem(pem: str) -> bytes:
    begin = "-----BEGIN CERTIFICATE-----"
    end = "-----END CERTIFICATE-----"
    if pem.count(begin) != 1 or pem.count(end) != 1:
        raise ValueError("expected exactly one PEM certificate")
    encoded = pem.split(begin, 1)[1].split(end, 1)[0]
    try:
        return base64.b64decode("".join(encoded.split()), validate=True)
    except (binascii.Error, ValueError) as error:
        raise ValueError("invalid PEM certificate") from error


def load_verified_certificate(
    certificate_path: Path = CERTIFICATE_PATH,
    lock_path: Path = CERTIFICATE_LOCK_PATH,
) -> bytes:
    der = decode_pem(certificate_path.read_text(encoding="ascii"))
    expected = load_certificate_lock(lock_path)["der_sha256"]
    actual = hashlib.sha256(der).hexdigest()
    if actual != expected:
        raise ValueError(f"unexpected certificate SHA-256: {actual}")
    return der


def format_cpp_array(name: str, data: bytes) -> str:
    lines = []
    for offset in range(0, len(data), 12):
        chunk = data[offset : offset + 12]
        lines.append("    " + ", ".join(f"0x{byte:02x}" for byte in chunk) + ",")
    return f"inline constexpr uint8_t {name}[] = {{\n" + "\n".join(lines) + "\n};"


def generated_header(der: bytes) -> str:
    digest = hashlib.sha256(der).hexdigest()
    return f"""/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this
 * file, You can obtain one at http://mozilla.org/MPL/2.0/. */

#ifndef security_certverifier_RutheniumRoot_h
#define security_certverifier_RutheniumRoot_h

#include <stdint.h>

// Russian Trusted Root CA, DER SHA-256: {digest}
{format_cpp_array("kRutheniumRussianRootDER", der)}

#endif  // security_certverifier_RutheniumRoot_h
"""


def replace_once(source: str, old: str, new: str, description: str) -> str:
    if new in source:
        return source
    count = source.count(old)
    if count != 1:
        raise ValueError(f"{description}: expected one anchor, found {count}")
    return source.replace(old, new, 1)


def patch_fenix_gradle(source: str) -> str:
    source = replace_once(
        source,
        '        applicationId "org.mozilla"',
        '        applicationId "app.bearium"',
        "Fenix application ID",
    )
    source = replace_once(
        source,
        '''            } else {
                include "armeabi-v7a", "arm64-v8a", "x86_64"
                if (gradle.mozconfig.substs.MOZILLA_OFFICIAL || System.getenv("MOZ_BUILD_CONFIG_LINT") == "1") {
                    universalApk true
                }
            }''',
        '''            } else {
                // Build one ABI selected by the isolated CI matrix job.
                def rfirefoxTargetAbi = System.getenv("RFIREFOX_TARGET_ABI")
                def rfirefoxSupportedAbis = ["armeabi-v7a", "arm64-v8a", "x86_64"]
                if (!rfirefoxTargetAbi || !rfirefoxSupportedAbis.contains(rfirefoxTargetAbi)) {
                    throw new GradleException(
                        "RFIREFOX_TARGET_ABI must be one of: " +
                            rfirefoxSupportedAbis.join(", ")
                    )
                }
                include rfirefoxTargetAbi
            }''',
        "Fenix single-ABI split",
    )
    start = source.find("        release releaseTemplate >> {")
    end = source.find("        benchmark releaseTemplate >> {", start)
    if start == -1 or end == -1:
        raise ValueError("Fenix release build type was not found")
    section = source[start:end]
    section = replace_once(
        section,
        "        release releaseTemplate >> {\n",
        """        release releaseTemplate >> {
            // Production never falls back to the public development key.
            def beariumProduction = System.getenv("BEARIUM_PRODUCTION") == "1"
            debuggable false
            if (beariumProduction) {
                def required = ["BEARIUM_KEYSTORE", "BEARIUM_STORE_PASSWORD", "BEARIUM_KEY_ALIAS", "BEARIUM_KEY_PASSWORD", "BEARIUM_VERSION_CODE"]
                required.each { key ->
                    if (!System.getenv(key)) throw new GradleException(key + " is required")
                }
                def upload = signingConfigs.maybeCreate("beariumUpload")
                upload.storeFile = project.file(System.getenv("BEARIUM_KEYSTORE"))
                upload.storePassword = System.getenv("BEARIUM_STORE_PASSWORD")
                upload.keyAlias = System.getenv("BEARIUM_KEY_ALIAS")
                upload.keyPassword = System.getenv("BEARIUM_KEY_PASSWORD")
                signingConfig = upload
            } else {
                def rfirefoxDebugKeystore = System.getenv("RFIREFOX_DEBUG_KEYSTORE")
                if (!rfirefoxDebugKeystore) throw new GradleException("RFIREFOX_DEBUG_KEYSTORE is required")
                signingConfigs.debug.storeFile = project.file(rfirefoxDebugKeystore)
                signingConfigs.debug.storePassword = "android"
                signingConfigs.debug.keyAlias = "androiddebugkey"
                signingConfigs.debug.keyPassword = "android"
                signingConfig = signingConfigs.debug
            }
""",
        "Fenix release debug signing",
    )
    replacements = {
        'def deepLinkSchemeValue = "fenix"':
            'def deepLinkSchemeValue = "bearium"',
        '"sharedUserId": "org.mozilla.firefox.sharedID"':
            '"sharedUserId": "app.bearium.browser.sharedID"',
    }
    for old, new in replacements.items():
        if new not in section:
            if section.count(old) != 1:
                raise ValueError(f"Fenix release branding anchor is ambiguous: {old}")
            section = section.replace(old, new, 1)
    section = replace_once(section, 'applicationIdSuffix ".firefox"',
        'applicationIdSuffix (System.getenv("BEARIUM_PRODUCTION") == "1" ? ".browser" : ".browser.dev")',
        "Bearium package suffix")
    source = source[:start] + section + source[end:]
    marker = "// BEGIN Bearium packaging"
    if marker not in source:
        source += "\n" + (REPOSITORY_ROOT / "native/bearium-build.gradle").read_text()
    return source


def patch_fenix_strings(source: str) -> str:
    replacements = {
        '<string name="app_name" translatable="false">Firefox Fenix</string>':
            '<string name="app_name" translatable="false">Bearium</string>',
        '<string name="firefox" translatable="false">Firefox</string>':
            '<string name="firefox" translatable="false">Bearium</string>',
        '<string name="app_name_firefox" tools:ignore="BrandUsage">Firefox</string>':
            '<string name="app_name_firefox" tools:ignore="BrandUsage">Bearium</string>',
    }
    for old, new in replacements.items():
        source = replace_once(source, old, new, "Fenix application name")
    return source


def patch_fenix_release_strings(source: str) -> str:
    return replace_once(
        source,
        '<string name="app_name" translatable="false">Firefox</string>',
        '<string name="app_name" translatable="false">Bearium</string>',
        "Fenix release application name",
    )


RFIREFOX_ADAPTIVE_FOREGROUND = (ICON_SOURCE_DIR / "bearium-foreground.xml").read_text()


def patch_fenix_launcher_foreground(source: str) -> str:
    if '<vector ' not in source:
        raise ValueError("unexpected launcher vector")
    return RFIREFOX_ADAPTIVE_FOREGROUND


def patch_fenix_adaptive_icon(source: str) -> str:
    if '<adaptive-icon ' not in source or '<monochrome ' not in source:
        raise ValueError("unexpected adaptive icon")
    return source.replace('@color/ic_launcher_background', '@drawable/bearium_background')


def patch_webauthn(source: str) -> str:
    gate = '(BuildConfig.MOZILLA_OFFICIAL || "app.bearium.browser".equals(GeckoAppShell.getApplicationContext().getPackageName()))'
    if gate in source:
        return source
    if source.count('BuildConfig.MOZILLA_OFFICIAL') != 4:
        raise ValueError("WebAuthn privileged-browser gates changed upstream")
    # Google still verifies the package AND signing certificate. This selects
    # the browser API; it does not grant provider privileges or change origins.
    return source.replace('BuildConfig.MOZILLA_OFFICIAL', gate)


def patch_release_manifest(source: str) -> str:
    # Both Bearium identities are new apps, never members of Firefox's shared UID.
    return source.replace('\n    android:sharedUserId="${sharedUserId}"', '')


def patch_support(source: str) -> str:
    source = source.replace('https://www.mozilla.org/firefox/android/notes',
        'https://github.com/ISAIandCO/Bearium/releases')
    anchor = '        val path = page.path'
    replacement = '''        if (page == MozillaPage.PRIVACY_NOTICE || page == MozillaPage.PRIVACY_NOTICE_UPDATE || page == MozillaPage.PRIVACY_NOTICE_NEXT) {
            return "https://github.com/ISAIandCO/Bearium/blob/main/docs/PRIVACY.md"
        }
        if (page == MozillaPage.TERMS_OF_SERVICE) {
            return "https://github.com/ISAIandCO/Bearium/blob/main/docs/TERMS.md"
        }
        val path = page.path'''
    return replace_once(source, anchor, replacement, "Bearium policy links")


def rebrand_resources(source_root: Path) -> list[Path]:
    changed = []
    app = source_root / "mobile/android/fenix/app/src"
    # Resource identifiers stay stable; only product text and product artwork change.
    for variant in ("main", "release"):
        res = app / variant / "res"
        for path in res.glob("values*/strings.xml"):
            source = path.read_text()
            def brand(match):
                key, body = match.group(1), match.group(2)
                if key in ("onboarding_term_of_service_line_three", "onboarding_redesign_tou_body_three", "nova_onboarding_tou_body_line_3"):
                    text = "Телеметрия и отправка отчётов о сбоях отключены в Bearium. %1$s" if path.parent.name == "values-ru" else "Telemetry and crash reporting are disabled in Bearium. %1$s"
                    return match.group(0).replace(body, text)
                if any(service in key.lower() for service in ("relay", "sync", "account", "mozilla", "vpn")):
                    return match.group(0)
                return match.group(0).replace(body, re.sub(r"\bFirefox\b", "Bearium", body))
            patched = re.sub(r'<string[^>]*name="([^" ]+)"[^>]*>(.*?)</string>', brand, source, flags=re.S)
            if patched != source:
                path.write_text(patched)
                changed.append(path.relative_to(source_root))
        for folder in res.glob("drawable*"):
            for name in ("ic_firefox", "expressive_firefox", "ic_splash_logo", "ic_status_logo", "ic_onboarding_welcome"):
                path = folder / (name + ".xml")
                if path.is_file():
                    asset = "bearium-monochrome.xml" if name == "ic_status_logo" else "bearium-foreground.xml"
                    content = (ICON_SOURCE_DIR / asset).read_text()
                    if path.read_text() != content:
                        path.write_text(content)
                        changed.append(path.relative_to(source_root))
    return changed


TRANSFORMS: dict[Path, Callable[[str], str]] = {
    Path("mobile/android/geckoview/src/main/java/org/mozilla/geckoview/WebAuthnTokenManager.java"): patch_webauthn,
    Path("mobile/android/fenix/app/src/release/AndroidManifest.xml"): patch_release_manifest,
    Path("mobile/android/fenix/app/src/main/java/org/mozilla/fenix/settings/SupportUtils.kt"): patch_support,
    FENIX_GRADLE: patch_fenix_gradle,
    FENIX_STRINGS: patch_fenix_strings,
    FENIX_RELEASE_STRINGS: patch_fenix_release_strings,
    FENIX_LAUNCHER_FOREGROUND: patch_fenix_launcher_foreground,
    FENIX_RELEASE_LAUNCHER_FOREGROUND: patch_fenix_launcher_foreground,
    FENIX_ADAPTIVE_ICON: patch_fenix_adaptive_icon,
    FENIX_ADAPTIVE_ROUND_ICON: patch_fenix_adaptive_icon,
}

native_policy.install(TRANSFORMS)


def patch_checkout(source_root: Path, der: bytes) -> list[Path]:
    changed: list[Path] = []
    for relative_path, transform in TRANSFORMS.items():
        path = source_root / relative_path
        original = path.read_text(encoding="utf-8")
        patched = transform(original)
        if patched != original:
            path.write_text(patched, encoding="utf-8")
            changed.append(relative_path)
    header_path = source_root / GENERATED_HEADER
    header = generated_header(der)
    if not header_path.exists() or header_path.read_text(encoding="utf-8") != header:
        header_path.write_text(header, encoding="utf-8")
        changed.append(GENERATED_HEADER)
    changed.extend(copy_branding_icons(source_root))
    changed.extend(rebrand_resources(source_root))
    for relative_path, content in native_policy.generated_files().items():
        destination = source_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if not destination.exists() or destination.read_text() != content:
            destination.write_text(content, encoding="utf-8")
            changed.append(relative_path)
    return changed


def copy_branding_icons(source_root: Path) -> list[Path]:
    changed: list[Path] = []
    for asset_path, relative_path in FENIX_LEGACY_ICONS:
        if not asset_path.is_file():
            raise ValueError(f"launcher icon asset is missing: {asset_path}")
        destination = source_root / relative_path
        if not destination.is_file():
            raise ValueError(f"upstream launcher icon is missing: {relative_path}")
        if destination.read_bytes() != asset_path.read_bytes():
            shutil.copyfile(asset_path, destination)
            changed.append(relative_path)
    for asset_path, relative_path in FENIX_ADAPTIVE_ICONS:
        if not asset_path.is_file():
            raise ValueError(f"launcher icon asset is missing: {asset_path}")
        destination = source_root / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        if (
            not destination.is_file()
            or destination.read_bytes() != asset_path.read_bytes()
        ):
            shutil.copyfile(asset_path, destination)
            changed.append(relative_path)
    return changed


def fetch_text(url: str) -> str:
    request = urllib.request.Request(
        url, headers={"User-Agent": "Ruthenium-Firefox-patch-check/1"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return response.read().decode("utf-8", "strict")


def check_remote(raw_base_url: str, der: bytes) -> None:
    native_policy.generated_files()  # Validate pinned log keys and intervals too.
    for relative_path, transform in TRANSFORMS.items():
        source = fetch_text(f"{raw_base_url.rstrip('/')}/{relative_path.as_posix()}")
        patched = transform(source)
        if patched == source:
            raise ValueError(f"remote source already appears patched: {relative_path}")
        if transform(patched) != patched:
            raise ValueError(f"patch is not idempotent: {relative_path}")
    header = generated_header(der)
    if hashlib.sha256(der).hexdigest() not in header:
        raise ValueError("generated header does not record the certificate digest")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path)
    parser.add_argument(
        "--check-remote",
        metavar="RAW_BASE_URL",
        help="validate all text transforms against an hg raw-file base URL",
    )
    parser.add_argument("--list-targets", action="store_true")
    args = parser.parse_args()

    if args.list_targets:
        for path in (
            *TRANSFORMS,
            *(path for _, path in FENIX_LEGACY_ICONS),
            *(path for _, path in FENIX_ADAPTIVE_ICONS),
            GENERATED_HEADER,
            *native_policy.generated_files(),
        ):
            print(path)
        return

    der = load_verified_certificate()
    if args.check_remote:
        check_remote(args.check_remote, der)
        print("Ruthenium patch compatibility passed")
        return
    if args.source is None:
        parser.error("--source is required unless --check-remote or --list-targets is used")
    changed = patch_checkout(args.source.resolve(), der)
    if changed:
        print("patched:")
        for path in changed:
            print(f"  {path}")
    else:
        print("already patched")


if __name__ == "__main__":
    main()
