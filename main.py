"""
DM Reader — reads on-screen game text aloud in an immersive voice.

Flow:
  1. Press the hotkey (default F8).
  2. Drag a box around the text you want read.
  3. The tool captures that exact screen region (works with true
     exclusive-fullscreen games, unlike normal screenshot tools),
     runs OCR on it, sends the text to your chosen narration engine,
     and auto-plays the result.

Run settings_gui.py (or DMReaderSettings.exe once built) any time to
change the engine, hotkeys, or volume — this app picks up changes to
config.json automatically, no restart needed.
"""

import os
import sys
import atexit
import time
import threading
import tkinter as tk

import mss
import numpy as np
import pytesseract
from PIL import Image
import bettercam
import keyboard

import common
import tts_engines


def first_time_setup():
    print("=" * 60)
    print("First-time setup")
    print("=" * 60)
    print("Which narration engine do you want to use?")
    print("  1) Edge TTS    — free, unlimited, no signup needed")
    print("  2) Gemini TTS  — free tier, most expressive, needs a free")
    print("                   Google AI Studio API key")
    print("  3) ElevenLabs  — best quality, ~10 min/month free, needs an")
    print("                   ElevenLabs account + API key")
    choice = input("Enter 1, 2, or 3 [default: 1]: ").strip() or "1"

    config = dict(common.DEFAULT_CONFIG)
    config["hotkey"] = (input("Hotkey to trigger capture [default: f8]: ").strip() or "f8").lower()
    config["exit_key"] = (input("Hotkey to quit the app [default: f9]: ").strip() or "f9").lower()

    if choice == "2":
        config["tts_provider"] = "gemini"
        config["gemini_api_key"] = input(
            "Paste your free Google AI Studio API key "
            "(get one at aistudio.google.com/apikey): "
        ).strip()
        config["gemini_voice"] = input("Gemini voice name [default: Kore]: ").strip() or "Kore"
    elif choice == "3":
        config["tts_provider"] = "elevenlabs"
        config["api_key"] = input("Paste your ElevenLabs API key: ").strip()
        config["voice_id"] = input("Paste the ElevenLabs Voice ID you want to use: ").strip()
    else:
        config["tts_provider"] = "edge"
        config["edge_voice"] = input(
            "Edge voice name [default: en-US-GuyNeural — try "
            "en-GB-RyanNeural or en-US-ChristopherNeural too]: "
        ).strip() or "en-US-GuyNeural"

    common.write_config(config)
    print("\nSaved to config.json.")
    print("Run settings_gui.py any time to change engine, hotkeys, or volume")
    print("without editing this file by hand.\n")
    return config


class RegionSelector:
    """Fullscreen click-drag overlay that returns the selected box, in
    absolute virtual-desktop coordinates (so it works correctly no
    matter which monitor the box is drawn on).

    - "desktop" mode spans every monitor at once, so you can drag a box
      on any of them in a single overlay.
    - "fullscreen_game" mode spans only the chosen monitor_index, since
      the underlying capture method for that mode (Desktop Duplication)
      is inherently tied to one specific monitor.
    """

    def __init__(self, capture_mode="fullscreen_game", monitor_index=0):
        self.coords = None
        self.capture_mode = capture_mode
        self.monitor_index = monitor_index

    def _get_bounds(self):
        with mss.MSS() as sct:
            if self.capture_mode == "desktop":
                m = sct.monitors[0]  # index 0 = full virtual desktop
            else:
                monitors = sct.monitors[1:]  # skip the combined entry
                idx = self.monitor_index if self.monitor_index < len(monitors) else 0
                m = monitors[idx]
            return m["left"], m["top"], m["width"], m["height"]

    def select(self):
        left, top, width, height = self._get_bounds()

        root = tk.Tk()
        # overrideredirect + explicit geometry (rather than the
        # -fullscreen attribute) is what lets this window position
        # itself on a secondary monitor, including ones with negative
        # coordinates relative to the primary display.
        root.overrideredirect(True)
        root.geometry(f"{width}x{height}+{left}+{top}")
        root.attributes("-alpha", 0.25)
        root.attributes("-topmost", True)
        root.configure(bg="black")
        root.config(cursor="crosshair")
        root.focus_force()

        canvas = tk.Canvas(root, bg="grey11", highlightthickness=0)
        canvas.pack(fill=tk.BOTH, expand=True)

        canvas.create_text(
            width // 2, 40,
            text="Click and drag over the text you want read  •  Esc to cancel",
            fill="white", font=("Segoe UI", 16),
        )

        state = {"start": None, "rect": None}

        def on_press(event):
            state["start"] = (event.x, event.y)
            state["rect"] = canvas.create_rectangle(
                event.x, event.y, event.x, event.y,
                outline="#ff4d4d", width=2,
            )

        def on_drag(event):
            if state["rect"] is not None:
                sx, sy = state["start"]
                canvas.coords(state["rect"], sx, sy, event.x, event.y)

        def on_release(event):
            sx, sy = state["start"]
            # Convert from this window's local coords back to absolute
            # virtual-desktop coords by adding the window's own offset.
            l = min(sx, event.x) + left
            t = min(sy, event.y) + top
            r = max(sx, event.x) + left
            b = max(sy, event.y) + top
            if r - l > 4 and b - t > 4:
                self.coords = (l, t, r, b)
            root.quit()

        def on_escape(_event):
            self.coords = None
            root.quit()

        canvas.bind("<ButtonPress-1>", on_press)
        canvas.bind("<B1-Motion>", on_drag)
        canvas.bind("<ButtonRelease-1>", on_release)
        root.bind("<Escape>", on_escape)

        root.mainloop()
        root.destroy()
        return self.coords


