#!/usr/bin/env python3
"""Install the ONNX toolchain selected by Mozilla's exact release task graph.

Do not reconstruct Taskcluster cache keys from a local release checkout: its
default taskgraph parameters can differ from the official decision task.
Never fall back to nightly/latest or silently disable ONNX.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


ROOT = "https://firefox-ci-tc.services.mozilla.com/api"
TARGETS = {
    "arm-linux-androideabi": (1, 40),
    "aarch64-linux-android": (2, 183),
    "x86_64-linux-android": (2, 62),
}


def fetch_json(url: str) -> object:
    for attempt in range(4):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": "Bearium-ONNX/1"})
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except urllib.error.HTTPError as error:
            if error.code not in (429, 500, 502, 503, 504) or attempt == 3:
                raise
        except (urllib.error.URLError, TimeoutError):
            if attempt == 3:
                raise
        time.sleep(2 ** attempt)
    raise RuntimeError("Unreachable")


def task_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9_-]{22}", value):
        raise ValueError(f"Invalid Taskcluster task ID: {value!r}")
    return value


def artifact_url(task: str, name: str) -> str:
    return f"{ROOT}/queue/v1/task/{task_id(task)}/artifacts/public/{name}"


def resolve_toolchain(revision: str, target: str, fetch=fetch_json) -> tuple[str, str]:
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or target not in TARGETS:
        raise ValueError("Expected an exact Firefox revision and supported Android target")
    index = f"gecko.v2.mozilla-release.revision.{revision}.taskgraph.decision"
    decision = task_id(fetch(f"{ROOT}/index/v1/task/{index}")["taskId"])
    label = f"toolchain-onnxruntime-{target}"
    labels = fetch(artifact_url(decision, "label-to-taskid.json"))
    if label in labels:
        return decision, task_id(labels[label])

    # Release promotion may schedule the toolchain later. Use only cache indices
    # recorded in this revision's official graph, never locally recomputed ones.
    graph = fetch(artifact_url(decision, "full-task-graph.json"))
    indices = graph.get(label, {}).get("optimization", {}).get("index-search", [])
    for index in indices:
        if not isinstance(index, str) or not re.fullmatch(r"gecko\.cache\.[A-Za-z0-9_.-]+", index):
            raise ValueError(f"Unexpected official toolchain index: {index!r}")
        try:
            return decision, task_id(fetch(f"{ROOT}/index/v1/task/{index}")["taskId"])
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise
    raise RuntimeError(f"No official {label} artifact for Firefox revision {revision}; ONNX remains required")


def verify_library(path: Path, target: str) -> None:
    with path.open("rb") as stream:
        header = stream.read(20)
    elf_class, machine = TARGETS[target]
    if (len(header) != 20 or header[:4] != b"\x7fELF"
            or header[4:7] != bytes((elf_class, 1, 1))
            or struct.unpack_from("<HH", header, 16) != (3, machine)):
        raise ValueError(f"{path} is not an Android {target} ELF shared library")


def configure(mozconfig: Path, runtime: Path) -> None:
    source = mozconfig.read_text()
    source = "\n".join(line for line in source.splitlines()
                       if not re.match(r"\s*ac_add_options\s+['\"]?--(?:with|without)-onnx-runtime(?:=|\s|['\"]|$)", line))
    mozconfig.write_text(source + "\nac_add_options "
                        + shlex.quote(f"--with-onnx-runtime={runtime.resolve()}") + "\n")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--revision", required=True)
    parser.add_argument("--target", choices=TARGETS, required=True)
    parser.add_argument("--mozconfig", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    decision, task = resolve_toolchain(args.revision, args.target)
    name = f"onnxruntime-{args.target}"
    artifact = f"public/build/{name}.tar.zst"
    print(f"ONNX: revision={args.revision} target={args.target} decision={decision} task={task}", flush=True)
    args.output.mkdir(parents=True, exist_ok=True)
    # Download into an empty directory: a stale cache must not mask a missing or
    # wrong-architecture release artifact. Mach handles decompression/downloads.
    with tempfile.TemporaryDirectory(dir=args.output) as staging:
        subprocess.run([str(args.source.resolve() / "mach"), "artifact", "toolchain",
                        "--from-task", f"{task}:{artifact}"], cwd=staging, check=True)
        runtime = Path(staging) / name
        library = runtime / "libonnxruntime.so"
        verify_library(library, args.target)
        provenance = {"revision": args.revision, "target": args.target,
                      "decision_task": decision, "toolchain_task": task,
                      "artifact": artifact, "sha256": hashlib.sha256(library.read_bytes()).hexdigest()}
        destination = args.output.resolve() / args.revision / name
        destination.parent.mkdir(parents=True, exist_ok=True)
        if destination.exists():
            shutil.rmtree(destination)
        shutil.move(str(runtime), destination)
        (destination / "source.json").write_text(json.dumps(provenance, indent=2) + "\n")
    configure(args.mozconfig, destination)


if __name__ == "__main__":
    main()
