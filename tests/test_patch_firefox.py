from __future__ import annotations

import hashlib
import tempfile
import unittest
import xml.etree.ElementTree as ElementTree
from pathlib import Path

from scripts import patch_firefox


class CertificatePatchTest(unittest.TestCase):
    def test_pinned_certificate(self) -> None:
        der = patch_firefox.load_verified_certificate()
        self.assertEqual(
            hashlib.sha256(der).hexdigest(),
            "d26d2d0231b7c39f92cc738512ba54103519e4405d68b5bd703e9788ca8ecf31",
        )

    def test_generated_header_contains_only_the_pinned_root(self) -> None:
        header = patch_firefox.generated_header(patch_firefox.load_verified_certificate())
        self.assertIn("kRutheniumRussianRootDER", header)
        self.assertNotIn("kRutheniumNameConstraintsDER", header)

    def test_product_patches_are_idempotent(self) -> None:
        strings = """<resources xmlns:tools="http://schemas.android.com/tools">
    <string name="app_name" translatable="false">Firefox Fenix</string>
    <string name="firefox" translatable="false">Firefox</string>
    <string name="app_name_firefox" tools:ignore="BrandUsage">Firefox</string>
</resources>
"""
        patched = patch_firefox.patch_fenix_strings(strings)
        self.assertIn(">Rufox</string>", patched)
        self.assertEqual(patched, patch_firefox.patch_fenix_strings(patched))

        release_strings = (
            '<resources><string name="app_name" translatable="false">'
            "Firefox</string></resources>"
        )
        patched_release = patch_firefox.patch_fenix_release_strings(
            release_strings
        )
        self.assertIn(">Rufox</string>", patched_release)
        self.assertEqual(
            patched_release,
            patch_firefox.patch_fenix_release_strings(patched_release),
        )

    def test_release_variant_explicitly_uses_debug_signing(self) -> None:
        gradle = """android {
    defaultConfig {
        applicationId "org.mozilla"
    }
    splits {
        abi {
            if (project.hasProperty("benchmarkTest")) {
                include "arm64-v8a"
            } else {
                include "armeabi-v7a", "arm64-v8a", "x86_64"
                if (gradle.mozconfig.substs.MOZILLA_OFFICIAL || System.getenv("MOZ_BUILD_CONFIG_LINT") == "1") {
                    universalApk true
                }
            }
        }
    }
    buildTypes {
        release releaseTemplate >> {
            def deepLinkSchemeValue = "fenix"
            manifestPlaceholders.putAll([
                    "sharedUserId": "org.mozilla.firefox.sharedID",
            ])
        }
        benchmark releaseTemplate >> {
        }
    }
}
"""
        patched = patch_firefox.patch_fenix_gradle(gradle)
        self.assertIn("signingConfig = signingConfigs.debug", patched)
        self.assertIn("RFIREFOX_DEBUG_KEYSTORE", patched)
        self.assertIn('signingConfigs.debug.keyAlias = "androiddebugkey"', patched)
        self.assertIn('applicationId "app.ruthenium"', patched)
        self.assertIn('System.getenv("RFIREFOX_TARGET_ABI")', patched)
        self.assertIn(
            '["armeabi-v7a", "arm64-v8a", "x86_64"]',
            patched,
        )
        self.assertIn("include rfirefoxTargetAbi", patched)
        self.assertNotIn(
            'include "armeabi-v7a", "arm64-v8a", "x86_64"', patched
        )
        self.assertNotIn("universalApk true", patched)
        self.assertEqual(patched, patch_firefox.patch_fenix_gradle(patched))

    def test_launcher_uses_integrated_fox_r_adaptive_assets(self) -> None:
        upstream = """<vector xmlns:android="http://schemas.android.com/apk/res/android"
    android:viewportWidth="108"><path android:pathData="M0,0" /></vector>
"""
        patched = patch_firefox.patch_fenix_launcher_foreground(upstream)
        self.assertEqual(patched, patch_firefox.RFIREFOX_ADAPTIVE_FOREGROUND)
        self.assertNotIn('android:pathData="M0,0"', patched)
        self.assertIn("Rufox adaptive fox-R foreground", patched)
        self.assertIn(
            'android:src="@drawable/rfirefox_launcher_foreground"', patched
        )
        self.assertNotIn("<path", patched)
        foreground_root = ElementTree.fromstring(patched)
        self.assertEqual(foreground_root.tag, "bitmap")
        self.assertEqual(
            foreground_root.attrib[
                "{http://schemas.android.com/apk/res/android}src"
            ],
            "@drawable/rfirefox_launcher_foreground",
        )
        self.assertEqual(
            foreground_root.attrib[
                "{http://schemas.android.com/apk/res/android}gravity"
            ],
            "fill",
        )
        self.assertEqual(
            patched,
            patch_firefox.patch_fenix_launcher_foreground(patched),
        )

        self.assertEqual(len(patch_firefox.FENIX_LEGACY_ICONS), 10)
        self.assertEqual(len(patch_firefox.FENIX_ADAPTIVE_ICONS), 1)
        for asset_path, _ in (
            *patch_firefox.FENIX_LEGACY_ICONS,
            *patch_firefox.FENIX_ADAPTIVE_ICONS,
        ):
            data = Path(asset_path).read_bytes()
            self.assertTrue(data.startswith(b"RIFF"), asset_path)
            self.assertEqual(data[8:12], b"WEBP", asset_path)

        for asset_path, _ in patch_firefox.FENIX_ADAPTIVE_ICONS:
            data = Path(asset_path).read_bytes()
            self.assertEqual(data[12:16], b"VP8L", asset_path)
            self.assertEqual(data[20], 0x2F, asset_path)
            lossless_header = int.from_bytes(data[21:25], "little")
            width = (lossless_header & 0x3FFF) + 1
            height = ((lossless_header >> 14) & 0x3FFF) + 1
            self.assertEqual((width, height), (432, 432), asset_path)
            self.assertTrue(lossless_header & (1 << 28), asset_path)

    def test_themed_launcher_does_not_flatten_fox_r_to_black_r(self) -> None:
        adaptive_icon = """<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background"/>
    <foreground android:drawable="@drawable/ic_launcher_foreground"/>
    <monochrome android:drawable="@drawable/ic_launcher_monochrome"/>
</adaptive-icon>
"""
        adaptive_icon = patch_firefox.patch_fenix_adaptive_icon(adaptive_icon)
        self.assertIn("intentionally keeps its full-colour", adaptive_icon)
        self.assertNotIn("<monochrome", adaptive_icon)
        adaptive_root = ElementTree.fromstring(adaptive_icon)
        self.assertEqual(adaptive_root.tag, "adaptive-icon")
        self.assertEqual(
            adaptive_icon,
            patch_firefox.patch_fenix_adaptive_icon(adaptive_icon),
        )

    def test_launcher_assets_are_copied_idempotently(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            source_root = Path(directory)
            for _, relative_path in patch_firefox.FENIX_LEGACY_ICONS:
                destination = source_root / relative_path
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(b"upstream icon")

            changed = patch_firefox.copy_branding_icons(source_root)
            self.assertEqual(
                len(changed),
                len(patch_firefox.FENIX_LEGACY_ICONS)
                + len(patch_firefox.FENIX_ADAPTIVE_ICONS),
            )
            self.assertEqual(patch_firefox.copy_branding_icons(source_root), [])
            for asset_path, relative_path in (
                *patch_firefox.FENIX_LEGACY_ICONS,
                *patch_firefox.FENIX_ADAPTIVE_ICONS,
            ):
                self.assertEqual(
                    (source_root / relative_path).read_bytes(),
                    Path(asset_path).read_bytes(),
                )


if __name__ == "__main__":
    unittest.main()
