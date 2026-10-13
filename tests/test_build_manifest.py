import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from scripts import build_manifest as manifest
from tests.test_onnx_runtime import elf


class BuildManifestTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = {"version": "157.0.1", "revision": "a" * 40, "source_commit": "b" * 40,
                       "version_code": 7, "archive_url": manifest.STABLE_REPOSITORY + "/archive/" + "a" * 40 + ".zip"}
        self.manifests = []
        for abi, target in manifest.ABI_TARGETS.items():
            runtime = self.root / self.source["revision"] / f"onnxruntime-{target}"
            runtime.mkdir(parents=True)
            library = elf(target)
            (runtime / "libonnxruntime.so").write_bytes(library)
            (runtime / "source.json").write_text(json.dumps({
                "revision": self.source["revision"], "target": target,
                "sha256": hashlib.sha256(library).hexdigest(), "toolchain_task": "T" * 22,
            }))
            value = manifest.make_manifest(self.source, "c" * 64, abi, self.root)
            self.manifests.append(value)
            (self.root / f"build-manifest-{abi}.json").write_text(json.dumps(value))
        self.source.update(policy_fingerprint=value["policy_fingerprint"],
                           certificate_sha256=value["certificate_der_sha256"])

    def test_all_abis_share_one_archive_without_changing_release_identity(self):
        result = manifest.merge_manifests(self.source, self.root)
        for key in self.source:
            self.assertEqual(result[key], self.source[key])
        self.assertEqual(result["archive_sha256"], "c" * 64)
        self.assertEqual(len(result["build_manifests"]), 3)
        self.assertEqual(result["build_materials_version"], 1)

    def test_changed_archives_policy_or_commit_stop_the_release(self):
        path = self.root / "build-manifest-arm64-v8a.json"
        original = json.loads(path.read_text())
        for key in ("archive_sha256", "policy_fingerprint", "bearium_commit", "firefox_revision"):
            with self.subTest(key=key):
                changed = {**original, key: "d" * len(original[key])}
                path.write_text(json.dumps(changed))
                with self.assertRaises(ValueError):
                    manifest.merge_manifests(self.source, self.root)
        path.write_text(json.dumps(original))
        with self.assertRaises(ValueError):
            manifest.merge_manifests({**self.source, "source_commit": "e" * 40}, self.root)

    def test_missing_or_duplicate_abi_is_rejected(self):
        path = self.root / "build-manifest-arm64-v8a.json"
        original = path.read_text()
        path.unlink()
        with self.assertRaises(ValueError):
            manifest.merge_manifests(self.source, self.root)
        changed = json.loads(original)
        changed["abi"] = "x86_64"
        path.write_text(json.dumps(changed))
        with self.assertRaises(ValueError):
            manifest.merge_manifests(self.source, self.root)

    def test_stale_onnx_bytes_cannot_match_the_manifest(self):
        library = self.root / self.source["revision"] / "onnxruntime-aarch64-linux-android/libonnxruntime.so"
        library.write_bytes(library.read_bytes() + b"different")
        with self.assertRaisesRegex(ValueError, "ONNX provenance"):
            manifest.make_manifest(self.source, "c" * 64, "arm64-v8a", self.root)

    def test_source_archive_url_and_hash_are_validated(self):
        with self.assertRaises(ValueError):
            manifest.make_manifest(self.source, "bad", "arm64-v8a", self.root)
        with self.assertRaises(ValueError):
            manifest.make_manifest({**self.source, "archive_url": "https://example.com/source.zip"},
                                   "c" * 64, "arm64-v8a", self.root)

    def test_workflow_cli_accepts_both_source_storage_paths(self):
        output = self.root / "cli.json"
        subprocess.run(["python3", "-m", "scripts.build_manifest", "--abi", "arm64-v8a",
                        "--onnx-root", str(self.root), "--output", str(output)], check=True,
                       cwd=manifest.REPOSITORY_ROOT, env={**os.environ, "SOURCE_JSON": json.dumps(self.source),
                       "FIREFOX_ARCHIVE_SHA256": "c" * 64})
        self.assertEqual(json.loads(output.read_text())["archive_sha256"], "c" * 64)
        source = self.root / "source.json"
        source.write_text(json.dumps(self.source))
        subprocess.run(["python3", "-m", "scripts.build_manifest", "--merge-dir", str(self.root),
                        "--source-json", str(source), "--output", str(source)], check=True,
                       cwd=manifest.REPOSITORY_ROOT)
        self.assertEqual(json.loads(source.read_text())["build_materials_version"], 1)


if __name__ == "__main__":
    unittest.main()
