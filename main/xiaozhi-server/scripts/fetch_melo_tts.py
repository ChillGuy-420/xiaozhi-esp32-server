#!/usr/bin/env python3
"""Download MeloTTS from the pinned Hugging Face revision and check file hashes.

Does not use the GitHub release tarball. model.int8.onnx is omitted: the
verified archive only contains its Git LFS pointer, and this server loads
model.onnx.
"""

from __future__ import annotations

import hashlib
import sys
import urllib.request
from pathlib import Path

REVISION = "a0d5c6a264c0ef92d70d8661d8cc502d79627cd6"
REPO = "csukuangfj/vits-melo-tts-zh_en"
BASE = f"https://huggingface.co/{REPO}/resolve/{REVISION}/"
MANIFEST = Path(__file__).with_name("melo-tts-files.sha256")


def _entries() -> list[tuple[str, int, str]]:
    rows = []
    for line in MANIFEST.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        digest, size, name, _flag = line.split(maxsplit=3)
        rows.append((digest, int(size), name))
    return rows


def main() -> None:
    dest = Path(sys.argv[1] if len(sys.argv) > 1 else "vits-melo-tts-zh_en")
    dest.mkdir(parents=True, exist_ok=True)
    for digest, size, name in _entries():
        target = dest / name
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.is_file() and target.stat().st_size == size:
            got = hashlib.sha256(target.read_bytes()).hexdigest()
            if got == digest:
                print(f"keep {name}")
                continue
        url = BASE + name
        print(f"get {name}")
        urllib.request.urlretrieve(url, target)
        got = hashlib.sha256(target.read_bytes()).hexdigest()
        if got != digest or target.stat().st_size != size:
            raise SystemExit(f"{name} hash or size mismatch")
        print(f"ok {name}")


if __name__ == "__main__":
    main()
