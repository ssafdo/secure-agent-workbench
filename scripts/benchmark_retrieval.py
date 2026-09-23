from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from agent_workbench.embeddings import (
    MODEL_FILE_SHA256,
    MODEL_LICENSE,
    MODEL_REPOSITORY,
    MODEL_REVISION,
    Model2VecEmbeddingProvider,
)
from agent_workbench.retrieval import search_documents


def _citation_is_correct(match: dict[str, Any], documents: dict[str, str]) -> bool:
    path = match.get("path")
    start = match.get("startLine")
    end = match.get("endLine")
    text = match.get("text")
    if not isinstance(path, str) or path not in documents:
        return False
    if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
        return False
    lines = documents[path].splitlines()
    return end <= len(lines) and "\n".join(lines[start - 1 : end]).strip() == text


def evaluate(dataset: Path, provider: Model2VecEmbeddingProvider | None) -> dict[str, Any]:
    payload = json.loads(dataset.read_text(encoding="utf-8"))
    cases = payload["cases"]
    reciprocal_ranks: list[float] = []
    recall_at_1: list[float] = []
    recall_at_3: list[float] = []
    citation_checks: list[bool] = []
    unsupported_checks: list[bool] = []
    case_results = []
    for case in cases:
        documents = {item["path"]: item["content"] for item in case["documents"]}
        result = search_documents(
            case["query"],
            list(documents.items()),
            limit=5,
            embedding_provider=provider,
        )
        matches = result["matches"]
        paths = [match["path"] for match in matches]
        relevant = set(case["relevantPaths"])
        if case["supported"]:
            ranks = [index + 1 for index, path in enumerate(paths) if path in relevant]
            first_rank = min(ranks, default=0)
            reciprocal_ranks.append(0.0 if first_rank == 0 else 1.0 / first_rank)
            recall_at_1.append(float(bool(relevant.intersection(paths[:1]))))
            recall_at_3.append(float(bool(relevant.intersection(paths[:3]))))
        else:
            first_rank = 0
            unsupported_checks.append(not matches)
        citation_checks.extend(
            _citation_is_correct(match, documents) for match in matches
        )
        case_results.append(
            {
                "id": case["id"],
                "mode": result["retrievalMode"],
                "paths": paths,
                "firstRelevantRank": first_rank,
            }
        )

    mean = lambda values: sum(values) / len(values) if values else 1.0
    return {
        "mode": "hybrid" if provider is not None else "lexical",
        "cases": len(cases),
        "recallAt1": round(mean(recall_at_1), 6),
        "recallAt3": round(mean(recall_at_3), 6),
        "mrr": round(mean(reciprocal_ranks), 6),
        "citationCorrectness": round(mean([float(v) for v in citation_checks]), 6),
        "unsupportedAccuracy": round(mean([float(v) for v in unsupported_checks]), 6),
        "caseResults": case_results,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark lexical and hybrid retrieval.")
    parser.add_argument(
        "--dataset",
        type=Path,
        default=Path("benchmarks/retrieval_cases.json"),
    )
    parser.add_argument("--model-path", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--require-improvement", action="store_true")
    args = parser.parse_args()
    lexical = evaluate(args.dataset, None)
    results: dict[str, Any] = {
        "schemaVersion": 1,
        "dataset": {
            "path": str(args.dataset).replace("\\", "/"),
            "sha256": hashlib.sha256(args.dataset.read_bytes()).hexdigest(),
        },
        "lexical": lexical,
    }
    if args.model_path is not None:
        provider = Model2VecEmbeddingProvider.from_local_path(args.model_path)
        hybrid = evaluate(args.dataset, provider)
        results["model"] = {
            "repository": MODEL_REPOSITORY,
            "revision": MODEL_REVISION,
            "license": MODEL_LICENSE,
            "fileSha256": MODEL_FILE_SHA256,
        }
        results["hybrid"] = hybrid
        if args.require_improvement and not (
            hybrid["recallAt1"] > lexical["recallAt1"]
            and hybrid["mrr"] > lexical["mrr"]
            and hybrid["citationCorrectness"] == 1.0
            and hybrid["unsupportedAccuracy"] == 1.0
        ):
            print(json.dumps(results, ensure_ascii=False, indent=2))
            return 1
    rendered = json.dumps(results, ensure_ascii=False, indent=2)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
