"""Install or update the PockPock permission plugin in the local OpenClaw installation.

Run from the repository root:

    .venv\\Scripts\\python.exe backend\\projects\\openclaw_bridge\\install_plugin.py

It copies ``plugin/pockpock-permissions.ts`` to ``~/.openclaw/policies/``, points
``plugins.load.paths`` at the copy, enables the plugin, and reloads it (restarting the OpenClaw
gateway when an in-place reload is not possible). Other entries already in
``plugins.load.paths`` are kept. Rerun it after changing the plugin source.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from bridge import openclaw_state_dir

PLUGIN_ID = "pockpock-permissions"
SOURCE = Path(__file__).with_name("plugin") / f"{PLUGIN_ID}.ts"


def run(openclaw: str, *arguments: str) -> subprocess.CompletedProcess:
    return subprocess.run([openclaw, *arguments], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=120)


def main() -> int:
    openclaw = shutil.which("openclaw")
    if not openclaw:
        print("OpenClaw is not installed. Install it first: npm install -g openclaw@latest")
        return 1
    state_dir = openclaw_state_dir()
    target = state_dir / "policies" / SOURCE.name
    target.parent.mkdir(parents=True, exist_ok=True)
    (state_dir / "pockpock").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(SOURCE, target)
    print(f"Copied plugin to {target}")

    current = run(openclaw, "config", "get", "plugins.load.paths", "--json")
    try:
        paths = json.loads(current.stdout) if current.returncode == 0 else []
    except ValueError:
        paths = []
    if not isinstance(paths, list):
        paths = []
    plugin_path = target.as_posix()
    if not any(Path(str(entry)).as_posix().lower() == plugin_path.lower() for entry in paths):
        paths.append(plugin_path)
    steps = (
        ("config", "set", "plugins.load.paths", json.dumps(paths), "--strict-json"),
        ("config", "set", f"plugins.entries.{PLUGIN_ID}.enabled", "true", "--strict-json"),
        ("plugins", "reload", PLUGIN_ID),
    )
    for step in steps:
        result = run(openclaw, *step)
        if result.returncode != 0:
            # On Windows the in-place reload needs symlink permission and usually fails, and it
            # also fails when the gateway is stopped. A restart loads the new source either way.
            if step[0] == "plugins":
                restart = run(openclaw, "gateway", "restart")
                if restart.returncode == 0:
                    print("Restarted the OpenClaw gateway to load the plugin.")
                else:
                    print("The gateway could not be reloaded or restarted. Run: openclaw gateway restart")
                continue
            print(f"openclaw {' '.join(step[:3])} failed:\n{(result.stderr or result.stdout).strip()[-600:]}")
            return 1
    print("Permission plugin installed and enabled. Check PockPock: the OpenClaw status chip should read Ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
