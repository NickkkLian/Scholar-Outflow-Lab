#!/usr/bin/env python3
"""
launchd entry shim — it does exactly one thing: start daily.sh.

## Why this layer exists (don't remove it)

Folders such as Desktop are protected by macOS TCC, and **TCC grants access per executable**.
A LaunchAgent that runs `/bin/bash` directly gets blocked from reading scripts in such a folder
and dies with **exit code 126**. Observed first-hand: the first registration of
com.scholaroutflow.daily failed exactly like that (runs=1, exit 126), while another agent on
the same machine using a project venv's python had run 13 times with exit 0.

So the plist points at that **already-authorised python**, which spawns bash — child processes
inherit the authorisation under the responsible-process rule. No second round of per-executable
approvals needed.

## Fragility (written down so a future failure isn't a mystery)

This depends on the TCC grant held by the Python interpreter the plist names (a virtualenv's python on
the maintainer's machine). If that venv is rebuilt or deleted, the grant may go with it and this job
reverts to 126. The self-check below **reports
that case explicitly** instead of failing silently — "no error" is not the same as "working".
"""

import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "scripts", "daily.sh")
LOG = os.path.join(ROOT, "data", "daily.log")


def log(msg):
    line = f"[{time.strftime('%F %T')}] {msg}"
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a") as f:
            f.write(line + "\n")
    except OSError:
        pass          # if even the log can't be written, the self-check below reports why


def main():
    # Self-check: can the project directory actually be read? Under a TCC block this fails
    # here, instead of daily.sh half-running and spinning on nothing.
    try:
        os.listdir(ROOT)
    except PermissionError:
        log(f"⛔ TCC block: cannot read {ROOT}. "
            "This job relies on the TCC grant of the Python interpreter named in the LaunchAgent plist; "
            "if that venv was rebuilt or deleted, the grant went with it. "
            "Fix: grant access to a dedicated .app whose main executable is a real Mach-O "
            "binary (a shell script will not do).")
        return 126

    if not os.path.exists(SCRIPT):
        log(f"⛔ {SCRIPT} not found")
        return 127

    r = subprocess.run(["/bin/bash", SCRIPT], cwd=ROOT)
    if r.returncode != 0:
        log(f"daily.sh exited with {r.returncode}")
    return r.returncode


if __name__ == "__main__":
    sys.exit(main())
