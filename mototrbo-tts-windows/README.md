# MotoTRBO TTS for Windows

A Windows app that turns text into **MOTOTRBO CPS voice-announcement WAV files**, based on
[clifjones/mototrbo_tts](https://github.com/clifjones/mototrbo_tts).

The original needs Docker, VS Code Dev Containers, bash and ffmpeg. This version is a normal Windows
installer. **Every English Piper voice (US and UK) is built in**, so you can switch voices instantly
and work fully offline.

It produces the same files the original does: Piper neural TTS, loudness-normalized to
-16 LUFS with peaks at or below -4 dBTP, 8 kHz mono G.711 mu-law WAV, with a warning if a file is over 320 kB.

## Installing

1. Open the repo's **Releases** page (right-hand side of the repo's main page) and pick the newest one.
2. Download **every file** listed under *Assets*: `MotoTRBO-TTS-Setup.exe` plus all the
   `MotoTRBO-TTS-Setup-1.bin`, `-2.bin`, ... files. Put them **in the same folder**.
   The voices make the installer several GB, so it's split into parts under GitHub's 2 GB file limit.
3. Run `MotoTRBO-TTS-Setup.exe`. Windows SmartScreen may warn because the app isn't code-signed; click
   **More info → Run anyway**. Setup unpacks the voices into `C:\Program Files\MotoTRBO TTS\voices`.

## Using it

1. **Voice:** pick a language and voice. Built-in voices show ✓ and say "built in".
   Only English is listed by default; tick **Show other languages** to see the rest. Those download
   once on first use into `%LOCALAPPDATA%\MotoTRBO TTS\voices` and are kept there.
   *Sample voices online...* opens a page to hear them all.
2. **Announcements:** type a file name (no `.wav`) and the phrase, then press Enter or click **Add / Update**.
   Double-click any row, or click **▶ Preview**, to hear it exactly as the radio will (8 kHz).
   **Import .lst / Export .lst** read and write the original `phrases.lst` format (`filename=phrase`).
   Your list is saved automatically between sessions.
3. **Generate WAV files** writes them to the output folder (default `Documents\MotoTRBO Voice Announcements`).
4. **Copy to CPS folder** copies them into
   `C:\Program Files (x86)\Motorola\MOTOTRBO CPS\voiceannouncement`. Windows asks for administrator
   permission. Change the path if your CPS is installed elsewhere.
5. Restart CPS, then continue as in the original guide: *Manage Voice Announcement* → send files to
   the radio → read the codeplug back → set announcement type to *Voice Announcement Files* → assign
   files to zones/channels.

**Speed** slows or quickens speech. **Speaker #** is enabled only for voices with multiple speakers.

### Command line (optional)

```
MotoTRBO-TTS.exe --generate --phrases phrases.lst --out C:\wav [--voice en_US-amy-medium] [--speed 1.1] [--log run.log]
```

## Building the installer

### On GitHub (no software needed on your PC)

1. Put all the files from this folder in a GitHub repository.
   **The web uploader skips the `.github` folder**, so add the build file separately:
   *Add file → Create new file*, name it exactly `.github/workflows/build-windows.yml`,
   paste in the contents of that file from this folder, and commit.
2. The **Actions** tab shows *Build Windows installer* running. If it doesn't start, click it and
   press **Run workflow**.
3. The first build takes roughly 30–60 minutes, mostly downloading and compressing the voices.
   Later builds reuse the downloaded voices. The workflow:
   - builds the app and downloads every English voice, checking each file's MD5 checksum;
   - generates sample announcements and makes **every built-in voice speak** a test phrase;
   - opens the window to make sure it starts;
   - builds the installer, installs it silently and runs the installed copy;
   - publishes the installer files as a new **Release**.
4. Each new commit to `main` publishes a new release (`build-N`). Push a tag like `v1.1.0` for a
   named release.

To bundle fewer voices, change `VOICE_MATCH` at the top of the workflow and change `VOICE_MATCH_ID`
with it. For example, `"^en_US-(amy|kathleen|ryan)-"` bundles just those three voices.

### On your own PC

Install 64-bit Python 3.10–3.13 from python.org with **Add python.exe to PATH** ticked, and
[Inno Setup 6](https://jrsoftware.org/isdl.php). Then double-click `build.bat`. You need about 15 GB
free. The installer files end up in `installer-output`.

### Run from source

```
py -m pip install -r requirements.txt
py fetch_voices.py        (optional: puts English voices in .\voices)
py app.py
```

## Troubleshooting

- **"Disk 2 not found" / setup asks for a file:** a `.bin` part is missing or in another folder.
- **App closes on start:** install the
  [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe).
- **Errors** are written to `%LOCALAPPDATA%\MotoTRBO TTS\last_error.log`.
- **Antivirus quarantines the app:** a common false positive with PyInstaller apps. Building it
  yourself and allow-listing it usually helps.

## Files

| File | Purpose |
|---|---|
| `app.py` | Windows GUI, command-line and test modes |
| `mototrbo_core.py` | Engine: built-in/downloaded voices, Piper synthesis, EBU R128 loudness, 8 kHz resample, mu-law WAV writer (bit-identical to `ffmpeg -acodec pcm_mulaw`) |
| `fetch_voices.py` | Build-time download of the voices to bundle, with MD5 checks and resume |
| `installer.iss` | Inno Setup installer script (LZMA2 compression, split into parts under 2 GB) |
| `build.bat` | Local build |
| `.github/workflows/build-windows.yml` | Cloud build, tests and Release publishing |
| `phrases.lst` | Example phrase list from the original project |

## License

GPL-3.0, the same as the original project and Piper.
