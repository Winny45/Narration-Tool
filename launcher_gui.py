"""
DM Reader — Launcher

A single control-panel window: Start/Stop the reader, open Settings,
and watch a live activity log — no console window, no juggling
multiple .bat files.

Runs the reader as a separate process (main.py, or DMReader.exe once
built) rather than importing it directly. This keeps the reader's own
screen-selection overlay window completely independent of this GUI's
window, which is both simpler and safer than trying to run two
Tkinter interfaces in one process.
"""

import os
import sys
import queue
import threading
import subprocess
import tkinter as tk
from tkinter import ttk

try:
    import sv_ttk
except ImportError:
    sv_ttk = None

import common
from settings_gui import SettingsApp


def find_reader_command():
    base = common.get_base_dir()

    exe_path = os.path.join(base, "DMReader.exe")
    if os.path.exists(exe_path):
        return [exe_path]

    # pythonw.exe (no console window) is preferred over python.exe —
    # otherwise Windows pops up a second terminal window every time
    # the reader is started, since python.exe always allocates one.
    venv_pythonw = os.path.join(base, "venv", "Scripts", "pythonw.exe")
    venv_python = os.path.join(base, "venv", "Scripts", "python.exe")
    if os.path.exists(venv_pythonw):
        python_exe = venv_pythonw
    elif os.path.exists(venv_python):
        python_exe = venv_python
    else:
        python_exe = sys.executable

    main_py = os.path.join(base, "main.py")
    return [python_exe, main_py]


MUTED = "#9a9ea6"
DANGER = "#e5534b"
SUCCESS = "#3fb950"
WARNING = "#d29922"


def apply_theme(root):
    """Applies a modern dark theme. Uses sv_ttk (Windows-11-style) if
    installed; falls back to a hand-styled dark 'clam' theme otherwise
    so the app still looks reasonable without the optional dependency.
    """
    if sv_ttk is not None:
        sv_ttk.set_theme("dark")
    else:
        style = ttk.Style(root)
        style.theme_use("clam")
        bg, bg_alt, fg, border, accent = "#1e1f24", "#2a2c33", "#e8e8ea", "#3a3d46", "#5b8cff"

        root.configure(bg=bg)
        style.configure(".", background=bg, foreground=fg, font=("Segoe UI", 10))
        style.configure("TFrame", background=bg)
        style.configure("TLabel", background=bg, foreground=fg)
        style.configure("TLabelframe", background=bg, foreground=fg, bordercolor=border)
        style.configure("TLabelframe.Label", background=bg, foreground=MUTED, font=("Segoe UI", 9, "bold"))
        style.configure("TButton", background=bg_alt, foreground=fg, bordercolor=border, padding=(12, 6))
        style.map("TButton", background=[("active", border), ("disabled", bg)])
        style.configure("Accent.TButton", background=accent, foreground="white", padding=(14, 7))
        style.map("Accent.TButton", background=[("active", "#4a76e0"), ("disabled", bg_alt)])
        style.configure("TEntry", fieldbackground=bg_alt, foreground=fg)
        style.configure("Horizontal.TScale", background=bg)

        # TNotebook (Settings' tab bar) isn't touched by the 'clam'
        # base theme either — it falls back to a light tan/khaki tab
        # bar with washed-out text that clashes hard against everything
        # else here and is barely legible on the selected tab.
        style.configure("TNotebook", background=bg, bordercolor=border)
        style.configure(
            "TNotebook.Tab", background=bg_alt, foreground=MUTED,
            padding=(14, 7), bordercolor=border,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", bg)],
            foreground=[("selected", fg)],
            expand=[("selected", (1, 1, 1, 0))],
        )

    # Regardless of which base theme just got applied above, force
    # higher-contrast colors specifically for combobox dropdowns —
    # both sv_ttk's dark theme and the plain 'clam' fallback render
    # "readonly" comboboxes (used throughout Settings) with dim,
    # low-contrast text by default.
    style = ttk.Style(root)
    combo_bg, combo_fg, combo_select = "#2a2c33", "#f4f4f6", "#5b8cff"
    style.configure(
        "TCombobox", fieldbackground=combo_bg, background=combo_bg,
        foreground=combo_fg, arrowcolor=combo_fg, insertcolor=combo_fg,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", combo_bg), ("disabled", "#242529")],
        foreground=[("readonly", combo_fg), ("disabled", MUTED)],
        selectbackground=[("readonly", combo_bg)],
        selectforeground=[("readonly", combo_fg)],
    )
    # The dropdown popup list itself (what appears when you click the
    # arrow) is a separate, non-ttk widget under the hood, styled via
    # the older option_add mechanism rather than ttk.Style.
    root.option_add("*TCombobox*Listbox.background", combo_bg)
    root.option_add("*TCombobox*Listbox.foreground", combo_fg)
    root.option_add("*TCombobox*Listbox.selectBackground", combo_select)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    root.option_add("*TCombobox*Listbox.font", ("Segoe UI", 10))

    # Spinbox (OCR upscale, Monitor index) isn't touched by either
    # sv_ttk or the 'clam' fallback above, so it falls back to the
    # platform default — a white field with barely-visible pale grey
    # text. Same fix as the combobox block above.
    style.configure(
        "TSpinbox", fieldbackground=combo_bg, background=combo_bg,
        foreground=combo_fg, arrowcolor=combo_fg, insertcolor=combo_fg,
    )
    style.map(
        "TSpinbox",
        fieldbackground=[("disabled", "#242529")],
        foreground=[("disabled", MUTED)],
    )


class LauncherApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=20)
        self.pack(fill=tk.BOTH, expand=True)

        self.process = None
        self.log_queue = queue.Queue()
        self._config_mtime = None

        self._build_ui()
        self._poll_log()
        self._poll_process()
        self._poll_config()

    def _build_ui(self):
        header = ttk.Frame(self)
        header.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(header, text="DM Reader", font=("Segoe UI", 20, "bold")).pack(anchor="w")
        ttk.Label(
            header, text="Reads on-screen game text aloud in an immersive voice",
            foreground=MUTED, font=("Segoe UI", 9),
        ).pack(anchor="w", pady=(2, 0))

        status_row = ttk.Frame(self)
        status_row.pack(fill=tk.X, pady=(14, 16))
        self.status_dot = ttk.Label(status_row, text="●", font=("Segoe UI", 12), foreground=DANGER)
        self.status_dot.pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="Stopped")
        ttk.Label(
            status_row, textvariable=self.status_var, font=("Segoe UI", 10, "bold"),
        ).pack(side=tk.LEFT, padx=(6, 0))
        self.engine_var = tk.StringVar(value="")
        ttk.Label(
            status_row, textvariable=self.engine_var, foreground=MUTED, font=("Segoe UI", 9),
        ).pack(side=tk.LEFT, padx=(10, 0))

        controls = ttk.LabelFrame(self, text="Controls", padding=14)
        controls.pack(fill=tk.X, pady=(0, 14))
        btn_row = ttk.Frame(controls)
        btn_row.pack(fill=tk.X)
        self.start_button = ttk.Button(
            btn_row, text="▶  Start Reader", command=self.start_reader, style="Accent.TButton"
        )
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(
            btn_row, text="■  Stop", command=self.stop_reader, state="disabled"
        )
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        self.pause_button = ttk.Button(
            btn_row, text="⏸  Pause", command=self.toggle_pause, state="disabled"
        )
        self.pause_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btn_row, text="⚙  Settings...", command=self.open_settings).pack(
            side=tk.LEFT, padx=(8, 0)
        )

        action_row = ttk.Frame(controls)
        action_row.pack(fill=tk.X, pady=(8, 0))
        self.capture_button = ttk.Button(
            action_row, text="▭  Capture", command=self.trigger_capture, state="disabled"
        )
        self.capture_button.pack(side=tk.LEFT)
        self.recapture_button = ttk.Button(
            action_row, text="↻  Recapture", command=self.trigger_recapture, state="disabled"
        )
        self.recapture_button.pack(side=tk.LEFT, padx=(8, 0))
        self.watch_button = ttk.Button(
            action_row, text="◎  Watch", command=self.trigger_watch, state="disabled"
        )
        self.watch_button.pack(side=tk.LEFT, padx=(8, 0))
        self.skip_button = ttk.Button(
            action_row, text="⏭  Skip", command=self.trigger_skip, state="disabled"
        )
        self.skip_button.pack(side=tk.LEFT, padx=(8, 0))

        quick = ttk.LabelFrame(self, text="Quick Settings", padding=14)
        quick.pack(fill=tk.X, pady=(0, 14))

        volume_row = ttk.Frame(quick)
        volume_row.pack(fill=tk.X)
        ttk.Label(volume_row, text="Volume", width=11).pack(side=tk.LEFT)
        self.volume_var = tk.DoubleVar(value=self._load_current_volume() * 100)
        ttk.Scale(
            volume_row, from_=0, to=100, variable=self.volume_var,
            length=260, command=self._on_volume_change,
        ).pack(side=tk.LEFT, padx=(8, 0))

        preset_row = ttk.Frame(quick)
        preset_row.pack(fill=tk.X, pady=(10, 0))
        ttk.Label(preset_row, text="Style preset", width=11).pack(side=tk.LEFT)
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(
            preset_row, textvariable=self.preset_var, state="readonly", width=28,
        )
        self.preset_combo.pack(side=tk.LEFT, padx=(8, 0))
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        ttk.Label(
            quick, text="Style preset applies when the narration engine is Gemini — manage the list in Settings.",
            foreground=MUTED, font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(8, 0))

        preview_row = ttk.Frame(quick)
        preview_row.pack(fill=tk.X, pady=(10, 0))
        self.preview_var = tk.BooleanVar(value=self._load_current_preview_enabled())
        ttk.Checkbutton(
            preview_row, text="Show text preview while narrating",
            variable=self.preview_var, command=self._on_preview_toggle,
        ).pack(side=tk.LEFT)
        ttk.Label(preview_row, text="Position", foreground=MUTED).pack(side=tk.LEFT, padx=(16, 6))
        self.preview_position_var = tk.StringVar()
        self.preview_position_combo = ttk.Combobox(
            preview_row, textvariable=self.preview_position_var,
            values=["Top", "Center", "Bottom", "Custom"], state="readonly", width=10,
        )
        self.preview_position_combo.pack(side=tk.LEFT)
        self.preview_position_combo.bind("<<ComboboxSelected>>", self._on_preview_position_change)
        ttk.Button(
            preview_row, text="Drag to position...", command=self._drag_to_position,
        ).pack(side=tk.LEFT, padx=(8, 0))

        self._refresh_preset_dropdown()

        log_section = ttk.LabelFrame(self, text="Activity Log", padding=(14, 10, 14, 14))
        log_section.pack(fill=tk.BOTH, expand=True)

        toolbar = ttk.Frame(log_section)
        toolbar.pack(fill=tk.X, pady=(0, 8))
        ttk.Button(toolbar, text="Clear", command=self._clear_log, width=8).pack(side=tk.RIGHT)

        log_frame = ttk.Frame(log_section)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(
            log_frame, width=76, height=18, state="disabled",
            bg="#111318", fg="#dcdcdc", insertbackground="#dcdcdc",
            wrap="word", relief="flat", font=("Consolas", 9),
            padx=10, pady=8,
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        self.log_text.tag_config("error", foreground=DANGER)
        self.log_text.tag_config("warning", foreground=WARNING)
        self.log_text.tag_config("success", foreground=SUCCESS)

    def _clear_log(self):
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.config(state="disabled")

    def _append_log(self, text):
        lowered = text.lower()
        if any(w in lowered for w in ("error", "failed", "exception", "traceback")):
            tag = "error"
        elif any(w in lowered for w in ("warning", "warn:")):
            tag = "warning"
        elif any(w in lowered for w in ("started", "ready", "done")):
            tag = "success"
        else:
            tag = None

        self.log_text.config(state="normal")
        if tag:
            self.log_text.insert("end", text, tag)
        else:
            self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def start_reader(self):
        if self.process is not None:
            return
        if not common.config_exists():
            self._append_log("No config.json found yet — click Settings first to pick an engine.\n")
            return

        cmd = find_reader_command()
        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            self.process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=common.get_base_dir(),
                creationflags=creationflags, startupinfo=startupinfo,
            )
        except Exception as e:
            self._append_log(f"Failed to start reader: {e}\n")
            self.process = None
            return

        self._append_log(f"Started ({' '.join(cmd)})\n")
        self.status_var.set("Running")
        self.status_dot.config(foreground=SUCCESS)
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.pause_button.config(state="normal", text="Pause")
        self.capture_button.config(state="normal")
        self.recapture_button.config(state="normal")
        self.watch_button.config(state="normal", text="◎  Watch", style="TButton")
        self.skip_button.config(state="normal")
        common.write_control({"paused": False})

        threading.Thread(target=self._read_process_output, daemon=True).start()

    def _read_process_output(self):
        proc = self.process
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            self.log_queue.put(line)
        self.log_queue.put("__PROCESS_ENDED__")

    def stop_reader(self):
        if self.process is None:
            return
        pid = self.process.pid
        try:
            if os.name == "nt":
                # Kills the whole process tree, not just the direct
                # child — a plain .terminate() can leave the reader
                # (and any audio it's mid-playback on) still running if
                # it ended up in a separate process group.
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                self.process.terminate()
        except Exception as e:
            self._append_log(f"Failed to stop reader cleanly: {e}\n")

    def _load_current_volume(self):
        if common.config_exists():
            try:
                return float(common.read_config().get("volume", 1.0))
            except (ValueError, OSError):
                pass
        return 1.0

    def _on_volume_change(self, value):
        if not common.config_exists():
            return
        config = common.read_config()
        config["volume"] = round(float(value) / 100, 2)
        common.write_config(config)

    def _load_current_preview_enabled(self):
        if common.config_exists():
            return bool(common.read_config().get("show_ocr_preview", True))
        return True

    def _on_preview_toggle(self):
        config = common.read_config() if common.config_exists() else dict(common.DEFAULT_CONFIG)
        config["show_ocr_preview"] = bool(self.preview_var.get())
        common.write_config(config)

    def _on_preview_position_change(self, _event):
        config = common.read_config() if common.config_exists() else dict(common.DEFAULT_CONFIG)
        config["ocr_preview_position"] = self.preview_position_var.get().lower()
        common.write_config(config)

    def _refresh_preview_controls(self):
        config = common.read_config() if common.config_exists() else dict(common.DEFAULT_CONFIG)
        self.preview_var.set(bool(config.get("show_ocr_preview", True)))
        self.preview_position_var.set(config.get("ocr_preview_position", "top").capitalize())

    def _drag_to_position(self):
        self._append_log("Drag a box on your screen to position the text preview — Esc to cancel.\n")
        result_queue = queue.Queue()

        def run():
            rect = common.select_screen_rect(
                "Click and drag to position the text preview box  •  Esc to cancel"
            )
            result_queue.put(rect)

        threading.Thread(target=run, daemon=True).start()
        self._poll_drag_result(result_queue)

    def _poll_drag_result(self, result_queue):
        try:
            rect = result_queue.get_nowait()
        except queue.Empty:
            self.after(100, lambda: self._poll_drag_result(result_queue))
            return

        if rect is None:
            self._append_log("Preview position unchanged.\n")
            return

        config = common.read_config() if common.config_exists() else dict(common.DEFAULT_CONFIG)
        config["ocr_preview_position"] = "custom"
        config["ocr_preview_custom_rect"] = list(rect)
        common.write_config(config)
        self.preview_position_var.set("Custom")
        self._append_log(f"Preview box set to {rect[2]}×{rect[3]} px at ({rect[0]}, {rect[1]}).\n")

    def _refresh_engine_label(self):
        if not common.config_exists():
            self.engine_var.set("")
            return
        provider = common.read_config().get("tts_provider", "edge")
        self.engine_var.set(f"Engine: {provider}")

    def _refresh_preset_dropdown(self):
        self._refresh_engine_label()
        self._refresh_preview_controls()
        if not common.config_exists():
            self.preset_combo.config(values=[p["name"] for p in common.GEMINI_STYLE_PRESETS])
            return
        config = common.read_config()
        presets = common.GEMINI_STYLE_PRESETS + config.get("gemini_custom_presets", [])
        names = [p["name"] for p in presets]
        self.preset_combo.config(values=names)

        current_prompt = config.get("gemini_style_prompt", "").strip()
        match = next((p["name"] for p in presets if p["prompt"].strip() == current_prompt), "")
        self.preset_var.set(match)

    def _on_preset_selected(self, _event):
        name = self.preset_var.get()
        if not common.config_exists():
            return
        config = common.read_config()
        presets = common.GEMINI_STYLE_PRESETS + config.get("gemini_custom_presets", [])
        preset = next((p for p in presets if p["name"] == name), None)
        if preset:
            config["gemini_style_prompt"] = preset["prompt"]
            common.write_config(config)

    def _poll_config(self):
        try:
            mtime = os.path.getmtime(common.CONFIG_PATH)
        except OSError:
            mtime = None
        if mtime != self._config_mtime:
            self._config_mtime = mtime
            self._refresh_preset_dropdown()
        self.after(1000, self._poll_config)

    def toggle_pause(self):
        control = common.read_control()
        paused = not control.get("paused", False)
        control["paused"] = paused
        common.write_control(control)
        if paused:
            self.pause_button.config(text="Resume")
            self.status_var.set("Paused")
            self.status_dot.config(foreground=WARNING)
        else:
            self.pause_button.config(text="Pause")
            self.status_var.set("Running")
            self.status_dot.config(foreground=SUCCESS)

    def trigger_capture(self):
        common.send_command("capture")

    def trigger_recapture(self):
        common.send_command("recapture")

    def trigger_watch(self):
        common.send_command("toggle_watch")
        # Optimistic local toggle, same as the Pause button above — the
        # reader process owns the real state; this just reflects the
        # click immediately rather than waiting on a round trip.
        turning_on = self.watch_button.cget("text") == "◎  Watch"
        if turning_on:
            self.watch_button.config(text="◎  Stop Watching", style="Accent.TButton")
        else:
            self.watch_button.config(text="◎  Watch", style="TButton")

    def trigger_skip(self):
        common.send_command("skip")

    def open_settings(self):
        top = tk.Toplevel(self)
        top.title("DM Reader — Settings")
        top.resizable(False, False)
        config = common.read_config() if common.config_exists() else dict(common.DEFAULT_CONFIG)
        SettingsApp(top, config)

    def _poll_log(self):
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line == "__PROCESS_ENDED__":
                    self.process = None
                    self.status_var.set("Stopped")
                    self.status_dot.config(foreground=DANGER)
                    self.start_button.config(state="normal")
                    self.stop_button.config(state="disabled")
                    self.pause_button.config(state="disabled", text="Pause")
                    self.capture_button.config(state="disabled")
                    self.recapture_button.config(state="disabled")
                    self.watch_button.config(state="disabled", text="◎  Watch", style="TButton")
                    self.skip_button.config(state="disabled")
                else:
                    self._append_log(line)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    def _poll_process(self):
        # Safety net in case the reader process exits without its
        # stdout pipe closing cleanly.
        if self.process is not None and self.process.poll() is not None:
            self.log_queue.put("__PROCESS_ENDED__")
        self.after(500, self._poll_process)


def main():
    root = tk.Tk()
    root.title("DM Reader")
    apply_theme(root)
    root.geometry("700x680")
    root.minsize(600, 560)
    app = LauncherApp(root)

    def on_close():
        app.stop_reader()
        root.after(200, root.destroy)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
