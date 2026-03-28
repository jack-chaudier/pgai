"""Audio conversion utilities for bridging Twilio and Nova Sonic audio formats."""

import base64

import numpy as np

# G.711 mu-law constants
_MULAW_BIAS = 0x84  # 132
_MULAW_CLIP = 32635

# Precomputed decode table: mu-law byte -> int16 PCM sample
_DECODE_TABLE = np.zeros(256, dtype=np.int16)

for _i in range(256):
    _val = ~_i & 0xFF
    _sign = _val & 0x80
    _exp = (_val >> 4) & 0x07
    _man = _val & 0x0F
    _sample = ((_man << 3) + _MULAW_BIAS) << _exp
    _sample -= _MULAW_BIAS
    _DECODE_TABLE[_i] = np.int16(-_sample if _sign else _sample)


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
    """Resample audio using linear interpolation. Returns int16 ndarray."""
    if len(samples) == 0:
        return np.array([], dtype=np.int16)
    if from_rate == to_rate:
        return samples.astype(np.int16)

    num_output = int(len(samples) * to_rate / from_rate)
    x_old = np.arange(len(samples))
    x_new = np.linspace(0, len(samples) - 1, num_output)
    resampled = np.interp(x_new, x_old, samples.astype(np.float64))
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
