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

import requests

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


def find_chatterbox_command():
    """Returns (command_list, working_dir), or None if the separate
    Chatterbox environment hasn't been set up yet (install_chatterbox.bat
    not run)."""
    base = common.get_base_dir()
    cb_dir = os.path.join(base, "chatterbox_server")
    server_py = os.path.join(cb_dir, "server.py")
    if not os.path.exists(server_py):
        return None

    venv_pythonw = os.path.join(cb_dir, "venv", "Scripts", "pythonw.exe")
    venv_python = os.path.join(cb_dir, "venv", "Scripts", "python.exe")
    if os.path.exists(venv_pythonw):
        python_exe = venv_pythonw
    elif os.path.exists(venv_python):
        python_exe = venv_python
    else:
        return None

    return [python_exe, server_py], cb_dir


class LauncherApp(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=16)
        self.pack(fill=tk.BOTH, expand=True)

        self.process = None
        self.chatterbox_process = None
        self.log_queue = queue.Queue()
        self._config_mtime = None

        self._build_ui()
        self._poll_log()
        self._poll_process()
        self._poll_config()

    def _build_ui(self):
        ttk.Label(self, text="DM Reader", font=("Segoe UI", 16, "bold")).pack(anchor="w")

        status_row = ttk.Frame(self)
        status_row.pack(fill=tk.X, pady=(4, 12))
        ttk.Label(status_row, text="Status:").pack(side=tk.LEFT)
        self.status_var = tk.StringVar(value="Stopped")
        self.status_label = ttk.Label(status_row, textvariable=self.status_var, foreground="#c33")
        self.status_label.pack(side=tk.LEFT, padx=(4, 0))

        btn_row = ttk.Frame(self)
        btn_row.pack(fill=tk.X, pady=(0, 12))
        self.start_button = ttk.Button(btn_row, text="Start Reader", command=self.start_reader)
        self.start_button.pack(side=tk.LEFT)
        self.stop_button = ttk.Button(btn_row, text="Stop Reader", command=self.stop_reader, state="disabled")
        self.stop_button.pack(side=tk.LEFT, padx=(8, 0))
        self.pause_button = ttk.Button(btn_row, text="Pause", command=self.toggle_pause, state="disabled")
        self.pause_button.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(btn_row, text="Settings...", command=self.open_settings).pack(side=tk.LEFT, padx=(8, 0))

        volume_row = ttk.Frame(self)
        volume_row.pack(fill=tk.X, pady=(0, 12))
        ttk.Label(volume_row, text="Volume:").pack(side=tk.LEFT)
        self.volume_var = tk.DoubleVar(value=self._load_current_volume() * 100)
        volume_scale = ttk.Scale(
            volume_row, from_=0, to=100, variable=self.volume_var,
            length=220, command=self._on_volume_change,
        )
        volume_scale.pack(side=tk.LEFT, padx=(8, 0))

        preset_row = ttk.Frame(self)
        preset_row.pack(fill=tk.X, pady=(0, 4))
        ttk.Label(preset_row, text="Style preset:").pack(side=tk.LEFT)
        self.preset_var = tk.StringVar()
        self.preset_combo = ttk.Combobox(preset_row, textvariable=self.preset_var, state="readonly", width=26)
        self.preset_combo.pack(side=tk.LEFT, padx=(8, 0))
        self.preset_combo.bind("<<ComboboxSelected>>", self._on_preset_selected)
        ttk.Label(
            self, text="(used when narration engine is Gemini — manage the list in Settings)",
            foreground="#888", font=("Segoe UI", 8),
        ).pack(anchor="w", pady=(0, 12))
        self._refresh_preset_dropdown()

        ttk.Label(self, text="Activity log:").pack(anchor="w")
        log_frame = ttk.Frame(self)
        log_frame.pack(fill=tk.BOTH, expand=True)
        self.log_text = tk.Text(
            log_frame, width=76, height=20, state="disabled",
            bg="#111318", fg="#dcdcdc", wrap="word", relief="flat",
        )
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

    def _append_log(self, text):
        self.log_text.config(state="normal")
        self.log_text.insert("end", text)
        self.log_text.see("end")
        self.log_text.config(state="disabled")

    def start_reader(self):
        if self.process is not None:
            return
        if not common.config_exists():
            self._append_log("No config.json found yet — click Settings first to pick an engine.\n")
            return

        config = common.read_config()
        self.ensure_chatterbox_running(config)

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
        self.status_label.config(foreground="#2a7")
        self.start_button.config(state="disabled")
        self.stop_button.config(state="normal")
        self.pause_button.config(state="normal", text="Pause")
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

    def _refresh_preset_dropdown(self):
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

    def is_chatterbox_running(self, port=8765):
        try:
            r = requests.get(f"http://127.0.0.1:{port}/health", timeout=1)
            return r.status_code == 200
        except Exception:
            return False

    def ensure_chatterbox_running(self, config):
        if config.get("tts_provider") != "chatterbox":
            return

        port = config.get("chatterbox_port", 8765)
        if self.is_chatterbox_running(port):
            self._append_log("Chatterbox server already running.\n")
            return
        if self.chatterbox_process is not None and self.chatterbox_process.poll() is None:
            self._append_log("Chatterbox server is already starting...\n")
            return

        result = find_chatterbox_command()
        if result is None:
            self._append_log(
                "Chatterbox isn't set up yet — run install_chatterbox.bat first.\n"
            )
            return
        cmd, cwd = result

        creationflags = 0
        startupinfo = None
        if os.name == "nt":
            creationflags = subprocess.CREATE_NO_WINDOW
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW

        try:
            self.chatterbox_process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, cwd=cwd,
                creationflags=creationflags, startupinfo=startupinfo,
            )
        except Exception as e:
            self._append_log(f"Failed to start Chatterbox server: {e}\n")
            return

        self._append_log(
            "Starting Chatterbox server in the background — first-time "
            "model load can take a minute or two. Look for 'Chatterbox "
            "is ready' below once it's up.\n"
        )
        threading.Thread(target=self._read_chatterbox_output, daemon=True).start()

    def _read_chatterbox_output(self):
        proc = self.chatterbox_process
        if proc is None or proc.stdout is None:
            return
        for line in proc.stdout:
            self.log_queue.put(f"[Chatterbox] {line}")

    def stop_chatterbox(self):
        if self.chatterbox_process is None:
            return
        pid = self.chatterbox_process.pid
        try:
            if os.name == "nt":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    creationflags=subprocess.CREATE_NO_WINDOW,
                )
            else:
                self.chatterbox_process.terminate()
        except Exception:
            pass
        self.chatterbox_process = None

    def toggle_pause(self):
        control = common.read_control()
        paused = not control.get("paused", False)
        control["paused"] = paused
        common.write_control(control)
        self.pause_button.config(text="Resume" if paused else "Pause")

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
                    self.status_label.config(foreground="#c33")
                    self.start_button.config(state="normal")
                    self.stop_button.config(state="disabled")
                    self.pause_button.config(state="disabled", text="Pause")
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
    root.geometry("620x560")
    app = LauncherApp(root)

    def on_close():
        app.stop_reader()
        app.stop_chatterbox()
        root.after(200, root.destroy)

    root.protocol("WM_DELETE_WINDOW", on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
