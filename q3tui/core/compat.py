"""The few places where Linux and Windows differ, decided at run time (`sys.platform`): file locks, process groups, interrupts.

Everything else in Q3TUI is portable Python; code that needs one of these calls this module instead of `fcntl` / `os.killpg`.
"""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from typing import IO, Any

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    import msvcrt
else:
    import fcntl


# -- file locks (one writer at a time, between processes) ------------------------------------------------------------


def lock_file(fh: IO[Any]) -> None:
    """Exclusive lock on an open file, waiting until it is free; released by `unlock_file` or when the file is closed."""
    if not IS_WINDOWS:
        fcntl.flock(fh, fcntl.LOCK_EX)
        return
    fh.seek(0)
    while True:
        try:
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # (LK_LOCK gives up after ten seconds; a writer may wait longer)
            return
        except OSError:
            time.sleep(0.05)


def unlock_file(fh: IO[Any]) -> None:
    if not IS_WINDOWS:
        fcntl.flock(fh, fcntl.LOCK_UN)
        return
    fh.seek(0)
    try:
        msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


# -- process groups: a tool and everything it starts -------------------------------------------------------------------


def group_kwargs() -> dict[str, Any]:
    """`subprocess.Popen` arguments that put the child in a group of its own (killed and interrupted as one)."""
    if IS_WINDOWS:
        return {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session": True}


def kill_group(pid: int) -> None:
    """Kill the process `pid` started with `group_kwargs()` and all its children; a process that is gone is not an error."""
    if IS_WINDOWS:
        subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
        return
    try:
        os.killpg(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def interrupt(pid: int) -> None:
    """The Ctrl-C of a child started with `group_kwargs()`: it cancels what it runs and records that."""
    os.kill(pid, signal.CTRL_BREAK_EVENT if IS_WINDOWS else signal.SIGINT)


def install_interrupt_handler() -> None:
    """Windows delivers the interrupt as Ctrl-Break: make it the same KeyboardInterrupt as Ctrl-C."""
    if IS_WINDOWS:
        signal.signal(signal.SIGBREAK, signal.default_int_handler)


def stop_group(pgid: int, grace_s: float = 3.0) -> int:
    """After a tool ended: stop what it left running in its group (gently, then for sure). Returns how many were left; Windows
    cannot list a group once its leader is gone, so the tree was already killed with `kill_group` and this returns 0."""
    if IS_WINDOWS:
        return 0
    from pathlib import Path

    def members() -> list[int]:
        out = []
        for d in Path("/proc").iterdir() if Path("/proc").is_dir() else []:
            if d.name.isdigit():
                try:
                    if os.getpgid(int(d.name)) == pgid:
                        out.append(int(d.name))
                except OSError:
                    pass
        return out

    try:
        os.killpg(pgid, 0)
    except (ProcessLookupError, PermissionError):
        return 0
    left = len(members()) or 1
    for sig, wait in ((signal.SIGTERM, grace_s), (signal.SIGKILL, 1.0)):
        try:
            os.killpg(pgid, sig)
        except (ProcessLookupError, PermissionError):
            return left
        end = time.monotonic() + wait
        while time.monotonic() < end:
            try:
                os.killpg(pgid, 0)
            except (ProcessLookupError, PermissionError):
                return left
            time.sleep(0.1)
    return left


# -- text encoding ------------------------------------------------------------------------------------------------------


def ensure_utf8_mode() -> None:
    """Windows opens text files in the console's code page (cp1252) unless Python runs in UTF-8 mode; Q3TUI's files (specs,
    prompts, reports) are UTF-8. Start the same command again in UTF-8 mode (once) and pass its exit code on. Linux: nothing to do.
    The variable is also inherited by the runs the TUI starts."""
    if not IS_WINDOWS or sys.flags.utf8_mode:
        return
    env = {**os.environ, "PYTHONUTF8": "1", "PYTHONIOENCODING": "utf-8"}
    argv = [sys.executable, "-X", "utf8", "-m", "q3tui.core.cli", *sys.argv[1:]]  # (the console script is an .exe: not a script to pass on)
    raise SystemExit(subprocess.call(argv, env=env))
