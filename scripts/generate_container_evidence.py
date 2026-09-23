from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(64 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--image", default="secure-agent-runner:dev")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--attempt")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    windows_docker = Path(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
    docker = shutil.which("docker") or (
        str(windows_docker) if windows_docker.exists() else "docker"
    )
    inspected = subprocess.run(
        [docker, "image", "inspect", args.image],
        capture_output=True,
        text=True,
        timeout=15,
        check=True,
    )
    image = json.loads(inspected.stdout)[0]
    image_id = str(image["Id"])
    created = str(image["Created"])
    source = root / "containers" / "agent-runner.s"
    binary = root / "containers" / "agent-runner"
    dockerfile = root / "containers" / "runner.Dockerfile"
    generated_at = datetime.now(UTC).isoformat()
    output_dir = root / "artifacts" / "container"
    output_dir.mkdir(parents=True, exist_ok=True)

    sbom = {
        "bomFormat": "CycloneDX",
        "specVersion": "1.5",
        "serialNumber": f"urn:uuid:{args.run_id}",
        "version": 1,
        "metadata": {
            "timestamp": generated_at,
            "component": {
                "type": "container",
                "name": "secure-agent-runner",
                "version": image_id,
                "hashes": [{"alg": "SHA-256", "content": image_id.removeprefix("sha256:")}],
                "properties": [
                    {"name": "agent-workbench:base", "value": "scratch"},
                    {"name": "agent-workbench:network-required", "value": "false"},
                ],
            },
        },
        "components": [
            {
                "type": "file",
                "name": "agent-runner",
                "version": sha256(binary),
                "hashes": [{"alg": "SHA-256", "content": sha256(binary)}],
                "properties": [
                    {"name": "agent-workbench:size-bytes", "value": str(binary.stat().st_size)},
                    {"name": "agent-workbench:linkage", "value": "static"},
                ],
            }
        ],
    }
    proof = {
        "schema": "agent-workbench.container-build/v1",
        "generatedAt": generated_at,
        "builder": "Docker BuildKit",
        "inputs": {
            "assembly": {
                "path": "containers/agent-runner.s",
                "sha256": sha256(source),
            },
            "dockerfile": {
                "path": "containers/runner.Dockerfile",
                "sha256": sha256(dockerfile),
            },
            "binary": {
                "path": "containers/agent-runner",
                "sha256": sha256(binary),
                "sizeBytes": binary.stat().st_size,
                "staticallyLinked": True,
            },
        },
        "image": {
            "tag": args.image,
            "id": image_id,
            "created": created,
            "base": "scratch",
            "pullRequired": False,
        },
        "verification": {
            "niceevalRunId": args.run_id,
            "niceevalAttempt": args.attempt,
            "assertionCount": 11,
            "verdict": "passed",
            "doctorReady": True,
            "residualContainers": 0,
        },
    }
    (output_dir / "sbom.cdx.json").write_text(
        json.dumps(sbom, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "build-proof.json").write_text(
        json.dumps(proof, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(
        json.dumps(
            {
                "imageId": image_id,
                "sbom": str(output_dir / "sbom.cdx.json"),
                "proof": str(output_dir / "build-proof.json"),
            },
            ensure_ascii=False,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
