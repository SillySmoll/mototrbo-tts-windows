"""
Core engine for MotoTRBO TTS (Windows edition).

Replaces the original bash + ffmpeg pipeline from clifjones/mototrbo_tts:
  Piper TTS  ->  loudness normalize (I=-16 LUFS, TP=-4 dBTP)  ->  8 kHz  ->  G.711 mu-law WAV

No ffmpeg, Docker or WSL is needed; everything is done in Python/numpy/scipy.
"""

from __future__ import annotations

import io
import json
import os
import re
import struct
import sys
import threading
import urllib.request
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

import numpy as np
from scipy import signal
from scipy.ndimage import minimum_filter1d

APP_NAME = "MotoTRBO TTS"
DEFAULT_VOICE = "en_US-kathleen-low"
HF_BASE = "https://huggingface.co/rhasspy/piper-voices/resolve/main"
VOICES_JSON_URL = f"{HF_BASE}/voices.json"

TARGET_RATE = 8000
TARGET_LUFS = -16.0
TARGET_TRUE_PEAK_DB = -4.0
MAX_FILE_BYTES = 320 * 1024  # CPS limit noted in the original project

DEFAULT_CPS_DIR = r"C:\Program Files (x86)\Motorola\MOTOTRBO CPS\voiceannouncement"

INVALID_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
                  *(f"LPT{i}" for i in range(1, 10))}


# --------------------------------------------------------------------------
# Paths / settings
# --------------------------------------------------------------------------

def app_data_dir() -> Path:
    base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
    if base:
        p = Path(base) / APP_NAME
    else:
        p = Path.home() / ".mototrbo_tts"
    p.mkdir(parents=True, exist_ok=True)
    return p


def voices_dir() -> Path:
    p = app_data_dir() / "voices"
    p.mkdir(parents=True, exist_ok=True)
    return p


def default_output_dir() -> Path:
    docs = Path.home() / "Documents"
    return (docs if docs.exists() else Path.home()) / "MotoTRBO Voice Announcements"


