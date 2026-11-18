"""Import-level check for the UI module.

The window itself needs a display, which CI and headless machines do not have. This
test stubs tkinter so the import graph and class bodies are still verified - it
catches missing imports and typos in module-level code without opening a window.
"""

from __future__ import annotations

import sys
import types
from unittest import mock


def _stub_tkinter() -> dict[str, types.ModuleType]:
    tk = types.ModuleType("tkinter")
    tk.Tk = type("Tk", (), {})
    tk.Widget = type("Widget", (), {})
    tk.StringVar = type("StringVar", (), {"__init__": lambda self, **kw: None})
    tk.Text = type("Text", (), {})
    tk.END = "end"

    ttk = types.ModuleType("tkinter.ttk")
    for name in ("Frame", "Label", "Button", "Entry", "Treeview", "Scrollbar",
                 "LabelFrame", "Combobox"):
        setattr(ttk, name, type(name, (), {}))

    filedialog = types.ModuleType("tkinter.filedialog")
    filedialog.askopenfilenames = mock.Mock(return_value=())
    filedialog.askdirectory = mock.Mock(return_value="")

    messagebox = types.ModuleType("tkinter.messagebox")
    for name in ("showerror", "showwarning", "showinfo", "askyesno"):
        setattr(messagebox, name, mock.Mock(return_value=True))

    tk.ttk = ttk
    tk.filedialog = filedialog
    tk.messagebox = messagebox
    return {
        "tkinter": tk,
        "tkinter.ttk": ttk,
        "tkinter.filedialog": filedialog,
        "tkinter.messagebox": messagebox,
    }


def test_ui_module_imports_with_stubbed_tkinter() -> None:
    stubs = _stub_tkinter()
    with mock.patch.dict(sys.modules, stubs):
        sys.modules.pop("autobook.ui.app", None)
        import autobook.ui.app as app_module

        assert hasattr(app_module, "App")
        assert callable(app_module.main)
        # The dialog filter must stay in sync with the supported extensions.
        assert app_module.FILE_TYPES
        labels = [label for label, _pattern in app_module.FILE_TYPES]
        assert "Packing lists" in labels
