"""
Download Piper voices to bundle with the installer (build-time only).

    python fetch_voices.py                 # all English voices (en_US, en_GB, ...) -> .\\voices
    python fetch_voices.py --match "^en_US-(amy|ryan)"   # a custom subset (regex on voice key)

Every file is checked against the MD5 listed in voices.json, and existing good files are
skipped, so the script can be re-run safely after an interruption.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

HF_BASE = os.environ.get("PIPER_VOICES_BASE",
                         "https://huggingface.co/rhasspy/piper-voices/resolve/main")
UA = {"User-Agent": "MotoTRBO-TTS-build/1.1"}


def get(url: str, timeout: float = 60) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def md5_of(path: Path) -> str:
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download(url: str, dest: Path, size: int, md5: str | None, tries: int = 5) -> None:
    if dest.exists() and dest.stat().st_size == size and (not md5 or md5_of(dest) == md5):
        print(f"  have {dest.name}")
        return
    tmp = dest.with_name(dest.name + ".part")
    for attempt in range(1, tries + 1):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=120) as r, open(tmp, "wb") as f:
                while chunk := r.read(1 << 20):
                    f.write(chunk)
            if size and tmp.stat().st_size != size:
                raise IOError(f"size {tmp.stat().st_size} != expected {size}")
            if md5 and md5_of(tmp) != md5:
                raise IOError("MD5 mismatch")
            tmp.replace(dest)
            print(f"  got  {dest.name}  ({size / 1e6:.1f} MB)")
            return
        except Exception as e:
            print(f"  retry {attempt}/{tries} for {dest.name}: {e}")
            time.sleep(min(30, 3 * attempt))
    raise SystemExit(f"FAILED to download {url}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--match", default=r"^en_", help="regex on voice key (default: all English)")
    ap.add_argument("--out", default="voices")
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    raw = get(f"{HF_BASE}/voices.json")
    catalog = json.loads(raw)
    (out / "voices.json").write_bytes(raw)  # lets the app show the voice list offline

    pat = re.compile(args.match)
    keys = sorted(k for k in catalog if pat.search(k))
    if not keys:
        raise SystemExit(f"No voices match {args.match!r}")

    total = 0
    for k in keys:
        files = catalog[k].get("files", {})
        for path, meta in files.items():
            if path.endswith(".onnx") or path.endswith(".onnx.json"):
                total += int(meta.get("size_bytes", 0))
    print(f"{len(keys)} voices, {total / 1e9:.2f} GB to bundle")

    for i, k in enumerate(keys, 1):
        print(f"[{i}/{len(keys)}] {k}")
        files = catalog[k].get("files", {})
        wanted = [(p, m) for p, m in files.items() if p.endswith((".onnx", ".onnx.json"))]
        if len(wanted) != 2:
            raise SystemExit(f"{k}: expected .onnx and .onnx.json in catalog, found {list(files)}")
        # .json first so a half-finished voice is never treated as installed
        for path, meta in sorted(wanted, key=lambda pm: not pm[0].endswith(".json")):
            name = Path(path).name
            download(f"{HF_BASE}/{path}?download=true", out / name,
                     int(meta.get("size_bytes", 0)), meta.get("md5_digest"))

    stray = [p for p in out.glob("*.part")]
    for p in stray:
        p.unlink()
    print(f"Done: {len(keys)} voices in {out.resolve()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
