"""Tests for src/audio.py — mu-law codec, resampling, and format conversion."""

import base64

import numpy as np
import pytest

from src.audio import mulaw_decode, mulaw_encode, nova_to_twilio, resample, twilio_to_nova


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sine_int16(freq_hz: float, sample_rate: int, num_samples: int) -> np.ndarray:
    """Return a full-scale 440 Hz sine wave as int16 samples."""
    t = np.arange(num_samples) / sample_rate
    wave = np.sin(2 * np.pi * freq_hz * t)
    return (wave * 32767).astype(np.int16)


def _dominant_frequency(samples: np.ndarray, sample_rate: int) -> float:
    """Return the dominant frequency (Hz) found via FFT."""
    spectrum = np.abs(np.fft.rfft(samples.astype(np.float64)))
    freqs = np.fft.rfftfreq(len(samples), d=1.0 / sample_rate)
    return float(freqs[np.argmax(spectrum)])


# ---------------------------------------------------------------------------
# mu-law round-trip
# ---------------------------------------------------------------------------


def test_mulaw_roundtrip_zero():
    """Silence (all zeros) survives encode → decode as all zeros."""
    samples = np.zeros(160, dtype=np.int16)
    decoded = mulaw_decode(mulaw_encode(samples))
    assert np.all(decoded == 0)


def test_mulaw_roundtrip_large_values_within_tolerance():
    """Large int16 values survive a mu-law round-trip within quantization tolerance."""
    rng = np.random.default_rng(42)
    samples = rng.integers(-32768, 32767, size=160, dtype=np.int16)
    decoded = mulaw_decode(mulaw_encode(samples))
    assert decoded.shape == samples.shape
    assert decoded.dtype == np.int16
    max_error = np.max(np.abs(samples.astype(np.int32) - decoded.astype(np.int32)))
    assert max_error <= 800, f"Max quantization error {max_error} exceeds tolerance 800"


def test_mulaw_roundtrip_preserves_length():
    """Encoded then decoded byte count matches the original sample count."""
    samples = _sine_int16(440, 8000, 320)
    decoded = mulaw_decode(mulaw_encode(samples))
    assert len(decoded) == len(samples)


# ---------------------------------------------------------------------------
# resample — identity
# ---------------------------------------------------------------------------


def test_resample_identity_same_rate():
    """Resampling at equal from/to rate returns the same samples unchanged."""
    samples = _sine_int16(440, 8000, 160)
    result = resample(samples, 8000, 8000)
    np.testing.assert_array_equal(result, samples.astype(np.int16))


def test_resample_identity_preserves_dtype():
    """Identity resample always returns int16."""
    samples = np.array([1000, 2000, -1000], dtype=np.int16)
    result = resample(samples, 16000, 16000)
    assert result.dtype == np.int16


# ---------------------------------------------------------------------------
# resample — upsample length
# ---------------------------------------------------------------------------


def test_resample_upsample_8k_to_16k_yields_double_samples():
    """160 samples at 8 kHz resampled to 16 kHz should produce 320 samples."""
    samples = _sine_int16(440, 8000, 160)
    result = resample(samples, 8000, 16000)
    assert len(result) == 320


def test_resample_upsample_returns_int16():
    """Upsampled output dtype is int16."""
    samples = _sine_int16(440, 8000, 160)
    result = resample(samples, 8000, 16000)
    assert result.dtype == np.int16


# ---------------------------------------------------------------------------
# resample — downsample length
# ---------------------------------------------------------------------------


def test_resample_downsample_24k_to_8k_yields_third_samples():
    """480 samples at 24 kHz resampled to 8 kHz should produce 160 samples."""
    samples = _sine_int16(440, 24000, 480)
    result = resample(samples, 24000, 8000)
    assert len(result) == 160


def test_resample_downsample_returns_int16():
    """Downsampled output dtype is int16."""
    samples = _sine_int16(440, 24000, 480)
    result = resample(samples, 24000, 8000)
    assert result.dtype == np.int16


# ---------------------------------------------------------------------------
# twilio_to_nova output size
# ---------------------------------------------------------------------------


def test_twilio_to_nova_output_byte_count():
    """160 mu-law bytes (20 ms at 8 kHz) → decoded output is 640 bytes (320 int16 at 16 kHz)."""
    mulaw_bytes = mulaw_encode(_sine_int16(440, 8000, 160))
    assert len(mulaw_bytes) == 160
    b64_input = base64.b64encode(mulaw_bytes).decode("ascii")
    b64_output = twilio_to_nova(b64_input)
    output_bytes = base64.b64decode(b64_output)
    assert len(output_bytes) == 640, (
        f"Expected 640 bytes (320 × int16), got {len(output_bytes)}"
    )


