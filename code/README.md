# Support Triage Pipeline

This directory contains the Python implementation for the HackerRank Orchestrate support-ticket agent.

The codebase is organized so the entrypoint scripts stay at the root of `code/`, while the implementation details are grouped by responsibility:

```text
code/
├── main.py                  # Batch entrypoint used for production runs
├── evaluate_sample.py       # Sample-set evaluator for categorical accuracy
├── manual_regressions.py    # High-risk manual regression checks
├── inspect_output.py        # Output-quality inspection against a baseline
├── core/                    # Shared config, schema, and taxonomy code
├── retrieval/               # Corpus parsing, chunking, retrieval, and reranking
├── triage/                  # Deterministic orchestration, safety, and reply building
├── ai/                      # Optional provider wrapper and AI-overlay validation
└── .cache/                  # Local cache artifacts and AI trace output
```

## Requirements

- Python 3.14 was used in this workspace, but any modern Python 3.x runtime that supports the current `pydantic` version should work.
- One external Python dependency is required for the current implementation: `pydantic`.
- The deterministic baseline works without any LLM API keys.
- Optional AI modes read configuration from `code/.env` if present.

## Setup

From the repository root:

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install pydantic
```

```bash
python -m venv .venv
source .venv/bin/activate
pip install pydantic
```

Optional environment setup:

1. Copy `.env.example` to `.env` in `code/`.
2. Add provider keys only if you want to use optional AI modes.
3. Leave `AI_MODE` unset or set it to `off` for the deterministic baseline, or `triage` to enable the full triage overlay.

Important behavior:

- The repo auto-loads `code/.env` through `code/core/config.py`.
- Shell-exported environment variables override `.env` values.
- The default safe mode is deterministic `AI_MODE=off` unless you explicitly enable an AI mode.
- Keep `code/.env` local-only and out of any submission zip.

## Run The Batch Job

Recommended command from the repository root:

```bash
python code/main.py --output support_tickets/output.csv
```

Equivalent command from inside `code/`:

```bash
python main.py --output ../support_tickets/output.csv
```

What this does:

- reads `support_tickets/support_tickets.csv`
- processes every ticket through the deterministic baseline and any optional bounded AI overlay
- writes the required submission columns to the chosen output file

The expected output header is:

```text
issue,subject,company,response,product_area,status,request_type,justification
```

## Run The Evaluators

Sample-set evaluation:

```bash
python code/evaluate_sample.py
```

Manual regression checks:

```bash
python code/manual_regressions.py
```

Output-quality inspection against the accepted baseline:

```bash
python code/inspect_output.py --output support_tickets/output.csv --baseline support_tickets/output.baseline.csv
```

Useful development variant from inside `code/`:

```bash
python inspect_output.py --output ../support_tickets/output.csv --baseline ../support_tickets/output.baseline.csv
```

## AI Modes

The deterministic baseline is the source of truth. Optional provider-backed behavior is gated behind `AI_MODE`:

- `off`: deterministic baseline only
- `synthesis`: bounded wording-only rewrite for safe replied rows
- `triage`: bounded structured proposal over deterministic evidence, validated before acceptance
- `review`: warning-only analysis mode

Example:

```bash
AI_MODE=triage python code/main.py --output support_tickets/output.triage.csv
```

Optional rate-limit controls from `.env.example`:

- `LLM_PROVIDER`
- `GEMINI_API_KEY`
- `GEMINI_MODEL`
- `OPENAI_API_KEY`
- `OPENAI_MODEL`
- `LLM_RATE_LIMIT_RPM`
- `LLM_RATE_LIMIT_BURST`
- `LLM_RATE_LIMIT_MAX_WAIT_SECONDS`

## Architecture Summary

The pipeline is organized into four implementation areas plus root entrypoints.

### Root entrypoints

- `main.py` runs the production batch flow.
- `evaluate_sample.py` compares predicted categorical fields against the sample CSV.
- `manual_regressions.py` checks the high-risk routing and escalation cases.
- `inspect_output.py` flags low-quality or invalid production output patterns.

### `core/`

- `config.py` resolves repo-relative paths, cache paths, `.env` loading, and provider defaults.
- `schemas.py` defines enums and Pydantic models shared across the pipeline.
- `taxonomy.py` validates and maps allowed `product_area` values.

### `retrieval/`

- `corpus.py` discovers markdown files, normalizes them, and creates heading-aware chunks.
- `retriever.py` provides lexical retrieval over the local corpus.
- `retrieval_policy.py` handles query expansion and reranking preferences.

### `triage/`

- `agent.py` orchestrates one ticket through normalization, domain detection, safety, retrieval, optional AI overlay, and final serialization.
- `safety.py` owns deterministic escalation rules and weak-evidence checks.
- `response_builder.py` builds deterministic replies, constructive escalations, and justifications.

### `ai/`

- `llm.py` wraps optional provider calls with strict JSON handling, retry logic, and fail-closed behavior.
- `ai_validation.py` validates bounded AI proposals before they can override deterministic output.

### End-to-end flow

1. Load one ticket from CSV.
2. Normalize the subject, issue, and domain clues.
3. Apply deterministic safety and request-type rules.
4. Retrieve and rerank local corpus evidence.
5. Map the best grounded evidence to an allowed `product_area`.
6. Build a deterministic reply or escalation.
7. Optionally run bounded AI synthesis or triage when enabled.
8. Serialize the final row to the submission schema.

## Local Artifacts

The implementation writes local artifacts under `code/.cache/`.

Important files:

- `corpus_cache.json`: normalized corpus cache
- `taxonomy_cache.json`: cached taxonomy data if generated
- `retrieval_index.json`: retrieval cache artifact if generated
- `ai_trace.jsonl`: optional AI decision trace file

These files are useful for development and validation, but they are not the main deliverable.

## Limitations

- All answers are grounded only in the provided local corpus. The system intentionally does not use live web retrieval for support truth.
- Weak, missing, or conflicting evidence is designed to escalate rather than guess.
- Optional AI modes are bounded, but provider availability, quota, and rate-limit behavior can still affect experimental runs.
- The evaluator focuses first on categorical correctness (`status`, `request_type`, `product_area`) and safe grounding, not just wording quality.
- Some escalated rows may still include constructive next steps, but they intentionally remain escalated when account-specific or safety-sensitive handling is required.

## Submission Checklist

Before submission:

1. Run `python code/evaluate_sample.py` and confirm the categorical checks are still clean.
2. Run `python code/manual_regressions.py` and confirm the manual safety/routing cases still pass.
3. Run `python code/main.py --output support_tickets/output.csv` to generate the production predictions.
4. Run `python code/inspect_output.py --output support_tickets/output.csv --baseline support_tickets/output.baseline.csv` to check for flagged output issues.
5. Zip the `code/` directory only. Exclude virtualenvs, `__pycache__`, and any unnecessary local artifacts.
6. Upload `support_tickets/output.csv` as the prediction file.
7. Upload the external transcript log required by `AGENTS.md`.

Transcript artifact path:

- Windows: `%USERPROFILE%\hackerrank_orchestrate\log.txt`
- macOS/Linux: `$HOME/hackerrank_orchestrate/log.txt`

## Notes For Step 21

The final hardening pass should rebuild caches once, rerun the batch and evaluators, confirm repeatability, and prepare the final code zip plus output artifacts.