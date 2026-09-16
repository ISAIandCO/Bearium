from __future__ import annotations

import json
import struct
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from scripts import prepare_onnx_runtime as onnx


REVISION = "a" * 40
DECISION = "D" * 22
TASK = "T" * 22
ROOT = Path(__file__).resolve().parents[1]


def elf(target):
    elf_class, machine = onnx.TARGETS[target]
    header = bytearray(64)
    header[:7] = b"\x7fELF" + bytes((elf_class, 1, 1))
    struct.pack_into("<HH", header, 16, 3, machine)
    return bytes(header)


class OnnxRuntimeTest(unittest.TestCase):
    def test_exact_release_graph_selects_each_abi(self):
        for target in onnx.TARGETS:
            with self.subTest(target=target):
                calls = []
                def fetch(url):
                    calls.append(url)
                    if "/index/" in url:
                        self.assertIn(f"mozilla-release.revision.{REVISION}.", url)
                        return {"taskId": DECISION}
                    self.assertEqual(url, onnx.artifact_url(DECISION, "label-to-taskid.json"))
                    return {f"toolchain-onnxruntime-{target}": TASK}
                self.assertEqual(onnx.resolve_toolchain(REVISION, target, fetch), (DECISION, TASK))
                self.assertEqual(len(calls), 2)

    def test_official_graph_cache_indices_when_not_scheduled(self):
        target = "aarch64-linux-android"
        responses = iter([
            {"taskId": DECISION}, {},
            {f"toolchain-onnxruntime-{target}": {"optimization": {"index-search": [
                "gecko.cache.level-3.toolchains.v3.onnxruntime.hash1",
                "gecko.cache.level-2.toolchains.v3.onnxruntime.hash2"]}}},
            urllib.error.HTTPError("url", 404, "missing", {}, None), {"taskId": TASK}])
        def fetch(url):
            value = next(responses)
            if isinstance(value, Exception):
                raise value
            return value
        self.assertEqual(onnx.resolve_toolchain(REVISION, target, fetch), (DECISION, TASK))

    def test_missing_artifact_fails_without_latest_fallback(self):
        responses = iter([{"taskId": DECISION}, {}, {}])
        with self.assertRaisesRegex(RuntimeError, "ONNX remains required"):
            onnx.resolve_toolchain(REVISION, "x86_64-linux-android", lambda url: next(responses))

    def test_invalid_inputs_are_rejected_before_network(self):
        for revision, target in [("latest", "aarch64-linux-android"), (REVISION, "x86")]:
            with self.assertRaises(ValueError):
                onnx.resolve_toolchain(revision, target, lambda url: self.fail(url))

    def test_elf_must_be_shared_and_match_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "libonnxruntime.so"
            for target in onnx.TARGETS:
                path.write_bytes(elf(target))
                onnx.verify_library(path, target)
                other = next(t for t in onnx.TARGETS if t != target)
                with self.assertRaises(ValueError):
                    onnx.verify_library(path, other)
            for data in [b"", b"not an ELF", elf(target)[:16] + b"\x02\x00" + elf(target)[18:]]:
                path.write_bytes(data)
                with self.assertRaises(ValueError):
                    onnx.verify_library(path, target)

    def test_install_replaces_stale_library_and_requires_onnx(self):
        target = "aarch64-linux-android"
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "firefox"
            source.mkdir()
            mach = source / "mach"
            mach.write_text("#!/usr/bin/env python3\nimport pathlib, sys\n"
                            f"assert sys.argv[1:] == ['artifact', 'toolchain', '--from-task', '{TASK}:public/build/onnxruntime-{target}.tar.zst']\n"
                            f"p=pathlib.Path('onnxruntime-{target}'); p.mkdir()\n"
                            f"(p/'libonnxruntime.so').write_bytes({elf(target)!r})\n")
            mach.chmod(0o755)
            config = source / "mozconfig"
            config.write_text("ac_add_options --target=aarch64-linux-android\nac_add_options --without-onnx-runtime\n")
            output = root / "runtime with spaces"
            dest = output / REVISION / f"onnxruntime-{target}"
            dest.mkdir(parents=True)
            (dest / "libonnxruntime.so").write_bytes(b"stale")
            argv = ["prepare", "--source", str(source), "--revision", REVISION,
                    "--target", target, "--mozconfig", str(config), "--output", str(output)]
            with patch.object(sys, "argv", argv), patch.object(onnx, "resolve_toolchain", return_value=(DECISION, TASK)):
                onnx.main()
            onnx.verify_library(dest / "libonnxruntime.so", target)
            metadata = json.loads((dest / "source.json").read_text())
            self.assertEqual(metadata["revision"], REVISION)
            self.assertEqual(metadata["toolchain_task"], TASK)
            content = config.read_text()
            self.assertNotIn("--without-onnx-runtime", content)
            self.assertIn("--target=aarch64-linux-android", content)
            onnx.configure(config, dest)
            self.assertEqual(config.read_text(), content)

    def test_both_workflows_install_before_build(self):
        for name in ("build-android.yml", "build-play.yml"):
            content = (ROOT / ".github/workflows" / name).read_text()
            self.assertLess(content.index("run_bootstrap_with_heartbeat.sh"), content.index("prepare_onnx_runtime.py"))
            self.assertLess(content.index("prepare_onnx_runtime.py"), content.index("run: ./mach build"))
            self.assertIn('FIREFOX_REVISION: ${{ needs.resolve.outputs.revision }}', content)
            self.assertIn('--target "$RFIREFOX_TARGET"', content)


if __name__ == "__main__":
    unittest.main()