class DMReader:
    def __init__(self, config):
        self.config = config
        self.busy = False
        self._config_mtime = None
        self._control_mtime = None
        self._refresh_mtime()

        # Interrupting narration mid-playback (for the quit hotkey and
        # pause/resume) requires it to run somewhere other than the
        # main loop, so the loop stays free to keep checking for key
        # presses and the control file the whole time it's talking.
        self.stop_narration_event = threading.Event()
        self.pause_event = threading.Event()

        tpath = common.find_tesseract()
        if tpath:
            pytesseract.pytesseract.tesseract_cmd = tpath
        else:
            print(
                "WARNING: Tesseract-OCR not found in the default install "
                "location. Install it from "
                "https://github.com/UB-Mannheim/tesseract/wiki if OCR fails."
            )

        # bettercam wraps the Windows Desktop Duplication API, which can
        # see into exclusive-fullscreen DirectX/Vulkan surfaces that
        # normal screenshot tools render as black. One camera per
        # monitor is created lazily, only when that monitor is actually
        # used, since creating one is a bit expensive.
        self._bettercam_cameras = {}
        atexit.register(self._release_cameras)

    def _get_bettercam_camera(self, monitor_index):
        camera = self._bettercam_cameras.get(monitor_index)
        if camera is None:
            camera = bettercam.create(output_idx=monitor_index, output_color="RGB")
            self._bettercam_cameras[monitor_index] = camera
        return camera

    def _refresh_mtime(self):
        try:
            self._config_mtime = os.path.getmtime(common.CONFIG_PATH)
        except OSError:
            self._config_mtime = None

    def reload_config_if_changed(self):
        """Picks up changes saved from settings_gui.py without a restart."""
        try:
            mtime = os.path.getmtime(common.CONFIG_PATH)
        except OSError:
            return
        if mtime != self._config_mtime:
            try:
                self.config = common.read_config()
                self._config_mtime = mtime
            except (ValueError, OSError):
                # File may be mid-write from the settings GUI; try again
                # on the next loop iteration.
                pass

    def poll_control(self):
        """Picks up pause/resume toggled from the launcher GUI (or the
        in-app pause hotkey, which also writes through this same file
        so both sources stay in sync)."""
        try:
            mtime = os.path.getmtime(common.CONTROL_PATH)
        except OSError:
            return
        if mtime != self._control_mtime:
            control = common.read_control()
            paused = control.get("paused", False)
            if paused and not self.pause_event.is_set():
                print("Paused.")
            elif not paused and self.pause_event.is_set():
                print("Resumed.")
            if paused:
                self.pause_event.set()
            else:
                self.pause_event.clear()
            self._control_mtime = mtime

    def toggle_pause(self):
        control = common.read_control()
        control["paused"] = not control.get("paused", False)
        common.write_control(control)

    def _release_cameras(self):
        # Prevents a noisy (harmless) COM cleanup error some systems throw
        # when the interpreter exits while a DXGI capture device is
        # still attached.
        for camera in self._bettercam_cameras.values():
            try:
                if hasattr(camera, "release"):
                    camera.release()
                elif hasattr(camera, "stop"):
                    camera.stop()
            except Exception:
                pass

    def capture_region(self, region):
        """region = absolute virtual-desktop (left, top, right, bottom)."""
        if self.config.get("capture_mode", "fullscreen_game") == "desktop":
            return self._capture_with_mss(region)
        return self._capture_with_bettercam(region)

    def _capture_with_mss(self, region):
        left, top, right, bottom = region
        with mss.MSS() as sct:
            shot = sct.grab({
                "left": left, "top": top,
                "width": right - left, "height": bottom - top,
            })
            # mss returns BGRA; drop alpha and flip to RGB for PIL/OCR.
            frame = np.array(shot)[:, :, [2, 1, 0]]
            return frame

    def _capture_with_bettercam(self, region, retries=6):
        monitor_index = int(self.config.get("monitor_index", 0))
        camera = self._get_bettercam_camera(monitor_index)

        # bettercam wants coordinates local to the target monitor, not
        # absolute virtual-desktop coordinates, so translate using that
        # monitor's own origin.
        with mss.MSS() as sct:
            monitors = sct.monitors[1:]
            idx = monitor_index if monitor_index < len(monitors) else 0
            m = monitors[idx]
        left, top, right, bottom = region
        local_region = (left - m["left"], top - m["top"], right - m["left"], bottom - m["top"])

        for attempt in range(retries):
            frame = camera.grab(region=local_region)
            if frame is not None:
                return frame
            time.sleep(0.05)
        raise RuntimeError(
            "Capture came back empty after several tries. If the game is in "
            "true exclusive-fullscreen mode, try switching it to "
            "'Borderless' or 'Fullscreen Window' in its display settings — "
            "most engines default to this anyway. If the game is on a "
            "different monitor than expected, try changing 'Monitor' in "
            "Settings."
        )

    def ocr_frame(self, frame):
        image = Image.fromarray(frame)
        scale = float(self.config.get("ocr_upscale", 2.0))
        if scale != 1.0:
            image = image.resize(
                (int(image.width * scale), int(image.height * scale)),
                Image.LANCZOS,
            )
        text = pytesseract.image_to_string(image)
        return " ".join(text.split())

    def handle_capture(self):
        if self.busy:
            return
        self.busy = True
        try:
            selector = RegionSelector(
                capture_mode=self.config.get("capture_mode", "fullscreen_game"),
                monitor_index=int(self.config.get("monitor_index", 0)),
            )
            region = selector.select()
            if region is None:
                print("Selection cancelled.")
                return

            t0 = time.time()
            print(f"Capturing region {region} ...")
            frame = self.capture_region(region)

            print("Running OCR ...")
            text = self.ocr_frame(frame)
            if not text.strip():
                print("No text detected in that region.")
                return

            print(f"Read: {text[:120]}{'...' if len(text) > 120 else ''}")
            print(f"Requesting narration via {self.config.get('tts_provider', 'edge')} ...")
            tts_engines.speak(
                text, self.config,
                stop_event=self.stop_narration_event,
                pause_event=self.pause_event,
            )
            if self.stop_narration_event.is_set():
                print("Narration stopped.\n")
            else:
                print(f"Done in {time.time() - t0:.1f}s.\n")
        except Exception as e:
            print(f"Error: {e}")
        finally:
            self.busy = False

    def run(self):
        printed_hotkey = None
        printed_exit_key = None

        print("=" * 60)
        print("DM Reader is running")
        print("=" * 60)

        while True:
            self.reload_config_if_changed()
            self.poll_control()
            hotkey = self.config.get("hotkey", "f8")
            exit_key = self.config.get("exit_key", "f9")
            pause_key = self.config.get("pause_key", "f10")

            if (hotkey, exit_key) != (printed_hotkey, printed_exit_key):
                print(f"  Press [{hotkey.upper()}] to capture & read text")
                print(f"  Press [{pause_key.upper()}] to pause/resume narration")
                print(f"  Press [{exit_key.upper()}] to quit")
                print(f"  Engine: {self.config.get('tts_provider', 'edge')}")
                print("-" * 60)
                printed_hotkey, printed_exit_key = hotkey, exit_key

            try:
                if keyboard.is_pressed(exit_key):
                    print("Exiting.")
                    # Interrupt any in-progress narration immediately
                    # rather than waiting for it to finish naturally.
                    self.stop_narration_event.set()
                    time.sleep(0.15)
                    break

                if keyboard.is_pressed(pause_key):
                    self.toggle_pause()
                    while keyboard.is_pressed(pause_key):
                        time.sleep(0.05)

                if keyboard.is_pressed(hotkey):
                    if self.busy:
                        print("Still reading the last capture — press "
                              f"[{pause_key.upper()}] to pause it, or wait for it to finish.")
                    else:
                        # Runs capture + narration on a background
                        # thread so this loop stays free to keep
                        # checking for the quit/pause keys the whole
                        # time narration is playing.
                        threading.Thread(target=self.handle_capture, daemon=True).start()
                    while keyboard.is_pressed(hotkey):
                        time.sleep(0.05)
            except ValueError:
                # A hotkey string in config.json isn't a key keyboard
                # recognizes (e.g. mid-edit in the settings GUI).
                pass

            time.sleep(0.05)


def main():
    if common.config_exists():
        config = common.read_config()
    else:
        config = first_time_setup()

    # Start unpaused regardless of whatever a previous run left behind.
    common.write_control({"paused": False})

    reader = DMReader(config)
    reader.run()


if __name__ == "__main__":
    main()
