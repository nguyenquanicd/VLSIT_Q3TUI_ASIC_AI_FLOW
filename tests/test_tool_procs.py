"""A tool's leftovers: what it started and left running is stopped when it is done (eda/base.run_command: VC Static's server kept 25 GB after its shell crashed)."""

import os
import time

from q3tui.eda.base import run_command


def test_what_a_tool_leaves_running_is_stopped_when_it_exits(tmp_path):
    pid_file = tmp_path / "child.pid"
    t0 = time.monotonic()
    rc, out, _, timed_out = run_command(["sh", "-c", f"sleep 60 >/dev/null 2>&1 & echo $! > {pid_file}; echo started"], tmp_path, tmp_path / "t.log", 30)
    assert rc == 0 and not timed_out and "started" in out and time.monotonic() - t0 < 15
    pid = int(pid_file.read_text())
    time.sleep(0.2)
    try:
        os.kill(pid, 0)
        gone = open(f"/proc/{pid}/stat").read().split()[2] == "Z"  # (a zombie waiting for init is gone)
    except (ProcessLookupError, FileNotFoundError):
        gone = True
    assert gone
    assert "process(es) the tool left running were stopped" in (tmp_path / "t.log").read_text()


def test_a_tool_that_leaves_nothing_says_nothing(tmp_path):
    rc, out, _, _ = run_command(["sh", "-c", "echo hi"], tmp_path, tmp_path / "t.log", 30)
    assert rc == 0 and "left running" not in (tmp_path / "t.log").read_text()
