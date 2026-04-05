"""
Voice Engine — Local TTS/STT for Soul Personalities

Text-to-Speech: Kokoro TTS (82M params, ~200MB, runs on MPS)
Speech-to-Text: pywhispercpp (whisper.cpp bindings, ~150MB base model)

Both run 100% locally on Apple Silicon. No cloud. No API keys.

Big Five → Voice Mapping:
- Openness: pitch variation (monotone → expressive)
- Conscientiousness: speaking rate (fast+precise → slow+deliberate)
- Extraversion: volume/energy (quiet → loud)
- Agreeableness: warmth (cold/sharp → warm/soft)
- Neuroticism: stability (steady → trembling/rushed)
"""

import os
import io
import wave
import logging
import tempfile
from typing import Optional

logger = logging.getLogger("voice_engine")

# Lazy-load singletons
_tts_pipeline = None
_stt_model = None

# Voice preset mapping based on Big Five traits
VOICE_PRESETS = {
    "warm_f":      {"voice": "af_heart",   "speed": 1.0},   # High agreeableness
    "warm_m":      {"voice": "am_michael", "speed": 1.0},
    "assertive_f": {"voice": "af_star",    "speed": 1.1},   # High extraversion
    "assertive_m": {"voice": "am_fenrir",  "speed": 1.1},
    "calm_f":      {"voice": "af_sky",     "speed": 0.9},   # High conscientiousness
    "calm_m":      {"voice": "am_adam",    "speed": 0.9},
    "expressive_f":{"voice": "af_bella",   "speed": 1.05},  # High openness
    "expressive_m":{"voice": "am_echo",    "speed": 1.05},
    "nervous_f":   {"voice": "af_nicole",  "speed": 1.15},  # High neuroticism
    "nervous_m":   {"voice": "am_eric",    "speed": 1.15},
    "default_f":   {"voice": "af_bella",   "speed": 1.0},
    "default_m":   {"voice": "am_adam",    "speed": 1.0},
}


def _get_tts():
    """Lazy-load Kokoro TTS pipeline."""
    global _tts_pipeline
    if _tts_pipeline is None:
        try:
            from kokoro import KPipeline
            _tts_pipeline = KPipeline(lang_code="a")  # 'a' = American English
            logger.info("[VOICE] Kokoro TTS loaded (82M params)")
        except ImportError:
            logger.warning("[VOICE] kokoro not installed. Run: pip install kokoro soundfile")
            return None
    return _tts_pipeline


def _get_stt():
    """Lazy-load Whisper STT model."""
    global _stt_model
    if _stt_model is None:
        try:
            from pywhispercpp.model import Model
            _stt_model = Model("base", print_progress=False)
            logger.info("[VOICE] Whisper STT loaded (base model, ~150MB)")
        except ImportError:
            logger.warning("[VOICE] pywhispercpp not installed. Run: pip install pywhispercpp")
            return None
    return _stt_model


# Broader list of stable Kokoro voices by gender
KOKORO_MALE = ["am_adam", "am_michael", "am_puck", "am_onyx", "am_echo"]
KOKORO_FEMALE = ["af_heart", "af_sky", "af_bella", "af_sarah", "af_alloy"]

def soul_to_voice_preset(traits: dict) -> dict:
    """
    Map Big Five personality scores to a deterministic, unique voice preset.
    """
    o = traits.get("openness", 50)
    c = traits.get("conscientiousness", 50)
    e = traits.get("extraversion", 50)
    a = traits.get("agreeableness", 50)
    n = traits.get("neuroticism", 50)

    # Use trait scores to deterministically assign gender variation
    trait_sum = int(o + c + e + a + n)
    is_male = trait_sum % 2 == 0
    
    # Deterministically select a base voice based on their unique trait breakdown
    # This guarantees massive diversity instead of clustering 4444 souls into just 10 trait buckets
    voice_list = KOKORO_MALE if is_male else KOKORO_FEMALE
    # Use sum of squared traits to avoid linear collision
    seed = int(o**2 + c**2 + e**2 + a**2 + n**2)
    base_voice = voice_list[seed % len(voice_list)]

    preset = {"voice": base_voice, "speed": 1.0}

    # Fine-tune speed and add broader parameter variation based on specific traits
    # Extraversion increases speed, Conscientiousness decreases it
    speed_mod = (e - 50) * 0.005 + (50 - c) * 0.004
    # Neuroticism makes speech slightly faster/rushed
    speed_mod += (n - 50) * 0.002
    
    preset["speed"] = round(preset["speed"] + speed_mod, 2)
    # Clamp speed to a safe intelligible range for Kokoro (too fast = artifacts/laughing)
    preset["speed"] = max(0.85, min(1.20, preset["speed"]))

    preset["dominant_trait"] = "unique_hash"
    return preset


