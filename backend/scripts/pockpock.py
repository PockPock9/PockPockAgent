"""Cross-platform setup and foreground supervisor for local PockPock services."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from urllib.request import urlopen

from pockpock_paths import app_data_dir, migrate_legacy_data


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SERVICES = (
    ("planner", "planner", 8771),
    ("validator", "validator", 8772),
    ("run-store", "run_store", 8773),
    ("browser-automation", "browser_automation", 8774),
    ("agent-verifier", "agent_verifier", 8775),
)
STARTUP_TIMEOUT_SECONDS = 45
MINIMUM_PYTHON = (3, 12)


@dataclass(frozen=True)
class ManagedProcess:
    name: str
    process: subprocess.Popen
    log_path: Path


def venv_python_path(root: Path = REPOSITORY_ROOT, platform_name: str | None = None) -> Path:
    platform_name = platform_name or sys.platform
    scripts_dir = Path("Scripts") if platform_name == "win32" else Path("bin")
    executable = "python.exe" if platform_name == "win32" else "python"
    return root / ".venv" / scripts_dir / executable


def requirements_files(root: Path = REPOSITORY_ROOT) -> list[Path]:
    backend_root = root / "backend"
    files = [backend_root / "scripts" / "requirements-pockpock.txt"]
    files.extend(sorted((backend_root / "projects").rglob("requirements.txt")))
    missing = [path for path in files if not path.is_file()]
    if missing:
        raise RuntimeError(f"Required dependency manifest is missing: {missing[0]}")
    return files


def check_python_version(python: Path) -> None:
    result = subprocess.run(
        [
            str(python),
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    try:
        version = tuple(int(part) for part in result.stdout.strip().split("."))
    except ValueError as err:
        raise RuntimeError(f"Could not read the Python version from {python}.") from err
    if version < MINIMUM_PYTHON:
        required = ".".join(str(part) for part in MINIMUM_PYTHON)
        actual = ".".join(str(part) for part in version)
        raise RuntimeError(f"Python {required} or newer is required; the project environment uses {actual}.")


def install_browser(python: Path, root: Path, attempts: int = 3, delay_seconds: float = 5.0, run=subprocess.run, sleep=time.sleep) -> None:
    """Install Playwright's Chromium, retrying: one slow or failed download should not fail setup (#51)."""
    for attempt in range(1, attempts + 1):
        try:
            run([str(python), "-m", "playwright", "install", "chromium"], cwd=root, check=True)
            return
        except subprocess.CalledProcessError:
            if attempt == attempts:
                raise RuntimeError(
                    f"Could not download the agent browser after {attempts} tries. Check the internet connection, "
                    f"then run '{sys.executable} backend/scripts/pockpock.py setup' again."
                ) from None
            print(f"The agent browser download failed (try {attempt} of {attempts}); trying again.", flush=True)
            sleep(delay_seconds * attempt)


def setup_environment(root: Path = REPOSITORY_ROOT) -> None:
    if sys.version_info[:2] < MINIMUM_PYTHON:
        required = ".".join(str(part) for part in MINIMUM_PYTHON)
        actual = ".".join(str(part) for part in sys.version_info[:2])
        raise RuntimeError(f"Python {required} or newer is required to set up PockPock; found {actual}.")

    python = venv_python_path(root)
    if not python.is_file():
        subprocess.run([sys.executable, "-m", "venv", str(root / ".venv")], cwd=root, check=True)
    if not python.is_file():
        raise RuntimeError(f"Could not create the project Python environment at {root / '.venv'}.")
    check_python_version(python)

    subprocess.run([str(python), "-m", "pip", "install", "--upgrade", "pip"], cwd=root, check=True)
    install_args = [str(python), "-m", "pip", "install"]
    for requirements in requirements_files(root):
        install_args.extend(["-r", str(requirements)])
    subprocess.run(install_args, cwd=root, check=True)
    install_browser(python, root)
    print(f"Backend dependencies are installed in {root / '.venv'}.")
    print("Run this command again with 'start' to launch the local backend services.")


def get_internal_token() -> str:
    data_directory = app_data_dir("PockPock")
    data_directory.mkdir(parents=True, exist_ok=True)
    token_path = data_directory / "services.token"
    try:
        descriptor = os.open(token_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    except FileExistsError:
        token = token_path.read_text(encoding="utf-8").strip()
    else:
        token = secrets.token_urlsafe(32)
        with os.fdopen(descriptor, "w", encoding="utf-8") as token_file:
            token_file.write(token + "\n")
    if os.name != "nt":
        token_path.chmod(0o600)
    if not token:
        raise RuntimeError(f"The internal service token is empty: {token_path}")
    return token


def service_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "POCKPOCK_INTERNAL_TOKEN": get_internal_token(),
            "POCKPOCK_PLANNER_URL": "http://127.0.0.1:8771",
            "POCKPOCK_VALIDATOR_URL": "http://127.0.0.1:8772",
            "POCKPOCK_RUN_STORE_URL": "http://127.0.0.1:8773",
            "POCKPOCK_BROWSER_AUTOMATION_URL": "http://127.0.0.1:8774",
            "POCKPOCK_AGENT_VERIFIER_URL": "http://127.0.0.1:8775",
            "POCKPOCK_PORT": "8766",
        }
    )
    return environment


