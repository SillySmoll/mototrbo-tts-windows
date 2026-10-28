# MotoTRBO TTS for Windows

A native Windows app that turns text into **MOTOTRBO CPS voice-announcement WAV files**, based on
[clifjones/mototrbo_tts](https://github.com/clifjones/mototrbo_tts).

The original needs Docker, VS Code Dev Containers, bash and ffmpeg. This version is a single
`MotoTRBO-TTS.exe` with a window: no Docker, no VS Code, no ffmpeg, no Python install.

It produces the same files the original does: Piper neural TTS, loudness-normalized to
-16 LUFS with peaks at or below -4 dBTP, 8 kHz mono G.711 mu-law WAV, with a warning if a file is over 320 kB.

## Using it

1. Run `MotoTRBO-TTS.exe`. Windows SmartScreen may warn because the app isn't code-signed; click
   **More info → Run anyway**.
2. **Voice:** pick a language and voice. Voices download automatically the first time you use them
   (about 20–110 MB each) and are kept in `%LOCALAPPDATA%\MotoTRBO TTS\voices`.
   ✓ marks voices already downloaded. *Sample voices online...* opens a page to hear them all.
   The default is `en_US-kathleen-low`, same as the original project.
3. **Announcements:** type a file name (no `.wav`) and the phrase, then press Enter or click **Add / Update**.
   Double-click any row, or click **▶ Preview**, to hear it exactly as the radio will (8 kHz).
   **Import .lst / Export .lst** read and write the original `phrases.lst` format (`filename=phrase`).
   Your list is saved automatically between sessions.
4. **Generate WAV files** writes them to the output folder (default `Documents\MotoTRBO Voice Announcements`).
5. **Copy to CPS folder** copies them into
   `C:\Program Files (x86)\Motorola\MOTOTRBO CPS\voiceannouncement`. That's a protected folder, so
   Windows asks for administrator permission. Change the path if your CPS is installed elsewhere.
6. Restart CPS, then continue as in the original guide: *Manage Voice Announcement* → send files to
   the radio → read the codeplug back → set announcement type to *Voice Announcement Files* → assign
   files to zones/channels.

**Speed** slows or quickens speech. **Speaker #** is enabled only for voices with multiple speakers.

### Command line (optional)

```
MotoTRBO-TTS.exe --generate --phrases phrases.lst --out C:\wav [--voice en_US-amy-medium] [--speed 1.1] [--log run.log]
```

## Getting the .exe

### Option A: let GitHub build it (no software needed on your PC)

1. Create a new GitHub repository and upload everything in this folder, including the hidden
   `.github` folder.
2. Open the repo's **Actions** tab. The *Build Windows app* workflow runs on its own; if it doesn't, click
   it and press **Run workflow**.
3. In about 5–8 minutes it builds the .exe, runs a self-test that synthesizes real announcements with
   a Piper voice and checks each WAV is 8 kHz mono mu-law, then opens the GUI to make sure it starts.
4. Open the finished run and download **MotoTRBO-TTS-windows** under *Artifacts*. You can also download
   **sample-wav-output** to try the self-test announcements in CPS.
5. Optional: push a tag such as `v1.0.0` and the .exe is attached to a GitHub Release.

### Option B: build on your own PC

Install 64-bit Python 3.10–3.13 from python.org with **Add python.exe to PATH** ticked, then
double-click `build.bat`. The result is `dist\MotoTRBO-TTS.exe`.

### Option C: run from source

```
py -m pip install -r requirements.txt
py app.py
```

## Troubleshooting

- **Voice list empty / download fails:** the app needs internet access to `huggingface.co` the first
  time you use each voice. After that it works offline.
- **App closes on start:** install the
  [Microsoft Visual C++ Redistributable (x64)](https://aka.ms/vs/17/release/vc_redist.x64.exe).
- **Errors** are written to `%LOCALAPPDATA%\MotoTRBO TTS\last_error.log`.
- **Antivirus quarantines the exe:** this is a common false positive with PyInstaller one-file apps.
  Building it yourself (Option A or B) and allow-listing it usually helps.

## Files

| File | Purpose |
|---|---|
| `app.py` | Windows GUI, command-line and self-test modes |
| `mototrbo_core.py` | Engine: voice download, Piper synthesis, EBU R128 loudness, 8 kHz resample, mu-law WAV writer (bit-identical to `ffmpeg -acodec pcm_mulaw`) |
| `build.bat` | Local build with PyInstaller |
| `.github/workflows/build-windows.yml` | Cloud build + self-test on Windows |
| `phrases.lst` | Example phrase list from the original project |

## License

GPL-3.0, the same as the original project and Piper.
