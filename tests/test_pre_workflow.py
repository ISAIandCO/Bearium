"""Keep manual test builds isolated from production publishing and signing."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/build-pre.yml"


class PreWorkflowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text()

    def test_manual_build_has_no_production_publish_or_signing_path(self):
        triggers = self.workflow.split("on:\n", 1)[1].split("permissions:", 1)[0]
        self.assertIn("workflow_dispatch:", triggers)
        for trigger in ("push:", "schedule:", "workflow_run:", "pull_request:"):
            self.assertNotIn(trigger, triggers)
        self.assertIn("contents: read", self.workflow)
        self.assertIn('BEARIUM_PRODUCTION: "0"', self.workflow)
        self.assertNotRegex(self.workflow, r"\$\{\{\s*secrets\.")
        for forbidden in ("contents: write", "release-signing", "gh release",
                          "resolve_policy_release", "prepare_play_signing", "upload_play"):
            self.assertNotIn(forbidden, self.workflow)
        self.assertIn("group: bearium-pre-", self.workflow)
        self.assertNotIn("Build and release Bearium for Android", self.workflow)

    def test_development_package_key_and_native_abi_are_checked(self):
        self.assertIn("default: dev", self.workflow)
        self.assertIn("ref: ${{ inputs.source_ref }}", self.workflow)
        self.assertIn("persist-credentials: false", self.workflow)
        self.assertIn("RFIREFOX_TARGET: aarch64-linux-android", self.workflow)
        self.assertIn("RFIREFOX_TARGET_ABI: arm64-v8a", self.workflow)
        self.assertNotIn("matrix:", self.workflow)
        self.assertIn("package: name='app.bearium.browser.dev'", self.workflow)
        self.assertIn('if [[ "$signer_sha256" != "$RFIREFOX_DEBUG_CERT_SHA256" ]]', self.workflow)
        self.assertIn('verify_android_apk.py --apk "$test_apk" --abi "$TARGET_ABI"', self.workflow)
        self.assertLess(self.workflow.index("prepare_onnx_runtime.py"),
                        self.workflow.index("run: ./mach build"))
        self.assertIn("name: bearium-pre-arm64-v8a-", self.workflow)

    def test_apk_checks_report_the_failed_contract(self):
        # Run the workflow's actual checks, with Android tools represented by
        # their text output. A mismatched version must not just exit silently.
        start = self.workflow.index('          if [[ "$signer_sha256" !=')
        end = self.workflow.index('          (cd "$artifact_dir"', start)
        script = textwrap.dedent(self.workflow[start:end])
        digest = "a" * 64
        valid = "package: name='app.bearium.browser.dev' versionName='157.0.1'\nnative-code: 'arm64-v8a'"
        cases = (
            (digest, valid, None),
            ("b" * 64, valid, "signer"),
            (digest, valid.replace("browser.dev", "browser"), "application ID"),
            (digest, valid.replace("157.0.1", "null"), "versionName"),
            (digest, valid.replace("arm64-v8a", "x86_64"), "native code"),
            (digest, valid + "\napplication-debuggable", "debug/test-only"),
        )
        with tempfile.TemporaryDirectory() as directory:
            aapt = Path(directory) / "aapt2"
            aapt.write_text('#!/bin/sh\nprintf "%s\\n" "$APK_BADGING"\n')
            aapt.chmod(0o755)
            for signer, badging, error in cases:
                with self.subTest(error=error):
                    result = subprocess.run(["bash", "-e", "-c", script], capture_output=True, text=True, env={
                        **os.environ, "signer_sha256": signer, "RFIREFOX_DEBUG_CERT_SHA256": digest,
                        "aapt2": str(aapt), "test_apk": "test.apk", "APK_BADGING": badging,
                        "FIREFOX_VERSION": "157.0.1", "TARGET_ABI": "arm64-v8a",
                    })
                    self.assertEqual(result.returncode, 1 if error else 0)
                    if error:
                        self.assertIn("::error::", result.stdout)
                        self.assertIn(error, result.stdout)

    def test_source_metadata_uses_checked_out_code_instead_of_workflow_commit(self):
        script = textwrap.dedent(self.workflow.split("<<'PYCODE'\n", 1)[1].split("          PYCODE", 1)[0])
        source_commit = "a" * 40
        workflow_commit = "b" * 40
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)
            # git stands in for the checkout action's selected source revision.
            git = path / "git"
            git.write_text(f"#!/bin/sh\nprintf '%s\\n' '{source_commit}'\n")
            git.chmod(0o755)
            (path / "source.json").write_text(json.dumps({
                "version": "157.0.1", "revision": "c" * 40,
                "archive_url": "https://example.invalid/archive.zip",
            }))
            subprocess.run(["python3", "-c", script], cwd=path, check=True, env={
                **os.environ, "PATH": str(path) + os.pathsep + os.environ["PATH"],
                "SOURCE_REF": "dev", "GITHUB_SHA": workflow_commit,
                "GITHUB_RUN_ID": "123", "GITHUB_RUN_ATTEMPT": "2",
                "GITHUB_OUTPUT": str(path / "outputs"), "GITHUB_ENV": str(path / "env"),
            })
            metadata = json.loads((path / "source.json").read_text())
            self.assertEqual(metadata["source_commit"], source_commit)
            self.assertEqual(metadata["workflow_commit"], workflow_commit)
            self.assertEqual(metadata["application_id"], "app.bearium.browser.dev")
            self.assertIn("MOZ_BUILD_DATE=", (path / "env").read_text())


if __name__ == "__main__":
    unittest.main()
