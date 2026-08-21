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
import re
import sys
import bisect
import atexit
import queue
import time
import threading
import tkinter as tk
import tkinter.font as tkfont

import mss
import numpy as np
import pytesseract
from PIL import Image
import bettercam
import keyboard

import common
import tts_engines

# When the launcher starts this as a subprocess, stdout is a pipe, not
# a real console — Python defaults to fully block-buffered output in
# that case, so the launcher's Activity Log would only catch up in
# occasional big chunks instead of live. Force line buffering so every
# print() shows up there right away.
try:
    sys.stdout.reconfigure(line_buffering=True)
except Exception:
    pass


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


class OcrPreviewWindow:
    """A small topmost overlay that shows the OCR'd text and, once
    narration actually starts, highlights it word-by-word in sync with
    playback — exact timing for file-based engines (Edge/ElevenLabs),
    a chars-per-second estimate for Gemini's streamed audio (see
    tts_engines.speak_gemini).

    Owns its own Tk root and mainloop on a dedicated thread, since a
    Tk window can only safely be driven from the thread that created
    it. Everything from the capture/speak thread comes in through a
    thread-safe queue and is only ever acted on from inside this
    window's own after()-driven poll loop.
    """

    _POLL_MS = 40

    def __init__(self, text, config):
        self.text = text
        self.config = config
        self._queue = queue.Queue()
        self._words = [(m.start(), m.end()) for m in re.finditer(r"\S+", text)]
        self._word_starts = [w[0] for w in self._words]
        self._total_chars = max(1, self._words[-1][1] if self._words else 1)

        self._root = None
        self._text_widget = None
        self._start_time = None
        self._duration = None
        self._current_word_idx = -1

        threading.Thread(target=self._run, daemon=True).start()

    # ---- thread-safe public API (called from the capture/speak thread) ----

    def start_highlighting(self, duration):
        self._queue.put(("start", max(0.05, float(duration))))

    def close(self, linger_ms=800):
        self._queue.put(("close", linger_ms))

    # ---- everything below only ever runs on this window's own thread ----

    def _run(self):
        try:
            with mss.MSS() as sct:
                m = sct.monitors[0]

            root = tk.Tk()
            self._root = root
            root.overrideredirect(True)
            root.attributes("-topmost", True)
            try:
                root.attributes("-alpha", 0.94)
            except tk.TclError:
                pass
            root.configure(bg="#111318")

            font = ("Segoe UI", 13)
            position = self.config.get("ocr_preview_position", "top")
            custom_rect = self.config.get("ocr_preview_custom_rect")
            custom_xy = None
            if position == "custom" and custom_rect and len(custom_rect) >= 3:
                cx, cy, cw = custom_rect[0], custom_rect[1], custom_rect[2]
                # The Text widget sizes itself in characters, not
                # pixels, so the dragged pixel width is converted using
                # this font's actual measured character width — that's
                # what makes wrapping land close to the box the user
                # drew rather than the fixed generic width used below.
                avg_char_px = max(4, tkfont.Font(font=font).measure("0"))
                chars_per_line = max(10, int(cw / avg_char_px))
                custom_xy = (cx, cy)
            else:
                chars_per_line = 64

            lines = max(1, min(8, -(-len(self.text) // chars_per_line)))
            widget = tk.Text(
                root, wrap="word", width=chars_per_line, height=lines,
                bg="#111318", fg="#8a8d94", relief="flat",
                font=font, padx=18, pady=14,
                borderwidth=0, highlightthickness=0, cursor="arrow",
            )
            widget.insert("1.0", self.text)
            widget.tag_config("read", foreground="#f4f4f6")
            widget.tag_config("current", background="#5b8cff", foreground="#ffffff")
            widget.config(state="disabled")
            widget.pack()
            self._text_widget = widget

            root.update_idletasks()
            w = root.winfo_reqwidth()
            h = root.winfo_reqheight()
            if custom_xy is not None:
                # Height still auto-fits the text (narration length
                # varies every capture) — only position and wrap width
                # come from the box the user dragged, so text is never
                # clipped off the bottom of a fixed-height box.
                x = max(m["left"], min(custom_xy[0], m["left"] + m["width"] - w))
                y = max(m["top"], min(custom_xy[1], m["top"] + m["height"] - h))
            else:
                x = m["left"] + (m["width"] - w) // 2
                if position == "center":
                    y = m["top"] + (m["height"] - h) // 2
                elif position == "bottom":
                    y = m["top"] + m["height"] - h - 60
                else:
                    y = m["top"] + 40
            root.geometry(f"{w}x{h}+{x}+{y}")

            root.after(self._POLL_MS, self._poll)
            root.mainloop()
        except Exception:
            pass

    def _poll(self):
        try:
            while True:
                kind, value = self._queue.get_nowait()
                if kind == "start":
                    self._duration = value
                    self._start_time = time.time()
                elif kind == "close":
                    self._root.after(value, self._safe_destroy)
                    return  # stop polling — a destroy is already scheduled
        except queue.Empty:
            pass

        if self._start_time is not None and self._words:
            elapsed = time.time() - self._start_time
            frac = min(1.0, elapsed / self._duration) if self._duration else 1.0
            char_pos = frac * self._total_chars
            idx = bisect.bisect_right(self._word_starts, char_pos) - 1
            idx = max(-1, min(idx, len(self._words) - 1))
            if idx != self._current_word_idx:
                self._apply_highlight(idx)

        self._root.after(self._POLL_MS, self._poll)

    def _apply_highlight(self, idx):
        self._current_word_idx = idx
        widget = self._text_widget
        widget.tag_remove("current", "1.0", "end")
        if idx < 0:
            return
        end_pos = f"1.0+{self._words[idx][1]}c"
        widget.tag_add("read", "1.0", end_pos)
        start_pos = f"1.0+{self._words[idx][0]}c"
        widget.tag_add("current", start_pos, end_pos)

    def _safe_destroy(self):
        try:
            self._root.destroy()
        except Exception:
            pass


class DMReader:
    def __init__(self, config):
        self.config = config
        self.busy = False
        self._config_mtime = None
        self._control_mtime = None
        self._last_command_id = 0
        self._refresh_mtime()

        # Interrupting narration mid-playback (for the quit hotkey and
        # pause/resume) requires it to run somewhere other than the
        # main loop, so the loop stays free to keep checking for key
        # presses and the control file the whole time it's talking.
        self.stop_narration_event = threading.Event()
        self.pause_event = threading.Event()

        # Last region drawn (by hand or by Watch mode), reused by the
        # recapture hotkey and by Watch mode so you don't have to
        # redraw the same box on the same dialogue box every line.
        self.last_region = None
        self.watch_mode = False
        self.watch_last_text = ""

        logs_dir = os.path.join(common.get_base_dir(), "logs")
        os.makedirs(logs_dir, exist_ok=True)
        self._log_path = os.path.join(logs_dir, f"session_{time.strftime('%Y%m%d_%H%M%S')}.txt")

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
        so both sources stay in sync) — and any Capture/Recapture/Watch/
        Skip button pressed there, sent through the same file via
        common.send_command()."""
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

            command_id = control.get("command_id", 0)
            if command_id != self._last_command_id:
                self._last_command_id = command_id
                self._dispatch_command(control.get("command"))

    def _dispatch_command(self, action):
        if action == "capture":
            if self.busy:
                print("Still reading the last capture — use Skip to "
                      "interrupt it, or wait for it to finish.")
            else:
                threading.Thread(target=self.handle_capture, daemon=True).start()
        elif action == "recapture":
            if self.busy:
                print("Still reading the last capture — use Skip to interrupt it first.")
            else:
                threading.Thread(target=self.handle_recapture, daemon=True).start()
        elif action == "toggle_watch":
            threading.Thread(target=self.toggle_watch_mode, daemon=True).start()
        elif action == "skip":
            if self.busy:
                print("Skipping current narration...")
                self.stop_narration_event.set()

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

    def _capture_and_ocr(self, region, quiet=False):
        if not quiet:
            print(f"Capturing region {region} ...")
        frame = self.capture_region(region)
        if not quiet:
            print("Running OCR ...")
        return self.ocr_frame(frame)

    def _log_transcript(self, text):
        try:
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(f"[{time.strftime('%H:%M:%S')}] {text}\n")
        except OSError:
            pass

    def _speak_and_log(self, text):
        """Plays already-OCR'd text and appends it to the session
        transcript. Owns the busy flag so this — not just capture — is
        what serializes manual captures, recaptures, and Watch mode
        against each other."""
        if self.busy:
            return False
        self.busy = True
        preview = None
        try:
            print(f"Read: {text[:120]}{'...' if len(text) > 120 else ''}")
            if self.config.get("show_ocr_preview", True):
                preview = OcrPreviewWindow(text, self.config)

            def on_playback_start(duration):
                if preview is not None:
                    preview.start_highlighting(duration)

            print(f"Requesting narration via {self.config.get('tts_provider', 'edge')} ...")
            t0 = time.time()
            tts_engines.speak(
                text, self.config,
                stop_event=self.stop_narration_event,
                pause_event=self.pause_event,
                on_playback_start=on_playback_start,
            )
            stopped = self.stop_narration_event.is_set()
            self.stop_narration_event.clear()
            if stopped:
                print("Narration stopped.\n")
            else:
                print(f"Done in {time.time() - t0:.1f}s.\n")

            self._log_transcript(text)
            return True
        except Exception as e:
            print(f"Error: {e}")
            return False
        finally:
            if preview is not None:
                linger_ms = int(float(self.config.get("ocr_preview_seconds", 2.5)) * 1000)
                preview.close(linger_ms)
            self.busy = False

    def handle_capture(self, region=None):
        if self.busy:
            return
        if region is None:
            selector = RegionSelector(
                capture_mode=self.config.get("capture_mode", "fullscreen_game"),
                monitor_index=int(self.config.get("monitor_index", 0)),
            )
            region = selector.select()
            if region is None:
                print("Selection cancelled.")
                return
        self.last_region = region

        try:
            text = self._capture_and_ocr(region)
        except Exception as e:
            print(f"Error: {e}")
            return
        if not text.strip():
            print("No text detected in that region.")
            return
        self._speak_and_log(text)

    def handle_recapture(self):
        if self.busy:
            return
        if self.last_region is None:
            print("No previous capture yet — use the capture hotkey first.")
            return
        try:
            text = self._capture_and_ocr(self.last_region)
        except Exception as e:
            print(f"Error: {e}")
            return
        if not text.strip():
            print("No text detected in that region.")
            return
        self._speak_and_log(text)

    def toggle_watch_mode(self):
        if self.watch_mode:
            self.watch_mode = False
            print("Watch mode OFF.\n")
            return

        region = self.last_region
        if region is None:
            print("Watch mode needs a region — draw one now...")
            selector = RegionSelector(
                capture_mode=self.config.get("capture_mode", "fullscreen_game"),
                monitor_index=int(self.config.get("monitor_index", 0)),
            )
            region = selector.select()
            if region is None:
                print("Watch mode cancelled — no region selected.\n")
                return
            self.last_region = region

        self.watch_mode = True
        self.watch_last_text = ""
        interval = float(self.config.get("watch_interval_seconds", 2.0))
        watch_key = self.config.get("watch_key", "f12")
        print(
            f"Watch mode ON — watching region {region} every {interval:.1f}s, "
            f"speaking whenever the text changes. Press [{watch_key.upper()}] again to stop.\n"
        )
        threading.Thread(target=self._watch_loop, daemon=True).start()

    def _watch_loop(self):
        while self.watch_mode:
            interval = float(self.config.get("watch_interval_seconds", 2.0))
            waited = 0.0
            while waited < interval and self.watch_mode:
                time.sleep(0.1)
                waited += 0.1
            if not self.watch_mode:
                break

            if self.busy or self.pause_event.is_set():
                continue

            try:
                text = self._capture_and_ocr(self.last_region, quiet=True)
            except Exception as e:
                print(f"Watch mode capture error: {e}")
                continue

            if text.strip() and text != self.watch_last_text:
                self.watch_last_text = text
                print(f"Watch mode detected new text: {text[:120]}{'...' if len(text) > 120 else ''}")
                self._speak_and_log(text)

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
            recapture_key = self.config.get("recapture_key", "f7")
            skip_key = self.config.get("skip_key", "f11")
            watch_key = self.config.get("watch_key", "f12")

            if (hotkey, exit_key) != (printed_hotkey, printed_exit_key):
                print(f"  Press [{hotkey.upper()}] to capture & read text")
                print(f"  Press [{recapture_key.upper()}] to re-read the same region")
                print(f"  Press [{watch_key.upper()}] to toggle Watch mode (auto-read on change)")
                print(f"  Press [{pause_key.upper()}] to pause/resume narration")
                print(f"  Press [{skip_key.upper()}] to skip the current narration")
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

                if keyboard.is_pressed(skip_key):
                    if self.busy:
                        print("Skipping current narration...")
                        self.stop_narration_event.set()
                    while keyboard.is_pressed(skip_key):
                        time.sleep(0.05)

                if keyboard.is_pressed(watch_key):
                    threading.Thread(target=self.toggle_watch_mode, daemon=True).start()
                    while keyboard.is_pressed(watch_key):
                        time.sleep(0.05)

                if keyboard.is_pressed(recapture_key):
                    if self.busy:
                        print("Still reading the last capture — press "
                              f"[{skip_key.upper()}] to skip it first.")
                    else:
                        threading.Thread(target=self.handle_recapture, daemon=True).start()
                    while keyboard.is_pressed(recapture_key):
                        time.sleep(0.05)

                if keyboard.is_pressed(hotkey):
                    if self.busy:
                        print("Still reading the last capture — press "
                              f"[{skip_key.upper()}] to skip it, or wait for it to finish.")
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
