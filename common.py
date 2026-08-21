"""Shared constants and config helpers used by main.py and settings_gui.py."""

import json
import os
import sys

DEFAULT_TESSERACT_PATHS = [
    r"C:\Program Files\Tesseract-OCR\tesseract.exe",
    r"C:\Program Files (x86)\Tesseract-OCR\tesseract.exe",
]

DEFAULT_DM_STYLE_PROMPT = (
    "Say the following in the voice of a theatrical dungeon master "
    "narrating to players around a table: deep, deliberate pacing, "
    "a sense of drama and mystery, with weight on evocative words."
)

# Built-in style "loadouts" for Gemini TTS. Users can add their own on
# top of these from the Settings window; those are stored separately
# in config.json under gemini_custom_presets so they survive updates
# to this file.
GEMINI_STYLE_PRESETS = [
    {"name": "Dungeon Master", "prompt": DEFAULT_DM_STYLE_PROMPT},
    {
        "name": "Grim Narrator",
        "prompt": (
            "Say the following in a dark, foreboding voice full of dread "
            "and menace, speaking slowly with ominous weight on every "
            "word, as if delivering a warning."
        ),
    },
    {
        "name": "Whimsical Storyteller",
        "prompt": (
            "Say the following in a warm, playful, sing-song storyteller "
            "voice, like reading a beloved fairy tale aloud to a child, "
            "full of wonder and gentle humor."
        ),
    },
    {
        "name": "Battle Herald",
        "prompt": (
            "Say the following in a booming, urgent, rallying voice, as "
            "if shouting orders and encouragement across a battlefield, "
            "full of intensity and adrenaline."
        ),
    },
    {
        "name": "Calm Narrator",
        "prompt": (
            "Say the following in a clear, calm, measured narrator "
            "voice, neutral and easy to follow, prioritizing clarity "
            "over drama."
        ),
    },
]

# The 30 voice names Gemini TTS currently supports.
GEMINI_VOICES = [
    "Zephyr", "Puck", "Charon", "Kore", "Fenrir", "Leda", "Orus", "Aoede",
    "Callirrhoe", "Autonoe", "Enceladus", "Iapetus", "Umbriel", "Algieba",
    "Despina", "Erinome", "Algenib", "Rasalgethi", "Laomedeia", "Achernar",
    "Alnilam", "Schedar", "Gacrux", "Pulcherrima", "Achird", "Zubenelgenubi",
    "Vindemiatrix", "Sadachbia", "Sadaltager", "Sulafat",
]

# Fast models chosen as defaults for lower latency; can be overridden.
ELEVENLABS_MODELS = ["eleven_flash_v2_5", "eleven_turbo_v2_5", "eleven_multilingual_v2"]

# gemini-3.1-flash-tts-preview is the only model that actually streams
# audio in pieces as it's generated — the others accept a streaming
# API call but still send one complete chunk at the end, so there's
# no real speed benefit from streaming with them. Listed first as the
# recommended/default choice for lowest latency.
GEMINI_MODELS = [
    "gemini-3.1-flash-tts-preview",
    "gemini-2.5-flash-lite-preview-tts",
    "gemini-2.5-flash-preview-tts",
    "gemini-2.5-pro-preview-tts",
]

EDGE_VOICE_SUGGESTIONS = [
    "en-US-GuyNeural", "en-US-ChristopherNeural", "en-US-EricNeural",
    "en-GB-RyanNeural", "en-GB-ThomasNeural", "en-AU-WilliamNeural",
]

DEFAULT_CONFIG = {
    "tts_provider": "edge",
    "hotkey": "f8",
    "exit_key": "f9",
    "pause_key": "f10",
    "recapture_key": "f7",
    "skip_key": "f11",
    "watch_key": "f12",
    "watch_interval_seconds": 2.0,
    "show_ocr_preview": True,
    "ocr_preview_seconds": 2.5,
    "ocr_preview_position": "top",  # "top", "center", "bottom", or "custom"
    "ocr_preview_custom_rect": None,  # [left, top, width] from dragging the box by hand
    "ocr_upscale": 2.0,
    "volume": 1.0,
    "speed": 1.0,
    "capture_mode": "fullscreen_game",  # "fullscreen_game" or "desktop"
    "monitor_index": 0,
    "edge_voice": "en-US-GuyNeural",
    "edge_rate": "+0%",
    "edge_pitch": "-5Hz",
    "gemini_api_key": "",
    "gemini_model": "gemini-3.1-flash-tts-preview",
    "gemini_voice": "Kore",
    "gemini_style_prompt": DEFAULT_DM_STYLE_PROMPT,
    "gemini_custom_presets": [],
    "api_key": "",
    "voice_id": "",
    "model_id": "eleven_flash_v2_5",
    "stability": 0.45,
    "similarity_boost": 0.8,
    "style": 0.65,
    "chatterbox_port": 8765,
    "chatterbox_exaggeration": 0.5,
    "chatterbox_cfg_weight": 0.5,
    "chatterbox_temperature": 0.8,
    "chatterbox_voice_sample": "",
}


