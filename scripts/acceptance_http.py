"""Start an isolated local demo backend, exercise real HTTP, and stop the owned process."""
from __future__ import annotations

from datetime import datetime
import argparse
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4

import httpx

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--executable", type=Path, help="Check a frozen backend instead of the source package")
    args = parser.parse_args()
    backend = [str(args.executable.resolve())] if args.executable else [sys.executable, "-m", "local_vision_solver"]
    run = ROOT / ".cache" / "acceptance-http" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6])
    run.mkdir(parents=True)
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    base = f"http://127.0.0.1:{port}"
    config = run / "config.toml"
    config.write_text('[pipeline]\nsession_directory = "sessions"\n[server]\n'
                      f'host = "127.0.0.1"\nport = {port}\nadvertise = false\n', encoding="utf-8")
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
    flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
    with (run / "server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([*backend, "--config", str(config),
                                    "serve", "--demo", "--no-discovery"], cwd=ROOT, env=env,
                                   stdout=log, stderr=subprocess.STDOUT, creationflags=flags)
        try:
            deadline = time.monotonic() + 20
            with httpx.Client(trust_env=False, follow_redirects=False, timeout=1) as client:
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError(f"Demo server exited ({process.returncode}); see {run / 'server.log'}")
                    try:
                        health = client.get(base + "/health")
                        if health.status_code == 200 and health.json().get("demo"):
                            break
                    except (httpx.HTTPError, ValueError):
                        pass
                    time.sleep(.1)
                else:
                    raise RuntimeError(f"Demo server did not start; see {run / 'server.log'}")
            result = subprocess.run([sys.executable, "scripts/smoke_api.py", "--url", base, "--output", str(run)],
                                    cwd=ROOT, env=env, check=False, capture_output=True, text=True, encoding="utf-8")
            if result.returncode:
                print(result.stdout + result.stderr, file=sys.stderr)
                return result.returncode
            report = json.loads((run / "report.json").read_text(encoding="utf-8"))
            print(f"real HTTP: PASS; pages={report['pages_uploaded']}; checksum={report['checksum_verified']}; demo=True")
            print(f"report: {(run / 'report.json').relative_to(ROOT)}")
            return 0
        finally:
            # Stop only the child started by this script; never an existing user's backend.
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
