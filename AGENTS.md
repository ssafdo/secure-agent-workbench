# Project Rules

## WHAT

Secure Agent Workbench is a small platform core for running specialized agents in isolated project workspaces. Phase 18 adds independent dual annotation and third-reviewer adjudication before the local-only blind-routing protocol for deidentified natural tasks. Private candidates, annotations, datasets, manifests, and results must never enter Git, NiceEval, or CI. It preserves the 50 curated bilingual routing set and separate end-to-end single-agent ablation, and builds on the official-SDK MCP boundary, measured hybrid retrieval, private GitHub CI evidence workflow, hard-gated Docker executor, same-origin browser workbench, provider-neutral model loop, versioned sessions, and optional OpenAI-compatible or DeepSeek Responses providers.

## WHY

- A project may only read or write beneath its own workspace.
- Read operations can run automatically; write operations require explicit approval.
- Network and process execution remain disabled by default; process execution may only be registered through the digest-pinned, no-network container executor.
- Every tool attempt, including denied and failed calls, must be traceable.
- Never put API keys, model keys, or user secrets in prompts, traces, fixtures, or source control.

## HOW

From the project root in PowerShell:

```powershell
$env:PYTHONPATH = "src"
python -m agent_workbench demo
python -m agent_workbench inspect --project-id <project-id>
```

## TEST

Run this after every behavior change:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

Security changes require a negative test. File-system changes must cover absolute paths, `..` traversal, and symlink or junction escape where the operating system permits creating one.

Natural-task blind evaluation requires explicit human review and deidentification. Automated sensitive-data scanning is only a secondary guard. Seal the dataset before changing routing code, and never weaken the hash checks or print task text in results.

Category, routing specialist, and error-cost labels must come from two distinct pseudonymous reviewers who cannot see each other's labels. Every disagreement requires a distinct third adjudicator; do not silently drop difficult cases to improve agreement.
