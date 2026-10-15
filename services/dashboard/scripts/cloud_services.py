"""Development-machine process manager; production uses Docker restart policies."""

import argparse
import json
import os
from pathlib import Path
import signal
import subprocess
import sys

SERVICE = Path(__file__).resolve().parents[1]
ROOT = SERVICE.parents[1]
RUNTIME = ROOT / "runtime"


def pid(service):
    path = RUNTIME / f"{service}.pid"
    try:
        number = int(path.read_text())
        command = Path(f"/proc/{number}/cmdline").read_bytes()
        return number if f"myquant-{service}".encode() in command else None
    except (OSError, ValueError):
        return None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=["start", "stop", "status"])
    parser.add_argument("--service", choices=["web", "worker", "all"], default="all")
    args = parser.parse_args()
    RUNTIME.mkdir(exist_ok=True, mode=0o700)
    environment = {**os.environ, "MYQUANT_RUNTIME": str(RUNTIME),
                   "RESEARCH_PROTOCOL": str(ROOT / "research/protocol.json")}
    for service in ["worker", "web"]:
        if args.service not in ("all", service):
            continue
        previous = pid(service)
        if args.action == "start" and previous is None:
            log = RUNTIME / f"{service}.log"
            stream = log.open("a")
            log.chmod(0o600)
            command = [str(SERVICE / ".venv/bin" / f"myquant-{service}")]
            process = subprocess.Popen(command, cwd=SERVICE, env=environment,
                                       stdout=stream, stderr=stream, start_new_session=True)
            stream.close()
            (RUNTIME / f"{service}.pid").write_text(str(process.pid))
        elif args.action == "stop" and previous is not None:
            os.kill(previous, signal.SIGTERM)
    print(json.dumps({name: {"pid": pid(name), "running": pid(name) is not None} for name in ["web", "worker"]}))


if __name__ == "__main__":
    main()