def text_to_speech(text: str, output_path: str, voice: str = "af_heart",
                   speed: float = 1.0) -> dict:
    """
    Convert text to speech using Kokoro TTS.

    Args:
        text: Text to speak
        output_path: Where to save the WAV file
        voice: Kokoro voice preset name
        speed: Speaking speed multiplier (0.7-1.4)

    Returns:
        {"status": str, "path": str, "duration_ms": int}
    """
    pipeline = _get_tts()
    if pipeline is None:
        return {"status": "error", "message": "Kokoro TTS not installed"}

    # Validate output path stays within user directory
    resolved_out = os.path.realpath(output_path)
    if not resolved_out.startswith(os.path.expanduser("~")):
        return {"status": "error", "message": "Security Error: output_path must be under user directory."}

    # Cap text length to prevent OOM (~5 minutes of speech max)
    MAX_TTS_TEXT = 5000
    if len(text) > MAX_TTS_TEXT:
        text = text[:MAX_TTS_TEXT]

    speed = max(0.7, min(1.4, speed))

    # Ensure output directory exists
    os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)

    if not output_path.endswith('.wav'):
        output_path += '.wav'

    try:
        # Generate audio — Kokoro returns generator of (graphemes, phonemes, audio) tuples
        import soundfile as sf

        all_audio = []
        for _, _, audio in pipeline(text, voice=voice, speed=speed):
            all_audio.append(audio)

        if not all_audio:
            return {"status": "error", "message": "No audio generated"}

        # Concatenate all chunks
        import numpy as np
        full_audio = np.concatenate(all_audio)

        # Save as WAV (24kHz, mono)
        sf.write(output_path, full_audio, 24000)

        duration_ms = int(len(full_audio) / 24000 * 1000)
        logger.info(f"[VOICE] TTS: {len(text)} chars → {duration_ms}ms audio")

        return {
            "status": "success",
            "path": output_path,
            "duration_ms": duration_ms,
            "voice": voice,
            "speed": speed,
        }

    except Exception as e:
        logger.error(f"[VOICE] TTS failed: {e}")
        return {"status": "error", "message": str(e)}


def speech_to_text(audio_path: str) -> dict:
    """
    Convert speech to text using Whisper (via whisper.cpp).

    Args:
        audio_path: Path to audio file (WAV, MP3, etc.)

    Returns:
        {"status": str, "text": str, "segments": list}
    """
    model = _get_stt()
    if model is None:
        return {"status": "error", "message": "Whisper STT not installed"}

    try:
        segments = model.transcribe(audio_path)

        full_text = " ".join(seg.text.strip() for seg in segments)
        segment_list = [
            {
                "text": seg.text.strip(),
                "start_ms": int(seg.t0 * 10),  # whisper.cpp uses centiseconds
                "end_ms": int(seg.t1 * 10),
            }
            for seg in segments
        ]

        logger.info(f"[VOICE] STT: {len(segment_list)} segments → {len(full_text)} chars")

        return {
            "status": "success",
            "text": full_text,
            "segments": segment_list,
        }

    except Exception as e:
        logger.error(f"[VOICE] STT failed: {e}")
        return {"status": "error", "message": str(e)}


def text_to_speech_chunked(text: str, output_dir: str, voice: str = "af_heart",
                           speed: float = 1.0, max_chars: int = 200) -> dict:
    """
    Convert text to speech in sentence-sized chunks.
    Returns individual WAV files for streaming playback.
    """
    import re

    # Split into sentences
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks = []
    current = ""

    for s in sentences:
        if len(current) + len(s) > max_chars and current:
            chunks.append(current.strip())
            current = s
        else:
            current += " " + s if current else s

    if current.strip():
        chunks.append(current.strip())

    os.makedirs(output_dir, exist_ok=True)
    results = []

    for i, chunk in enumerate(chunks):
        path = os.path.join(output_dir, f"chunk_{i:03d}.wav")
        result = text_to_speech(chunk, path, voice=voice, speed=speed)
        results.append({
            "index": i,
            "text": chunk,
            **result,
        })

    total_duration = sum(r.get("duration_ms", 0) for r in results)

    return {
        "status": "success",
        "chunks": results,
        "total_chunks": len(results),
        "total_duration_ms": total_duration,
    }