def get_base_dir():
    """Directory the config file lives in — works both as a .py script
    and as a PyInstaller-frozen .exe (where __file__ points into a temp
    extraction folder instead of the exe's real location)."""
    if getattr(sys, "frozen", False):
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


CONFIG_PATH = os.path.join(get_base_dir(), "config.json")
CONTROL_PATH = os.path.join(get_base_dir(), "control.json")
# "command"/"command_id" is a one-shot channel the launcher uses to
# trigger a capture/recapture/watch-toggle/skip in the running reader
# process — same file-polling handshake pause already uses. The id is
# bumped on every send so the reader can tell "new command" apart from
# "same command, file just rewritten for an unrelated reason" (e.g. a
# pause toggle) even though both go through the same file.
DEFAULT_CONTROL = {"paused": False, "command": None, "command_id": 0}


def find_tesseract():
    for path in DEFAULT_TESSERACT_PATHS:
        if os.path.exists(path):
            return path
    return None


def config_exists():
    return os.path.exists(CONFIG_PATH)


def read_config():
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)
    # Fill in any keys missing from an older config file with defaults,
    # so upgrading never breaks on a KeyError.
    merged = dict(DEFAULT_CONFIG)
    merged.update(data)
    return merged


def write_config(config):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(config, f, indent=2)


def read_control():
    try:
        with open(CONTROL_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        merged = dict(DEFAULT_CONTROL)
        merged.update(data)
        return merged
    except (OSError, ValueError):
        return dict(DEFAULT_CONTROL)


def write_control(control):
    with open(CONTROL_PATH, "w", encoding="utf-8") as f:
        json.dump(control, f)


def send_command(action):
    """Asks the running reader process to perform one of "capture",
    "recapture", "toggle_watch", or "skip" — read by DMReader.poll_control
    on its next loop tick (~50ms). Preserves the existing paused state
    rather than clobbering it, since both travel through control.json."""
    control = read_control()
    control["command"] = action
    control["command_id"] = control.get("command_id", 0) + 1
    write_control(control)


def select_screen_rect(prompt="Click and drag to draw the box  •  Esc to cancel"):
    """Fullscreen click-drag overlay spanning the whole virtual desktop
    (all monitors at once) that returns the drawn box as
    (left, top, width, height) in absolute screen coordinates, or None
    if cancelled. Used to let the user place the OCR text-preview box
    anywhere on screen by hand, from either the launcher or Settings.

    Imports mss/tkinter lazily so this module stays a light, dependency
    -free import for anything that only needs config helpers.
    """
    import mss
    import tkinter as tk

    with mss.MSS() as sct:
        m = sct.monitors[0]
    left0, top0, width0, height0 = m["left"], m["top"], m["width"], m["height"]

    root = tk.Tk()
    root.overrideredirect(True)
    root.geometry(f"{width0}x{height0}+{left0}+{top0}")
    root.attributes("-alpha", 0.25)
    root.attributes("-topmost", True)
    root.configure(bg="black")
    root.config(cursor="crosshair")
    root.focus_force()

    canvas = tk.Canvas(root, bg="grey11", highlightthickness=0)
    canvas.pack(fill=tk.BOTH, expand=True)
    canvas.create_text(
        width0 // 2, 40, text=prompt, fill="white", font=("Segoe UI", 16),
    )

    result = {"rect": None}
    state = {"start": None, "rect_id": None}

    def on_press(event):
        state["start"] = (event.x, event.y)
        state["rect_id"] = canvas.create_rectangle(
            event.x, event.y, event.x, event.y, outline="#5b8cff", width=2,
        )

    def on_drag(event):
        if state["rect_id"] is not None:
            sx, sy = state["start"]
            canvas.coords(state["rect_id"], sx, sy, event.x, event.y)

    def on_release(event):
        sx, sy = state["start"]
        left = min(sx, event.x) + left0
        top = min(sy, event.y) + top0
        width = abs(event.x - sx)
        height = abs(event.y - sy)
        if width > 20 and height > 20:
            result["rect"] = (left, top, width, height)
        root.quit()

    def on_escape(_event):
        root.quit()

    canvas.bind("<ButtonPress-1>", on_press)
    canvas.bind("<B1-Motion>", on_drag)
    canvas.bind("<ButtonRelease-1>", on_release)
    root.bind("<Escape>", on_escape)

    root.mainloop()
    root.destroy()
    return result["rect"]
