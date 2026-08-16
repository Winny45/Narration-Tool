"""
DM Reader — Settings

A small always-on-top window for changing the narration engine, API
keys/voices, hotkeys, and volume. Saves to the same config.json the
main reader uses — changes apply live, no need to restart the reader.
"""

import queue
import threading
import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog

import keyboard

import common
import tts_engines

SAMPLE_TEXT = (
    "The old door creaks open, revealing a chamber untouched for a "
    "hundred years. Dust drifts through a shaft of pale light."
)


class HotkeyCapture(ttk.Frame):
    """Entry box + 'Set' button that listens for the next key press."""

    def __init__(self, master, initial_value):
        super().__init__(master)
        self.value = tk.StringVar(value=initial_value)
        self._queue = queue.Queue()

        self.entry = ttk.Entry(self, textvariable=self.value, width=12, state="readonly")
        self.entry.pack(side=tk.LEFT, padx=(0, 6))

        self.button = ttk.Button(self, text="Set...", command=self._start_capture)
        self.button.pack(side=tk.LEFT)

        self._poll_queue()

    def _start_capture(self):
        self.button.config(text="Press a key...", state="disabled")

        def listen():
            try:
                event = keyboard.read_event(suppress=False)
                while event.event_type != "down":
                    event = keyboard.read_event(suppress=False)
                self._queue.put(event.name)
            except Exception:
                self._queue.put(None)

        threading.Thread(target=listen, daemon=True).start()

    def _poll_queue(self):
        try:
            name = self._queue.get_nowait()
        except queue.Empty:
            name = "__none__"

        if name != "__none__":
            if name:
                self.value.set(name.lower())
            self.button.config(text="Set...", state="normal")

        self.after(100, self._poll_queue)

    def get(self):
        return self.value.get()


