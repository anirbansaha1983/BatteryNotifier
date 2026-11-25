#!/usr/bin/env python3
"""Give a Windows shortcut the Battery Notifier icon.

A `.bat` file cannot carry an icon of its own — Windows always draws the
generic batch-file glyph on it, and the file's embedded icon resources are
ignored by Explorer. The only way to see a custom icon on a shortcut to
`run_tray.bat` is to create a `.lnk` and stamp an icon location onto it.

    python windows/shortcut_icon.py                  # Desktop + Start Menu
    python windows/shortcut_icon.py --where desktop  # Desktop only
    python windows/shortcut_icon.py --script windows/restart.bat
    python windows/shortcut_icon.py --name "Battery Notifier"
    python windows/shortcut_icon.py --remove         # delete them again

Each shortcut runs `cmd.exe /c "<repo>\\windows\\run_tray.bat"` minimised, so
double-clicking behaves exactly like double-clicking the batch file, but with
the battery icon. Nothing is installed system-wide; only `.lnk` files are
written, and `--remove` deletes them.

On macOS/Linux this is unnecessary: Finder and most desktops let you set an
icon on a file directly, and the `.bat` launchers do not apply there.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(HERE)
ICON = os.path.join(REPO, "assets", "battery-notifier.ico")
DEFAULT_SCRIPT = os.path.join(HERE, "run_tray.bat")
DEFAULT_NAME = "Battery Notifier (Tray)"

#: Set to False in tests to exercise the non-Windows error path.
IS_WINDOWS = sys.platform == "win32"

WHERE_HELP = "desktop, startmenu, or both"


def _ps_quote(value: str) -> str:
    """Quote a string for a PowerShell single-quoted literal."""
    return "'" + value.replace("'", "''") + "'"


def _shortcut_folders(where: str) -> list:
    """Resolve the requested shell folders to absolute paths (Windows only)."""
    wanted = {
        "desktop": "Desktop",
        "startmenu": "Programs",
    }
    if where not in wanted and where != "both":
        raise ValueError(f"unknown --where {where!r} (use {WHERE_HELP})")
    keys = list(wanted) if where == "both" else [where]

    expr = ";".join(
        f"[Environment]::GetFolderPath('{wanted[k]}')" for k in keys
    )
    script = f"@({expr}) | ForEach-Object {{ Write-Output $_ }}"
    out = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, check=True,
    ).stdout
    return [line.strip() for line in out.splitlines() if line.strip()]


def _lnk_script(links, target: str, arguments: str, workdir: str,
                icon: str, description: str, remove: bool) -> str:
    """Build the PowerShell that creates (or deletes) the .lnk files.

    Kept as a pure function so it can be asserted on from any platform.
    """
    lines = ["$ErrorActionPreference = 'Stop'"]
    if remove:
        for path in links:
            lines.append(
                f"Remove-Item -LiteralPath {_ps_quote(path)} "
                "-ErrorAction SilentlyContinue"
            )
        for path in links:
            lines.append(f"Write-Output {_ps_quote(path)}")
        return "\n".join(lines)

    lines += [
        "$shell = New-Object -ComObject WScript.Shell",
    ]
    for path in links:
        lines += [
            f"$lnk = $shell.CreateShortcut({_ps_quote(path)})",
            f"$lnk.TargetPath = {_ps_quote(target)}",
            f"$lnk.Arguments = {_ps_quote(arguments)}",
            f"$lnk.WorkingDirectory = {_ps_quote(workdir)}",
            f"$lnk.IconLocation = {_ps_quote(icon + ',0')}",
            "$lnk.WindowStyle = 7",  # minimised: no lingering console window
            f"$lnk.Description = {_ps_quote(description)}",
            "$lnk.Save()",
            f"Write-Output {_ps_quote(path)}",
        ]
    return "\n".join(lines)


def create_shortcuts(where: str = "both", script: str = DEFAULT_SCRIPT,
                     name: str = DEFAULT_NAME, remove: bool = False,
                     icon: str = ICON) -> list:
    """Create (or remove) the shortcuts and return their paths."""
    if not IS_WINDOWS:
        raise OSError("Shortcut icons are a Windows feature; "
                      "run this on Windows.")
    if not os.path.exists(icon):
        raise FileNotFoundError(
            f"Icon not found: {icon}\n"
            "Generate it first: python assets/make_icon.py")
    if not os.path.exists(script):
        raise FileNotFoundError(f"Script not found: {script}")

    script = os.path.abspath(script)
    links = [os.path.join(folder, name + ".lnk")
             for folder in _shortcut_folders(where)]
    # cmd.exe /c ""<path>"" - the doubled quotes survive the path's spaces.
    ps = _lnk_script(
        links,
        target=os.path.join(os.environ.get("SystemRoot", r"C:\Windows"),
                            "System32", "cmd.exe"),
        arguments=f'/c ""{script}""',
        workdir=os.path.dirname(script),
        icon=os.path.abspath(icon),
        description="Battery Notifier - system tray monitor",
        remove=remove,
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise OSError(f"PowerShell failed:\n{result.stderr.strip()}")
    return links


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Put the Battery Notifier icon on a shortcut to run_tray.bat")
    ap.add_argument("--where", default="both", choices=("desktop", "startmenu", "both"),
                    help=f"where to create the shortcut ({WHERE_HELP}; default both)")
    ap.add_argument("--script", default=DEFAULT_SCRIPT,
                    help="batch file the shortcut should run "
                         "(default: windows/run_tray.bat)")
    ap.add_argument("--name", default=DEFAULT_NAME,
                    help=f"shortcut name (default: {DEFAULT_NAME!r})")
    ap.add_argument("--remove", action="store_true",
                    help="delete the shortcuts instead of creating them")
    args = ap.parse_args(argv)

    try:
        links = create_shortcuts(where=args.where, script=args.script,
                                 name=args.name, remove=args.remove)
    except (OSError, FileNotFoundError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    verb = "Removed" if args.remove else "Created"
    for path in links:
        print(f"{verb}: {path}")
    if not args.remove:
        print("\nThe icon may take a moment to appear; press F5 in the folder "
              "or sign out and back in if it does not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
