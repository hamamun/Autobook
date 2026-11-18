# Running Autobook from VS Code

## The entry point

There is **no single "main.py"**. The program is a package, and its entry point is:

```
autobook/__main__.py     ->  calls autobook/ui/app.py : main()
```

Run it as a module, not as a file:

```bat
python -m autobook
```

Do **not** run `autobook\ui\app.py` directly. It uses relative imports, so running it as
a script fails with `ImportError: attempted relative import with no known parent package`
(or, on a machine without tkinter, a confusing `ModuleNotFoundError`). Always go through
`python -m autobook`.

## First-time setup (once per machine)

Open the project folder in VS Code, then **Terminal > New Terminal** (PowerShell) and run:

```bat
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -e ".[dev]"
```

Notes:

* `.venv\Scripts\activate` (lowercase, no extension) is the cmd.exe version;
  `Activate.ps1` is for PowerShell.
* If PowerShell blocks activation, run once:
  `Set-ExecutionPolicy -Scope CurrentUser RemoteSigned`
* `-e` means *editable* — the code you edit runs immediately, no reinstall needed.
* `[dev]` installs pytest. Drop it if you only want to run the app.
* In VS Code press `Ctrl+Shift+P` → **Python: Select Interpreter** → pick
  `.venv\Scripts\python.exe`. The integrated terminal then activates it automatically.

## Daily commands

| Purpose | Command |
|---|---|
| Start the window | `python -m autobook` |
| Run all tests | `python -m pytest -q` |
| Run the pipeline without the window (good for testing) | `python scripts/run_prepare.py "samples\JMF-26-GS-3844 SEA CA.csv"` |
| Check the installed dependencies | `pip list` |

## Debugging with F5

`.vscode/launch.json` is included with three configurations:

* **Autobook (window)** — runs `python -m autobook` under the debugger
* **Prepare sample (no window)** — runs the sample file through the pipeline
* **Tests** — runs pytest under the debugger

Breakpoints work in all three. The window config uses `"justMyCode": false` so you can
step into library code when diagnosing an extraction problem.

## Expected first-run behaviour on Windows

1. The window opens (no console window when packaged; a console appears this way).
2. Press **Browse for packing lists…**, choose `samples\JMF-26-GS-3844 SEA CA.csv`.
3. Press **Prepare data sheet**.
4. Files are copied to `%LOCALAPPDATA%\Autobook\work\<timestamp>\`, and the sheet is
   written to `%LOCALAPPDATA%\Autobook\output\`.

To keep test runs out of your real folders:

```bat
set AUTOBOOK_HOME=C:\temp\autobook-test
python -m autobook
```

## Common errors

| Message | Cause and fix |
|---|---|
| `ModuleNotFoundError: No module named 'tkinter'` | Not the official python.org build, or Linux without `python3-tk`. On Windows, reinstall Python from python.org (Tk is included by default) |
| `ModuleNotFoundError: No module named 'autobook'` | The venv is not activated, or `pip install -e .` was not run |
| `ImportError: attempted relative import with no known parent package` | You ran a file inside the package directly. Use `python -m autobook` |
| `No module named pytest` | Use `pip install -e ".[dev]"` |
| Window opens but Prepare does nothing | Check the log panel at the bottom; every skipped file is listed with a reason |

## Packaging later

See `docs/windows-install.md` for the PyInstaller + Inno Setup route to a real installer.
