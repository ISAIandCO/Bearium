"""Record source/policy/ONNX inputs and require identical source archives across ABIs."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re

from scripts.patch_firefox import REPOSITORY_ROOT, load_verified_certificate
from scripts.prepare_onnx_runtime import verify_library
from scripts.resolve_firefox_source import STABLE_REPOSITORY, version_to_android_tag
from scripts.resolve_policy_release import fingerprint


ABI_TARGETS = {"arm64-v8a": "aarch64-linux-android", "armeabi-v7a": "arm-linux-androideabi", "x86_64": "x86_64-linux-android"}


def digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise ValueError("Expected a SHA-256 digest")
    return value


def make_manifest(source, archive_sha256, abi, onnx_root):
    for key in ("source_commit", "revision"):
        if not isinstance(source.get(key), str) or not re.fullmatch(r"[0-9a-f]{40}", source[key]):
            raise ValueError(f"Invalid {key}")
    version_to_android_tag(source["version"])
    if source.get("archive_url") != f"{STABLE_REPOSITORY}/archive/{source['revision']}.zip":
        raise ValueError("Unexpected Mozilla source archive URL")
    target = ABI_TARGETS[abi]
    runtime = onnx_root / source["revision"] / f"onnxruntime-{target}"
    onnx = json.loads((runtime / "source.json").read_text())
    library = runtime / "libonnxruntime.so"
    verify_library(library, target)
    if (onnx.get("revision") != source["revision"] or onnx.get("target") != target
            or digest(onnx.get("sha256")) != hashlib.sha256(library.read_bytes()).hexdigest()):
        raise ValueError("ONNX provenance does not match the installed library")
    certificate = load_verified_certificate()
    logs = (REPOSITORY_ROOT / "native/ct-log-list.json").read_bytes()
    return {
        "format_version": 1, "abi": abi, "bearium_commit": source["source_commit"],
        "firefox_version": source["version"], "firefox_revision": source["revision"],
        "archive_url": source["archive_url"], "archive_sha256": digest(archive_sha256),
        "certificate_der_sha256": hashlib.sha256(certificate).hexdigest(),
        "ct_log_list_sha256": hashlib.sha256(logs).hexdigest(),
        "policy_fingerprint": fingerprint(logs, certificate), "onnx": onnx,
    }


def merge_manifests(source, directory):
    paths = sorted(directory.glob("build-manifest-*.json"))
    manifests = [json.loads(path.read_text()) for path in paths]
    if len(manifests) != len(ABI_TARGETS) or {m.get("abi") for m in manifests} != set(ABI_TARGETS):
        raise ValueError("Expected one build manifest for each release ABI")
    reference = manifests[0]
    common = ("bearium_commit", "firefox_version", "firefox_revision", "archive_url", "archive_sha256",
              "certificate_der_sha256", "ct_log_list_sha256", "policy_fingerprint")
    for manifest in manifests:
        if manifest.get("format_version") != 1 or any(manifest.get(k) != reference.get(k) for k in common):
            raise ValueError("ABI builds used different source archives or policy materials")
        digest(manifest.get("archive_sha256"))
        for key, field in (("source_commit", "bearium_commit"), ("version", "firefox_version"),
                           ("revision", "firefox_revision"), ("archive_url", "archive_url"),
                           ("policy_fingerprint", "policy_fingerprint"), ("certificate_sha256", "certificate_der_sha256")):
            if source.get(key) != manifest.get(field):
                raise ValueError(f"Build manifest does not match resolved {key}")
    return {**source, "archive_sha256": reference["archive_sha256"],
            "build_materials_version": 1, "build_manifests": [p.name for p in paths]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-json", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--abi", choices=ABI_TARGETS)
    mode.add_argument("--merge-dir", type=Path)
    parser.add_argument("--onnx-root", type=Path)
    args = parser.parse_args()
    source = json.loads(args.source_json.read_text() if args.source_json else os.environ["SOURCE_JSON"])
    if args.merge_dir:
        result = merge_manifests(source, args.merge_dir)
    else:
        if not args.onnx_root:
            parser.error("--onnx-root is required with --abi")
        result = make_manifest(source, os.environ.get("FIREFOX_ARCHIVE_SHA256", source.get("archive_sha256")),
                               args.abi, args.onnx_root)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
