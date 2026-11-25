"""Tests for the Windows shortcut icon helper (runs on any platform)."""

import os
import struct
import subprocess
import sys

import pytest

REPO = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(REPO, "windows"))

import shortcut_icon as si  # noqa: E402

ASSETS = os.path.join(REPO, "assets")
ICO = os.path.join(ASSETS, "battery-notifier.ico")
PNG = os.path.join(ASSETS, "battery-notifier.png")


# --------------------------------------------------------------------------- #
# The icon files themselves
# --------------------------------------------------------------------------- #

def test_icon_assets_are_committed():
    assert os.path.isfile(ICO), "missing assets/battery-notifier.ico"
    assert os.path.isfile(PNG), "missing assets/battery-notifier.png"
    assert os.path.getsize(ICO) > 1000


def _ico_directory(path=ICO):
    """Parse the ICONDIR + entries of an .ico; return [(w, h, bpp, kind)]."""
    with open(path, "rb") as fh:
        raw = fh.read()
    reserved, kind, count = struct.unpack("<HHH", raw[:6])
    assert (reserved, kind) == (0, 1), "not a valid icon container"

    entries, off = [], 6
    for _ in range(count):
        w, h, _colours, _res, planes, bpp, size, offset = struct.unpack(
            "<BBBBHHII", raw[off:off + 16])
        off += 16
        payload = raw[offset:offset + size]
        frame = "png" if payload.startswith(b"\x89PNG\r\n\x1a\n") else "dib"
        entries.append((w or 256, h or 256, planes, bpp, frame))
    return entries


def test_ico_declares_windows_sizes():
    sizes = {(w, h) for w, h, *_ in _ico_directory()}
    # Explorer picks nearest-match; these are the sizes it actually asks for.
    for expected in ((16, 16), (32, 32), (48, 48), (256, 256)):
        assert expected in sizes, f"{expected} frame missing from the .ico"


def test_ico_frames_are_32_bit():
    for w, h, planes, bpp, _frame in _ico_directory():
        assert planes == 1, f"{w}x{h} has {planes} planes"
        assert bpp == 32, f"{w}x{h} is {bpp}-bit, need 32-bit for alpha"


def test_ico_uses_png_only_for_large_frames():
    # Windows ignores PNG-compressed frames below Vista-ish sizes, so the
    # small ones must be DIBs and only 128/256 may be PNG.
    for w, _h, _planes, _bpp, frame in _ico_directory():
        if frame == "png":
            assert w >= 128, f"{w}px frame must not be PNG-compressed"


def test_ico_payloads_are_in_bounds():
    with open(ICO, "rb") as fh:
        raw = fh.read()
    _reserved, _kind, count = struct.unpack("<HHH", raw[:6])
    for i in range(count):
        entry = raw[6 + i * 16:6 + (i + 1) * 16]
        _w, _h, _c, _r, _p, _b, size, offset = struct.unpack("<BBBBHHII", entry)
        assert offset + size <= len(raw), f"frame {i} runs past end of file"


def test_icon_is_square_and_not_blank():
    pytest.importorskip("PIL", reason="Pillow not installed")
    from PIL import Image

    img = Image.open(ICO)
    img.size = (256, 256)
    img.load()
    assert img.size == (256, 256)
    alpha = img.getchannel("A")
    assert alpha.getextrema() == (0, 255), "icon should be partly transparent"
    # A battery green must actually be present, not just an empty outline.
    colours = img.convert("RGB").getcolors(maxcolors=1 << 20) or []
    greens = [c for _n, c in colours if c[1] > c[0] and c[1] > c[2]]
    assert greens, "no green pixels in the icon"


def test_png_asset_matches_ico_size():
    pytest.importorskip("PIL", reason="Pillow not installed")
    from PIL import Image

    with Image.open(PNG) as png:
        assert png.size == (256, 256)


# --------------------------------------------------------------------------- #
# Shortcut generation (pure functions - safe off Windows)
# --------------------------------------------------------------------------- #

def test_ps_quote_escapes_single_quotes():
    assert si._ps_quote(r"C:\plain") == r"'C:\plain'"
    assert si._ps_quote("O'Brien") == "'O''Brien'"


def test_lnk_script_sets_every_required_property():
    script = si._lnk_script(
        [r"C:\Users\bob\Desktop\Battery Notifier (Tray).lnk"],
        target=r"C:\Windows\System32\cmd.exe",
        arguments=r'/c ""C:\repo\windows\run_tray.bat""',
        workdir=r"C:\repo\windows",
        icon=r"C:\repo\assets\battery-notifier.ico",
        description="Battery Notifier - system tray monitor",
        remove=False,
    )
    for needle in ("CreateShortcut", "TargetPath", "Arguments",
                   "WorkingDirectory", "IconLocation", "Description", ".Save()"):
        assert needle in script, f"{needle} missing from generated shortcut"
    # Icon index 0 is required; Windows falls back to a generic icon without it.
    assert r"battery-notifier.ico,0" in script
    # No console window should linger after the launcher starts.
    assert "$lnk.WindowStyle = 7" in script


