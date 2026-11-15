"""Start the worker and web app on the local computer."""
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not (root / "frontend" / "dist" / "index.html").is_file():
        parser.exit(2, "Build the frontend first using npm ci and npm run build in frontend.\n")
    worker = subprocess.Popen([sys.executable, "-m", "app.worker"], cwd=root)
    try:
        return subprocess.call([sys.executable, "-m", "uvicorn", "app.main:app",
                                "--host", "127.0.0.1", "--port", str(args.port)], cwd=root)
    except KeyboardInterrupt:
        return 0
    finally:
        if worker.poll() is None:
            worker.terminate()
            try:
                worker.wait(timeout=5)
            except subprocess.TimeoutExpired:
                worker.kill()
                worker.wait()


if __name__ == "__main__":
    raise SystemExit(main())
