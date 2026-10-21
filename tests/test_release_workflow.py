from __future__ import annotations

import unittest
import os
import shlex
import subprocess
import tempfile
import textwrap
import zipfile
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = REPOSITORY_ROOT / ".github/workflows/build-android.yml"
BOOTSTRAP_SCRIPT = REPOSITORY_ROOT / "scripts/run_bootstrap_with_heartbeat.sh"


class ReleaseWorkflowPolicyTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_signer_pipeline_passes_output_and_preserves_certificate_report(self) -> None:
        start = self.workflow.index('          printf \'%s\\n\' "$signer_info"')
        end = self.workflow.index('          expected_signer=', start)
        script = textwrap.dedent(self.workflow[start:end])
        digest = "a" * 64
        signer_info = f"Verifies\nV2 Signer: certificate SHA-256 digest: {digest}"
        with tempfile.TemporaryDirectory() as directory:
            apk = Path(directory) / "release.apk"
            result = subprocess.run(
                ["bash", "-e", "-c", script + '\nprintf "%s\\n" "$signer_sha256"'],
                env={**os.environ, "signer_info": signer_info,
                     "release_apk": str(apk), "GITHUB_WORKSPACE": str(REPOSITORY_ROOT)},
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(result.stdout.splitlines()[-1], digest)
            self.assertEqual(Path(str(apk) + ".certificate.txt").read_text(), signer_info + "\n")

    def test_native_policy_pr_build_cannot_publish_a_release(self) -> None:
        trigger_section = self.workflow.split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", trigger_section)
        self.assertIn("schedule:", trigger_section)
        self.assertNotIn("push:", trigger_section)
        self.assertNotIn("pull_request:", trigger_section)
        publish = self.workflow.split("  publish:", 1)[1]
        self.assertIn("github.event_name != 'pull_request'", publish)
        self.assertIn("github.ref == 'refs/heads/main'", publish)

    def test_release_uses_private_key_and_plain_version_tag(self) -> None:
        self.assertNotIn("-PdisableDebugSigning", self.workflow)
        self.assertNotIn('"$apksigner" sign', self.workflow)
        self.assertIn('"$apksigner" verify', self.workflow)
        self.assertIn("parse_apksigner_output.py", self.workflow)
        self.assertNotIn(
            "s/^Signer #1 certificate SHA-256 digest: //p", self.workflow
        )
        self.assertIn("signing/rfirefox-debug.keystore", self.workflow)
        self.assertIn(
            "d7a19050129bbb6e7af6f29dc899a123757ca226ea0ee3c7395c43527592035f",
            self.workflow,
        )
        self.assertIn('python3 -m scripts.resolve_policy_release', self.workflow)
        self.assertIn('BEARIUM_PRODUCTION: "1"', self.workflow)
        self.assertIn("prepare_play_signing.py", self.workflow)
        self.assertIn("environment: release-signing", self.workflow)
        self.assertIn('--title "$RELEASE_TAG"', self.workflow)
        self.assertIn('gh release create "$RELEASE_TAG"', self.workflow)

    def test_existing_firefox_release_skips_the_expensive_build(self) -> None:
        self.assertIn("release_exists:", self.workflow)
        self.assertIn(
            "needs.resolve.outputs.release_exists != 'true' || "
            "github.event_name == 'workflow_dispatch'",
            self.workflow,
        )
        self.assertIn(
            'RELEASE_EXISTS: ${{ needs.resolve.outputs.release_exists }}',
            self.workflow,
        )
        self.assertIn('gh release upload "$RELEASE_TAG"', self.workflow)
        self.assertIn("--clobber", self.workflow)

    def test_each_abi_uses_an_isolated_matrix_job(self) -> None:
        self.assertIn("strategy:", self.workflow)
        self.assertIn("fail-fast: false", self.workflow)
        for abi, target in (
            ("arm64-v8a", "aarch64-linux-android"),
            ("armeabi-v7a", "arm-linux-androideabi"),
            ("x86_64", "x86_64-linux-android"),
        ):
            self.assertIn(f"- abi: {abi}", self.workflow)
            self.assertIn(f"target: {target}", self.workflow)
        self.assertIn(
            "MOZ_OBJDIR_NAME: obj-ruthenium-${{ matrix.abi }}", self.workflow
        )
        self.assertIn("RFIREFOX_TARGET: ${{ matrix.target }}", self.workflow)
        self.assertIn("TARGET_ABI: ${{ matrix.abi }}", self.workflow)
        self.assertIn("RFIREFOX_TARGET_ABI: ${{ matrix.abi }}", self.workflow)
        self.assertIn(
            "ac_add_options --target=$RFIREFOX_TARGET", self.workflow
        )
        self.assertIn(
            "'/^[[:space:]]*ac_add_options[[:space:]]+--target=/d'",
            self.workflow,
        )
        self.assertNotIn("i686-linux-android", self.workflow)

    def test_each_apk_must_contain_matching_gecko_libraries(self) -> None:
        self.assertIn("scripts/verify_android_apk.py", self.workflow)
        self.assertIn('--abi "$TARGET_ABI"', self.workflow)
        self.assertIn("native-code: '$TARGET_ABI'", self.workflow)
        self.assertIn("name: bearium-apk-${{ matrix.abi }}", self.workflow)
        self.assertIn("path: artifacts-${{ matrix.abi }}/", self.workflow)

    def test_release_is_published_only_after_all_abis_pass(self) -> None:
        self.assertIn("needs: [resolve, build]", self.workflow)
        self.assertIn("needs.build.result == 'success'", self.workflow)
        self.assertIn("pattern: bearium-apk-*", self.workflow)
        self.assertIn("merge-multiple: true", self.workflow)
        self.assertIn(
            "expected_abis=(arm64-v8a armeabi-v7a x86_64)", self.workflow
        )
        self.assertIn(
            'if [[ "${#apks[@]}" -ne "${#expected_abis[@]}" ]]',
            self.workflow,
        )
        self.assertIn('--abi "$abi"', self.workflow)
        self.assertIn("ABIs: arm64-v8a, armeabi-v7a, x86_64", self.workflow)

    def test_matrix_jobs_do_not_share_abi_caches_or_object_directories(self) -> None:
        self.assertIn(
            "key: firefox-android-${{ matrix.abi }}-v3-${{ runner.os }}-",
            self.workflow,
        )
        self.assertIn(
            "restore-keys: |\n"
            "            firefox-android-${{ matrix.abi }}-v3-${{ runner.os }}-",
            self.workflow,
        )
        self.assertIn(
            "MOZ_OBJDIR_NAME: obj-ruthenium-${{ matrix.abi }}", self.workflow
        )

    def test_rufox_branding_is_checked_before_publish(self) -> None:
        self.assertIn("Build and release Bearium for Android", self.workflow)
        self.assertIn("application-label:'Bearium'", self.workflow)
        self.assertIn(
            'release_name="Bearium-$RELEASE_TAG-$upstream_name.apk"',
            self.workflow,
        )
        self.assertIn("Product: Bearium", self.workflow)

    def test_release_publication_retries_and_is_idempotent(self) -> None:
        self.assertIn("retry_gh() {", self.workflow)
        self.assertIn("max_attempts=5", self.workflow)
        self.assertIn("delay_seconds=$((delay_seconds * 2))", self.workflow)
        self.assertIn('gh release view "$RELEASE_TAG"', self.workflow)
        self.assertIn("release_ready=true", self.workflow)
        self.assertIn(
            "for asset in artifacts/*.apk artifacts/*.apk.sha256 "
            "artifacts/*.certificate.txt artifacts/build-info.txt",
            self.workflow,
        )
        self.assertIn(
            'retry_gh gh release upload "$RELEASE_TAG" "$asset" --clobber',
            self.workflow,
        )

    def test_bootstrap_discards_cached_ndk_before_bootstrap(self) -> None:
        for name in ("build-android.yml", "build-play.yml", "build-pre.yml"):
            with self.subTest(workflow=name), tempfile.TemporaryDirectory() as directory:
                workflow = WORKFLOW.with_name(name).read_text(encoding="utf-8")
                self.assertIn('test "$HOME" = "/home/runner"', workflow)
                start = workflow.index("          rm -rf --")
                end = workflow.index(
                    '          bash "$GITHUB_WORKSPACE/scripts/run_bootstrap_with_heartbeat.sh"',
                    start,
                )
                mozbuild = Path(directory) / ".mozbuild"
                cleanup = textwrap.dedent(workflow[start:end]).replace(
                    "/home/runner/.mozbuild", shlex.quote(str(mozbuild))
                )
                for cached in ("mozboot", "android-ndk-r29", "android-ndk-r30",
                               "android-ndk-r31", "android-sdk-linux", "clang"):
                    path = mozbuild / cached
                    path.mkdir(parents=True)
                    (path / "cached").write_text("preserve other toolchains")
                archive = Path(directory) / "ndk.zip"
                with zipfile.ZipFile(archive, "w") as output:
                    output.writestr("android-ndk-r30/wrap.sh/hwasan.sh", "fresh NDK")
                # A cache containing a newer NDK must not make unzip prompt,
                # including when cleanup runs again after an interrupted build.
                for _ in range(2):
                    subprocess.run(["bash", "-e", "-c", cleanup], check=True)
                    subprocess.run(
                        ["unzip", "-q", str(archive)], cwd=mozbuild,
                        stdin=subprocess.DEVNULL, capture_output=True, check=True,
                    )
                    self.assertEqual(
                        (mozbuild / "android-ndk-r30/wrap.sh/hwasan.sh").read_text(),
                        "fresh NDK",
                    )
                for removed in ("mozboot", "android-ndk-r29", "android-ndk-r31"):
                    self.assertFalse((mozbuild / removed).exists())
                for preserved in ("android-sdk-linux", "clang"):
                    self.assertTrue((mozbuild / preserved / "cached").is_file())

    def test_bootstrap_has_live_diagnostics_without_an_extra_timeout(self) -> None:
        bootstrap_script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")

        self.assertNotIn("timeout-minutes: 100", self.workflow)
        self.assertNotIn("RFIREFOX_BOOTSTRAP_TIMEOUT", self.workflow)
        self.assertIn("run_bootstrap_with_heartbeat.sh", self.workflow)
        self.assertIn("Upload bootstrap diagnostics", self.workflow)
        self.assertIn("if: ${{ always() }}", self.workflow)
        self.assertNotIn("timeout --", bootstrap_script)
        self.assertIn("PYTHONUNBUFFERED=1 stdbuf", bootstrap_script)
        self.assertIn("Firefox bootstrap heartbeat", bootstrap_script)
        self.assertIn("bootstrap.log", bootstrap_script)
        self.assertIn("summary.txt", bootstrap_script)

    def test_bootstrap_creates_the_default_mozconfig_before_building(self) -> None:
        bootstrap_script = BOOTSTRAP_SCRIPT.read_text(encoding="utf-8")

        self.assertIn(
            'echo "MOZCONFIG=$RUNNER_TEMP/firefox-source/mozconfig"', self.workflow
        )
        self.assertNotIn(
            'echo "MOZCONFIG=$RUNNER_TEMP/firefox-source/.mozconfig"', self.workflow
        )
        self.assertIn(
            "unset MOZCONFIG ANDROID_HOME ANDROID_SDK_ROOT", bootstrap_script
        )
        self.assertLess(
            bootstrap_script.index("unset MOZCONFIG"),
            bootstrap_script.index("./mach --no-interactive bootstrap"),
        )

    def test_fenix_packaging_uses_one_bounded_gradle_process(self) -> None:
        self.assertIn(
            "Stop GeckoView Gradle daemons before Fenix packaging", self.workflow
        )
        self.assertIn("./gradlew --stop", self.workflow)
        self.assertIn('GRADLE_INVOKED_WITHIN_MACH_BUILD: "1"', self.workflow)
        self.assertIn(
            "./mach gradle --no-daemon --max-workers=2 fenix:assembleRelease",
            self.workflow,
        )


if __name__ == "__main__":
    unittest.main()
