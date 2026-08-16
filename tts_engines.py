"""Narration engines: Edge TTS, Gemini TTS, ElevenLabs.

Each speak_* function takes text + the config dict and blocks until
playback finishes. Shared here so both main.py (the reader) and
settings_gui.py (the "Test Voice" button) use identical logic.
"""

import os
import time
import wave
import asyncio
import tempfile

import requests
import pygame
import numpy as np
import sounddevice as sd

from common import DEFAULT_DM_STYLE_PROMPT

# A single requests.Session is reused across calls to avoid repeated
# TCP/TLS handshake overhead on every capture — a real (if modest)
# latency win when you're reading text back-to-back.
_session = requests.Session()

# The Gemini client is expensive to construct repeatedly, so we cache
# one per API key.
_gemini_clients = {}


def _ensure_mixer():
    if not pygame.mixer.get_init():
        pygame.mixer.init()


def play_and_delete(path, volume=1.0, stop_event=None, pause_event=None):
    _ensure_mixer()
    pygame.mixer.music.load(path)
    pygame.mixer.music.set_volume(max(0.0, min(1.0, float(volume))))
    pygame.mixer.music.play()

    paused = False
    while True:
        if stop_event is not None and stop_event.is_set():
            pygame.mixer.music.stop()
            break

        want_pause = pause_event is not None and pause_event.is_set()
        if want_pause and not paused:
            pygame.mixer.music.pause()
            paused = True
        elif not want_pause and paused:
            pygame.mixer.music.unpause()
            paused = False

        if not paused and not pygame.mixer.music.get_busy():
            break

        time.sleep(0.05)

    try:
        os.remove(path)
    except OSError:
        pass


def speak_edge(text, config, stop_event=None, pause_event=None):
    import edge_tts

    voice = config.get("edge_voice", "en-US-GuyNeural")
    pitch = config.get("edge_pitch", "-5Hz")
    volume = config.get("volume", 1.0)

    # A single "speed" slider (0.5-2.0) drives Edge's native rate
    # parameter directly — real prosody control, not post-processing.
    speed = float(config.get("speed", 1.0))
    rate_percent = int(round((speed - 1.0) * 100))
    rate = f"{'+' if rate_percent >= 0 else ''}{rate_percent}%"

    fd, path = tempfile.mkstemp(suffix=".mp3")
    os.close(fd)

    async def _generate():
        communicate = edge_tts.Communicate(text, voice, rate=rate, pitch=pitch)
        await communicate.save(path)

    try:
        asyncio.run(_generate())
    except Exception as e:
        if os.path.exists(path):
            os.remove(path)
        raise RuntimeError(f"Edge TTS error: {e}") from e

    play_and_delete(path, volume, stop_event, pause_event)


def speak_gemini(text, config, stop_event=None, pause_event=None):
    """Streams audio and plays it as chunks arrive rather than waiting
    for the full clip to be generated first.

    Only gemini-3.1-flash-tts-preview actually sends audio incrementally
    — older models accept the same streaming call but still return one
    complete chunk at the end, so this code path works correctly (just
    without the speed benefit) on those too.
    """
    from google import genai
    from google.genai import types

    api_key = config.get("gemini_api_key", "")
    if not api_key:
        raise RuntimeError("Gemini error: no gemini_api_key set.")

    model = config.get("gemini_model", "gemini-3.1-flash-tts-preview")
    voice_name = config.get("gemini_voice", "Kore")
    style_prompt = config.get("gemini_style_prompt", DEFAULT_DM_STYLE_PROMPT)
    volume = max(0.0, min(1.0, float(config.get("volume", 1.0))))

    # Gemini's TTS API has no numeric "speed" parameter — it's steered
    # entirely by natural-language direction, so the speed slider is
    # translated into a pacing instruction instead of a hard value.
    speed = float(config.get("speed", 1.0))
    if speed <= 0.85:
        pace_note = " Speak at a slow, deliberate pace."
    elif speed >= 1.15:
        pace_note = " Speak briskly, noticeably faster than a normal conversational pace."
    else:
        pace_note = ""

    client = _gemini_clients.get(api_key)
    if client is None:
        client = genai.Client(api_key=api_key)
        _gemini_clients[api_key] = client

    prompt = f"{style_prompt}{pace_note}\n\nText to read aloud:\n{text}"
    gen_config = types.GenerateContentConfig(
        response_modalities=["AUDIO"],
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name=voice_name)
            )
        ),
    )

    stream = None
    got_audio = False
    error_to_raise = None
    try:
        response_stream = client.models.generate_content_stream(
            model=model, contents=prompt, config=gen_config,
        )
        for chunk in response_stream:
            if stop_event is not None and stop_event.is_set():
                break

            # Pausing withholds further chunks from being written to
            # the output stream — already-buffered audio (a fraction
            # of a second) finishes naturally, then it goes quiet until
            # resumed, at which point it picks back up on the very
            # next chunk rather than skipping ahead.
            while pause_event is not None and pause_event.is_set():
                if stop_event is not None and stop_event.is_set():
                    break
                time.sleep(0.05)
            if stop_event is not None and stop_event.is_set():
                break

            if not chunk.candidates:
                continue
            parts = chunk.candidates[0].content.parts
            if not parts:
                continue
            inline = getattr(parts[0], "inline_data", None)
            if not inline or not inline.data:
                continue

            got_audio = True
            if stream is None:
                # Opened lazily on first chunk so nothing plays until
                # there's actually audio to play.
                stream = sd.OutputStream(samplerate=24000, channels=1, dtype="int16")
                stream.start()

            pcm = np.frombuffer(inline.data, dtype=np.int16)
            if volume != 1.0:
                pcm = (pcm.astype(np.float32) * volume).clip(-32768, 32767).astype(np.int16)
            stream.write(pcm)

        if not got_audio and (stop_event is None or not stop_event.is_set()):
            error_to_raise = RuntimeError(
                "Gemini TTS error: no audio returned. The preview model "
                "occasionally returns text instead of audio — try again, "
                "or switch to gemini-2.5-flash-preview-tts in Settings."
            )
    except Exception as e:
        error_to_raise = RuntimeError(f"Gemini TTS error: {e}")
    finally:
        if stream is not None:
            stream.stop()
            stream.close()

    if error_to_raise is not None:
        raise error_to_raise


