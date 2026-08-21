# DM Reader

Select any on-screen game text and have it read aloud in an immersive
voice. Works with fullscreen games, including true "exclusive
fullscreen" modes that make normal screenshot tools return a black image.

## What's in this folder

| File | Purpose |
|---|---|
| `launcher_gui.py` | **The one to use day-to-day** — Start/Stop, Settings, and a live log, all in one window. |
| `main.py` | The reader itself — hotkey, capture, OCR, narration. Runs on its own (or is launched by the launcher). |
| `settings_gui.py` | Settings window: engine, hotkeys, volume, voices. Also opens from inside the launcher. |
| `common.py` / `tts_engines.py` | Shared code used by the above. |
| `install.bat` | One-time setup: creates a venv, installs packages. |
| `run.bat` / `run_settings.bat` / `run_launcher.bat` | Launch the reader / settings window / launcher directly (without building an exe). |
| `build_exe.bat` | Packages everything into standalone `.exe` files. |

## Setup (Windows)

1. **Install Python**: https://www.python.org/downloads/ — tick
   **"Add python.exe to PATH"** during install.
2. **Double-click `install.bat`.**
3. **Install Tesseract-OCR** (does the text recognition):
   https://github.com/UB-Mannheim/tesseract/wiki — download the `.exe`
   installer (not the source code), keep the default install path.
4. **Double-click `run_launcher.bat`.** This opens the main window —
   click **Settings** to pick a narration engine and enter any needed
   API key, then **Start Reader**.

## Using the launcher

`run_launcher.bat` (or `DMReaderLauncher.exe` once built) opens one
window with:

- **Start Reader** / **Stop Reader** — runs the reader in the
  background; the activity log shows exactly what it's doing (same
  info that used to only appear in a console window). If Chatterbox
  is your selected engine, Start Reader also starts the Chatterbox
  server automatically if it isn't already running (look for
  `[Chatterbox]`-prefixed lines in the log) — no need to separately
  double-click `run_chatterbox.bat` first anymore. It stays running
  even after you click Stop Reader, so it doesn't have to reload the
  model every time; it only fully shuts down when you close the
  launcher window.
- **Pause** / **Resume** — pauses narration exactly where it is and
  picks back up from that same point when pressed again, rather than
  starting over. Works mid-sentence.
- **Volume** — the slider right below the buttons controls narration
  volume and applies immediately, whether or not the reader is
  currently running.
- **Style preset** — a dropdown of your saved Gemini style loadouts,
  right on the home screen, for quick switching without opening
  Settings. Managing the list itself (adding/deleting presets) still
  happens in Settings.
- **Settings...** — opens the same settings window as before, without
  leaving the launcher. Changes apply automatically, even while the
  reader is running — no restart needed.

There's also an in-game **Pause/Resume hotkey** (default F10, set in
Settings) that does the same thing without alt-tabbing to the launcher
— handy since F8/F9 already work this way.

The quit hotkey (F9) now also cuts off any narration that's currently
playing immediately, rather than waiting for it to finish first.

You can still use `run.bat` / `run_settings.bat` directly if you'd
rather skip the launcher and just see a plain console window.

## Changing settings later

Click **Settings...** inside the launcher window, or double-click
`run_settings.bat` (or `DMReaderSettings.exe`) directly. From there
you can:

- Switch between Edge / Gemini / ElevenLabs
- Change API keys and voices per engine — click **Show** next to a key
  field to verify what you pasted
- Rebind the capture and quit hotkeys by clicking "Set..." and pressing
  the new key
- Adjust volume and narration speed
- Choose capture mode: **Fullscreen game** vs **Screen / windowed apps**
  (see Multi-monitor section below)
- Hit **Test Voice** to preview your current settings immediately
- Click **Save**

The reader picks up saved changes automatically within a fraction of a
second — no restart needed, even for hotkey changes.

## Multi-monitor & capture modes

Two capture modes, switchable in Settings:

- **Fullscreen game** (default) — uses the Desktop Duplication method
  described below, which is what lets it see into true exclusive
  fullscreen. Because of how that API works, it's tied to *one specific
  monitor* at a time. If your game is on a second monitor, change
  **Monitor** in Settings from `0` (primary) to `1`, `2`, etc.
  Unfortunately there's no reliable way to auto-detect which number
  corresponds to which physical monitor on every system — if `1`
  captures the wrong screen, just try `2`, and so on; it's a small
  amount of trial and error the first time, then it's saved.
- **Screen / windowed apps** — uses a different, simpler capture method
  that works seamlessly across *all* your monitors at once (drag a
  selection box on any of them, no monitor number needed). This is the
  one to use for browser text, notes apps, windowed or borderless
  games, or anything that isn't running in true exclusive fullscreen.
  It won't see into exclusive-fullscreen games (same black-screen
  problem as the original tools this project replaced).

