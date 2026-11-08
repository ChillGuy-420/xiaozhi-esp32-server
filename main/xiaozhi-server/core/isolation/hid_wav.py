"""PCM and IMA-ADPCM WAV for the HID capture. This is not the Xiaozhi Opus stream."""

from __future__ import annotations

import struct
import wave
from io import BytesIO

import numpy as np

_STEP = (
    7, 8, 9, 10, 11, 12, 13, 14, 16, 17, 19, 21, 23, 25, 28, 31, 34, 37, 41, 45,
    50, 55, 60, 66, 73, 80, 88, 97, 107, 118, 130, 143, 157, 173, 190, 209, 230,
    253, 279, 307, 337, 371, 408, 449, 494, 544, 598, 658, 724, 796, 876, 963,
    1060, 1166, 1282, 1411, 1552, 1707, 1878, 2066, 2272, 2499, 2749, 3024, 3327,
    3660, 4026, 4428, 4871, 5358, 5894, 6484, 7132, 7845, 8630, 9493, 10442, 11487,
    12635, 13899, 15289, 16818, 18500, 20350, 22385, 24623, 27086, 29794, 32767,
)
_INDEX = (-1, -1, -1, -1, 2, 4, 6, 8, -1, -1, -1, -1, 2, 4, 6, 8)


class HidWavError(ValueError):
    pass


def _chunks(blob: bytes) -> dict[str, bytes]:
    if len(blob) < 12 or blob[:4] != b"RIFF" or blob[8:12] != b"WAVE":
        raise HidWavError("not a wav")
    found: dict[str, bytes] = {}
    offset = 12
    while offset + 8 <= len(blob):
        name = blob[offset : offset + 4].decode("ascii", errors="replace")
        size = struct.unpack_from("<I", blob, offset + 4)[0]
        start = offset + 8
        found[name] = blob[start : start + size]
        offset = start + size + (size & 1)
    return found


def _decode_nibble(nibble: int, predictor: int, index: int) -> tuple[int, int]:
    step = _STEP[index]
    delta = step >> 3
    if nibble & 1:
        delta += step >> 2
    if nibble & 2:
        delta += step >> 1
    if nibble & 4:
        delta += step
    predictor += -delta if nibble & 8 else delta
    predictor = max(-32768, min(32767, predictor))
    index = max(0, min(88, index + _INDEX[nibble & 7]))
    return predictor, index


def _decode_ima_block(block: bytes, samples_per_block: int) -> list[int]:
    if len(block) < 4:
        raise HidWavError("short ima block")
    predictor = struct.unpack_from("<h", block, 0)[0]
    index = block[2]
    if index > 88:
        raise HidWavError("ima step index")
    samples = [predictor]
    for byte in block[4:]:
        for nibble in (byte & 0x0F, byte >> 4):
            predictor, index = _decode_nibble(nibble, predictor, index)
            samples.append(predictor)
            if len(samples) >= samples_per_block:
                return samples
    return samples


def decode_hid_wav(blob: bytes) -> tuple[np.ndarray, int]:
    """Return mono int16 samples and their sample rate."""
    chunks = _chunks(blob)
    fmt = chunks.get("fmt ")
    data = chunks.get("data")
    if not fmt or data is None or len(fmt) < 16:
        raise HidWavError("wav is missing fmt or data")
    audio_format, channels, rate, _byte_rate, block_align, bits = struct.unpack_from("<HHIIHH", fmt)
    if channels != 1 or rate < 8000 or rate > 48000:
        raise HidWavError("wav must be mono 8-48 kHz")
    if audio_format == 1:
        if bits != 16:
            raise HidWavError("pcm wav must be 16-bit")
        usable = len(data) - (len(data) % 2)
        return np.frombuffer(data[:usable], dtype="<i2").copy(), rate
    if audio_format != 0x0011:
        raise HidWavError("wav codec is not pcm or ima")
    samples_per_block = 505
    if len(fmt) >= 20:
        samples_per_block = struct.unpack_from("<H", fmt, 18)[0] or samples_per_block
    if block_align < 4:
        raise HidWavError("ima block align")
    decoded: list[int] = []
    for start in range(0, len(data) - block_align + 1, block_align):
        decoded.extend(_decode_ima_block(data[start : start + block_align], samples_per_block))
    fact = chunks.get("fact")
    if fact and len(fact) >= 4:
        count = struct.unpack_from("<I", fact)[0]
        decoded = decoded[:count]
    if not decoded:
        raise HidWavError("ima wav has no samples")
    return np.asarray(decoded, dtype=np.int16), rate


def encode_ima_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    """Microsoft IMA WAV: 256-byte blocks, 505 samples, low nibble first."""
    pcm = np.asarray(samples, dtype=np.int16)
    if pcm.size == 0:
        raise HidWavError("empty pcm")
    block_align = 256
    per_block = 505
    blocks = []
    offset = 0
    while offset < pcm.size:
        chunk = pcm[offset : offset + per_block]
        offset += per_block
        if chunk.size < per_block:
            chunk = np.pad(chunk, (0, per_block - chunk.size), mode="edge")
        predictor = int(chunk[0])
        index = 0
        nibbles = []
        for sample in chunk[1:]:
            step = _STEP[index]
            diff = int(sample) - predictor
            nibble = 0
            if diff < 0:
                nibble = 8
                diff = -diff
            if diff >= step:
                nibble |= 4
                diff -= step
            if diff >= step >> 1:
                nibble |= 2
                diff -= step >> 1
            if diff >= step >> 2:
                nibble |= 1
            predictor, index = _decode_nibble(nibble, predictor, index)
            nibbles.append(nibble)
        raw = bytearray(block_align)
        struct.pack_into("<h", raw, 0, int(chunk[0]))
        raw[2] = 0
        for i in range(0, len(nibbles), 2):
            raw[4 + i // 2] = nibbles[i] | (nibbles[i + 1] << 4)
        blocks.append(bytes(raw))
    data = b"".join(blocks)
    fmt = struct.pack("<HHIIHHH", 0x0011, 1, sample_rate, sample_rate * block_align // per_block, block_align, 4, 2)
    fmt += struct.pack("<H", per_block)
    fact = struct.pack("<I", int(pcm.size))

    def chunk(name: bytes, payload: bytes) -> bytes:
        return name + struct.pack("<I", len(payload)) + payload + (b"\x00" if len(payload) & 1 else b"")

    body = chunk(b"fmt ", fmt) + chunk(b"fact", fact) + chunk(b"data", data)
    return b"RIFF" + struct.pack("<I", 4 + len(body)) + b"WAVE" + body


def pcm16_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    buffer = BytesIO()
    with wave.open(buffer, "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(sample_rate)
        handle.writeframes(np.asarray(samples, dtype="<i2").tobytes())
    return buffer.getvalue()


def resample_int16(samples: np.ndarray, source_rate: int, target_rate: int = 16000) -> np.ndarray:
    samples = np.asarray(samples, dtype=np.int16)
    if source_rate == target_rate:
        return samples
    count = max(1, int(round(samples.size * target_rate / source_rate)))
    stretched = np.interp(
        np.linspace(0, samples.size - 1, count),
        np.arange(samples.size),
        samples.astype(np.float32),
    )
    return np.clip(np.rint(stretched), -32768, 32767).astype(np.int16)
