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
        ICON_SOURCE_DIR / f"rfirefox-{density}.webp",
        Path(
            f"mobile/android/fenix/app/src/release/res/mipmap-{density}/"
            "ic_launcher.webp"
        ),
    )
    for density in ICON_DENSITIES
) + tuple(
    (
        ICON_SOURCE_DIR / f"rfirefox-round-{density}.webp",
        Path(
            f"mobile/android/fenix/app/src/release/res/mipmap-{density}/"
            "ic_launcher_round.webp"
        ),
    )
    for density in ICON_DENSITIES
)
FENIX_ADAPTIVE_ICONS = (
    (
        ICON_SOURCE_DIR / "rfirefox-adaptive-foreground.webp",
        Path(
            "mobile/android/fenix/app/src/main/res/drawable-xxxhdpi/"
            "rfirefox_launcher_foreground.webp"
        ),
    ),
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
        '        applicationId "app.ruthenium"',
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
            // Rufox development releases use the public debug key that is
            // pinned and passed in by the build tooling repository.
            def rfirefoxDebugKeystore = System.getenv("RFIREFOX_DEBUG_KEYSTORE")
            if (!rfirefoxDebugKeystore) {
                throw new GradleException("RFIREFOX_DEBUG_KEYSTORE is required")
            }
            signingConfigs.debug.storeFile = project.file(rfirefoxDebugKeystore)
            signingConfigs.debug.storePassword = "android"
            signingConfigs.debug.keyAlias = "androiddebugkey"
            signingConfigs.debug.keyPassword = "android"
            signingConfig = signingConfigs.debug
""",
        "Fenix release debug signing",
    )
    replacements = {
        'def deepLinkSchemeValue = "fenix"':
            'def deepLinkSchemeValue = "ruthenium"',
        '"sharedUserId": "org.mozilla.firefox.sharedID"':
            '"sharedUserId": "app.ruthenium.firefox.sharedID"',
    }
    for old, new in replacements.items():
        if new not in section:
            if section.count(old) != 1:
                raise ValueError(f"Fenix release branding anchor is ambiguous: {old}")
            section = section.replace(old, new, 1)
    return source[:start] + section + source[end:]


def patch_fenix_strings(source: str) -> str:
    replacements = {
        '<string name="app_name" translatable="false">Firefox Fenix</string>':
            '<string name="app_name" translatable="false">Rufox</string>',
        '<string name="firefox" translatable="false">Firefox</string>':
            '<string name="firefox" translatable="false">Rufox</string>',
        '<string name="app_name_firefox" tools:ignore="BrandUsage">Firefox</string>':
            '<string name="app_name_firefox" tools:ignore="BrandUsage">Rufox</string>',
    }
    for old, new in replacements.items():
        source = replace_once(source, old, new, "Fenix application name")
    return source


def patch_fenix_release_strings(source: str) -> str:
    return replace_once(
        source,
        '<string name="app_name" translatable="false">Firefox</string>',
        '<string name="app_name" translatable="false">Rufox</string>',
        "Fenix release application name",
    )


RFIREFOX_ADAPTIVE_FOREGROUND = """<?xml version="1.0" encoding="utf-8"?>
<!-- Rufox adaptive fox-R foreground. -->
<bitmap xmlns:android="http://schemas.android.com/apk/res/android"
    android:src="@drawable/rfirefox_launcher_foreground"
    android:antialias="true"
    android:dither="true"
    android:filter="true"
    android:gravity="fill" />
"""

RFIREFOX_THEMED_ICON_COMMENT = (
    "    <!-- Rufox intentionally keeps its full-colour fox-R artwork when "
    "themed icons are enabled. -->\n"
)


def patch_fenix_launcher_foreground(source: str) -> str:
    if source == RFIREFOX_ADAPTIVE_FOREGROUND:
        return source
    required = ('<vector xmlns:android=', 'android:viewportWidth="108"', '<path')
    if not all(anchor in source for anchor in required):
        raise ValueError("Fenix launcher foreground has an unexpected format")
    return RFIREFOX_ADAPTIVE_FOREGROUND


def patch_fenix_adaptive_icon(source: str) -> str:
    if RFIREFOX_THEMED_ICON_COMMENT in source:
        return source
    required = (
        "<adaptive-icon ",
        '<foreground android:drawable="@drawable/ic_launcher_foreground"/>',
        '<monochrome android:drawable="@drawable/ic_launcher_monochrome"/>',
    )
    if not all(anchor in source for anchor in required):
        raise ValueError("Fenix adaptive launcher icon has an unexpected format")
    return source.replace(
        '    <monochrome android:drawable="@drawable/ic_launcher_monochrome"/>\n',
        RFIREFOX_THEMED_ICON_COMMENT,
        1,
    )


TRANSFORMS: dict[Path, Callable[[str], str]] = {
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