def test_twilio_to_nova_output_sample_count():
    """Decoded output of twilio_to_nova for 160 input bytes contains 320 int16 samples."""
    mulaw_bytes = mulaw_encode(_sine_int16(440, 8000, 160))
    b64_input = base64.b64encode(mulaw_bytes).decode("ascii")
    b64_output = twilio_to_nova(b64_input)
    samples = np.frombuffer(base64.b64decode(b64_output), dtype=np.int16)
    assert len(samples) == 320


# ---------------------------------------------------------------------------
# nova_to_twilio output size
# ---------------------------------------------------------------------------


def test_nova_to_twilio_output_byte_count():
    """480 int16 samples (20 ms at 24 kHz) → decoded output is 160 mu-law bytes."""
    samples = _sine_int16(440, 24000, 480)
    pcm_bytes = samples.tobytes()
    assert len(pcm_bytes) == 960  # 480 samples × 2 bytes each
    b64_input = base64.b64encode(pcm_bytes).decode("ascii")
    b64_output = nova_to_twilio(b64_input)
    output_bytes = base64.b64decode(b64_output)
    assert len(output_bytes) == 160, (
        f"Expected 160 mu-law bytes, got {len(output_bytes)}"
    )


def test_nova_to_twilio_input_byte_length():
    """Sanity: 480 int16 samples produce 960 bytes before encoding."""
    samples = _sine_int16(440, 24000, 480)
    assert len(samples.tobytes()) == 960


# ---------------------------------------------------------------------------
# Sine wave frequency preservation through full round-trip
# ---------------------------------------------------------------------------


def test_sine_wave_dominant_frequency_preserved_through_roundtrip():
    """440 Hz sine survives mulaw encode/decode and resampling with same dominant frequency.

    Real data path: Twilio 8kHz mulaw -> twilio_to_nova (16kHz PCM) -> [Nova processes] ->
    Nova outputs 24kHz PCM -> nova_to_twilio (8kHz mulaw). We simulate the Nova step by
    resampling 16kHz->24kHz in between.
    """
    freq_hz = 440
    sample_rate = 8000
    samples = _sine_int16(freq_hz, sample_rate, 8000)

    # Step 1: encode to mu-law and convert to Nova input format (16kHz PCM)
    mulaw_bytes = mulaw_encode(samples)
    twilio_b64 = base64.b64encode(mulaw_bytes).decode("ascii")
    nova_b64 = twilio_to_nova(twilio_b64)

    # Step 2: simulate Nova outputting at 24kHz by resampling 16kHz -> 24kHz
    nova_pcm = np.frombuffer(base64.b64decode(nova_b64), dtype=np.int16)
    nova_out = resample(nova_pcm, 16000, 24000)
    nova_out_b64 = base64.b64encode(nova_out.tobytes()).decode("ascii")

    # Step 3: convert Nova output back to Twilio format (8kHz mulaw)
    twilio_b64_rt = nova_to_twilio(nova_out_b64)

    # Step 4: decode and verify dominant frequency
    rt_bytes = base64.b64decode(twilio_b64_rt)
    rt_pcm = mulaw_decode(rt_bytes)

    dominant = _dominant_frequency(rt_pcm, sample_rate)
    assert abs(dominant - freq_hz) < 20, (
        f"Expected dominant frequency ~{freq_hz} Hz, got {dominant} Hz"
    )


# ---------------------------------------------------------------------------
# Empty input handling
# ---------------------------------------------------------------------------


def test_mulaw_decode_empty_bytes_returns_empty_array():
    """mulaw_decode(b'') returns an empty int16 ndarray without error."""
    result = mulaw_decode(b"")
    assert isinstance(result, np.ndarray)
    assert result.dtype == np.int16
    assert len(result) == 0


def test_mulaw_encode_empty_array_returns_empty_bytes():
    """mulaw_encode of an empty int16 array returns b'' without error."""
    result = mulaw_encode(np.array([], dtype=np.int16))
    assert result == b""


def test_twilio_to_nova_empty_string_returns_empty_string():
    """twilio_to_nova('') returns '' without error."""
    result = twilio_to_nova("")
    assert result == ""


def test_nova_to_twilio_empty_string_returns_empty_string():
    """nova_to_twilio('') returns '' without error."""
    result = nova_to_twilio("")
    assert result == ""