def speak_elevenlabs(text, config, stop_event=None, pause_event=None):
    api_key = config.get("api_key", "")
    voice_id = config.get("voice_id", "")
    volume = config.get("volume", 1.0)
    if not api_key or not voice_id:
        raise RuntimeError("ElevenLabs error: api_key or voice_id missing in config.")

    # The /stream endpoint sends audio chunks as they're synthesized
    # instead of waiting for the entire clip to finish server-side —
    # noticeably faster time-to-first-byte on longer text than the
    # non-streaming endpoint.
    url = f"https://api.elevenlabs.io/v1/text-to-speech/{voice_id}/stream"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {
        "text": text,
        "model_id": config.get("model_id", "eleven_flash_v2_5"),
        "voice_settings": {
            "stability": config.get("stability", 0.45),
            "similarity_boost": config.get("similarity_boost", 0.8),
            "style": config.get("style", 0.65),
            "use_speaker_boost": True,
            # ElevenLabs only supports 0.7-1.2, unlike the wider
            # 0.5-2.0 range the slider allows — clamp rather than error.
            "speed": max(0.7, min(1.2, float(config.get("speed", 1.0)))),
        },
    }

    try:
        response = _session.post(
            url, json=payload, headers=headers, timeout=60, stream=True
        )
    except requests.RequestException as e:
        raise RuntimeError(f"ElevenLabs request failed: {e}") from e

    if response.status_code != 200:
        raise RuntimeError(f"ElevenLabs error {response.status_code}: {response.text[:300]}")

    fd, path = tempfile.mkstemp(suffix=".mp3")
    with os.fdopen(fd, "wb") as f:
        for chunk in response.iter_content(chunk_size=4096):
            if chunk:
                f.write(chunk)

    play_and_delete(path, volume, stop_event, pause_event)


def speak_chatterbox(text, config, stop_event=None, pause_event=None):
    """Talks to a local Chatterbox server (chatterbox_server/server.py)
    over HTTP on localhost. That server runs in its own Python 3.11
    environment and must already be running — see run_chatterbox.bat.
    """
    volume = config.get("volume", 1.0)
    port = config.get("chatterbox_port", 8765)
    url = f"http://127.0.0.1:{port}/speak"

    payload = {
        "text": text,
        "exaggeration": float(config.get("chatterbox_exaggeration", 0.5)),
        "cfg_weight": float(config.get("chatterbox_cfg_weight", 0.5)),
        "temperature": float(config.get("chatterbox_temperature", 0.8)),
    }
    voice_sample = config.get("chatterbox_voice_sample", "")
    if voice_sample:
        payload["audio_prompt_path"] = voice_sample

    try:
        response = _session.post(url, json=payload, timeout=180)
    except requests.RequestException as e:
        raise RuntimeError(
            f"Chatterbox server isn't reachable at {url} — make sure "
            f"run_chatterbox.bat is running and has finished loading "
            f"the model first. ({e})"
        ) from e

    if response.status_code != 200:
        raise RuntimeError(f"Chatterbox error {response.status_code}: {response.text[:300]}")

    fd, path = tempfile.mkstemp(suffix=".wav")
    with os.fdopen(fd, "wb") as f:
        f.write(response.content)

    play_and_delete(path, volume, stop_event, pause_event)


def speak(text, config, stop_event=None, pause_event=None):
    provider = config.get("tts_provider", "edge")
    if provider == "gemini":
        speak_gemini(text, config, stop_event, pause_event)
    elif provider == "elevenlabs":
        speak_elevenlabs(text, config, stop_event, pause_event)
    elif provider == "chatterbox":
        speak_chatterbox(text, config, stop_event, pause_event)
    else:
        speak_edge(text, config, stop_event, pause_event)
