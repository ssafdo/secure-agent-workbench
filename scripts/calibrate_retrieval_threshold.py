from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
SOURCE_ROOT = REPOSITORY_ROOT / "src"
for path in (REPOSITORY_ROOT, SOURCE_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from agent_workbench.embeddings import Model2VecEmbeddingProvider
from scripts.benchmark_retrieval import evaluate


def calibrate(dataset: Path, model_paths: list[Path]) -> dict[str, object]:
    candidates = [round(value / 100, 2) for value in range(0, 81, 2)]
    rows: list[dict[str, object]] = []
    for model_path in model_paths:
        provider = Model2VecEmbeddingProvider.from_local_path(model_path)
        for threshold in candidates:
            result = evaluate(
                dataset,
                provider,
                minimum_hybrid_score=threshold,
            )
            supported_rate = result["allRelevantInTop3Rate"]
            unsupported_rate = result["unsupportedAccuracy"]
            balanced_score = round((supported_rate + unsupported_rate) / 2, 6)
            rows.append(
                {
                    "model": {
                        "repository": provider.spec.repository,
                        "revision": provider.spec.revision,
                        "license": provider.spec.license,
                        "fileSha256": provider.spec.file_sha256,
                    },
                    "threshold": threshold,
                    "supportedAllRelevantInTop3": supported_rate,
                    "unsupportedAccuracy": unsupported_rate,
                    "balancedScore": balanced_score,
                    "mrr": result["mrr"],
                    "passRate": result["passRate"],
                }
            )
    eligible = [
        row for row in rows if row["supportedAllRelevantInTop3"] >= 0.7
    ]
    pool = eligible or rows
    selected = max(
        pool,
        key=lambda row: (
            row["balancedScore"],
            row["unsupportedAccuracy"],
            row["supportedAllRelevantInTop3"],
            row["mrr"],
            -row["threshold"],
        ),
    )
    return {
        "schemaVersion": 1,
        "dataset": {
            "path": str(dataset).replace("\\", "/"),
            "sha256": hashlib.sha256(dataset.read_bytes()).hexdigest(),
            "split": "development",
        },
        "selectionRule": {
            "objective": "maximize mean(all-relevant-in-top3, unsupported-accuracy)",
            "minimumSupportedCoverage": 0.7,
            "tieBreakers": [
                "unsupportedAccuracy",
                "supportedAllRelevantInTop3",
                "mrr",
                "lowerThreshold",
            ],
        },
        "selected": selected,
        "candidates": rows,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Choose a hybrid acceptance threshold on a development-only set."
    )
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument(
        "--model-path", type=Path, action="append", required=True
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = calibrate(args.dataset, args.model_path)
    rendered = json.dumps(result, ensure_ascii=False, indent=2)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
