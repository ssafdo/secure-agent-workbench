from __future__ import annotations

import argparse
import hmac
import ipaddress
import json
import re
import secrets
import subprocess
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path


def wsl_path(path: Path) -> str:
    resolved = path.resolve()
    drive = resolved.drive.rstrip(":").lower()
    if len(drive) != 1:
        raise ValueError("The repository must be on a Windows drive for WSL evaluation.")
    remainder = resolved.as_posix().split(":", 1)[1].lstrip("/")
    return f"/mnt/{drive}/{remainder}"


def parse_wsl_gateway(route: str) -> str:
    match = re.search(r"(?:^|\s)via\s+((?:\d{1,3}\.){3}\d{1,3})(?:\s|$)", route)
    if not match:
        raise RuntimeError("WSL did not report a Windows gateway address.")
    gateway = match.group(1)
    try:
        ipaddress.IPv4Address(gateway)
    except ipaddress.AddressValueError as exc:
        raise RuntimeError("WSL reported an invalid Windows gateway address.") from exc
    return gateway


def wsl_gateway(distro: str) -> str:
    result = subprocess.run(
        [
            "wsl",
            "-d",
            distro,
            "--",
            "ip",
            "-4",
            "route",
            "show",
            "default",
        ],
        capture_output=True,
        timeout=15,
        check=True,
    )
    route = result.stdout.decode("utf-8", errors="replace")
    return parse_wsl_gateway(route)


def make_handler(repository_root: Path, token: str):
    smoke_script = repository_root / "scripts" / "container-smoke.ps1"

    class SmokeHandler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_POST(self) -> None:
            supplied = self.headers.get("authorization", "")
            if self.path != "/smoke" or not hmac.compare_digest(
                supplied, f"Bearer {token}"
            ):
                self.send_error(HTTPStatus.NOT_FOUND)
                return
            completed = subprocess.run(
                [
                    "pwsh",
                    "-NoProfile",
                    "-NonInteractive",
                    "-File",
                    str(smoke_script),
                ],
                cwd=repository_root,
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
            lines = [line for line in completed.stdout.splitlines() if line.strip()]
            try:
                payload = json.loads(lines[-1])
            except (IndexError, json.JSONDecodeError):
                payload = {
                    "status": "failed",
                    "error": "Container smoke did not return valid JSON.",
                }
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            status = HTTPStatus.OK if completed.returncode == 0 else HTTPStatus.BAD_GATEWAY
            self.send_response(status)
            self.send_header("content-type", "application/json; charset=utf-8")
            self.send_header("content-length", str(len(body)))
            self.send_header("cache-control", "no-store")
            self.send_header("x-content-type-options", "nosniff")
            self.end_headers()
            self.wfile.write(body)

    return SmokeHandler


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--distro", default="NiceEval-Ubuntu")
    args = parser.parse_args()

    repository_root = Path(__file__).resolve().parent.parent
    artifacts = repository_root / "artifacts" / "container"
    artifacts.mkdir(parents=True, exist_ok=True)
    gateway = wsl_gateway(args.distro)
    token = secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(
        (gateway, 0), make_handler(repository_root, token)
    )
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    niceeval_root = f"{wsl_path(repository_root)}/niceeval"
    command = (
        f"cd {niceeval_root} && set -o pipefail; "
        "pnpm exec niceeval exp container container/smoke --rerun all --json "
        "--junit ../artifacts/container/niceeval-junit.xml "
        "| tee ../artifacts/container/niceeval.ndjson; "
        "exit ${PIPESTATUS[0]}"
    )
    try:
        completed = subprocess.run(
            [
                "wsl",
                "-d",
                args.distro,
                "--",
                "env",
                f"AGENT_WORKBENCH_CONTAINER_BRIDGE_URL=http://{gateway}:{port}",
                f"AGENT_WORKBENCH_CONTAINER_BRIDGE_TOKEN={token}",
                "bash",
                "-lc",
                command,
            ],
            cwd=repository_root,
            timeout=120,
            check=False,
        )
        return completed.returncode
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


if __name__ == "__main__":
    raise SystemExit(main())