def service_is_healthy(url: str, expected_service: str) -> bool:
    try:
        with urlopen(url, timeout=1) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (OSError, TimeoutError, ValueError):
        return False
    return isinstance(payload, dict) and payload.get("ok") is True and payload.get("service") == expected_service


def log_tail(path: Path, line_count: int = 30) -> str:
    try:
        return "\n".join(path.read_text(encoding="utf-8", errors="replace").splitlines()[-line_count:])
    except OSError as err:
        return f"Could not read {path}: {err}"


def launch_process(
    name: str,
    command: list[str],
    working_directory: Path,
    environment: dict[str, str],
    log_path: Path,
) -> ManagedProcess:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    options: dict[str, object] = {
        "cwd": working_directory,
        "env": environment,
        "stdin": subprocess.DEVNULL,
        "stdout": None,
        "stderr": subprocess.STDOUT,
    }
    with log_path.open("ab") as log_file:
        options["stdout"] = log_file
        if sys.platform == "win32":
            options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.CREATE_NO_WINDOW
        else:
            options["start_new_session"] = True
        process = subprocess.Popen(command, **options)
    return ManagedProcess(name=name, process=process, log_path=log_path)


def wait_for_service(
    managed: ManagedProcess,
    url: str,
    expected_service: str,
    timeout: int = STARTUP_TIMEOUT_SECONDS,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if service_is_healthy(url, expected_service):
            return
        exit_code = managed.process.poll()
        if exit_code is not None:
            detail = log_tail(managed.log_path)
            raise RuntimeError(
                f"The {managed.name} service exited with code {exit_code}. "
                f"Log: {managed.log_path}\n{detail}"
            )
        time.sleep(0.5)
    detail = log_tail(managed.log_path)
    raise RuntimeError(
        f"The {managed.name} service did not become healthy within {timeout} seconds. "
        f"Log: {managed.log_path}\n{detail}"
    )


def start_service(
    name: str,
    command: list[str],
    working_directory: Path,
    port: int,
    environment: dict[str, str],
    log_directory: Path,
    processes: list[ManagedProcess],
    health_path: str = "/health",
) -> None:
    health_url = f"http://127.0.0.1:{port}{health_path}"
    if service_is_healthy(health_url, name):
        print(f"{name} is already running.")
        return
    managed = launch_process(
        name,
        command,
        working_directory,
        environment,
        log_directory / f"{name}.log",
    )
    processes.append(managed)
    wait_for_service(managed, health_url, name)
    print(f"Started {name} on 127.0.0.1:{port}.")


def stop_processes(processes: list[ManagedProcess]) -> None:
    for managed in reversed(processes):
        if managed.process.poll() is None:
            try:
                managed.process.terminate()
            except ProcessLookupError:
                pass
    for managed in reversed(processes):
        try:
            managed.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            managed.process.kill()
            managed.process.wait(timeout=5)


def start_stack(root: Path = REPOSITORY_ROOT, supervise: bool = True) -> None:
    python = venv_python_path(root)
    if not python.is_file():
        raise RuntimeError(f"Backend dependencies are not installed. Run '{sys.executable} backend/scripts/pockpock.py setup' first.")
    check_python_version(python)

    migrate_legacy_data()  # the data folder was named FrogAI before 2026-11-15
    environment = service_environment()
    log_directory = app_data_dir("PockPock") / "logs"
    projects_root = root / "backend" / "projects"
    log_directory.mkdir(parents=True, exist_ok=True)
    processes: list[ManagedProcess] = []
    try:
        for name, directory, port in SERVICES:
            service_directory = projects_root / directory
            start_service(
                name,
                [str(python), "-m", "uvicorn", "app:app", "--host", "127.0.0.1", "--port", str(port)],
                service_directory,
                port,
                environment,
                log_directory,
                processes,
            )
        start_service(
            "PockPock AI",
            [str(python), "-u", str(root / "backend" / "scripts" / "pockpock_server.py")],
            root,
            8766,
            environment,
            log_directory,
            processes,
            health_path="/api/health",
        )
        if not processes:
            print("All PockPock backend services are already healthy.")
            return
        if not supervise:
            print("All PockPock backend services passed their health checks.")
            return
        print("PockPock backend is ready at http://127.0.0.1:8766. Press Ctrl+C to stop services started by this command.")
        while True:
            for managed in processes:
                exit_code = managed.process.poll()
                if exit_code is not None:
                    detail = log_tail(managed.log_path)
                    raise RuntimeError(
                        f"The {managed.name} service exited with code {exit_code}. "
                        f"Log: {managed.log_path}\n{detail}"
                    )
            time.sleep(1)
    except KeyboardInterrupt:
        print("Stopping PockPock services started by this command.")
    finally:
        stop_processes(processes)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Set up or run the local PockPock backend.")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("setup", help="create the Python environment and install backend/browser dependencies")
    commands.add_parser("start", help="start and supervise the local API and workflow services")
    commands.add_parser("check", help="start the local services, verify health, and stop services started by this command")
    args = parser.parse_args(argv)
    try:
        if args.command == "setup":
            setup_environment()
        elif args.command == "check":
            start_stack(supervise=False)
        else:
            start_stack()
    except subprocess.CalledProcessError as err:
        print(f"Command failed with exit code {err.returncode}: {err.cmd}", file=sys.stderr)
        return err.returncode or 1
    except (OSError, RuntimeError) as err:
        print(f"PockPock backend error: {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
