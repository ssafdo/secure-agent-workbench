from __future__ import annotations

import argparse
import json
import os
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()

    receipt: dict[str, object] | None = None
    for raw_line in args.receipt.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(raw_line)
        except json.JSONDecodeError:
            continue
        if not isinstance(value, dict):
            continue
        nested = value.get("receipt")
        if value.get("type") == "receipt" and isinstance(nested, dict):
            receipt = nested
        elif "completion" in value:
            receipt = value
    if receipt is None:
        raise SystemExit("NiceEval output did not contain a receipt.")
    if receipt.get("completion") != "completed":
        raise SystemExit(f"NiceEval completion was {receipt.get('completion')!r}.")
    run_ids = receipt.get("createdRunIds", receipt.get("runIds"))
    if not isinstance(run_ids, list) or len(run_ids) != 1 or not isinstance(run_ids[0], str):
        raise SystemExit("NiceEval receipt must contain exactly one created Run ID.")
    run_id = run_ids[0]
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"run_id={run_id}\n")
    print(run_id)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
