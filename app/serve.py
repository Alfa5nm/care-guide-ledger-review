"""Supervise the web process and worker on the single Railway volume."""
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from . import db
from .security import HOSTED, validate_configuration


def main():
    validate_configuration()
    if "RAILWAY_ENVIRONMENT" in os.environ:
        volume = Path(os.environ["RAILWAY_VOLUME_MOUNT_PATH"]).resolve()
        if not db.ROOT.is_relative_to(volume):
            raise RuntimeError("Railway storage must be on the persistent volume.")
    db.initialize()
    worker_env = os.environ.copy()
    if HOSTED:
        worker_env = {
            key: value for key, value in os.environ.items()
            if key in {"PATH", "HOME", "LANG", "DOCINTEL_DATA", "PYTHONUNBUFFERED", "TMPDIR"}
        }
    commands = [
        (["-m", "app.worker"], worker_env),
        (["-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port",
          os.getenv("PORT", "8000"), "--no-access-log"], os.environ),
    ]
    children = []
    stopping = False

    def stop(_signal, _frame):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        for command, env in commands:
            children.append(subprocess.Popen([sys.executable, *command], env=env))
        while not stopping:
            if any(child.poll() is not None for child in children):
                raise SystemExit("A Ledger Review process stopped.")
            time.sleep(0.25)
    finally:
        for child in children:
            if child.poll() is None:
                child.terminate()
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                child.kill()
                child.wait()


if __name__ == "__main__":
    main()
