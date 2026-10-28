"""
MotoTRBO TTS for Windows
Build MOTOTRBO CPS voice-announcement WAV files from text with Piper TTS.

GUI:      MotoTRBO-TTS.exe
Headless: MotoTRBO-TTS.exe --generate --phrases phrases.lst --out C:\\out [--voice en_US-kathleen-low] [--speed 1.0]
Selftest: MotoTRBO-TTS.exe --selftest C:\\some\\folder     (used by the Windows build pipeline)
"""

from __future__ import annotations

import argparse
import os
import queue
import shutil
import subprocess
import sys
import tempfile
import threading
import traceback
from pathlib import Path

# A windowed (no console) exe has no stdout/stderr; give libraries somewhere to write.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w")

import mototrbo_core as core

APP_TITLE = "MotoTRBO TTS - Voice Announcement Builder"
APP_VERSION = "1.0.0"
IS_WINDOWS = sys.platform == "win32"


# ==========================================================================
# Headless modes
# ==========================================================================

def run_headless(args) -> int:
    log_lines: list[str] = []

    def log(msg: str):
        log_lines.append(msg)
        try:
            print(msg, flush=True)
        except Exception:
            pass

    rc = 0
    out_dir = Path(args.selftest or args.out or core.default_output_dir())
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.selftest:
            phrases = core.SAMPLE_PHRASES
        else:
            phrases = core.parse_phrases(Path(args.phrases).read_text(encoding="utf-8-sig"))
        voice = args.voice or core.DEFAULT_VOICE
        log(f"{APP_TITLE} {APP_VERSION}")
        log(f"Voice: {voice}")
        model = core.local_model_path(voice)
        if not core.is_voice_installed(voice):
            info = None
            try:
                info = next((v for v in core.load_voice_catalog() if v.key == voice), None)
            except Exception as e:
                log(f"(voice list unavailable: {e}; guessing download path)")
            log("Downloading voice model...")
            model = core.download_voice(info or voice)
        written = core.generate_all(phrases, model, out_dir, speed=args.speed, log=log)
        if args.selftest:
            if len(written) != len(phrases):
                raise RuntimeError(f"expected {len(phrases)} files, got {len(written)}")
            for f in written:
                info = core.inspect_wav(f)
                ok = (info.get("format_tag") == 7 and info.get("rate") == 8000
                      and info.get("channels") == 1 and info.get("bits") == 8
                      and info.get("frames", 0) > 2000 and info["size"] <= core.MAX_FILE_BYTES)
                log(f"check {f.name}: {info} -> {'OK' if ok else 'FAIL'}")
                if not ok:
                    rc = 1
            log("SELFTEST PASSED" if rc == 0 else "SELFTEST FAILED")
        else:
            log(f"Done: {len(written)} file(s) in {out_dir}")
    except Exception:
        log(traceback.format_exc())
        log("SELFTEST FAILED" if args.selftest else "FAILED")
        rc = 1
    log_path = Path(args.log) if args.log else (out_dir / "selftest.log" if args.selftest else None)
    if log_path:
        log_path.write_text("\n".join(log_lines) + "\n", encoding="utf-8")
    return rc


# ==========================================================================
# GUI
# ==========================================================================

