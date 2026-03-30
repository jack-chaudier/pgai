"""Audio conversion utilities for bridging Twilio and Nova Sonic audio formats."""

import base64
from math import gcd

import numpy as np
from scipy.signal import resample_poly

# G.711 mu-law constants
_MULAW_BIAS = 0x84  # 132
_MULAW_CLIP = 32635

# Precomputed decode table: mu-law byte -> int16 PCM sample
def _build_decode_table() -> np.ndarray:
    table = np.zeros(256, dtype=np.int16)
    for i in range(256):
        val = ~i & 0xFF
        sign = val & 0x80
        exp = (val >> 4) & 0x07
        man = val & 0x0F
        sample = ((man << 3) + _MULAW_BIAS) << exp
        sample -= _MULAW_BIAS
        table[i] = np.int16(-sample if sign else sample)
    return table

_DECODE_TABLE = _build_decode_table()


def mulaw_decode(mulaw_bytes: bytes) -> np.ndarray:
    """Decode mu-law bytes to int16 PCM samples."""
    if not mulaw_bytes:
        return np.array([], dtype=np.int16)
    return _DECODE_TABLE[np.frombuffer(mulaw_bytes, dtype=np.uint8)].copy()


def mulaw_encode(pcm_samples: np.ndarray) -> bytes:
    """Encode int16 PCM samples to mu-law bytes."""
    if len(pcm_samples) == 0:
        return b""

    samples = pcm_samples.astype(np.int32)
    sign = np.where(samples < 0, np.int32(0x80), np.int32(0x00))
    mag = np.clip(np.abs(samples), 0, _MULAW_CLIP) + _MULAW_BIAS

    # Find exponent by checking highest set bit via successive thresholds.
    # Exponent = position of highest set bit minus 7.
    exp = np.zeros(len(mag), dtype=np.int32)
    for e in range(7, 0, -1):
        exp = np.where(mag & (1 << (e + 7)), np.maximum(exp, e), exp)

    mantissa = (mag >> (exp + 3)) & 0x0F
    result = (~(sign | (exp << 4) | mantissa)) & 0xFF
    return result.astype(np.uint8).tobytes()


def resample(samples: np.ndarray, from_rate: int, to_rate: int) -> np.ndarray:
    """Resample audio with proper anti-alias filtering. Returns int16 ndarray."""
    if len(samples) == 0:
        return np.array([], dtype=np.int16)
    if from_rate == to_rate:
        return samples.astype(np.int16)

    # resample_poly handles anti-aliasing internally
    g = gcd(from_rate, to_rate)
    up, down = to_rate // g, from_rate // g
    resampled = resample_poly(samples.astype(np.float64), up, down)
    return np.clip(resampled, -32768, 32767).astype(np.int16)


def twilio_to_nova(mulaw_b64: str) -> str:
    """Convert base64 mulaw 8kHz to base64 PCM16 16kHz."""
    if not mulaw_b64:
        return ""
    mulaw_bytes = base64.b64decode(mulaw_b64)
    pcm_samples = mulaw_decode(mulaw_bytes)
    resampled = resample(pcm_samples, 8000, 16000)
    return base64.b64encode(resampled.tobytes()).decode("ascii")


def nova_to_twilio(pcm_b64: str) -> str:
    """Convert base64 PCM16 24kHz to base64 mulaw 8kHz."""
    if not pcm_b64:
        return ""
    pcm_bytes = base64.b64decode(pcm_b64)
    samples = np.frombuffer(pcm_bytes, dtype=np.int16)
    resampled = resample(samples, 24000, 8000)
    mulaw_bytes = mulaw_encode(resampled)
    return base64.b64encode(mulaw_bytes).decode("ascii")
