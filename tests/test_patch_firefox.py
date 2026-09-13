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
        self.assertIn(">Bearium</string>", patched)
        self.assertEqual(patched, patch_firefox.patch_fenix_strings(patched))

        release_strings = (
            '<resources><string name="app_name" translatable="false">'
            "Firefox</string></resources>"
        )
        patched_release = patch_firefox.patch_fenix_release_strings(
            release_strings
        )
        self.assertIn(">Bearium</string>", patched_release)
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
            applicationIdSuffix ".firefox"
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
        self.assertIn('applicationId "app.bearium"', patched)
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

    def test_launcher_uses_approved_color_and_monochrome_assets(self) -> None:
        upstream = '<vector xmlns:android="http://schemas.android.com/apk/res/android"><path/></vector>'
        patched = patch_firefox.patch_fenix_launcher_foreground(upstream)
        self.assertEqual(ElementTree.fromstring(patched).tag, "bitmap")
        self.assertIn("@drawable/bearium_artwork", patched)
        self.assertEqual(patched, patch_firefox.patch_fenix_launcher_foreground(patched))
        for asset, _ in patch_firefox.FENIX_ADAPTIVE_ICONS:
            ElementTree.fromstring(asset.read_text())
        for asset, _ in patch_firefox.FENIX_LEGACY_ICONS:
            self.assertEqual(asset.read_bytes()[:4], b"RIFF")
        for asset, _ in patch_firefox.FENIX_COLOR_ARTWORK:
            self.assertEqual(asset.read_bytes()[:4], b"RIFF")

    def test_themed_launcher_does_not_flatten_fox_r_to_black_r(self) -> None:
        adaptive_icon = """<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">
    <background android:drawable="@color/ic_launcher_background"/>
    <foreground android:drawable="@drawable/ic_launcher_foreground"/>
    <monochrome android:drawable="@drawable/ic_launcher_monochrome"/>
</adaptive-icon>
"""
        adaptive_icon = patch_firefox.patch_fenix_adaptive_icon(adaptive_icon)
        self.assertIn("@drawable/bearium_background", adaptive_icon)
        self.assertIn("<monochrome", adaptive_icon)
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
                + len(patch_firefox.FENIX_ADAPTIVE_ICONS)
                + len(patch_firefox.FENIX_COLOR_ARTWORK),
            )
            self.assertEqual(patch_firefox.copy_branding_icons(source_root), [])
            for asset_path, relative_path in (
                *patch_firefox.FENIX_LEGACY_ICONS,
                *patch_firefox.FENIX_ADAPTIVE_ICONS,
                *patch_firefox.FENIX_COLOR_ARTWORK,
            ):
                self.assertEqual(
                    (source_root / relative_path).read_bytes(),
                    Path(asset_path).read_bytes(),
                )

    def test_compose_branding_uses_direct_bitmap_without_duplicate_xml(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            res = root / "mobile/android/fenix/app/src/main/res/drawable"
            res.mkdir(parents=True)
            for name in ("ic_splash_logo", "ic_firefox", "ic_status_logo"):
                (res / f"{name}.xml").write_text("<vector/>")
            patch_firefox.rebrand_resources(root)
            self.assertFalse((res / "ic_splash_logo.xml").exists())
            self.assertFalse((res / "ic_firefox.xml").exists())
            self.assertEqual((res / "ic_splash_logo.webp").read_bytes()[:4], b"RIFF")
            self.assertEqual(ElementTree.parse(res / "ic_status_logo.xml").getroot().tag, "vector")
            self.assertEqual(patch_firefox.rebrand_resources(root), [])


if __name__ == "__main__":
    unittest.main()
