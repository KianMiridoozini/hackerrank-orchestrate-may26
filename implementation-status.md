# Implementation Status

This file is the shared handoff board for implementation agents working on this repository.

It tracks current progress, evidence, blockers, and decisions so that any AI assistant or human can safely continue work without relying on chat memory alone.

## Document Roles

| File | Role |
|---|---|
| `AGENTS.md` | Repository rules, AI-tool behavior, transcript logging, onboarding, submission constraints, and non-negotiable agent instructions. |
| `plan-overview.md` | High-level architecture and strategy for the support triage solution. |
| `implementation-sequence.md` | Detailed development order, step-by-step implementation guidance, milestone gates, and execution rules. |
| `implementation-status.md` | Current implementation progress, evidence, blockers, decisions, and handoff state. |

## Status Meanings

| Status | Meaning |
|---|---|
| `NOT_STARTED` | No implementation work has been done. |
| `IN_PROGRESS` | Work has started but is not complete. |
| `BLOCKED` | Work cannot continue without a fix, clarification, or decision. |
| `DONE` | The implementation work appears complete, but has not been independently verified. |
| `VERIFIED` | The work is complete and backed by concrete evidence. |
| `SKIPPED` | The work was intentionally not implemented, with a recorded reason. |

## Update Rules

- Read `AGENTS.md`, `plan-overview.md`, `implementation-sequence.md`, and this file before starting work.
- Use this file as the source of truth for implementation progress.
- Use `implementation-sequence.md` as the source of truth for implementation order and step detail.
- Use `plan-overview.md` as the source of truth for architecture and strategy.
- Before editing files for a step, mark that step `IN_PROGRESS`.
- After completing a step, update its status and add evidence.
- Do not mark anything `VERIFIED` without concrete evidence.
- Evidence must be a command run, output file checked, test result, sample evaluation result, or clear manual inspection note.
- If evidence is incomplete, use `DONE`, `IN_PROGRESS`, or `BLOCKED`, not `VERIFIED`.
- Do not claim a milestone is complete unless its required steps are `DONE` or `VERIFIED`.
- Do not add new architecture beyond `plan-overview.md` unless the decision and reason are recorded under “Decisions Made.”
- Do not change implementation order from `implementation-sequence.md` unless the decision and reason are recorded under “Decisions Made.”
- Never include secrets, API keys, tokens, cookies, or private credentials in this file.
- When a new agent starts, it should continue from the first `NOT_STARTED` or `BLOCKED` step unless the user instructs otherwise.

---

## Current Summary

Last updated: `VERIFIED`

Updated by: `GitHub Copilot`

Current focus: `Step 7 is verified: code/corpus.py now splits long documents by headings, keeps short FAQ pages whole, and reuses a local corpus cache artifact.`

Current recommended next action: `Start Step 8: implement lexical retrieval with domain filtering and chunk provenance.`

---

## Milestones

