"""Windows only: run a service inside a hidden console that everything it starts shares.

The desktop app starts this helper with no console window (CREATE_NO_WINDOW). The service
started here inherits that hidden console, and so does every process the service starts
later. Without it, a process that has no console at all (such as one started detached)
gives each console child it starts a new, visible window. The venv's python.exe is such a
case: it is only a launcher that starts the real interpreter as a child process.

The service is not placed in the app's kill-on-close job, so it keeps running after the
app exits when the app is set to leave services running. This helper waits for the
service and exits with its exit code, so the app can still tell when a service crashed.

Usage: python hidden_launch.py <log file> -- <command> [arguments...]
"""

from __future__ import annotations

import subprocess
import sys


def parse_arguments(argv: list[str]) -> tuple[str, list[str]]:
    if len(argv) < 3 or argv[1] != "--":
        raise SystemExit("usage: hidden_launch.py <log file> -- <command> [arguments...]")
    return argv[0], argv[2:]


def main(argv: list[str]) -> int:
    log_path, command = parse_arguments(argv)
    with open(log_path, "ab") as log:
        process = subprocess.Popen(
            command,
            stdin=subprocess.DEVNULL,
            stdout=log,
            stderr=subprocess.STDOUT,
            creationflags=getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0),
        )
    try:
        return process.wait()
    except KeyboardInterrupt:
        return process.wait()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