def run_gui(smoke_log: str | None = None) -> int:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    from tkinter.scrolledtext import ScrolledText

    if IS_WINDOWS:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("MotoTRBO.TTS")
        except Exception:
            pass

    class App(tk.Tk):
        def __init__(self):
            super().__init__()
            self.title(APP_TITLE)
            self.minsize(820, 640)
            try:
                ico = core.resource_path("icon.ico")
                if ico.exists():
                    self.iconbitmap(default=str(ico))
            except Exception:
                pass

            self.settings = core.load_settings()
            self.msgs: queue.Queue = queue.Queue()
            self.busy = False
            self.cancel_evt = threading.Event()
            self.catalog: list[core.VoiceInfo] = []
            self.by_lang: dict[str, list[core.VoiceInfo]] = {}

            self.lang_var = tk.StringVar()
            self.voice_var = tk.StringVar()
            self.voice_status = tk.StringVar()
            self.speed_var = tk.DoubleVar(value=float(self.settings.get("speed", 1.0)))
            self.speaker_var = tk.IntVar(value=int(self.settings.get("speaker", 0)))
            self.name_var = tk.StringVar()
            self.text_var = tk.StringVar()
            self.out_var = tk.StringVar(value=self.settings.get("output_dir", str(core.default_output_dir())))
            self.cps_var = tk.StringVar(value=self.settings.get("cps_dir", core.DEFAULT_CPS_DIR))
            self.copy_after_var = tk.BooleanVar(value=bool(self.settings.get("copy_after", False)))

            self._build()
            self._load_phrases()
            self._load_catalog(refresh=False)
            self.protocol("WM_DELETE_WINDOW", self._on_close)
            self.after(100, self._pump)

        # ---------------- layout ----------------
        def _build(self):
            style = ttk.Style(self)
            style.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
            style.configure("Hint.TLabel", foreground="#666")
            pad = dict(padx=8, pady=4)

            outer = ttk.Frame(self, padding=10)
            outer.pack(fill="both", expand=True)
            outer.columnconfigure(0, weight=1)
            outer.rowconfigure(1, weight=1)

            # ---- Voice ----
            vf = ttk.LabelFrame(outer, text=" 1. Voice ", padding=8)
            vf.grid(row=0, column=0, sticky="ew")
            vf.columnconfigure(1, weight=1)
            vf.columnconfigure(3, weight=2)
            ttk.Label(vf, text="Language").grid(row=0, column=0, sticky="w")
            self.lang_cb = ttk.Combobox(vf, textvariable=self.lang_var, state="readonly", width=28)
            self.lang_cb.grid(row=0, column=1, sticky="ew", **pad)
            self.lang_cb.bind("<<ComboboxSelected>>", lambda e: self._on_lang())
            ttk.Label(vf, text="Voice").grid(row=0, column=2, sticky="w")
            self.voice_cb = ttk.Combobox(vf, textvariable=self.voice_var, state="readonly", width=36)
            self.voice_cb.grid(row=0, column=3, sticky="ew", **pad)
            self.voice_cb.bind("<<ComboboxSelected>>", lambda e: self._on_voice())
            ttk.Button(vf, text="Refresh list", command=lambda: self._load_catalog(True)).grid(row=0, column=4, **pad)

            ttk.Label(vf, textvariable=self.voice_status, style="Hint.TLabel").grid(
                row=1, column=1, columnspan=3, sticky="w", padx=8)
            sf = ttk.Frame(vf)
            sf.grid(row=2, column=0, columnspan=5, sticky="w", pady=(4, 0))
            ttk.Label(sf, text="Speed").pack(side="left")
            ttk.Scale(sf, from_=0.6, to=1.6, variable=self.speed_var, length=180,
                      command=lambda v: self.speed_lbl.config(text=f"{float(v):.2f}x")).pack(side="left", padx=6)
            self.speed_lbl = ttk.Label(sf, text=f"{self.speed_var.get():.2f}x", width=6)
            self.speed_lbl.pack(side="left")
            ttk.Button(sf, text="Reset", width=6, command=self._reset_speed).pack(side="left", padx=(0, 18))
            ttk.Label(sf, text="Speaker #").pack(side="left")
            self.speaker_sb = ttk.Spinbox(sf, from_=0, to=0, textvariable=self.speaker_var, width=5)
            self.speaker_sb.pack(side="left", padx=6)
            ttk.Button(sf, text="Sample voices online...", command=self._open_samples).pack(side="left", padx=18)

            # ---- Phrases ----
            pf = ttk.LabelFrame(outer, text=" 2. Announcements (file name = phrase) ", padding=8)
            pf.grid(row=1, column=0, sticky="nsew", pady=8)
            pf.columnconfigure(0, weight=1)
            pf.rowconfigure(0, weight=1)

            tree_box = ttk.Frame(pf)
            tree_box.grid(row=0, column=0, columnspan=2, sticky="nsew")
            tree_box.columnconfigure(0, weight=1)
            tree_box.rowconfigure(0, weight=1)
            self.tree = ttk.Treeview(tree_box, columns=("file", "phrase"), show="headings",
                                     selectmode="extended", height=9)
            self.tree.heading("file", text="File name (.wav)")
            self.tree.heading("phrase", text="Phrase spoken by the radio")
            self.tree.column("file", width=180, stretch=False)
            self.tree.column("phrase", width=480)
            self.tree.grid(row=0, column=0, sticky="nsew")
            sb = ttk.Scrollbar(tree_box, orient="vertical", command=self.tree.yview)
            sb.grid(row=0, column=1, sticky="ns")
            self.tree.configure(yscrollcommand=sb.set)
            self.tree.bind("<<TreeviewSelect>>", lambda e: self._on_select())
            self.tree.bind("<Delete>", lambda e: self._remove())
            self.tree.bind("<Double-1>", lambda e: self._preview())

            ed = ttk.Frame(pf)
            ed.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
            ed.columnconfigure(3, weight=1)
            ttk.Label(ed, text="File name").grid(row=0, column=0, sticky="w")
            self.name_entry = ttk.Entry(ed, textvariable=self.name_var, width=20)
            self.name_entry.grid(row=0, column=1, padx=6)
            ttk.Label(ed, text="Phrase").grid(row=0, column=2, sticky="w")
            self.text_entry = ttk.Entry(ed, textvariable=self.text_var)
            self.text_entry.grid(row=0, column=3, sticky="ew", padx=6)
            self.text_entry.bind("<Return>", lambda e: self._add_or_update())
            self.name_entry.bind("<Return>", lambda e: self.text_entry.focus_set())
            ttk.Button(ed, text="Add / Update", command=self._add_or_update).grid(row=0, column=4, padx=2)
            ttk.Button(ed, text="\u25b6 Preview", command=self._preview).grid(row=0, column=5, padx=2)

            bar = ttk.Frame(pf)
            bar.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(6, 0))
            for txt, cmd in [("Remove", self._remove), ("\u25b2 Up", lambda: self._move(-1)),
                             ("\u25bc Down", lambda: self._move(1)), ("Import .lst...", self._import),
                             ("Export .lst...", self._export), ("Load examples", self._load_examples),
                             ("Clear all", self._clear)]:
                ttk.Button(bar, text=txt, command=cmd).pack(side="left", padx=(0, 4))
            ttk.Label(bar, text="Tip: double-click a row to hear it", style="Hint.TLabel").pack(side="right")

            # ---- Output ----
            of = ttk.LabelFrame(outer, text=" 3. Generate ", padding=8)
            of.grid(row=2, column=0, sticky="ew")
            of.columnconfigure(1, weight=1)
            ttk.Label(of, text="Output folder").grid(row=0, column=0, sticky="w")
            ttk.Entry(of, textvariable=self.out_var).grid(row=0, column=1, sticky="ew", padx=6)
            ttk.Button(of, text="Browse...", command=lambda: self._browse(self.out_var)).grid(row=0, column=2)
            ttk.Button(of, text="Open", command=lambda: self._open_folder(self.out_var.get())).grid(row=0, column=3, padx=4)
            ttk.Label(of, text="CPS folder").grid(row=1, column=0, sticky="w", pady=(4, 0))
            ttk.Entry(of, textvariable=self.cps_var).grid(row=1, column=1, sticky="ew", padx=6, pady=(4, 0))
            ttk.Button(of, text="Browse...", command=lambda: self._browse(self.cps_var)).grid(row=1, column=2, pady=(4, 0))
            ttk.Button(of, text="Open", command=lambda: self._open_folder(self.cps_var.get())).grid(row=1, column=3, padx=4, pady=(4, 0))

            act = ttk.Frame(of)
            act.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(8, 0))
            self.gen_btn = ttk.Button(act, text="Generate WAV files", style="Accent.TButton", command=self._generate)
            self.gen_btn.pack(side="left")
            self.copy_btn = ttk.Button(act, text="Copy to CPS folder", command=self._copy_to_cps)
            self.copy_btn.pack(side="left", padx=6)
            ttk.Checkbutton(act, text="Copy to CPS automatically after generating",
                            variable=self.copy_after_var).pack(side="left", padx=6)
            self.cancel_btn = ttk.Button(act, text="Cancel", command=self.cancel_evt.set, state="disabled")
            self.cancel_btn.pack(side="right")
            self.prog = ttk.Progressbar(of, mode="determinate")
            self.prog.grid(row=3, column=0, columnspan=4, sticky="ew", pady=(8, 4))
            self.log_box = ScrolledText(of, height=8, font=("Consolas", 9), state="disabled", wrap="word")
            self.log_box.grid(row=4, column=0, columnspan=4, sticky="ew")

        # ---------------- helpers ----------------
        def log(self, msg: str):
            self.msgs.put(("log", msg))

        def _pump(self):
            try:
                while True:
                    item = self.msgs.get_nowait()
                    kind = item[0]
                    if kind == "log":
                        self.log_box.configure(state="normal")
                        self.log_box.insert("end", item[1] + "\n")
                        self.log_box.see("end")
                        self.log_box.configure(state="disabled")
                    elif kind == "progress":
                        self.prog.configure(maximum=item[2], value=item[1])
                    elif kind == "call":
                        item[1]()
            except queue.Empty:
                pass
            self.after(80, self._pump)

        def _ui(self, fn):
            self.msgs.put(("call", fn))

        def _set_busy(self, busy: bool):
            self.busy = busy
            state = "disabled" if busy else "normal"
            self.gen_btn.configure(state=state)
            self.copy_btn.configure(state=state)
            self.cancel_btn.configure(state="normal" if busy else "disabled")
            self.configure(cursor="watch" if busy else "")

        def run_bg(self, work, done=None):
            if self.busy:
                messagebox.showinfo(APP_TITLE, "Please wait for the current task to finish.")
                return
            self.cancel_evt.clear()
            self._set_busy(True)

            def runner():
                try:
                    result = work()
                    if done:
                        self._ui(lambda: done(result))
                except Exception as e:
                    self.log(f"ERROR: {e}")
                    tb = traceback.format_exc()
                    (core.app_data_dir() / "last_error.log").write_text(tb, encoding="utf-8")
                    msg = str(e)
                    self._ui(lambda: messagebox.showerror(APP_TITLE, msg))
                finally:
                    self._ui(lambda: self._set_busy(False))
            threading.Thread(target=runner, daemon=True).start()

        # ---------------- voices ----------------
        def _load_catalog(self, refresh: bool):
            def work():
                try:
                    return core.load_voice_catalog(refresh=refresh), None
                except Exception as e:
                    return [], e

            def done(res):
                cat, err = res
                if err:
                    self.log(f"Could not load the online voice list ({err}). Showing installed voices only.")
                    keys = set(core.installed_voices()) | {self.settings.get("voice", core.DEFAULT_VOICE)}
                    cat = []
                    for k in sorted(keys):
                        try:
                            lang, rest = k.split("-", 1)
                            name, q = rest.rsplit("-", 1)
                        except ValueError:
                            lang, name, q = "Other", k, ""
                        cat.append(core.VoiceInfo(k, lang, name, q, core._guess_onnx_path(k) if q else k + ".onnx"))
                elif refresh:
                    self.log(f"Voice list updated: {len(cat)} voices available.")
                self.catalog = cat
                self.by_lang = {}
                for v in cat:
                    self.by_lang.setdefault(v.language, []).append(v)
                self.lang_cb["values"] = sorted(self.by_lang)
                want = self.settings.get("voice", core.DEFAULT_VOICE)
                cur = next((v for v in cat if v.key == want), None) or (cat[0] if cat else None)
                if cur:
                    self.lang_var.set(cur.language)
                    self._on_lang(select_key=cur.key)
            self.run_bg(work, done)

        def _on_lang(self, select_key: str | None = None):
            voices = self.by_lang.get(self.lang_var.get(), [])
            labels = [self._voice_label(v) for v in voices]
            self.voice_cb["values"] = labels
            idx = next((i for i, v in enumerate(voices) if v.key == select_key), 0)
            if labels:
                self.voice_cb.current(idx)
            self._on_voice()

        def _voice_label(self, v: core.VoiceInfo) -> str:
            mark = "\u2713 " if core.is_voice_installed(v.key) else ""
            return mark + v.label

        def current_voice(self) -> core.VoiceInfo | None:
            voices = self.by_lang.get(self.lang_var.get(), [])
            i = self.voice_cb.current()
            return voices[i] if 0 <= i < len(voices) else None

        def _on_voice(self):
            v = self.current_voice()
            if not v:
                self.voice_status.set("")
                return
            if core.is_voice_installed(v.key):
                self.voice_status.set(f"{v.key}  -  installed")
            else:
                size = f" (~{v.size_bytes / 1e6:.0f} MB)" if v.size_bytes else ""
                self.voice_status.set(f"{v.key}  -  will be downloaded on first use{size}")
            self.speaker_sb.configure(to=max(0, v.num_speakers - 1),
                                      state="normal" if v.num_speakers > 1 else "disabled")
            if v.num_speakers <= 1:
                self.speaker_var.set(0)

        def _reset_speed(self):
            self.speed_var.set(1.0)
            self.speed_lbl.config(text="1.00x")

        def _open_samples(self):
            import webbrowser
            webbrowser.open("https://rhasspy.github.io/piper-samples/")

        def _ensure_voice(self, v: core.VoiceInfo) -> Path:
            """Runs in a worker thread."""
            if not core.is_voice_installed(v.key):
                self.log(f"Downloading voice {v.key} ...")
                last = [-1]

                def prog(label, frac):
                    pct = int(frac * 100)
                    if pct != last[0]:
                        last[0] = pct
                        self.msgs.put(("progress", pct, 100))
                core.download_voice(v, prog)
                self.log("Voice downloaded.")
                self._ui(lambda: (self._on_lang(select_key=v.key)))
            return core.local_model_path(v.key)

        def _speaker(self) -> int:
            try:
                return max(0, int(self.speaker_var.get()))
            except Exception:
                return 0

        def _synth_args(self, v):
            spk = self._speaker() if v.num_speakers > 1 else None
            return round(float(self.speed_var.get()), 2), spk

        # ---------------- phrases ----------------
        def phrases(self) -> list[core.Phrase]:
            return [core.Phrase(*self.tree.item(i, "values")) for i in self.tree.get_children()]

        def _set_phrases(self, items: list[core.Phrase]):
            self.tree.delete(*self.tree.get_children())
            for p in items:
                self.tree.insert("", "end", values=(p.filename, p.text))

        def _load_phrases(self):
            f = core.app_data_dir() / "phrases.lst"
            items = core.parse_phrases(f.read_text(encoding="utf-8")) if f.exists() else core.SAMPLE_PHRASES
            self._set_phrases(items)

        def _save_phrases(self):
            try:
                (core.app_data_dir() / "phrases.lst").write_text(core.format_phrases(self.phrases()), encoding="utf-8")
            except Exception:
                pass

        def _on_select(self):
            sel = self.tree.selection()
            if len(sel) == 1:
                name, text = self.tree.item(sel[0], "values")
                self.name_var.set(name)
                self.text_var.set(text)

        def _add_or_update(self):
            name = self.name_var.get().strip()
            if name.lower().endswith(".wav"):
                name = name[:-4]
            text = self.text_var.get().strip()
            err = core.validate_filename(name)
            if err:
                messagebox.showwarning(APP_TITLE, err)
                self.name_entry.focus_set()
                return
            if not text:
                messagebox.showwarning(APP_TITLE, "Type the phrase the radio should say.")
                self.text_entry.focus_set()
                return
            existing = next((i for i in self.tree.get_children()
                             if self.tree.item(i, "values")[0].lower() == name.lower()), None)
            if existing:
                self.tree.item(existing, values=(name, text))
            else:
                existing = self.tree.insert("", "end", values=(name, text))
            self.tree.selection_set(existing)
            self.tree.see(existing)
            self.name_var.set("")
            self.text_var.set("")
            self.name_entry.focus_set()
            self._save_phrases()

        def _remove(self):
            for i in self.tree.selection():
                self.tree.delete(i)
            self._save_phrases()

        def _move(self, d: int):
            for i in (self.tree.selection() if d < 0 else reversed(self.tree.selection())):
                self.tree.move(i, "", self.tree.index(i) + d)
            self._save_phrases()

        def _import(self):
            f = filedialog.askopenfilename(title="Import phrase list",
                                           filetypes=[("Phrase lists", "*.lst *.txt"), ("All files", "*.*")])
            if not f:
                return
            items = core.parse_phrases(Path(f).read_text(encoding="utf-8-sig"))
            if not items:
                messagebox.showwarning(APP_TITLE, "No 'filename=phrase' lines found in that file.")
                return
            if self.tree.get_children() and messagebox.askyesno(
                    APP_TITLE, f"Found {len(items)} phrases.\n\nReplace the current list?\n(No = add to it)"):
                self._set_phrases(items)
            else:
                self._set_phrases(self.phrases() + items)
            self._save_phrases()
            self.log(f"Imported {len(items)} phrases from {f}")

        def _export(self):
            f = filedialog.asksaveasfilename(title="Export phrase list", defaultextension=".lst",
                                             initialfile="phrases.lst",
                                             filetypes=[("Phrase lists", "*.lst"), ("Text", "*.txt")])
            if f:
                Path(f).write_text(core.format_phrases(self.phrases()), encoding="utf-8")
                self.log(f"Saved {f}")

        def _load_examples(self):
            self._set_phrases(self.phrases() + [p for p in core.SAMPLE_PHRASES
                                                if p.filename not in {x.filename for x in self.phrases()}])
            self._save_phrases()

        def _clear(self):
            if self.tree.get_children() and messagebox.askyesno(APP_TITLE, "Remove all phrases?"):
                self._set_phrases([])
                self._save_phrases()

        # ---------------- actions ----------------
        def _preview(self):
            text = self.text_var.get().strip()
            sel = self.tree.selection()
            if sel and (not text or self.tree.item(sel[0], "values")[1] == text):
                text = self.tree.item(sel[0], "values")[1]
            if not text:
                messagebox.showinfo(APP_TITLE, "Select a phrase or type one to preview.")
                return
            v = self.current_voice()
            if not v:
                return
            speed, spk = self._synth_args(v)

            def work():
                model = self._ensure_voice(v)
                self.log(f"Preview: {text}")
                y = core.render_phrase(text, model, speed, spk)
                data = core.pcm_wav_bytes(y, core.TARGET_RATE)  # what the radio will sound like
                if IS_WINDOWS:
                    import winsound
                    winsound.PlaySound(data, winsound.SND_MEMORY)
                else:
                    p = Path(tempfile.gettempdir()) / "mototrbo_preview.wav"
                    p.write_bytes(data)
                    self.log(f"(preview saved to {p})")
            self.run_bg(work)

        def _generate(self):
            items = self.phrases()
            if not items:
                messagebox.showinfo(APP_TITLE, "Add at least one phrase first.")
                return
            names = [p.filename.lower() for p in items]
            dups = sorted({n for n in names if names.count(n) > 1})
            if dups:
                messagebox.showwarning(APP_TITLE, "Duplicate file names: " + ", ".join(dups))
                return
            v = self.current_voice()
            if not v:
                messagebox.showwarning(APP_TITLE, "Pick a voice first.")
                return
            out = Path(self.out_var.get().strip() or core.default_output_dir())
            speed, spk = self._synth_args(v)
            self._save_settings()

            def work():
                model = self._ensure_voice(v)
                self.log(f"--- Generating {len(items)} file(s) with {v.key} -> {out}")
                self.msgs.put(("progress", 0, len(items)))
                written = core.generate_all(items, model, out, speed, spk, log=self.log,
                                            progress=lambda i, n: self.msgs.put(("progress", i, n)),
                                            cancel=self.cancel_evt)
                self.log(f"Done: {len(written)} of {len(items)} file(s) written.")
                return written

            def done(written):
                if written and self.copy_after_var.get():
                    self._copy_to_cps(written)
                elif written:
                    self.log("Next: click 'Copy to CPS folder' (or copy them yourself), then restart CPS.")
            self.run_bg(work, done)

        def _copy_to_cps(self, files: list[Path] | None = None):
            out = Path(self.out_var.get())
            if files is None:
                files = [out / f"{p.filename}.wav" for p in self.phrases()]
                files = [f for f in files if f.exists()]
            if not files:
                messagebox.showinfo(APP_TITLE, "No generated WAV files found yet. Click 'Generate WAV files' first.")
                return
            dst = Path(self.cps_var.get().strip())
            if not dst.parent.exists():
                messagebox.showwarning(APP_TITLE, f"CPS doesn't seem to be installed at:\n{dst.parent}\n\n"
                                       "Use Browse... to pick your CPS 'voiceannouncement' folder.")
                return
            self._save_settings()
            try:
                dst.mkdir(exist_ok=True)
                for f in files:
                    shutil.copy2(f, dst / f.name)
                self.log(f"Copied {len(files)} file(s) to {dst}. Restart CPS if it's open.")
                return
            except PermissionError:
                pass
            if not IS_WINDOWS:
                messagebox.showerror(APP_TITLE, f"Permission denied writing to {dst}")
                return
            # Program Files needs admin rights: copy through an elevated PowerShell (UAC prompt).
            q = lambda s: "'" + str(s).replace("'", "''") + "'"
            srcs = ",".join(q(f) for f in files)
            ps = (f"New-Item -ItemType Directory -Force -Path {q(dst)} | Out-Null; "
                  f"Copy-Item -LiteralPath @({srcs}) -Destination {q(dst)} -Force")
            import ctypes
            r = ctypes.windll.shell32.ShellExecuteW(
                None, "runas", "powershell.exe",
                f'-NoProfile -WindowStyle Hidden -Command "{ps}"', None, 0)
            if r <= 32:
                self.log("Copy to CPS folder was cancelled (administrator permission is needed).")
                return
            self.log("Copying with administrator permission...")

            def check(tries=0):
                ok = all((dst / f.name).exists() and (dst / f.name).stat().st_size == f.stat().st_size
                         for f in files)
                if ok:
                    self.log(f"Copied {len(files)} file(s) to {dst}. Restart CPS if it's open.")
                elif tries < 20:
                    self.after(500, lambda: check(tries + 1))
                else:
                    self.log("Couldn't confirm the copy. Check the CPS folder (Open button).")
            self.after(800, check)

        def _browse(self, var):
            d = filedialog.askdirectory(initialdir=var.get() if Path(var.get()).exists() else None)
            if d:
                var.set(str(Path(d)))

        def _open_folder(self, path: str):
            p = Path(path)
            if not p.exists():
                if p.parent.exists() and messagebox.askyesno(APP_TITLE, f"{p} doesn't exist yet. Create it?"):
                    try:
                        p.mkdir(parents=True)
                    except PermissionError:
                        messagebox.showerror(APP_TITLE, "Permission denied.")
                        return
                else:
                    return
            if IS_WINDOWS:
                os.startfile(str(p))
            else:
                subprocess.Popen(["xdg-open", str(p)])

        def _save_settings(self):
            v = self.current_voice()
            self.settings.update(
                voice=v.key if v else self.settings.get("voice", core.DEFAULT_VOICE),
                speed=round(float(self.speed_var.get()), 2),
                speaker=self._speaker(),
                output_dir=self.out_var.get(), cps_dir=self.cps_var.get(),
                copy_after=bool(self.copy_after_var.get()))
            core.save_settings(self.settings)

        def _on_close(self):
            self._save_settings()
            self._save_phrases()
            self.cancel_evt.set()
            self.destroy()

    if not smoke_log:
        App().mainloop()
        return 0

    # --gui-smoketest: build the window, exercise the widgets, report any Tk errors, exit.
    errors: list[str] = []
    tk.Tk.report_callback_exception = lambda self, et, ev, tb: errors.append(
        "".join(traceback.format_exception(et, ev, tb)))
    try:
        app = App()

        def finish():
            try:
                app.name_var.set("smoke-1")
                app.text_var.set("Smoke test")
                app._add_or_update()
                assert any(p.filename == "smoke-1" for p in app.phrases())
                app.tree.selection_set(app.tree.get_children()[-1])
                app._remove()
                app._on_lang()
                app._save_settings()
                app.update()
            except Exception:
                errors.append(traceback.format_exc())
            app.destroy()
        app.after(4000, finish)
        app.mainloop()
    except Exception:
        errors.append(traceback.format_exc())
    Path(smoke_log).write_text("\n".join(errors) or "GUI SMOKETEST PASSED\n", encoding="utf-8")
    return 1 if errors else 0


def main() -> int:
    ap = argparse.ArgumentParser(description=APP_TITLE)
    ap.add_argument("--generate", action="store_true", help="generate WAVs without the GUI")
    ap.add_argument("--phrases", help="phrases.lst file (filename=phrase per line)")
    ap.add_argument("--out", help="output folder")
    ap.add_argument("--voice", help=f"Piper voice key (default {core.DEFAULT_VOICE})")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--log", help="write a log file")
    ap.add_argument("--selftest", metavar="DIR", help="generate the sample phrases into DIR and verify them")
    ap.add_argument("--gui-smoketest", metavar="LOGFILE", help=argparse.SUPPRESS)
    args = ap.parse_args()
    if args.gui_smoketest:
        return run_gui(smoke_log=args.gui_smoketest)
    if args.selftest or args.generate:
        if args.generate and not args.phrases:
            ap.error("--generate needs --phrases")
        return run_headless(args)
    return run_gui()


if __name__ == "__main__":
    sys.exit(main())