def test_lnk_script_points_at_the_batch_file():
    script = si._lnk_script(
        [r"C:\x\a.lnk"], target=r"C:\Windows\System32\cmd.exe",
        arguments=r'/c ""C:\repo\windows\run_tray.bat""',
        workdir=r"C:\repo\windows", icon=r"C:\repo\assets\i.ico",
        description="d", remove=False,
    )
    assert "run_tray.bat" in script
    assert "cmd.exe" in script


def test_lnk_script_remove_deletes_without_creating():
    script = si._lnk_script([r"C:\x\a.lnk", r"C:\y\b.lnk"],
                            target="t", arguments="a", workdir="w",
                            icon="i", description="d", remove=True)
    assert script.count("Remove-Item") == 2
    assert "CreateShortcut" not in script
    assert "SilentlyContinue" in script  # removing twice must not fail


def test_default_target_is_run_tray():
    assert si.DEFAULT_SCRIPT.endswith(os.path.join("windows", "run_tray.bat"))


def test_default_icon_exists():
    assert os.path.isfile(si.ICON)
    assert si.ICON.endswith(".ico")


def test_refuses_to_run_off_windows(monkeypatch):
    monkeypatch.setattr(si, "IS_WINDOWS", False)
    with pytest.raises(OSError, match="Windows"):
        si.create_shortcuts()


def test_reports_missing_icon(monkeypatch, tmp_path):
    monkeypatch.setattr(si, "IS_WINDOWS", True)
    monkeypatch.setattr(si, "ICON", os.path.join(str(tmp_path), "nope.ico"))
    with pytest.raises(FileNotFoundError, match="Icon not found"):
        si.create_shortcuts(icon=os.path.join(str(tmp_path), "nope.ico"))


def test_rejects_bad_where():
    with pytest.raises(ValueError, match="unknown --where"):
        si._shortcut_folders("taskbar")


def test_cli_exits_cleanly_when_not_windows(monkeypatch, capsys):
    monkeypatch.setattr(si, "IS_WINDOWS", False)
    assert si.main(["--where", "desktop"]) == 1
    assert "Windows" in capsys.readouterr().err


def test_folders_resolved_via_powershell(monkeypatch):
    calls = {}

    def fake_run(cmd, **kwargs):
        calls["cmd"] = cmd
        return subprocess.CompletedProcess(cmd, 0, "C:\\Users\\bob\\Desktop\n", "")

    monkeypatch.setattr(si.subprocess, "run", fake_run)
    assert si._shortcut_folders("desktop") == [r"C:\Users\bob\Desktop"]
    joined = " ".join(calls["cmd"])
    assert "GetFolderPath('Desktop')" in joined
    assert "-NoProfile" in joined


def test_create_shortcuts_builds_expected_links(monkeypatch, tmp_path):
    monkeypatch.setattr(si, "IS_WINDOWS", True)
    monkeypatch.setattr(si, "_shortcut_folders",
                        lambda where: [str(tmp_path / "Desktop"),
                                       str(tmp_path / "StartMenu")])
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["script"] = cmd[-1]
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(si.subprocess, "run", fake_run)
    script = os.path.join(str(tmp_path), "run_tray.bat")
    open(script, "w").close()
    icon = os.path.join(str(tmp_path), "i.ico")
    open(icon, "wb").close()

    links = si.create_shortcuts(script=script, icon=icon, where="both")
    assert links == [os.path.join(str(tmp_path), "Desktop", si.DEFAULT_NAME + ".lnk"),
                     os.path.join(str(tmp_path), "StartMenu", si.DEFAULT_NAME + ".lnk")]
    assert "Battery Notifier (Tray).lnk" in seen["script"]
    assert icon in seen["script"]


def test_create_shortcuts_raises_on_powershell_failure(monkeypatch, tmp_path):
    monkeypatch.setattr(si, "IS_WINDOWS", True)
    monkeypatch.setattr(si, "_shortcut_folders", lambda where: [str(tmp_path)])
    monkeypatch.setattr(
        si.subprocess, "run",
        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 1, "", "boom"))
    script = os.path.join(str(tmp_path), "run_tray.bat")
    open(script, "w").close()
    icon = os.path.join(str(tmp_path), "i.ico")
    open(icon, "wb").close()
    with pytest.raises(OSError, match="boom"):
        si.create_shortcuts(script=script, icon=icon)
