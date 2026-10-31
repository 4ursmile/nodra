#!/usr/bin/env python3
"""Install the `nodra` command from this checkout. Python 3.9+ only, no git, no network, no pip.

    python3 install.py                 write ~/.nodra/bin/nodra, remember this folder, offer to add ~/.nodra/bin to your PATH
    python3 install.py --yes           ... and add it without asking
    python3 install.py --no-path       ... and never touch your shell config (the line to add is printed)
    python3 install.py --uninstall     remove the command and the PATH line (your packages and settings stay; see: nodra self-uninstall)

The command runs `python -m nodra.cli` with this folder on PYTHONPATH, so nothing is copied: updating the folder updates nodra.
Honours NODRA_HOME (default ~/.nodra). Safe to run again.
"""
import json
import os
import re
import stat
import subprocess
import sys

ROOT = os.path.dirname(os.path.abspath(__file__))
BEGIN, END = "# >>> nodra", "# <<< nodra"
WINDOWS = os.name == "nt"


def home_dir():
    return os.environ.get("NODRA_HOME") or os.path.join(os.path.expanduser("~"), ".nodra")


def bin_dir():
    return os.path.join(home_dir(), "bin")


def say(msg=""):
    print(msg)


# ---------------------------------------------------------------- the command

def _fwd(p):
    return p.replace("\\", "/")


def sh_body(root, python):
    return ('#!/bin/sh\n# managed by nodra install.py - run it again to refresh, python3 install.py --uninstall to remove\n'
            'PY="%s"\n[ -x "$PY" ] || PY=python3\nPYTHONPATH="%s${PYTHONPATH:+:$PYTHONPATH}" exec "$PY" -m nodra.cli "$@"\n' % (_fwd(python), _fwd(root)))


def cmd_body(root, python):
    return ('@echo off\r\nrem managed by nodra install.py\r\nset "PYTHONPATH=%s;%%PYTHONPATH%%"\r\n"%s" -m nodra.cli %%*\r\n' % (root, python))