def load_settings() -> dict:
    f = app_data_dir() / "settings.json"
    try:
        return json.loads(f.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_settings(data: dict) -> None:
    f = app_data_dir() / "settings.json"
    try:
        f.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


# --------------------------------------------------------------------------
# phrases.lst  (filename=phrase, '#' comments) - same format as the original
# --------------------------------------------------------------------------

@dataclass
class Phrase:
    filename: str
    text: str


def parse_phrases(content: str) -> list[Phrase]:
    out: list[Phrase] = []
    for raw in content.splitlines():
        line = raw.strip("\r\n")
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if "=" not in line:
            continue
        name, text = line.split("=", 1)
        name = name.strip()
        if name.lower().endswith(".wav"):
            name = name[:-4]
        if name:
            out.append(Phrase(name, text.strip()))
    return out


def format_phrases(phrases: Iterable[Phrase]) -> str:
    lines = ["# MotoTRBO TTS phrase list: filename=phrase (one per line)"]
    lines += [f"{p.filename}={p.text}" for p in phrases]
    return "\n".join(lines) + "\n"


def validate_filename(name: str) -> str | None:
    """Return an error message, or None if the name is OK for Windows."""
    if not name.strip():
        return "File name is empty."
    if INVALID_NAME_CHARS.search(name):
        return 'File name can\'t contain any of  < > : " / \\ | ? *'
    if name.endswith((" ", ".")):
        return "File name can't end with a space or a period."
    if name.split(".")[0].upper() in RESERVED_NAMES:
        return f"'{name}' is a reserved name on Windows."
    return None


SAMPLE_PHRASES = [
    Phrase("z1", "Zone 1"),
    Phrase("z1-loc", "Local"),
    Phrase("z1-echo", "Echo test"),
    Phrase("z1-mon-t1", "Monitor timeslot 1"),
    Phrase("z1-mon-t2", "Monitor timeslot 2"),
]


# --------------------------------------------------------------------------
# Voice catalog + download (Hugging Face rhasspy/piper-voices)
# --------------------------------------------------------------------------

@dataclass
class VoiceInfo:
    key: str              # e.g. en_US-kathleen-low
    language: str         # e.g. "English (United States)"
    name: str             # e.g. kathleen
    quality: str          # x_low / low / medium / high
    onnx_path: str        # path inside the HF repo
    size_bytes: int = 0
    num_speakers: int = 1

    @property
    def label(self) -> str:
        mb = f"  ({self.size_bytes / 1e6:.0f} MB)" if self.size_bytes else ""
        spk = f", {self.num_speakers} speakers" if self.num_speakers > 1 else ""
        return f"{self.name} - {self.quality}{spk}{mb}"


def _http_get(url: str, timeout: float = 30) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "MotoTRBO-TTS/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def _guess_onnx_path(key: str) -> str:
    # en_US-kathleen-low -> en/en_US/kathleen/low/en_US-kathleen-low.onnx
    lang, rest = key.split("-", 1)
    name, quality = rest.rsplit("-", 1)
    family = lang.split("_")[0]
    return f"{family}/{lang}/{name}/{quality}/{key}.onnx"


def _parse_catalog(data: dict) -> list[VoiceInfo]:
    voices = []
    for key, v in data.items():
        lang = v.get("language", {})
        language = lang.get("name_english", lang.get("code", "?"))
        country = lang.get("country_english")
        if country:
            language = f"{language} ({country})"
        onnx_path, size = None, 0
        for path, meta in (v.get("files") or {}).items():
            if path.endswith(".onnx"):
                onnx_path, size = path, int(meta.get("size_bytes", 0))
        voices.append(VoiceInfo(
            key=key, language=language, name=v.get("name", key),
            quality=v.get("quality", ""), onnx_path=onnx_path or _guess_onnx_path(key),
            size_bytes=size, num_speakers=int(v.get("num_speakers", 1) or 1)))
    order = {"x_low": 0, "low": 1, "medium": 2, "high": 3}
    voices.sort(key=lambda x: (x.language, x.name, order.get(x.quality, 9)))
    return voices


def load_voice_catalog(refresh: bool = False) -> list[VoiceInfo]:
    """Voice list from Hugging Face, cached locally so the app works offline."""
    cache = app_data_dir() / "voices.json"
    if refresh or not cache.exists():
        try:
            raw = _http_get(VOICES_JSON_URL)
            json.loads(raw)  # validate before caching
            cache.write_bytes(raw)
        except Exception:
            if not cache.exists():
                raise
    return _parse_catalog(json.loads(cache.read_text(encoding="utf-8")))


def local_model_path(key: str) -> Path:
    return voices_dir() / f"{key}.onnx"


def is_voice_installed(key: str) -> bool:
    p = local_model_path(key)
    return p.exists() and Path(str(p) + ".json").exists()


def installed_voices() -> list[str]:
    return sorted(p.stem for p in voices_dir().glob("*.onnx")
                  if Path(str(p) + ".json").exists())


def download_voice(voice: VoiceInfo | str,
                   progress: Callable[[str, float], None] | None = None) -> Path:
    """Download <key>.onnx and <key>.onnx.json into the voices folder."""
    if isinstance(voice, str):
        voice = VoiceInfo(voice, "", voice, "", _guess_onnx_path(voice))
    dest = local_model_path(voice.key)
    for suffix in (".onnx.json", ".onnx"):
        target = Path(str(dest)[: -len(".onnx")] + suffix)
        if target.exists() and target.stat().st_size > 0:
            continue
        url = f"{HF_BASE}/{voice.onnx_path[: -len('.onnx')]}{suffix}?download=true"
        tmp = target.with_suffix(target.suffix + ".part")
        req = urllib.request.Request(url, headers={"User-Agent": "MotoTRBO-TTS/1.0"})
        with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
            total = int(r.headers.get("Content-Length") or 0)
            done = 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress and total:
                    progress(f"Downloading {target.name}", done / total)
        tmp.replace(target)
    return dest


# --------------------------------------------------------------------------
# Piper synthesis
# --------------------------------------------------------------------------

_voice_cache: dict[str, object] = {}
_voice_lock = threading.Lock()


def _load_piper(model_path: Path):
    key = str(model_path)
    with _voice_lock:
        if key not in _voice_cache:
            from piper import PiperVoice  # imported lazily: heavy (onnxruntime)
            _voice_cache.clear()          # keep one voice in memory
            _voice_cache[key] = PiperVoice.load(key)
        return _voice_cache[key]


def synthesize(text: str, model_path: Path, speed: float = 1.0,
               speaker_id: int | None = None) -> tuple[np.ndarray, int]:
    """Return (float32 mono audio in [-1, 1], sample_rate)."""
    voice = _load_piper(model_path)
    syn_config = None
    if speed != 1.0 or speaker_id is not None:
        from piper import SynthesisConfig
        syn_config = SynthesisConfig(speaker_id=speaker_id,
                                     length_scale=1.0 / max(speed, 0.1))
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        if syn_config is not None:
            voice.synthesize_wav(text, wf, syn_config=syn_config)
        else:
            voice.synthesize_wav(text, wf)
    buf.seek(0)
    return read_wav(buf)


def read_wav(src) -> tuple[np.ndarray, int]:
    with wave.open(src, "rb") as wf:
        sr, ch, sw = wf.getframerate(), wf.getnchannels(), wf.getsampwidth()
        raw = wf.readframes(wf.getnframes())
    if sw != 2:
        raise ValueError("Expected 16-bit PCM from Piper")
    x = np.frombuffer(raw, dtype="<i2").astype(np.float32) / 32768.0
    if ch > 1:
        x = x.reshape(-1, ch).mean(axis=1)
    return x, sr


# --------------------------------------------------------------------------
# Loudness (ITU-R BS.1770 / EBU R128) + true-peak limiter
# --------------------------------------------------------------------------

def _biquad_shelf(fs: float):
    G, Q, fc = 4.0, 1 / np.sqrt(2), 1500.0
    A = 10 ** (G / 40)
    w0 = 2 * np.pi * fc / fs
    alpha = np.sin(w0) / (2 * Q)
    cw, sA = np.cos(w0), np.sqrt(A)
    b = [A * ((A + 1) + (A - 1) * cw + 2 * sA * alpha),
         -2 * A * ((A - 1) + (A + 1) * cw),
         A * ((A + 1) + (A - 1) * cw - 2 * sA * alpha)]
    a = [(A + 1) - (A - 1) * cw + 2 * sA * alpha,
         2 * ((A - 1) - (A + 1) * cw),
         (A + 1) - (A - 1) * cw - 2 * sA * alpha]
    return np.array(b) / a[0], np.array(a) / a[0]


def _biquad_highpass(fs: float):
    Q, fc = 0.5, 38.0
    w0 = 2 * np.pi * fc / fs
    alpha = np.sin(w0) / (2 * Q)
    cw = np.cos(w0)
    b = [(1 + cw) / 2, -(1 + cw), (1 + cw) / 2]
    a = [1 + alpha, -2 * cw, 1 - alpha]
    return np.array(b) / a[0], np.array(a) / a[0]


def integrated_loudness(x: np.ndarray, fs: int) -> float:
    """Integrated loudness in LUFS (mono)."""
    b1, a1 = _biquad_shelf(fs)
    b2, a2 = _biquad_highpass(fs)
    y = signal.lfilter(b2, a2, signal.lfilter(b1, a1, x.astype(np.float64)))
    block, step = int(0.4 * fs), int(0.1 * fs)
    if len(y) < block:  # shorter than one gating block: plain mean square
        z = np.array([np.mean(y ** 2)])
    else:
        n = 1 + (len(y) - block) // step
        z = np.array([np.mean(y[i * step: i * step + block] ** 2) for i in range(n)])
    lk = -0.691 + 10 * np.log10(np.maximum(z, 1e-12))
    z = z[lk > -70.0]
    if len(z) == 0:
        return -70.0
    rel = -0.691 + 10 * np.log10(np.mean(z)) - 10.0
    z2 = z[(-0.691 + 10 * np.log10(z)) > rel]
    if len(z2) == 0:
        z2 = z
    return float(-0.691 + 10 * np.log10(np.mean(z2)))


def true_peak_envelope(x: np.ndarray, oversample: int = 4) -> np.ndarray:
    up = signal.resample_poly(x, oversample, 1)[: len(x) * oversample]
    return np.abs(up).reshape(len(x), oversample).max(axis=1)


def limit_true_peak(x: np.ndarray, fs: int, ceiling_db: float) -> np.ndarray:
    thr = 10 ** (ceiling_db / 20)
    env = true_peak_envelope(x)
    need = np.minimum(1.0, thr / np.maximum(env, 1e-9))
    if need.min() >= 1.0:
        return x
    half = max(1, int(0.005 * fs))               # 5 ms lookahead/attack
    g = minimum_filter1d(need, size=2 * half + 1, mode="nearest")
    win = np.hanning(half + 1)
    win /= win.sum()
    g = np.convolve(g, win, mode="same")         # smooth, never above `need`
    return x * np.minimum(g, need)


def normalize(x: np.ndarray, fs: int,
              lufs: float = TARGET_LUFS, tp_db: float = TARGET_TRUE_PEAK_DB) -> np.ndarray:
    if len(x) == 0 or np.max(np.abs(x)) < 1e-6:
        return x
    gain_db = lufs - integrated_loudness(x, fs)
    y = x * (10 ** (gain_db / 20))
    return limit_true_peak(y, fs, tp_db)


# --------------------------------------------------------------------------
# 8 kHz + G.711 mu-law WAV (same layout ffmpeg writes: fmt(18) + fact + data)
# --------------------------------------------------------------------------

def resample(x: np.ndarray, fs: int, target: int = TARGET_RATE) -> np.ndarray:
    if fs == target:
        return x
    g = np.gcd(int(fs), int(target))
    return signal.resample_poly(x, target // g, fs // g)


def _ulaw2linear(u: int) -> int:
    u = ~u & 0xFF
    t = (((u & 0x0F) << 3) + 0x84) << ((u & 0x70) >> 4)
    return (0x84 - t) if (u & 0x80) else (t - 0x84)


def _build_ulaw_table() -> np.ndarray:
    # Port of ffmpeg libavcodec/pcm_tablegen.h build_xlaw_table(), mask=0xff,
    # so output bytes are identical to `ffmpeg -acodec pcm_mulaw`.
    mask = 0xFF
    t = np.zeros(16384, dtype=np.uint8)
    t[8192] = mask
    j = 1
    for i in range(127):
        v = (_ulaw2linear(i ^ mask) + _ulaw2linear((i + 1) ^ mask) + 4) >> 3
        while j < v:
            t[8192 - j] = i ^ (mask ^ 0x80)
            t[8192 + j] = i ^ mask
            j += 1
    while j < 8192:
        t[8192 - j] = 127 ^ (mask ^ 0x80)
        t[8192 + j] = 127 ^ mask
        j += 1
    t[0] = t[1]
    return t


_ULAW_TABLE = _build_ulaw_table()


def mulaw_encode(pcm16: np.ndarray) -> bytes:
    """G.711 mu-law, bit-identical to ffmpeg's pcm_mulaw encoder."""
    idx = (pcm16.astype(np.int32) + 32768) >> 2
    return _ULAW_TABLE[idx].tobytes()


def mulaw_decode(data: bytes) -> np.ndarray:
    u = ~np.frombuffer(data, dtype=np.uint8).astype(np.int32) & 0xFF
    sign, exponent, mantissa = u & 0x80, (u >> 4) & 0x07, u & 0x0F
    mag = (((mantissa << 3) + 0x84) << exponent) - 0x84
    return np.where(sign != 0, -mag, mag).astype(np.int16)


def to_pcm16(x: np.ndarray) -> np.ndarray:
    return np.clip(np.round(x * 32767.0), -32768, 32767).astype(np.int16)


def mulaw_wav_bytes(x8k: np.ndarray) -> bytes:
    data = mulaw_encode(to_pcm16(x8k))
    n = len(data)
    fmt = struct.pack("<HHIIHHH", 7, 1, TARGET_RATE, TARGET_RATE, 1, 8, 0)
    chunks = (b"fmt " + struct.pack("<I", len(fmt)) + fmt
              + b"fact" + struct.pack("<II", 4, n)
              + b"data" + struct.pack("<I", n) + data + (b"\x00" if n & 1 else b""))
    return b"RIFF" + struct.pack("<I", 4 + len(chunks)) + b"WAVE" + chunks


def pcm_wav_bytes(x: np.ndarray, fs: int) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(fs)
        wf.writeframes(to_pcm16(x).tobytes())
    return buf.getvalue()


def inspect_wav(path: Path) -> dict:
    d = Path(path).read_bytes()
    info = {"size": len(d)}
    i = 12
    while i + 8 <= len(d):
        cid, sz = d[i:i + 4], struct.unpack("<I", d[i + 4:i + 8])[0]
        if cid == b"fmt ":
            tag, ch, sr, _, _, bits = struct.unpack("<HHIIHH", d[i + 8:i + 24])
            info.update(format_tag=tag, channels=ch, rate=sr, bits=bits)
        elif cid == b"data":
            info["frames"] = sz
        i += 8 + sz + (sz & 1)
    return info


def process_audio(x: np.ndarray, fs: int) -> np.ndarray:
    """Normalize at source rate, resample to 8 kHz (the ffmpeg filter order)."""
    y = resample(normalize(x, fs), fs)
    peak = np.max(np.abs(y)) if len(y) else 0
    if peak > 0.999:
        y = y * (0.999 / peak)
    return y


def render_phrase(text: str, model_path: Path, speed: float = 1.0,
                  speaker_id: int | None = None) -> np.ndarray:
    x, fs = synthesize(text, model_path, speed, speaker_id)
    return process_audio(x, fs)


def generate_all(phrases: list[Phrase], model_path: Path, out_dir: Path,
                 speed: float = 1.0, speaker_id: int | None = None,
                 log: Callable[[str], None] = print,
                 progress: Callable[[int, int], None] | None = None,
                 cancel: threading.Event | None = None) -> list[Path]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    written = []
    for i, p in enumerate(phrases, 1):
        if cancel and cancel.is_set():
            log("Cancelled.")
            break
        err = validate_filename(p.filename)
        if err:
            log(f"SKIPPED {p.filename!r}: {err}")
            continue
        if not p.text.strip():
            log(f"SKIPPED {p.filename}: phrase is empty")
            continue
        log(f"Processing: {p.filename} = {p.text}")
        y = render_phrase(p.text, model_path, speed, speaker_id)
        data = mulaw_wav_bytes(y)
        dest = out_dir / f"{p.filename}.wav"
        dest.write_bytes(data)
        written.append(dest)
        size_note = ""
        if len(data) > MAX_FILE_BYTES:
            size_note = f"  WARNING: exceeds 320 kB ({len(data):,} bytes)"
        log(f"Created: {dest.name}  ({len(y) / TARGET_RATE:.1f} s, {len(data) / 1024:.1f} kB){size_note}")
        if progress:
            progress(i, len(phrases))
    return written


def resource_path(rel: str) -> Path:
    base = getattr(sys, "_MEIPASS", Path(__file__).resolve().parent)
    return Path(base) / rel
