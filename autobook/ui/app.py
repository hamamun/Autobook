"""Minimal desktop window.

Deliberately plain tkinter: it ships with Python, has no licence cost, packages small
with PyInstaller, and looks native enough on Windows. The layout is one thing at a
time, top to bottom: choose files -> see them -> Prepare -> read the result.

Rules followed here:

* the file chooser opens where the operator last browsed (persisted in settings);
* selections accumulate, so several packing lists can be added in more than one trip;
* the same file is not added twice;
* Prepare runs on a worker thread, so the window never freezes;
* every failure is shown in the log with what to do next - no silent stops.
"""

from __future__ import annotations

import os
import queue
import subprocess
import sys
import threading
import traceback
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk

from ..paths import work_dir
from ..pipeline import PrepareError, PrepareResult, prepare
from ..settings import Settings
from ..workdir import SUPPORTED_SUFFIXES, dialog_filetypes

FILE_TYPES = dialog_filetypes()


class App(tk.Tk):
    """Main window."""

    def __init__(self) -> None:
        super().__init__()
        self.title("Autobook - Prepare packing lists")
        self.geometry("980x680")
        self.minsize(820, 560)

        self.settings = Settings.load()
        self.selected: list[Path] = []
        self._messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self._worker: threading.Thread | None = None
        self._result: PrepareResult | None = None

        self._build()
        self.after(100, self._drain_messages)

    # ------------------------------------------------------------------ ui
    def _build(self) -> None:
        outer = ttk.Frame(self, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text="Autobook",
                  font=("Segoe UI", 16, "bold")).pack(anchor="w")
        ttk.Label(outer,
                  text="Choose packing lists, then press Prepare to build the data sheet.",
                  foreground="#555").pack(anchor="w", pady=(2, 14))

        # -- file selection -------------------------------------------------
        pick = ttk.LabelFrame(outer, text=" 1. Packing list files ", padding=12)
        pick.pack(fill="both", expand=True)

        row = ttk.Frame(pick)
        row.pack(fill="x")
        self.browse_btn = ttk.Button(row, text="Browse for packing lists...",
                                     command=self.on_browse)
        self.browse_btn.pack(side="left")
        ttk.Button(row, text="Remove selected", command=self.on_remove).pack(side="left", padx=(8, 0))
        ttk.Button(row, text="Clear all", command=self.on_clear).pack(side="left", padx=(8, 0))
        self.count_label = ttk.Label(row, text="No files selected", foreground="#555")
        self.count_label.pack(side="right")

        list_wrap = ttk.Frame(pick)
        list_wrap.pack(fill="both", expand=True, pady=(10, 0))
        self.tree = ttk.Treeview(list_wrap, columns=("name", "folder", "size"),
                                 show="headings", selectmode="extended", height=8)
        self.tree.heading("name", text="File")
        self.tree.heading("folder", text="Folder")
        self.tree.heading("size", text="Size")
        self.tree.column("name", width=280, anchor="w")
        self.tree.column("folder", width=480, anchor="w")
        self.tree.column("size", width=80, anchor="e")
        scroll = ttk.Scrollbar(list_wrap, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        self.tree.bind("<Double-1>", lambda _e: self.on_remove())

        # -- working directory ----------------------------------------------
        work = ttk.LabelFrame(outer, text=" 2. Working directory ", padding=12)
        work.pack(fill="x", pady=(12, 0))
        self.work_var = tk.StringVar(value=str(work_dir()))
        entry = ttk.Entry(work, textvariable=self.work_var, state="readonly")
        entry.pack(side="left", fill="x", expand=True)
        ttk.Button(work, text="Open folder",
                   command=lambda: self._open_folder(Path(self.work_var.get()))).pack(
                       side="left", padx=(8, 0))

        # -- prepare ---------------------------------------------------------
        action = ttk.Frame(outer)
        action.pack(fill="x", pady=(14, 0))
        self.prepare_btn = ttk.Button(action, text="Prepare data sheet",
                                      command=self.on_prepare)
        self.prepare_btn.pack(side="left")
        self.open_output_btn = ttk.Button(action, text="Open data sheet",
                                          command=self.on_open_output, state="disabled")
        self.open_output_btn.pack(side="left", padx=(8, 0))
        self.status = ttk.Label(action, text="Ready", foreground="#555")
        self.status.pack(side="right")

        # -- log -------------------------------------------------------------
        log_wrap = ttk.LabelFrame(outer, text=" Log ", padding=8)
        log_wrap.pack(fill="both", expand=True, pady=(12, 0))
        self.log = tk.Text(log_wrap, height=10, wrap="word", font=("Consolas", 9),
                           background="#111820", foreground="#d8e0e8",
                           insertbackground="#d8e0e8", relief="flat")
        log_scroll = ttk.Scrollbar(log_wrap, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=log_scroll.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        log_scroll.pack(side="right", fill="y")

        self._log(f"Working directory: {self.work_var.get()}")
        self._log("Supported files: " + ", ".join(sorted(SUPPORTED_SUFFIXES)))

    # -------------------------------------------------------------- helpers
    def _log(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message.rstrip() + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _set_status(self, text: str) -> None:
        self.status.configure(text=text)

    def _refresh_list(self) -> None:
        self.tree.delete(*self.tree.get_children())
        for path in self.selected:
            try:
                size = path.stat().st_size
                size_text = f"{size / 1024:.0f} KB" if size < 1_048_576 else f"{size / 1_048_576:.1f} MB"
            except OSError:
                size_text = "-"
            self.tree.insert("", "end", values=(path.name, str(path.parent), size_text))
        count = len(self.selected)
        self.count_label.configure(
            text="No files selected" if count == 0 else f"{count} file{'s' if count != 1 else ''} selected")
        self.prepare_btn.configure(state="normal" if count and not self._worker else "disabled")

    def _open_folder(self, path: Path) -> None:
        try:
            path.mkdir(parents=True, exist_ok=True)
            if sys.platform.startswith("win"):
                subprocess.Popen(["explorer", str(path)])
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(path)])
            else:
                subprocess.Popen(["xdg-open", str(path)])
        except OSError as exc:
            messagebox.showerror("Cannot open folder", str(exc))

    # -------------------------------------------------------------- actions
    def on_browse(self) -> None:
        """Open the file dialog at the last used folder; add the chosen files."""
        initial = self.settings.initial_browse_dir()
        chosen = filedialog.askopenfilenames(
            title="Select packing lists",
            initialdir=initial,
            filetypes=FILE_TYPES,
            parent=self,
        )
        if not chosen:
            return  # cancelled: do not move the remembered folder

        added = 0
        known = {p.resolve() for p in self.selected}
        for item in chosen:
            path = Path(item)
            if path.suffix.lower() not in SUPPORTED_SUFFIXES:
                self._log(f"Skipped (unsupported type): {path.name}")
                continue
            resolved = path.resolve()
            if resolved in known:
                self._log(f"Already in the list: {path.name}")
                continue
            self.selected.append(resolved)
            known.add(resolved)
            added += 1

        # Remember where we browsed so the next dialog opens in the same place.
        self.settings.remember_browse_dir(chosen)
        self.settings.save()

        self._refresh_list()
        self._log(f"Added {added} file(s). Folder remembered: {self.settings.last_browse_dir}")

    def on_remove(self) -> None:
        indexes = sorted((self.tree.index(i) for i in self.tree.selection()), reverse=True)
        for index in indexes:
            if 0 <= index < len(self.selected):
                self._log(f"Removed: {self.selected[index].name}")
                del self.selected[index]
        self._refresh_list()

    def on_clear(self) -> None:
        if self.selected and not messagebox.askyesno("Clear list", "Remove all selected files?"):
            return
        self.selected.clear()
        self._refresh_list()

    def on_prepare(self) -> None:
        if not self.selected or self._worker:
            return
        files = list(self.selected)
        self.prepare_btn.configure(state="disabled")
        self.open_output_btn.configure(state="disabled")
        self._set_status("Preparing...")
        self._log("")
        self._log(f"--- Prepare started: {len(files)} file(s) ---")

        def work() -> None:
            try:
                result = prepare(files)
                self._messages.put(("done", result))
            except PrepareError as exc:
                self._messages.put(("error", str(exc)))
            except Exception:
                self._messages.put(("error", traceback.format_exc()))

        self._worker = threading.Thread(target=work, daemon=True)
        self._worker.start()

    def on_open_output(self) -> None:
        if self._result and self._result.data_sheet:
            self._open_path(self._result.data_sheet)

    def _open_path(self, target: Path) -> None:
        """Hand a file to the OS default application."""
        try:
            if sys.platform.startswith("win") and hasattr(os, "startfile"):
                os.startfile(str(target))  # type: ignore[attr-defined]
            elif sys.platform == "darwin":
                subprocess.Popen(["open", str(target)])
            else:
                subprocess.Popen(["xdg-open", str(target)])
        except OSError as exc:
            messagebox.showerror("Cannot open file", f"{target}\n\n{exc}")

    # ------------------------------------------------------ worker messages
    def _drain_messages(self) -> None:
        try:
            while True:
                kind, payload = self._messages.get_nowait()
                self._worker = None
                if kind == "done":
                    self._on_finished(payload)  # type: ignore[arg-type]
                else:
                    self._on_failed(str(payload))
        except queue.Empty:
            pass
        self.after(100, self._drain_messages)

    def _on_finished(self, result: PrepareResult) -> None:
        self._result = result
        self._log(f"Copied into: {result.batch_dir}")
        for item in result.copied:
            verb = "copied" if item.copied else "already in work dir"
            self._log(f"  {verb}: {item.display_name}")

        for problem in result.problems:
            self._log(f"  NOT USED: {problem}")

        for pl in result.results:
            errors = [i for i in pl.issues if i.severity == "error"]
            flag = "FAILED" if errors else ("review" if pl.issues else "ok")
            self._log(f"  {pl.source.name}: {flag} "
                      f"({len(pl.cartons)} carton lines, {len(pl.issues)} note(s))")
            for issue in pl.issues:
                self._log(f"      - [{issue.severity}] {issue.field}: {issue.problem}")

        if result.data_sheet:
            self._log(f"Data sheet written: {result.data_sheet}")
            self.open_output_btn.configure(state="normal")
            self._set_status(f"Done - {result.ok_count}/{len(result.results)} file(s) clean")
        else:
            self._set_status("Nothing could be prepared")
            messagebox.showwarning(
                "Nothing prepared",
                "No usable packing lists were produced.\nSee the log for the reason for each file.")

        self._refresh_list()

    def _on_failed(self, message: str) -> None:
        self._log("ERROR: " + message)
        self._set_status("Failed")
        self._refresh_list()
        messagebox.showerror("Prepare failed", message)


def _enable_dpi_awareness() -> None:
    """Stop Windows from scaling the window into a blurry mess."""
    if not sys.platform.startswith("win"):
        return
    try:
        import ctypes

        ctypes.windll.shcore.SetProcessDpiAwareness(1)  # type: ignore[attr-defined]
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()  # type: ignore[attr-defined]
        except Exception:
            pass  # older Windows: better blurry than broken


def main() -> int:
    _enable_dpi_awareness()
    app = App()
    app.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