Practically: leave it on **Fullscreen game** for BG3 and most modern
titles (which default to borderless/flip-model anyway, so this mode
handles them fine). Switch to **Screen / windowed apps** if you want
to read text on a second monitor, in a browser, or in a windowed app.

## Narration speed

The Speed slider in Settings (0.5x–2.0x) works differently per engine
since each one exposes different controls:

- **Edge**: maps directly to its native rate parameter — full range,
  no quality loss.
- **ElevenLabs**: maps to their native speed setting, but their API
  only accepts 0.7x–1.2x — more extreme slider values get clamped to
  that range for this engine specifically.
- **Gemini**: has no numeric speed parameter at all — it's steered by
  natural language, so the slider adds a pacing instruction ("speak
  briskly" / "speak at a slow, deliberate pace") to the style prompt
  instead. Less precise than a real numeric control, but it does
  noticeably change the delivery.

## Building standalone .exe files

Once `install.bat` has been run at least once, double-click
**`build_exe.bat`**. It installs PyInstaller into your venv and
produces `DMReader.exe`, `DMReaderSettings.exe`, and
`DMReaderLauncher.exe` in this folder. `DMReaderLauncher.exe` is the
one worth pinning to your taskbar/desktop — it's the same all-in-one
window, just without needing Python or a terminal at all.

Keep `config.json` next to the `.exe` files; that's where they read and
write settings. Tesseract-OCR still needs to be installed separately
(same as before) — it isn't bundled into the exe.

If the build fails with a missing-module error (this can happen with
`bettercam`'s Windows COM bindings), rebuild with:
```
venv\Scripts\pyinstaller --onefile --console --name DMReader --collect-all bettercam --collect-all comtypes main.py
```

## Narration engines

| Engine | Cost | Setup | Expressiveness |
|---|---|---|---|
| **Edge TTS** (default) | Free, unlimited | None | Clear, minimal "acting" |
| **Gemini TTS** | Free tier, rate-limited | Free Google AI Studio key | Genuinely dramatic, directable |
| **ElevenLabs** | ~10 min/month free | Account + API key | Best raw quality |
| **Chatterbox (local)** | $0 forever, no quota | Separate Python 3.11 setup, see below | Numeric emotion dial + real voice cloning |

For the actual "immersive dungeon master" effect, **Gemini** is the
one to pick — it takes natural-language direction rather than reading
flatly. A DM-style direction is already set as the default
`gemini_style_prompt`; edit it in Settings to change the performance.

### Getting a Gemini key
Free at **aistudio.google.com/apikey**, no card needed. Good narrator
voices to try: `Algenib` (gravelly), `Charon` (informative/measured),
`Gacrux` (mature), `Orus`/`Alnilam` (firm). Preview any voice first in
AI Studio → Speech and Music before picking one in Settings.

**Style presets:** Settings includes five built-in "loadouts" for the
style direction — Dungeon Master, Grim Narrator, Whimsical
Storyteller, Battle Herald, and Calm Narrator. Pick one from the
dropdown to load it into the text box, tweak the wording if you like,
then click **+ Save as new** to add your own custom loadout to the
list (saved permanently, survives updates to the app). **Delete**
removes a custom preset you added — the five built-in ones can't be
deleted. The same dropdown also appears on the launcher's home screen
for quick switching mid-session.

### Getting an ElevenLabs key
1. Sign up at elevenlabs.io.
2. Profile → API Keys → Create Key, with **Text to Speech set to
   Access** (and Voices to at least Read).
3. Voices → My Voices, or Create Voice → Voice Design to generate one
   from a text description (works on the free plan — Voice Library
   voices do not work with a free-tier key).
4. Copy the Voice ID into Settings.

### Setting up Chatterbox (local, free, unlimited)

Chatterbox is an open-source TTS model that runs entirely on your own
PC — no account, no API key, no daily limit, ever. The tradeoff: it
needs its **own Python 3.11 environment**, separate from DM Reader's
main one (Chatterbox doesn't support newer Python versions yet), and
it runs as a small local server that has to be started before you use
it. It also isn't natural-language directable like Gemini — instead it
has two numeric dials (exaggeration, CFG weight) and, as a real
alternative, the ability to **clone any voice** from a short audio clip.

1. Double-click **`install_chatterbox.bat`**. If you don't have Python
   3.11, it'll tell you and link the installer — grab it, then run
   this again. This step downloads ~1-2GB of packages.
2. Double-click **`run_chatterbox.bat`** and leave that window open.
   The first time, it downloads the model itself (another 1-2GB) —
   wait for "Chatterbox is ready" before continuing.
3. In DM Reader Settings, switch the engine to **Chatterbox (local)**.
4. *(Optional)* For voice cloning: find a clean 10-30 second audio
   clip of a voice you like (a narrator reading, a character voice,
   anything without background noise), and set it as the **Voice
   sample** in Settings. Leave it blank to use Chatterbox's built-in
   default voice.
5. For a deliberate, dramatic delivery, try **exaggeration ≈ 0.7** with
   **CFG weight ≈ 0.3** — higher exaggeration alone tends to speed
   speech up, and lowering CFG weight compensates with slower, more
   weighted pacing.

Every time you want to use Chatterbox, `run_chatterbox.bat` needs to
already be running in the background (it can just sit there
minimized) — DM Reader talks to it over `localhost`, so if that
window isn't open, you'll get a "server isn't reachable" error.

Without a GPU, generation is noticeably slower than the cloud engines
— seconds rather than the near-instant response of Edge/Gemini/
ElevenLabs. With an NVIDIA GPU it's much faster.

## Speed

A few things were done to keep the wait after pressing the hotkey as
short as possible:

- **Gemini** now streams audio and starts playing each chunk as it
  arrives, rather than waiting for the whole clip to finish generating
  first. This only produces a real speed-up on `gemini-3.1-flash-tts-preview`
  (the new default) — it's currently the only Gemini TTS model that
  actually sends audio in pieces; older models accept the same
  streaming call but still send one complete chunk at the end, so
  they won't feel any faster. If the 3.1 preview model errors or isn't
  available on your account yet, switch to `gemini-2.5-flash-preview-tts`
  in Settings — you'll lose the streaming speed-up but everything else
  still works.
- **ElevenLabs** streams audio as it's generated instead of waiting for
  the whole clip server-side, and defaults to the `eleven_flash_v2_5`
  model, which trades a little quality for meaningfully lower latency.
- Network connections and API clients are reused across requests instead
  of reconnecting each time.

The remaining time is mostly OCR (Tesseract reading the screenshot) and
the provider's own generation time. If OCR feels slow, try lowering
`ocr_upscale` in Settings (2.0 is the default; 1.0 is faster but may
miss small text).

## Using it

1. Play your game as normal.
2. Press your capture hotkey (default **F8**).
3. Click and drag a box around the text you want read.
4. Wait a couple of seconds — narration plays automatically.
5. Press your quit hotkey (default **F9**) any time.

## Why this works with fullscreen games

Normal screenshot tools (`ImageGrab`, `pyautogui`, etc.) use an old
Windows API called BitBlt, which can't see into a true DirectX/Vulkan
**exclusive fullscreen** surface — you get a black image back. This
tool captures using the **Desktop Duplication API** instead (via the
`bettercam` library), the same approach OBS uses for "Display Capture."

A handful of older or anti-cheat-protected titles running in true
exclusive fullscreen can briefly flicker when the selection overlay
appears on top of them — a Windows/DWM behavior, not something any
capture tool can fully route around. Switching the game to
"Borderless"/"Fullscreen Window" avoids it entirely, and most modern
engines default to that mode anyway.

## Troubleshooting

| Symptom | Fix |
|---|---|
| "Tesseract not found" warning | Reinstall Tesseract to the default path. |
| OCR text is garbled | Raise `ocr_upscale` in Settings; select a tighter box. |
| Hotkey doesn't trigger in-game | Some anti-cheat blocks global keyboard hooks — try a different key, or run as Administrator. |
| `No module named 'cv2'` | Run `venv\Scripts\pip install opencv-python`. |
| Gemini "rate limited" error | Free tier has a requests-per-minute cap — wait a few seconds between captures. |
| Gemini "no audio returned" error | The 3.1 preview model occasionally returns text instead of audio — just try again, or switch models in Settings if it keeps happening. |
| ElevenLabs error in console | Invalid key/Voice ID, missing Text-to-Speech permission, a Voice Library voice on a free key, or quota reached. |
| Capture still comes back black | Confirm the game isn't in true exclusive fullscreen — switch to Borderless/Fullscreen Window. |
| Settings changes don't seem to apply | Make sure you clicked **Save** in the settings window, not just Test Voice. |
| A second terminal window pops up on Start Reader | Make sure you copied the latest `launcher_gui.py` — it now launches via `pythonw.exe` (no console window) instead of `python.exe`. |
| Stop Reader doesn't cut off narration immediately | Latest version kills the whole process tree (`taskkill /T /F`) rather than just the main process — if you're still on an older `launcher_gui.py`, update it. |
| Chatterbox "server isn't reachable" error | `run_chatterbox.bat` isn't running, or hasn't finished loading the model yet — wait for "Chatterbox is ready" in that window. |
| `install_chatterbox.bat` can't find Python 3.11 | Install it from the link the script prints, then run the script again — it uses the `py -3.11` launcher, which works even without adding it to PATH. |
