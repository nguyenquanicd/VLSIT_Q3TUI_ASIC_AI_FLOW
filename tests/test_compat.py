"""core/compat.py: file locks and process groups on the platform the tests run on."""

import subprocess
import sys
import time

from q3tui.core import compat


def test_a_file_lock_is_exclusive_between_processes(tmp_path):
    path = tmp_path / "x.lock"
    code = ("import sys, time\nfrom q3tui.core.compat import lock_file\n"
            "fh = open(sys.argv[1], 'a'); lock_file(fh); print('locked', flush=True); time.sleep(1.5)\n")
    other = subprocess.Popen([sys.executable, "-c", code, str(path)], stdout=subprocess.PIPE, text=True)
    assert other.stdout.readline().strip() == "locked"
    start = time.monotonic()
    with open(path, "a") as fh:
        compat.lock_file(fh)  # waits for the other process to end
        compat.unlock_file(fh)
    assert time.monotonic() - start > 0.5
    other.wait()


def test_kill_group_ends_a_tool_and_its_children():
    code = "import subprocess, sys, time\nsubprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\ntime.sleep(60)\n"
    proc = subprocess.Popen([sys.executable, "-c", code], **compat.group_kwargs())
    time.sleep(1)
    compat.kill_group(proc.pid)
    assert proc.wait(timeout=10) is not None
    compat.kill_group(proc.pid)  # already gone: not an error
    assert compat.stop_group(proc.pid) == 0