| ID | Milestone | Status | Evidence | Notes |
|---|---|---|---|---|
| A | Batch skeleton works | VERIFIED | `python code/main.py --output ../support_tickets/output.step4.csv` ran without crashing after `pydantic` was installed in the workspace venv; the command resolved `support_tickets/`, loaded 29 tickets, and wrote 29 rows. A follow-up CSV check confirmed the output header matched the sample header exactly. | `support_tickets/output.step4.csv` was used as the validation artifact for the Step 4 batch skeleton. |
| B | Corpus and taxonomy work | VERIFIED | `code/taxonomy.py` builds a 140-label allowed vocabulary from the sample CSV plus corpus folders and index breadcrumbs; `code/corpus.py` now discovers 773 markdown files, writes `code/.cache/corpus_cache.json`, and produces heading-aware chunk artifacts. Validation confirmed the April 2026 release notes file split into 66 chunks with heading context, a short Claude FAQ stayed as a single chunk, and manual inspection of `CorpusChunk` plus cache serialization preserved `source_path`, `title`, `breadcrumbs`, and `heading` provenance.` | Retrieval itself is still pending, but the corpus and taxonomy gate described for Milestone B now has concrete evidence. |
| C | Deterministic baseline works | NOT_STARTED | - | Agent can route, retrieve, escalate, and emit complete outputs without any LLM/provider dependency. |
| D | Sample evaluation is informative | NOT_STARTED | - | `evaluate_sample.py` reports categorical mismatches clearly. |
| E | Optional LLM layer is additive | NOT_STARTED | - | Provider-backed synthesis improves safe replies without weakening categorical consistency or safety. |
| F | Submission-ready run works | NOT_STARTED | - | Production CSV completes successfully, repeats reproducibly, and the submission checklist is satisfied. |

---

## Milestone Definitions of Done

### Milestone A — Batch skeleton works

Can be marked `VERIFIED` only when:

- The terminal command runs without crashing.
- It resolves the current tickets directory.
- It reads the input CSV.
- It writes an output CSV.
- The output has the expected number of rows.
- The output has the expected header/columns.
- The run does not require an LLM API key.

### Milestone B — Corpus and taxonomy work

Can be marked `VERIFIED` only when:

- Markdown files under `data/` are discovered.
- Corpus records include domain, path, title, breadcrumbs or folder-derived context, and text.
- Empty/stub/navigation-only pages are excluded or marked as non-answer-bearing.
- Heading-aware chunking works for long documents.
- Retrieved chunks preserve provenance.
- `product_area` validation rejects unknown labels.
- The taxonomy is seeded from sample labels and extended using corpus folders/breadcrumbs.

### Milestone C — Deterministic baseline works

Can be marked `VERIFIED` only when:

- The full pipeline runs without an LLM/provider key.
- Every row receives valid values for:
  - `status`
  - `product_area`
  - `response`
  - `justification`
  - `request_type`
- Safety rules escalate known risky examples.
- Replied rows are traceable to retrieved local corpus evidence.
- Escalated rows use deterministic templates or deterministic justifications.
- No output row depends on unsupported external knowledge.

### Milestone D — Sample evaluation is informative

Can be marked `VERIFIED` only when:

- `evaluate_sample.py` runs.
- It checks row count and required categorical values.
- It compares at least:
  - `status`
  - `request_type`
  - `product_area`
- It reports mismatches clearly enough to guide tuning.
- It does not require LLM/API access to perform categorical comparison.

### Milestone E — Optional LLM layer is additive

Can be marked `VERIFIED` only when:

- Missing API keys do not break the batch run.
- Provider failures do not break the batch run.
- Malformed or invalid JSON from the LLM falls back safely.
- LLM use is limited to bounded synthesis or rare tie-breaks over retrieved local evidence.
- LLM use does not worsen categorical sample results.
- Core routing, safety, taxonomy validation, and retrieval remain deterministic.

### Milestone F — Submission-ready run works

Can be marked `VERIFIED` only when:

- Production CSV generation completes.
- There are no missing rows.
- There are no invalid categorical values.
- The output header/columns match the current repo’s expected submission format.
- Re-running the same command produces materially identical output.
- `code/README.md` exists and explains install/run/evaluation/submission.
- The code zip can be prepared from `code/` only.
- The code zip excludes:
  - `data/`
  - support ticket CSVs
  - virtualenvs
  - `node_modules`
  - unnecessary cache/build artifacts
  - secrets
- The external AI-tool transcript file exists and is ready to upload separately.

---

## Development Steps

| Step | Task | Status | Files touched | Evidence | Next action |
|---|---|---|---|---|---|
| 1 | Create module layout under `code/` | VERIFIED | `implementation-status.md`, `code/main.py`, `code/config.py`, `code/schemas.py`, `code/corpus.py`, `code/retriever.py`, `code/safety.py`, `code/taxonomy.py`, `code/llm.py`, `code/agent.py`, `code/evaluate_sample.py`, `code/README.md` | `list_dir code/` showed the planned file set and `get_errors` reported no errors for the touched Python stubs. | Start Step 2: define config and schema boundaries. |
| 2 | Define config and schema boundaries | VERIFIED | `implementation-status.md`, `code/config.py`, `code/schemas.py` | `get_errors` reported no issues in `code/config.py` and `code/schemas.py`, and `python -c "import config, schemas; print('ok')"` returned `ok` from `code/` using the configured interpreter. | Start Step 3: inspect the sample header and implement the CSV writer contract. |
| 3 | Inspect sample header and implement CSV writer | VERIFIED | `implementation-status.md`, `code/main.py` | `get_errors` reported no issues in `code/main.py`; a Python snippet loaded the real sample header, wrote a temporary CSV, and confirmed the first line matched `Issue,Subject,Company,Response,Product Area,Status,Request Type`; `main()` returned `0` and printed that same header. | Start Step 4: build the CLI skeleton and placeholder agent flow. |
| 4 | Build CLI skeleton and placeholder agent flow | VERIFIED | `implementation-status.md`, `code/main.py`, `code/agent.py`, `support_tickets/output.step4.csv` | `get_errors` reported no issues in `code/main.py` and `code/agent.py`; `python main.py --output ../support_tickets/output.step4.csv` resolved `support_tickets/`, loaded 29 tickets, and wrote 29 rows; a follow-up CSV check confirmed `support_tickets/output.step4.csv` had 29 rows and the exact sample header. | Start Step 5: build the taxonomy module. |
| 5 | Build taxonomy module | VERIFIED | `implementation-status.md`, `code/taxonomy.py` | `get_errors` reported no issues in `code/taxonomy.py`; a Python validation snippet confirmed the six sample labels were present, `validate_product_area("screen")` succeeded, `validate_product_area("totally_unknown_label")` raised a `ValueError`, and evidence mapping resolved example paths to `conversation_management`, `travel_support`, and `community`. | Start Step 6: build the corpus parser. |
| 6 | Build corpus parser | VERIFIED | `implementation-status.md`, `code/corpus.py` | `get_errors` initially showed no editor issues, then a Python validation snippet caught and helped confirm a regex syntax fix; the rerun discovered 773 markdown files, parsed `data/claude/claude/features-and-capabilities/14465370-use-claude-for-word.md` with title `Use Claude for Word` and breadcrumbs `('Claude', 'Features and capabilities')`, flagged `data/claude/index.md` as `navigation_index`, and flagged `data/visa/support/consumer/checkout-fees-contact-form.md` as `short_stub`. | Start Step 7: add heading-aware chunking. |
| 7 | Add heading-aware chunking | VERIFIED | `implementation-status.md`, `code/corpus.py`, `code/.cache/corpus_cache.json` | `get_errors` surfaced one local syntax issue which was repaired immediately; Python validation then confirmed the April 2026 release notes file split into 66 chunks with heading context, the Claude conversation-management FAQ stayed as one chunk, `code/.cache/corpus_cache.json` existed after the first build, and repeated artifact loads returned the same record and chunk counts (`773` records, `4788` chunks). | Start Step 8: implement lexical retrieval. |
| 8 | Implement lexical retrieval | NOT_STARTED | - | - | Add TF-IDF or BM25 retrieval with domain filtering and provenance. |
| 9 | Implement domain detection | NOT_STARTED | - | - | Trust `company` when plausible; infer cautiously when missing. |
| 10 | Implement safety and `request_type` rules | NOT_STARTED | - | - | Add deterministic escalation categories and request heuristics. |
| 11 | Connect deterministic baseline | NOT_STARTED | - | - | Route, retrieve, escalate, map product area, and emit complete rows without LLM. |
| 12 | Add sample evaluator | NOT_STARTED | - | - | Compare categorical outputs against sample. |
| 13 | Tune deterministic baseline | NOT_STARTED | - | - | Fix structural routing, safety, taxonomy, and retrieval failures. |
| 14 | Add optional LLM wrapper | NOT_STARTED | - | - | Add env-based provider wrapper, temperature 0, strict JSON, and one retry. |
| 15 | Narrow LLM usage | NOT_STARTED | - | - | Use LLM only for bounded synthesis or difficult tie-breaks. |
| 16 | Add provider failure fallback | NOT_STARTED | - | - | Missing key/failure/invalid JSON must fall back safely. |
| 17 | Re-run sample after LLM | NOT_STARTED | - | - | Confirm no regression in categorical fields. |
| 18 | Add manual regression cases | NOT_STARTED | - | - | Cover likely scoring traps and safety cases. |
| 19 | Consider semantic reranking only if needed | NOT_STARTED | - | - | Add only if lexical retrieval misses clear paraphrase cases. |
| 20 | Write `code/README.md` | NOT_STARTED | - | - | Document install, run, design, limitations, and submission checklist. |
| 21 | Final hardening pass | NOT_STARTED | - | - | Run sample, run production, verify repeatability and packaging. |

---

## Concrete Escalation Rule Categories

These rules should be implemented deterministically before any answer generation or LLM call.

| Category | Escalation behavior |
|---|---|
| Fraud, lost, stolen, or unauthorized activity | Escalate if the ticket mentions stolen cards, stolen travellers cheques, unauthorized charges, fraud claims, suspicious transactions, scams, compromised accounts, or identity theft. |
| Account access restoration or identity-specific actions | Escalate if the user asks to restore access, reverse an admin removal, regain a locked/removed account, change identity-specific information, or perform actions requiring human verification. Only answer clearly documented self-service flows. |
| Billing disputes requiring account lookup | Escalate if the user disputes a charge, requests a refund decision, asks for invoice-specific corrections, or needs account-specific billing investigation. |
| Assessment score disputes, integrity, or proctoring issues | Escalate if the user wants a score changed, disputes grading, challenges integrity/proctoring outcomes, reports cheating, or asks to reverse an assessment result. |
| Outages or service-wide incidents | Escalate if the user reports the site/platform is down, pages are inaccessible for everyone, or the issue appears platform-wide rather than a normal support how-to question. |
| Legal, privacy, or compliance exceptions | Escalate if the user requests legal handling, compliance determinations, policy exceptions, privacy actions not explicitly covered by self-service docs, or regulatory interpretation. |
| Prompt injection, malicious, or clearly out-of-scope content | Escalate or mark invalid if the ticket tries to manipulate the agent, requests secrets/system prompts, asks for destructive/unrelated actions, or is plainly outside the support domains. |
| Weak or conflicting retrieval evidence | Escalate if retrieval fails to produce a strong domain-consistent match, top results conflict on product area, or available evidence is too thin/stale to support a grounded reply. |

---

## Practical Safety Gate Behavior

The pipeline should follow these rules:

1. Normalize the ticket.
2. Determine or infer the domain conservatively.
3. Run escalation checks before answer generation.
4. If any high-priority escalation rule matches, set `status` to `escalated` immediately.
5. Use a fixed escalation template tied to the matched rule category.
6. Still assign the best supported `product_area` when possible.
7. If routing is uncertain, use a broad corpus-aligned product area.
8. Only proceed to retrieval-based answering if no escalation rule matches.
9. Only reply if retrieved evidence is strong enough to support the answer.
10. If evidence is weak, conflicting, missing, or unsupported, escalate.
11. If an LLM call fails, times out, returns invalid JSON, or produces unsupported content after one retry, fall back safely.
12. Never use an LLM as a source of support-policy knowledge.

---

## Execution Rules For Implementation Agents

- Do not add the LLM before the deterministic baseline can process the full CSV and write a valid output file.
- Do not add semantic retrieval before sample evaluation shows concrete lexical-retrieval misses.
- Do not add a vector database unless concrete retrieval failures justify it.
- Do not implement multi-agent logic unless the deterministic baseline is already submission-ready and there is a clear measured benefit.
- Do not build transcript logging into the triage agent.
- Do not fetch live web pages, support docs, search results, or external policy information at runtime.
- The optional LLM provider may only synthesize or classify using retrieved local corpus evidence.
- Do not optimize wording before `status`, `request_type`, `product_area`, and safety behavior are stable.
- When in doubt, escalate rather than guess.
- Keep every module small and single-purpose.
- Avoid merging safety, retrieval, taxonomy, and generation logic into one file.
- After each major step, run the cheapest verification that proves the new layer works.
- Do not mark a step `VERIFIED` without evidence.

---

## Expected Module Responsibilities

| File | Responsibility |
|---|---|
| `code/main.py` | CLI entrypoint, path resolution, sample-header inspection, batch run over rows, final CSV writing. |
| `code/config.py` | Constants, provider/model settings, cache paths, environment variable names, temperature defaults, and `support_tickets` vs `support_issues` fallback. |
| `code/schemas.py` | Enums and Pydantic models for input tickets, normalized tickets, retrieved chunks, safety decisions, and final outputs. |
| `code/corpus.py` | Markdown scanning, frontmatter parsing, metadata extraction, title cleanup, stub-page filtering, and heading-based chunking. |
| `code/retriever.py` | TF-IDF or BM25 lexical retrieval with domain filtering, top-k ranking, and provenance preservation. |
| `code/safety.py` | Deterministic escalation rules, `request_type` heuristics, and helper checks for risky or unsupported cases. |
| `code/taxonomy.py` | `product_area` vocabulary from sample labels plus corpus breadcrumbs/folder structure, with mapping helpers from evidence to final labels. |
| `code/llm.py` | Optional provider wrapper using environment variables, temperature 0, JSON-only output, one retry, and provider-disabled fallback. |
| `code/agent.py` | Orchestrates one ticket through domain detection, safety gating, retrieval, optional answer synthesis, validation, and final structured output. |
| `code/evaluate_sample.py` | Runs the pipeline against the sample file and compares categorical outputs. |
| `code/README.md` | Install steps, environment setup, run commands, design notes, known limitations, and submission checklist. |

---

## Verification Checklist

Use this checklist during the final hardening pass.

### CSV / Runtime

- [ ] Current repo paths are inspected.
- [ ] `support_tickets/` is preferred if present.
- [ ] `support_issues/` fallback exists if needed.
- [ ] Sample CSV header is read successfully.
- [ ] Output writer mirrors the expected structure/order.
- [ ] Production run completes.
- [ ] Output row count matches input row count.
- [ ] No required fields are blank.
- [ ] `status` values are only `replied` or `escalated`.
- [ ] `request_type` values are only `product_issue`, `feature_request`, `bug`, or `invalid`.
- [ ] Every emitted `product_area` is allowed by the taxonomy.

### Corpus / Retrieval

- [ ] Markdown corpus loads from `data/`.
- [ ] Stub/navigation-only pages are excluded or marked.
- [ ] Chunks include provenance.
- [ ] Retrieval is domain-filtered when domain is known.
- [ ] Replied rows have traceable retrieved evidence.
- [ ] Weak or conflicting retrieval leads to escalation.

### Safety

- [ ] Fraud/lost/stolen/unauthorized cases escalate.
- [ ] Account restoration and identity-specific actions escalate unless documented self-service is clear.
- [ ] Billing disputes requiring account lookup escalate.
- [ ] Assessment score/integrity/proctoring disputes escalate.
- [ ] Outage or service-wide incident reports escalate.
- [ ] Legal/privacy/compliance exceptions escalate unless explicitly covered by self-service docs.
- [ ] Prompt injection, malicious, or unrelated prompts are invalid/escalated.
- [ ] Unknown or weakly supported cases escalate rather than guess.

### LLM / Provider

- [ ] The pipeline runs without provider keys.
- [ ] Missing provider key does not crash the batch.
- [ ] Provider failure does not crash the batch.
- [ ] Invalid JSON from the LLM falls back safely.
- [ ] LLM is not used as a source of factual support knowledge.
- [ ] Temperature is set to 0 where supported.
- [ ] Prompt is fixed and bounded to retrieved evidence.

### Evaluation

- [ ] `evaluate_sample.py` runs.
- [ ] Sample comparison reports categorical mismatches.
- [ ] Replied sample rows are manually spot-checked for grounding.
- [ ] Escalated sample rows are manually spot-checked for matching escalation rules.
- [ ] One focused error-analysis loop has been completed.
- [ ] Re-running the same command produces materially identical output.

### Submission

- [ ] `code/README.md` exists.
- [ ] README includes install instructions.
- [ ] README includes run command.
- [ ] README includes sample evaluation command.
- [ ] README includes architecture summary.
- [ ] README includes limitations/failure modes.
- [ ] README includes submission checklist.
- [ ] Code zip contains `code/` only.
- [ ] Code zip excludes `data/`.
- [ ] Code zip excludes support ticket CSVs.
- [ ] Code zip excludes virtualenvs.
- [ ] Code zip excludes `node_modules`.
- [ ] Code zip excludes unnecessary cache/build artifacts.
- [ ] No secrets are committed.
- [ ] External AI-tool transcript file exists and is ready to upload separately.

---

## Current Blockers

- None recorded.

---

## Decisions Made

| Decision | Reason | Date | Evidence |
|---|---|---|---|
| Use a structured batch pipeline instead of a free-form autonomous agent loop | The task is scored through deterministic CSV outputs, grounded answers, escalation logic, and reproducibility. | TBD | `plan-overview.md`, `implementation-sequence.md` |
| Use lexical retrieval first | The corpus is small enough for TF-IDF/BM25 and this keeps retrieval reproducible and easy to debug. | TBD | `plan-overview.md`, `implementation-sequence.md` |
| Keep LLM optional and additive | Core routing, safety, taxonomy, retrieval, and CSV writing should not depend on model behavior. | TBD | `plan-overview.md`, `implementation-sequence.md` |
| Do not build transcript logging into the triage app | Transcript logging is an external AI-tool submission artifact, not part of ticket triage. | TBD | `AGENTS.md`, `README.md` |
| Prefer escalation when confidence is low | The challenge penalizes hallucinated policies and unsupported answers. | TBD | `problem_statement.md`, `evalutation_criteria.md` |

---

## Handoff Notes For Next Agent

- Start from the first `NOT_STARTED` or `BLOCKED` development step.
- Do not redo `VERIFIED` work unless the evidence is invalid or the user explicitly asks.
- Read `AGENTS.md`, `plan-overview.md`, `implementation-sequence.md`, and this file before starting work.
- Read `plan-overview.md` and `implementation-sequence.md` before changing architecture or implementation order.
- Preserve terminal-based batch behavior.
- Preserve the local-corpus-only requirement.
- Preserve the deterministic safety gate before any LLM call.
- If unsure whether a ticket can be safely answered, escalate.
- If unsure whether a step is complete, mark it `IN_PROGRESS` or `BLOCKED`, not `DONE`.
- If unsure whether a step is verified, leave it as `DONE` and explain what verification is missing.

---

## Claim Discipline

Implementation agents must avoid overclaiming.

Do not write:

- “implemented”
- “working”
- “verified”
- “fixed”
- “complete”

unless you can point to concrete evidence such as:

- a file changed
- a command run
- a test result
- an output CSV inspected
- a sample evaluation result
- a manual check performed

Use softer language when evidence is incomplete:

- “appears complete”
- “partially implemented”
- “needs verification”
- “blocked pending inspection”
- “not yet tested”

---

## Latest Update Log

Append short project-state updates here when useful. Do not use this as a replacement for the external AGENTS transcript log.

### Update 1

- Timestamp: `TBD`
- Agent: `unknown`
- Summary: `implementation-status.md created. No implementation work has been verified yet.`
- Evidence: `This file exists.`

### Update 2

- Timestamp: `2026-05-01T10:08:39.0463655+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 1 was completed by creating the planned module layout under code/ with minimal placeholder contents only.`
- Evidence: `list_dir code/ showed all planned files and get_errors reported no errors for the touched Python files.`

### Update 3

- Timestamp: `2026-05-01T11:14:06.5882598+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 2 defined repository path and provider settings in code/config.py and added the shared enums and Pydantic models in code/schemas.py.`
- Evidence: `get_errors reported no issues in the edited files and python -c "import config, schemas; print('ok')" returned ok from code/.`

### Update 4

- Timestamp: `2026-05-01T12:24:38.5541933+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 3 updated code/main.py to read the sample CSV header as the output contract and to write rows using that exact column order.`
- Evidence: `get_errors reported no issues in code/main.py, a Python validation snippet confirmed a temporary output CSV used the same header as the sample, and main() returned 0 while printing that header.`

### Update 5

- Timestamp: `2026-05-01T12:37:37.3043239+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 4 added a minimal batch CLI in code/main.py and a placeholder per-ticket flow in code/agent.py so the pipeline can read the input CSV and write structurally valid output rows.`
- Evidence: `The CLI command loaded 29 tickets from support_tickets/support_tickets.csv and wrote 29 rows to support_tickets/output.step4.csv, then a follow-up CSV check confirmed the output header matched the sample header exactly.`

### Update 6

- Timestamp: `2026-05-01T13:03:37.3383255+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 5 added code/taxonomy.py to seed allowed product-area labels from the sample CSV and extend them with corpus-derived labels and aliases from the data indexes and folder structure.`
- Evidence: `get_errors reported no issues in code/taxonomy.py, and a Python validation snippet confirmed the sample labels were included, unknown labels were rejected, and representative evidence paths mapped to canonical labels.`

### Update 7

- Timestamp: `2026-05-01T13:36:08.5941108+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 6 replaced the corpus stub with file-level markdown discovery and parsing, including frontmatter extraction, title and breadcrumb derivation, text normalization, and non-answer-bearing page detection.`
- Evidence: `A Python validation snippet discovered 773 markdown files, parsed a representative Claude article correctly, and marked a corpus index page and a short Visa contact page as non-answer-bearing.`

### Update 8

- Timestamp: `2026-05-01T13:47:17.3410299+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 7 extended code/corpus.py with heading-aware chunking for long documents and a disk-backed corpus cache keyed to the markdown manifest.`
- Evidence: `Python validation confirmed the April 2026 release notes file split into 66 chunks with heading context, the short Claude conversation FAQ stayed whole, and repeated corpus loads reused the cache artifact while keeping the same record and chunk counts.`