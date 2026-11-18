# Running Autobook on Windows

## 1. Development run (recommended for now)

Requires **Python 3.10+ (64-bit)** from python.org — tick *"Add python.exe to PATH"* in the
installer.

```bat
cd C:\path\to\Autobook
python -m venv .venv
.venv\Scripts\activate
pip install -e .
python -m autobook
```

The window opens. Tkinter ships with the official python.org installer, so no extra
package is needed. (Microsoft Store Python also works, but the python.org build is less
surprising.)

## 2. Where it stores things

| Item | Location |
|---|---|
| Working directory (copies of your packing lists) | `%LOCALAPPDATA%\Autobook\work\<yyyy-mm-dd-hhmmss>\` |
| Data sheet | `%LOCALAPPDATA%\Autobook\output\data_sheet_<timestamp>.xlsx` |
| Remembered file-dialog folder + future settings | `%LOCALAPPDATA%\Autobook\settings.json` |
| Extraction profiles | `<install folder>\profiles\*.yaml` |

To test without touching your real data, set the environment variable
`AUTOBOOK_HOME=C:\temp\autobook-test` before launching.

## 3. Building a single-folder install

```bat
pip install -e .[build]
pyinstaller --noconfirm --windowed --name Autobook ^
  --add-data "profiles;profiles" ^
  autobook\__main__.py
```

That yields `dist\Autobook\Autobook.exe`. Use `--onedir` (the default, as above) rather
than `--onefile`: a one-file build unpacks itself on every launch and starts noticeably
slower.

### One code detail for a frozen build

`autobook/extract/profiles.py` locates the profile folder relative to the package file.
Inside a PyInstaller bundle that path changes. Add this to the top of that module when
you first package it:

```python
import sys
from pathlib import Path

PROFILE_DIR = (Path(sys._MEIPASS) / "profiles"          # frozen
               if getattr(sys, "frozen", False)
               else Path(__file__).resolve().parents[2] / "profiles")
```

## 4. Checks worth doing on a fresh Windows machine

1. Launch, press **Browse**, pick the sample `samples\JMF-26-GS-3844 SEA CA.csv`.
2. Press **Browse** again — the dialog must reopen in the folder you last used.
3. Select a second file, then press **Prepare**.
4. Confirm `%LOCALAPPDATA%\Autobook\work\<timestamp>\` contains copies and the originals
   are untouched.
5. Press **Open data sheet** — Excel opens with the 19 predefined columns.
6. Add the same file twice — the second attempt must be ignored rather than duplicated.
