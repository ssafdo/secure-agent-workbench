from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
from pathlib import Path


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-image", action="store_true")
    parser.add_argument("--image", default="secure-agent-runner:dev")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    proof = json.loads(
        (root / "artifacts" / "container" / "build-proof.json").read_text(
            encoding="utf-8"
        )
    )
    sbom = json.loads(
        (root / "artifacts" / "container" / "sbom.cdx.json").read_text(
            encoding="utf-8"
        )
    )
    require(proof.get("schema") == "agent-workbench.container-build/v1", "Bad proof schema.")
    require(sbom.get("bomFormat") == "CycloneDX", "Bad SBOM format.")
    require(sbom.get("specVersion") == "1.5", "Bad SBOM version.")

    inputs = proof["inputs"]
    for key in ("assembly", "dockerfile", "binary"):
        item = inputs[key]
        path = root / item["path"]
        require(path.is_file(), f"Missing evidence input: {item['path']}")
        require(sha256(path) == item["sha256"], f"Hash mismatch: {item['path']}")
    require(inputs["binary"]["sizeBytes"] == (root / inputs["binary"]["path"]).stat().st_size, "Binary size mismatch.")
    require(inputs["binary"]["staticallyLinked"] is True, "Runner is not marked static.")

    image_id = proof["image"]["id"]
    require(image_id.startswith("sha256:") and len(image_id) == 71, "Bad image ID.")
    require(proof["image"]["base"] == "scratch", "Unexpected base image.")
    require(proof["image"]["pullRequired"] is False, "Build unexpectedly requires pulling.")
    require(sbom["metadata"]["component"]["version"] == image_id, "SBOM image mismatch.")
    require(sbom["components"][0]["hashes"][0]["content"] == inputs["binary"]["sha256"], "SBOM binary hash mismatch.")

    verification = proof["verification"]
    require(verification["verdict"] == "passed", "NiceEval verdict is not passed.")
    require(verification["doctorReady"] is True, "Container doctor was not ready.")
    require(verification["residualContainers"] == 0, "Residual containers were reported.")
    require(verification["assertionCount"] == 11, "Unexpected assertion count.")

    if args.require_image:
        windows_docker = Path(r"C:\Program Files\Docker\Docker\resources\bin\docker.exe")
        docker = shutil.which("docker") or (
            str(windows_docker) if windows_docker.exists() else "docker"
        )
        inspected = subprocess.run(
            [docker, "image", "inspect", "--format", "{{.Id}}", args.image],
            capture_output=True,
            text=True,
            timeout=15,
            check=True,
        )
        require(inspected.stdout.strip() == image_id, "Local Docker image does not match proof.")

    print(
        json.dumps(
            {
                "status": "verified",
                "imageId": image_id,
                "niceevalRunId": verification["niceevalRunId"],
                "assertions": verification["assertionCount"],
            }
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
