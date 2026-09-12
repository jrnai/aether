"""Project Aether - Standalone Native File and Folder Picker Dialog.

This helper script is invoked as a separate process to display a native OS
file or folder selection dialog that is guaranteed to appear in the FOREGROUND
on top of any active windows (including Microsoft Edge in App mode).
"""

import argparse
import ctypes
import os
import sys
import tkinter as tk
from tkinter import filedialog


def main() -> None:
    parser = argparse.ArgumentParser(description="Aether Native File/Folder Picker")
    parser.add_argument("--type", choices=["folder", "file"], default="folder")
    parser.add_argument("--initial", default="")
    parser.add_argument("--title", default="")
    args = parser.parse_args()

    initial = (
        os.path.abspath(args.initial)
        if args.initial and os.path.exists(args.initial)
        else os.getcwd()
    )
    title = args.title or ("Select Folder" if args.type == "folder" else "Select File")

    # On Windows, allow foreground window activation from background processes
    if sys.platform == "win32":
        try:
            ctypes.windll.user32.AllowSetForegroundWindow(-1)
        except Exception:
            pass

    root = tk.Tk()
    root.title(title)
    # Position off-screen so the root window is not visible to the user,
    # but keep it mapped so it acts as an active, topmost parent for the modal dialog.
    root.geometry("1x1+-3000+-3000")
    root.attributes("-topmost", True)
    root.lift()
    root.focus_force()

    if sys.platform == "win32":
        try:
            hwnd = ctypes.windll.user32.GetParent(root.winfo_id()) or root.winfo_id()
            ctypes.windll.user32.SetForegroundWindow(hwnd)
        except Exception:
            pass

    selected = None
    try:
        if args.type == "folder":
            selected = filedialog.askdirectory(
                parent=root,
                initialdir=initial,
                title=title,
                mustexist=True,
            )
        else:
            selected = filedialog.askopenfilename(
                parent=root,
                initialdir=initial,
                title=title,
            )
    finally:
        try:
            root.destroy()
        except Exception:
            pass

    if selected:
        print(os.path.normpath(selected))


if __name__ == "__main__":
    main()