class SettingsApp(ttk.Frame):
    def __init__(self, master, config):
        super().__init__(master, padding=16)
        self.config_data = config
        self.pack(fill=tk.BOTH, expand=True)

        self._build_general_section()
        self._build_provider_sections()
        self._build_buttons()

        self.provider_var.set(self.config_data.get("tts_provider", "edge"))
        self._on_provider_change()

    # ---- General ----

    def _build_general_section(self):
        frame = ttk.LabelFrame(self, text="General", padding=12)
        frame.pack(fill=tk.X, pady=(0, 12))

        ttk.Label(frame, text="Narration engine:").grid(row=0, column=0, sticky="w", pady=4)
        self.provider_var = tk.StringVar()
        provider_combo = ttk.Combobox(
            frame, textvariable=self.provider_var,
            values=["edge", "gemini", "elevenlabs", "chatterbox"], state="readonly", width=15,
        )
        provider_combo.grid(row=0, column=1, sticky="w", pady=4)
        provider_combo.bind("<<ComboboxSelected>>", lambda e: self._on_provider_change())

        ttk.Label(frame, text="Capture hotkey:").grid(row=1, column=0, sticky="w", pady=4)
        self.hotkey_capture = HotkeyCapture(frame, self.config_data.get("hotkey", "f8"))
        self.hotkey_capture.grid(row=1, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="Quit hotkey:").grid(row=2, column=0, sticky="w", pady=4)
        self.exit_capture = HotkeyCapture(frame, self.config_data.get("exit_key", "f9"))
        self.exit_capture.grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="Pause/Resume hotkey:").grid(row=3, column=0, sticky="w", pady=4)
        self.pause_capture = HotkeyCapture(frame, self.config_data.get("pause_key", "f10"))
        self.pause_capture.grid(row=3, column=1, sticky="w", pady=4)

        ttk.Label(frame, text="Narration speed:").grid(row=4, column=0, sticky="w", pady=4)
        self.speed_var = tk.DoubleVar(value=float(self.config_data.get("speed", 1.0)) * 100)
        speed_scale = ttk.Scale(frame, from_=50, to=200, variable=self.speed_var, length=180)
        speed_scale.grid(row=4, column=1, sticky="w", pady=4)
        self.speed_label = ttk.Label(frame, text="1.0x")
        self.speed_label.grid(row=4, column=2, sticky="w", padx=(6, 0))
        speed_scale.configure(command=lambda v: self.speed_label.config(text=f"{float(v)/100:.1f}x"))
        self.speed_label.config(text=f"{self.speed_var.get()/100:.1f}x")

        ttk.Label(frame, text="OCR upscale:").grid(row=5, column=0, sticky="w", pady=4)
        self.ocr_var = tk.DoubleVar(value=float(self.config_data.get("ocr_upscale", 2.0)))
        ttk.Spinbox(
            frame, from_=1.0, to=4.0, increment=0.5, textvariable=self.ocr_var, width=6
        ).grid(row=5, column=1, sticky="w", pady=4)

        ttk.Label(
            frame, text="(Volume is controlled from the main launcher window)",
            foreground="#888", font=("Segoe UI", 8),
        ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(0, 4))

        ttk.Separator(frame, orient="horizontal").grid(row=7, column=0, columnspan=3, sticky="ew", pady=8)

        ttk.Label(frame, text="Capture mode:").grid(row=8, column=0, sticky="w", pady=4)
        self.capture_mode_display = tk.StringVar()
        capture_mode_combo = ttk.Combobox(
            frame, textvariable=self.capture_mode_display,
            values=["Fullscreen game", "Screen / windowed apps (multi-monitor)"],
            state="readonly", width=32,
        )
        capture_mode_combo.grid(row=8, column=1, columnspan=2, sticky="w", pady=4)
        current_mode = self.config_data.get("capture_mode", "fullscreen_game")
        self.capture_mode_display.set(
            "Fullscreen game" if current_mode == "fullscreen_game"
            else "Screen / windowed apps (multi-monitor)"
        )
        capture_mode_combo.bind("<<ComboboxSelected>>", lambda e: self._on_capture_mode_change())

        self.monitor_label = ttk.Label(frame, text="Monitor (0 = primary):")
        self.monitor_label.grid(row=9, column=0, sticky="w", pady=4)
        self.monitor_var = tk.IntVar(value=int(self.config_data.get("monitor_index", 0)))
        self.monitor_spinbox = ttk.Spinbox(frame, from_=0, to=8, textvariable=self.monitor_var, width=6)
        self.monitor_spinbox.grid(row=9, column=1, sticky="w", pady=4)
        self.monitor_hint = ttk.Label(
            frame, text="Only used in Fullscreen game mode — try 1, 2...\nif it captures the wrong screen.",
            foreground="#888", font=("Segoe UI", 8),
        )
        self.monitor_hint.grid(row=10, column=0, columnspan=3, sticky="w")

        self._on_capture_mode_change()

    def _on_capture_mode_change(self):
        is_fullscreen = self.capture_mode_display.get() == "Fullscreen game"
        state = "normal" if is_fullscreen else "disabled"
        self.monitor_spinbox.config(state=state)

    def _all_gemini_presets(self):
        custom = self.config_data.get("gemini_custom_presets", [])
        return common.GEMINI_STYLE_PRESETS + custom

    def _refresh_gemini_presets(self):
        presets = self._all_gemini_presets()
        names = [p["name"] for p in presets]
        self.gemini_preset_combo.config(values=names)

        current_text = self.gemini_style_text.get("1.0", "end").strip()
        match = next((p["name"] for p in presets if p["prompt"].strip() == current_text), "")
        self.gemini_preset_var.set(match)

    def _on_gemini_preset_selected(self, _event):
        name = self.gemini_preset_var.get()
        preset = next((p for p in self._all_gemini_presets() if p["name"] == name), None)
        if preset:
            self.gemini_style_text.delete("1.0", "end")
            self.gemini_style_text.insert("1.0", preset["prompt"])

    def _add_gemini_preset(self):
        name = simpledialog.askstring("Save preset", "Name for this style loadout:", parent=self)
        if not name:
            return
        prompt = self.gemini_style_text.get("1.0", "end").strip()
        if not prompt:
            messagebox.showwarning("Save preset", "Style direction is empty — nothing to save.")
            return

        custom = list(self.config_data.get("gemini_custom_presets", []))
        custom = [p for p in custom if p["name"] != name]  # replace if same name reused
        custom.append({"name": name, "prompt": prompt})
        self.config_data["gemini_custom_presets"] = custom

        # Persisted immediately so it isn't lost if the window is
        # closed without clicking the main Save button.
        common.write_config(self._collect_config())
        self._refresh_gemini_presets()
        self.gemini_preset_var.set(name)
        self.status_label.config(text=f"Saved preset '{name}'.")

    def _delete_gemini_preset(self):
        name = self.gemini_preset_var.get()
        if not name:
            messagebox.showinfo("Delete preset", "Select a preset from the dropdown first.")
            return

        built_in_names = {p["name"] for p in common.GEMINI_STYLE_PRESETS}
        if name in built_in_names:
            messagebox.showwarning(
                "Delete preset", f"'{name}' is one of the built-in presets and can't be deleted."
            )
            return

        if not messagebox.askyesno("Delete preset", f"Delete the '{name}' preset? This can't be undone."):
            return

        custom = [p for p in self.config_data.get("gemini_custom_presets", []) if p["name"] != name]
        self.config_data["gemini_custom_presets"] = custom
        common.write_config(self._collect_config())

        self.gemini_preset_var.set("")
        self._refresh_gemini_presets()
        self.status_label.config(text=f"Deleted preset '{name}'.")

    # ---- Provider-specific ----

    def _add_password_field(self, parent, row, label, initial_value):
        """Entry with a masked value and a 'Show' checkbox next to it."""
        ttk.Label(parent, text=label).grid(row=row, column=0, sticky="w", pady=4)
        var = tk.StringVar(value=initial_value)
        entry = ttk.Entry(parent, textvariable=var, width=32, show="•")
        entry.grid(row=row, column=1, sticky="w", pady=4)

        show_var = tk.BooleanVar(value=False)
        def toggle():
            entry.config(show="" if show_var.get() else "•")
        ttk.Checkbutton(parent, text="Show", variable=show_var, command=toggle).grid(
            row=row, column=2, sticky="w", padx=(6, 0)
        )
        return var

    def _build_provider_sections(self):
        self.provider_frames = {}

        # Edge
        edge = ttk.LabelFrame(self, text="Edge TTS settings", padding=12)
        ttk.Label(edge, text="Voice:").grid(row=0, column=0, sticky="w", pady=4)
        self.edge_voice_var = tk.StringVar(value=self.config_data.get("edge_voice", "en-US-GuyNeural"))
        ttk.Combobox(
            edge, textvariable=self.edge_voice_var,
            values=common.EDGE_VOICE_SUGGESTIONS, width=28,
        ).grid(row=0, column=1, sticky="w", pady=4)
        ttk.Label(edge, text="Rate (e.g. +10%):").grid(row=1, column=0, sticky="w", pady=4)
        self.edge_rate_var = tk.StringVar(value=self.config_data.get("edge_rate", "+0%"))
        ttk.Entry(edge, textvariable=self.edge_rate_var, width=10).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(edge, text="Pitch (e.g. -5Hz):").grid(row=2, column=0, sticky="w", pady=4)
        self.edge_pitch_var = tk.StringVar(value=self.config_data.get("edge_pitch", "-5Hz"))
        ttk.Entry(edge, textvariable=self.edge_pitch_var, width=10).grid(row=2, column=1, sticky="w", pady=4)
        self.provider_frames["edge"] = edge

        # Gemini
        gemini = ttk.LabelFrame(self, text="Gemini TTS settings", padding=12)
        self.gemini_key_var = self._add_password_field(
            gemini, 0, "API key:", self.config_data.get("gemini_api_key", "")
        )
        ttk.Label(gemini, text="Voice:").grid(row=1, column=0, sticky="w", pady=4)
        self.gemini_voice_var = tk.StringVar(value=self.config_data.get("gemini_voice", "Kore"))
        ttk.Combobox(
            gemini, textvariable=self.gemini_voice_var,
            values=common.GEMINI_VOICES, state="readonly", width=20,
        ).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(gemini, text="Model:").grid(row=2, column=0, sticky="w", pady=4)
        self.gemini_model_var = tk.StringVar(value=self.config_data.get("gemini_model", common.GEMINI_MODELS[0]))
        ttk.Combobox(
            gemini, textvariable=self.gemini_model_var,
            values=common.GEMINI_MODELS, state="readonly", width=28,
        ).grid(row=2, column=1, sticky="w", pady=4)

        ttk.Label(gemini, text="Style preset:").grid(row=3, column=0, sticky="w", pady=4)
        self.gemini_preset_var = tk.StringVar()
        self.gemini_preset_combo = ttk.Combobox(
            gemini, textvariable=self.gemini_preset_var, state="readonly", width=26,
        )
        self.gemini_preset_combo.grid(row=3, column=1, sticky="w", pady=4)
        self.gemini_preset_combo.bind("<<ComboboxSelected>>", self._on_gemini_preset_selected)
        preset_btn_frame = ttk.Frame(gemini)
        preset_btn_frame.grid(row=3, column=2, sticky="w", padx=(6, 0))
        ttk.Button(preset_btn_frame, text="+ Save as new", command=self._add_gemini_preset).pack(side=tk.LEFT)
        ttk.Button(preset_btn_frame, text="Delete", command=self._delete_gemini_preset).pack(
            side=tk.LEFT, padx=(4, 0)
        )

        ttk.Label(gemini, text="Style direction:").grid(row=4, column=0, sticky="nw", pady=4)
        self.gemini_style_text = tk.Text(gemini, width=40, height=3, wrap="word")
        self.gemini_style_text.insert("1.0", self.config_data.get("gemini_style_prompt", common.DEFAULT_DM_STYLE_PROMPT))
        self.gemini_style_text.grid(row=4, column=1, sticky="w", pady=4)
        self.provider_frames["gemini"] = gemini
        self._refresh_gemini_presets()

        # ElevenLabs
        eleven = ttk.LabelFrame(self, text="ElevenLabs settings", padding=12)
        self.eleven_key_var = self._add_password_field(
            eleven, 0, "API key:", self.config_data.get("api_key", "")
        )
        ttk.Label(eleven, text="Voice ID:").grid(row=1, column=0, sticky="w", pady=4)
        self.eleven_voice_var = tk.StringVar(value=self.config_data.get("voice_id", ""))
        ttk.Entry(eleven, textvariable=self.eleven_voice_var, width=32).grid(row=1, column=1, sticky="w", pady=4)
        ttk.Label(eleven, text="Model:").grid(row=2, column=0, sticky="w", pady=4)
        self.eleven_model_var = tk.StringVar(value=self.config_data.get("model_id", common.ELEVENLABS_MODELS[0]))
        ttk.Combobox(
            eleven, textvariable=self.eleven_model_var,
            values=common.ELEVENLABS_MODELS, state="readonly", width=28,
        ).grid(row=2, column=1, sticky="w", pady=4)
        self.provider_frames["elevenlabs"] = eleven

        # Chatterbox
        chatterbox = ttk.LabelFrame(self, text="Chatterbox (local) settings", padding=12)
        note = ttk.Label(
            chatterbox,
            text="Requires run_chatterbox.bat to be running separately —\n"
                 "see install_chatterbox.bat if you haven't set it up yet.",
            foreground="#888", font=("Segoe UI", 8),
        )
        note.grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        ttk.Label(chatterbox, text="Exaggeration:").grid(row=1, column=0, sticky="w", pady=4)
        self.cb_exaggeration_var = tk.DoubleVar(value=float(self.config_data.get("chatterbox_exaggeration", 0.5)))
        ttk.Scale(chatterbox, from_=0.0, to=2.0, variable=self.cb_exaggeration_var, length=180).grid(
            row=1, column=1, sticky="w", pady=4
        )

        ttk.Label(chatterbox, text="CFG weight:").grid(row=2, column=0, sticky="w", pady=4)
        self.cb_cfg_var = tk.DoubleVar(value=float(self.config_data.get("chatterbox_cfg_weight", 0.5)))
        ttk.Scale(chatterbox, from_=0.0, to=1.0, variable=self.cb_cfg_var, length=180).grid(
            row=2, column=1, sticky="w", pady=4
        )

        ttk.Label(chatterbox, text="Temperature:").grid(row=3, column=0, sticky="w", pady=4)
        self.cb_temp_var = tk.DoubleVar(value=float(self.config_data.get("chatterbox_temperature", 0.8)))
        ttk.Scale(chatterbox, from_=0.1, to=1.5, variable=self.cb_temp_var, length=180).grid(
            row=3, column=1, sticky="w", pady=4
        )

        tuning_hint = ttk.Label(
            chatterbox,
            text="For a deliberate, dramatic DM feel: try exaggeration\n"
                 "~0.7 with CFG weight ~0.3 (higher exaggeration alone\n"
                 "speeds speech up — lowering CFG weight compensates).",
            foreground="#888", font=("Segoe UI", 8),
        )
        tuning_hint.grid(row=4, column=0, columnspan=3, sticky="w", pady=(2, 8))

        ttk.Label(chatterbox, text="Voice sample (optional):").grid(row=5, column=0, sticky="w", pady=4)
        self.cb_voice_sample_var = tk.StringVar(value=self.config_data.get("chatterbox_voice_sample", ""))
        ttk.Entry(chatterbox, textvariable=self.cb_voice_sample_var, width=28).grid(
            row=5, column=1, sticky="w", pady=4
        )
        ttk.Button(chatterbox, text="Browse...", command=self._browse_voice_sample).grid(
            row=5, column=2, sticky="w", padx=(6, 0)
        )
        clone_hint = ttk.Label(
            chatterbox,
            text="A short (~10-30s) clean .wav/.mp3 clip clones that\n"
                 "voice. Leave blank to use Chatterbox's default voice.",
            foreground="#888", font=("Segoe UI", 8),
        )
        clone_hint.grid(row=6, column=0, columnspan=3, sticky="w")

        self.provider_frames["chatterbox"] = chatterbox

    def _browse_voice_sample(self):
        path = filedialog.askopenfilename(
            title="Choose a voice sample",
            filetypes=[("Audio files", "*.wav *.mp3"), ("All files", "*.*")],
        )
        if path:
            self.cb_voice_sample_var.set(path)

    def _on_provider_change(self):
        for frame in self.provider_frames.values():
            frame.pack_forget()
        selected = self.provider_frames.get(self.provider_var.get())
        if selected:
            selected.pack(fill=tk.X, pady=(0, 12))

    # ---- Buttons ----

    def _build_buttons(self):
        button_row = ttk.Frame(self)
        button_row.pack(fill=tk.X, pady=(8, 0))

        ttk.Button(button_row, text="Test Voice", command=self._test_voice).pack(side=tk.LEFT)
        ttk.Button(button_row, text="Save", command=self._save).pack(side=tk.RIGHT)

        self.status_label = ttk.Label(self, text="", foreground="#2a7")
        self.status_label.pack(anchor="w", pady=(8, 0))

    def _collect_config(self):
        config = dict(self.config_data)
        config["tts_provider"] = self.provider_var.get()
        config["hotkey"] = self.hotkey_capture.get()
        config["exit_key"] = self.exit_capture.get()
        config["pause_key"] = self.pause_capture.get()
        # Volume now lives on the launcher's home screen, not here — read
        # the live value from disk rather than a stale snapshot from
        # when this window opened, so Settings never accidentally
        # reverts a volume change made there.
        if common.config_exists():
            config["volume"] = common.read_config().get("volume", config.get("volume", 1.0))
        config["speed"] = round(self.speed_var.get() / 100, 2)
        config["ocr_upscale"] = float(self.ocr_var.get())
        config["capture_mode"] = (
            "fullscreen_game" if self.capture_mode_display.get() == "Fullscreen game"
            else "desktop"
        )
        config["monitor_index"] = int(self.monitor_var.get())

        config["edge_voice"] = self.edge_voice_var.get()
        config["edge_rate"] = self.edge_rate_var.get()
        config["edge_pitch"] = self.edge_pitch_var.get()

        config["gemini_api_key"] = self.gemini_key_var.get()
        config["gemini_voice"] = self.gemini_voice_var.get()
        config["gemini_model"] = self.gemini_model_var.get()
        config["gemini_style_prompt"] = self.gemini_style_text.get("1.0", "end").strip()

        config["api_key"] = self.eleven_key_var.get()
        config["voice_id"] = self.eleven_voice_var.get()
        config["model_id"] = self.eleven_model_var.get()

        config["chatterbox_exaggeration"] = round(self.cb_exaggeration_var.get(), 2)
        config["chatterbox_cfg_weight"] = round(self.cb_cfg_var.get(), 2)
        config["chatterbox_temperature"] = round(self.cb_temp_var.get(), 2)
        config["chatterbox_voice_sample"] = self.cb_voice_sample_var.get()

        return config

    def _save(self):
        config = self._collect_config()
        common.write_config(config)
        self.config_data = config
        self.status_label.config(text="Saved — the reader will pick this up automatically.")

    def _test_voice(self):
        config = self._collect_config()
        self.status_label.config(text="Playing test line...")
        self.update_idletasks()

        def run():
            try:
                tts_engines.speak(SAMPLE_TEXT, config)
                self.status_label.config(text="Done.")
            except Exception as e:
                messagebox.showerror("Test Voice failed", str(e))
                self.status_label.config(text="")

        threading.Thread(target=run, daemon=True).start()


def main():
    if common.config_exists():
        config = common.read_config()
    else:
        config = dict(common.DEFAULT_CONFIG)

    root = tk.Tk()
    root.title("DM Reader — Settings")
    root.resizable(False, False)
    SettingsApp(root, config)
    root.mainloop()


if __name__ == "__main__":
    main()