def write_shims(root=ROOT, python=None):
    """-> the files written. POSIX: one sh script. Windows: nodra.cmd (cmd, PowerShell) and an sh twin for Git Bash."""
    python = python or sys.executable or "python3"
    os.makedirs(bin_dir(), exist_ok=True)
    out = []
    sh = os.path.join(bin_dir(), "nodra")
    with open(sh, "w", newline="\n") as f:
        f.write(sh_body(root, python))
    os.chmod(sh, os.stat(sh).st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    out.append(sh)
    if WINDOWS:
        cmd = os.path.join(bin_dir(), "nodra.cmd")
        with open(cmd, "w", newline="") as f:
            f.write(cmd_body(root, python))
        out.append(cmd)
    return out


def remember_root(root=ROOT):
    cfg = os.path.join(home_dir(), "config.json")
    try:
        with open(cfg, encoding="utf-8") as f:
            c = json.load(f)
        if not isinstance(c, dict):
            c = {}
    except (OSError, ValueError):
        c = {}
    c["root"] = root
    os.makedirs(home_dir(), exist_ok=True)
    with open(cfg, "w", encoding="utf-8") as f:
        json.dump(c, f, indent=2)
    return cfg


def forget_root():
    cfg = os.path.join(home_dir(), "config.json")
    try:
        with open(cfg, encoding="utf-8") as f:
            c = json.load(f)
        if isinstance(c, dict) and c.pop("root", None) is not None:
            with open(cfg, "w", encoding="utf-8") as f:
                json.dump(c, f, indent=2)
    except (OSError, ValueError):
        pass


# ---------------------------------------------------------------- PATH

def rc_file():
    """The shell start-up file to put the PATH line in, and its flavour ('sh' or 'fish')."""
    home = os.path.expanduser("~")
    shell = os.path.basename(os.environ.get("SHELL") or "")
    if shell == "zsh":
        return os.path.join(os.environ.get("ZDOTDIR") or home, ".zshrc"), "sh"
    if shell == "fish":
        return os.path.join(home, ".config", "fish", "config.fish"), "fish"
    if shell == "bash":
        mac = sys.platform == "darwin"
        return os.path.join(home, ".bash_profile" if mac and not os.path.exists(os.path.join(home, ".bashrc")) else ".bashrc"), "sh"
    return os.path.join(home, ".profile"), "sh"


def path_block(flavour):
    d = bin_dir()
    line = 'fish_add_path "%s"' % d if flavour == "fish" else 'export PATH="%s:$PATH"' % d
    return "%s\n%s\n%s\n" % (BEGIN, line, END)


def strip_block(text):
    return re.sub(r"\n?%s\n.*?%s\n?" % (re.escape(BEGIN), re.escape(END)), "", text, flags=re.S)


def on_path():
    parts = [os.path.normcase(os.path.normpath(p)) for p in (os.environ.get("PATH") or "").split(os.pathsep) if p]
    return os.path.normcase(os.path.normpath(bin_dir())) in parts


def add_path_posix():
    f, flavour = rc_file()
    try:
        with open(f, encoding="utf-8") as fh:
            text = fh.read()
    except OSError:
        text = ""
    base = strip_block(text)
    if base and not base.endswith("\n"):
        base += "\n"
    new = base + ("\n" if base else "") + path_block(flavour)
    if new == text:
        return f, False
    os.makedirs(os.path.dirname(f), exist_ok=True)
    with open(f, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(new)
    return f, True


def remove_path_posix():
    """Take the block out of every start-up file we might have written to. -> files changed"""
    home = os.path.expanduser("~")
    files = [os.path.join(os.environ.get("ZDOTDIR") or home, ".zshrc"), os.path.join(home, ".bash_profile"), os.path.join(home, ".bashrc"),
             os.path.join(home, ".profile"), os.path.join(home, ".config", "fish", "config.fish")]
    changed = []
    for f in files:
        try:
            with open(f, encoding="utf-8") as fh:
                text = fh.read()
        except OSError:
            continue
        if BEGIN in text:
            with open(f, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(strip_block(text))
            changed.append(f)
    return changed


def _win_path(add):
    """Add or remove bin_dir in the user's PATH (registry). -> True when changed."""
    import winreg
    d = bin_dir()
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_READ | winreg.KEY_WRITE) as k:
        try:
            cur, kind = winreg.QueryValueEx(k, "Path")
        except FileNotFoundError:
            cur, kind = "", winreg.REG_EXPAND_SZ
        parts = [p for p in cur.split(";") if p]
        has = any(os.path.normcase(os.path.normpath(p)) == os.path.normcase(os.path.normpath(d)) for p in parts)
        if add == has:
            return False
        parts = parts + [d] if add else [p for p in parts if os.path.normcase(os.path.normpath(p)) != os.path.normcase(os.path.normpath(d))]
        winreg.SetValueEx(k, "Path", 0, kind, ";".join(parts))
    return True


def ask(question, default=True):
    if not (sys.stdin and sys.stdin.isatty()):
        return None
    try:
        a = input("%s [%s] " % (question, "Y/n" if default else "y/N")).strip().lower()
    except EOFError:
        return None
    return default if not a else a.startswith("y")


def setup_path(yes=False, no_path=False):
    d = bin_dir()
    if no_path or on_path() and not yes:
        if not no_path:
            say("  %s is already on your PATH" % d)
        else:
            say("  PATH left alone. To use 'nodra' anywhere, add this folder to PATH: %s" % d)
        return None
    if yes:
        ok = True
    else:
        ok = ask("Add %s to your PATH (a marked block in your shell config)?" % d, True)
    if not ok:
        f, flavour = (None, "sh") if WINDOWS else rc_file()
        say("  PATH not changed%s. Add it yourself when you like:" % ("" if ok is False else " (no terminal to ask on; use --yes)"))
        say("    " + (path_block(flavour).splitlines()[1] if not WINDOWS else "setx PATH \"%%PATH%%;%s\"" % d))
        return None
    if WINDOWS:
        changed = _win_path(True)
        say("  %s %s in your user PATH" % ("added" if changed else "already", d))
        return "registry"
    f, changed = add_path_posix()
    say("  %s the PATH line %s %s" % ("added" if changed else "kept", "to" if changed else "in", f))
    return f


# ---------------------------------------------------------------- main

def check_python():
    if sys.version_info < (3, 9):
        sys.exit("nodra needs Python 3.9 or newer; this is %s. Install a newer Python and run: python3 install.py" % sys.version.split()[0])


def verify(root=ROOT):
    env = dict(os.environ, PYTHONPATH=root + (os.pathsep + os.environ["PYTHONPATH"] if os.environ.get("PYTHONPATH") else ""))
    try:
        r = subprocess.run([sys.executable, "-m", "nodra.cli", "--version"], env=env, capture_output=True, text=True, timeout=60)
        return r.returncode == 0, (r.stdout or r.stderr).strip()
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)


def install(yes=False, no_path=False):
    check_python()
    if not os.path.isfile(os.path.join(ROOT, "nodra", "cli", "main.py")):
        sys.exit("this folder (%s) does not hold nodra/cli: run install.py from the repository you cloned or unzipped" % ROOT)
    say("Installing nodra from %s" % ROOT)
    files = write_shims()
    cfg = remember_root()
    say("  wrote %s" % ", ".join(files))
    say("  remembered this folder in %s" % cfg)
    setup_path(yes, no_path)
    ok, ver = verify()
    say("  %s" % (ver if ok else "warning: the command did not start: %s" % ver))
    say("")
    say("Done. Open a new terminal (or run: export PATH=\"%s:$PATH\"), then:" % bin_dir() if not WINDOWS else "Done. Open a new terminal, then:")
    say("  nodra chat        start the local chat")
    say("  nodra search      browse the packages")
    say("  nodra doctor      check this machine")
    return 0 if ok else 1


def uninstall():
    removed = []
    for n in ("nodra", "nodra.cmd"):
        f = os.path.join(bin_dir(), n)
        if os.path.exists(f):
            os.remove(f)
            removed.append(f)
    forget_root()
    changed = [] if WINDOWS else remove_path_posix()
    if WINDOWS:
        try:
            if _win_path(False):
                changed.append("user PATH")
        except Exception:
            pass
    say("Removed: %s" % (", ".join(removed + changed) or "nothing (it was not installed)"))
    say("Your settings, packages and sources in %s are untouched. To delete them too, run 'nodra self-uninstall' before uninstalling." % home_dir())
    return 0


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(description="Install the nodra command from this checkout (Python 3.9+, no git needed).")
    ap.add_argument("--yes", "-y", action="store_true", help="add ~/.nodra/bin to PATH without asking")
    ap.add_argument("--no-path", action="store_true", help="do not touch PATH or any shell config")
    ap.add_argument("--uninstall", action="store_true", help="remove the nodra command and the PATH line")
    a = ap.parse_args(argv)
    no_path = a.no_path or os.environ.get("NODRA_NO_MODIFY_PATH", "") not in ("", "0")
    return uninstall() if a.uninstall else install(a.yes, no_path)


if __name__ == "__main__":
    sys.exit(main())
