from __future__ import annotations

import argparse
import hashlib
import os
from pathlib import Path
from urllib.request import urlopen

from agent_workbench.relevance import MMARCO_MINILM_L12_SPEC


REMOTE_FILES = {
    "config.json": "config.json",
    "model.onnx": "onnx/model_quint8_avx2.onnx",
    "special_tokens_map.json": "special_tokens_map.json",
    "tokenizer.json": "tokenizer.json",
    "tokenizer_config.json": "tokenizer_config.json",
}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while block := stream.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download the pinned multilingual relevance verifier."
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    base = (
        f"https://huggingface.co/{MMARCO_MINILM_L12_SPEC.repository}/resolve/"
        f"{MMARCO_MINILM_L12_SPEC.revision}/"
    )
    for local_name, remote_name in REMOTE_FILES.items():
        destination = args.output / local_name
        expected = MMARCO_MINILM_L12_SPEC.file_sha256[local_name]
        if destination.is_file() and _sha256(destination) == expected:
            print(f"verified {local_name}")
            continue
        temporary = destination.with_suffix(destination.suffix + ".part")
        digest = hashlib.sha256()
        try:
            with urlopen(base + remote_name, timeout=60) as response, temporary.open(
                "wb"
            ) as stream:
                while block := response.read(1024 * 1024):
                    stream.write(block)
                    digest.update(block)
            if digest.hexdigest() != expected:
                raise ValueError(f"Checksum mismatch for {local_name}.")
            os.replace(temporary, destination)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"downloaded {local_name}")
    print(
        f"ready {MMARCO_MINILM_L12_SPEC.repository}@"
        f"{MMARCO_MINILM_L12_SPEC.revision}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
