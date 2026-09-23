from __future__ import annotations

import argparse
from pathlib import Path

from huggingface_hub import snapshot_download

from agent_workbench.embeddings import MODEL_FILE_SHA256, MODEL_REPOSITORY, MODEL_REVISION


def main() -> int:
    parser = argparse.ArgumentParser(description="Download the pinned retrieval model.")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    snapshot_download(
        repo_id=MODEL_REPOSITORY,
        revision=MODEL_REVISION,
        local_dir=args.output,
        allow_patterns=[*MODEL_FILE_SHA256, "README.md"],
    )
    # The application loader performs the same checksum verification.
    from agent_workbench.embeddings import Model2VecEmbeddingProvider

    Model2VecEmbeddingProvider.from_local_path(args.output)
    print(args.output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
