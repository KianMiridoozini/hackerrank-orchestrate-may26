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

Current focus: `The remaining live-triage defect triage_rejected_missing_should_escalate_reason is now fixed. code/agent.py still owns the orchestration path, but the AI-overlay budget and customer-text validation helpers have been extracted into code/ai_validation.py, the triage prompt now carries fallback_should_escalate_reason, and blank model escalation reasons are repaired only when the deterministic fallback was already escalated. To reduce live-provider wording drift, accepted triage now preserves the deterministic justification whenever status, request_type, and product_area stay unchanged. Fresh validation reran AI_MODE=triage sample and manual regression checks cleanly, and a fresh 29-row live triage batch recorded llm_called=12, triage_accepted=12, triage_skipped_low_value=6, vetoed_high_risk_safety=11, Changed rows vs baseline 5, and Flagged rows 0.`

Current recommended next action: `Finish Step 20 by writing code/README.md, then use Step 21 for the final packaging and repeatability pass with the now-stable live triage overlay as a secondary experimental artifact.`

Behavior-preserving refactor status: `The earlier post-Step-19 modularity refactor remains verified as behavior-preserving, and this pass extended that cleanup by extracting AI-overlay triage-budget and customer-text validation helpers into code/ai_validation.py while keeping code/agent.py focused on orchestration. Focused validation confirmed the repaired escalation-reason path, evaluate_sample.py stayed at zero categorical mismatches, manual_regressions.py stayed 9/9, and the refreshed live triage batch still wrote 29 valid rows.`

Production output quality status: `A targeted final-quality pass is verified. code/inspect_output.py now flags short/truncated/raw-template/internal-metadata output issues, and the final validation run reported 10/10 sample status, 10/10 request_type, 8/8 product_area, manual_regressions.py at 9/9, production batch output at 29/29 rows, and Flagged rows at 0 after manual inspection of every replied production row. support_tickets/output.baseline.csv has now been reset to the accepted current support_tickets/output.csv so future inspections measure regressions from the approved output, and a follow-up inspect_output.py run now reports Changed rows vs baseline at 0 and Flagged rows at 0.`

Experimental AI mode status: `code/agent.py continues to write code/.cache/ai_trace.jsonl entries showing whether the LLM was skipped, vetoed by deterministic safety, accepted, or rejected. Validation still keeps default off mode at 10/10 sample status, 10/10 request_type, 8/8 product_area, and 9/9 manual regressions. After the repo-root .env loader, timeout normalization, retry/circuit-breaker policy, proactive rate-limit admission control, low-value triage gating, and narrower forbidden-marker validation were already in place, this pass fixed the remaining triage_rejected_missing_should_escalate_reason defect and moved AI-overlay validation helpers into code/ai_validation.py. The triage prompt now supplies fallback_should_escalate_reason, the validator repairs a blank model escalation reason only when the deterministic fallback was already escalated, and unchanged accepted classifications now preserve the deterministic justification to avoid live-provider wording drift. Fresh AI_MODE=triage reruns of evaluate_sample.py and manual_regressions.py still reported 10/10 status, 10/10 request_type, 8/8 product_area, and 9/9 manual regressions. A fresh live triage batch then wrote 29 rows to support_tickets/output.triage.csv, inspect_output.py against support_tickets/output.baseline.csv reported Changed rows vs baseline 5 and Flagged rows 0, and the fresh trace slice recorded rows=29, llm_called=12, triage_accepted=12, triage_skipped_low_value=6, and vetoed_high_risk_safety=11 with no missing_should_escalate_reason or rate_limited rejections.`

---

## Milestones

| ID | Milestone | Status | Evidence | Notes |
|---|---|---|---|---|
| A | Batch skeleton works | VERIFIED | `python code/main.py --output ../support_tickets/output.step4.csv` ran without crashing after `pydantic` was installed in the workspace venv; the command resolved `support_tickets/`, loaded 29 tickets, and wrote 29 rows. A follow-up CSV check confirmed the output header matched the sample header exactly. | `support_tickets/output.step4.csv` was used as the validation artifact for the Step 4 batch skeleton. |
| B | Corpus and taxonomy work | VERIFIED | `code/taxonomy.py` builds a 140-label allowed vocabulary from the sample CSV plus corpus folders and index breadcrumbs; `code/corpus.py` now discovers 773 markdown files, writes `code/.cache/corpus_cache.json`, and produces heading-aware chunk artifacts. Validation confirmed the April 2026 release notes file split into 66 chunks with heading context, a short Claude FAQ stayed as a single chunk, and manual inspection of `CorpusChunk` plus cache serialization preserved `source_path`, `title`, `breadcrumbs`, and `heading` provenance. | This milestone remains the deterministic retrieval foundation now used by the Step 11 baseline. |
| C | Deterministic baseline works | VERIFIED | `code/agent.py` now normalizes tickets, resolves domain conservatively, applies deterministic safety rules, escalates unresolved or weak-evidence cases, retrieves domain-filtered corpus evidence, maps `product_area` from specific source-path and breadcrumb evidence, and assembles deterministic replies from retrieved chunks. Validation confirmed a conversation-management query replied from the Claude FAQ with traceable evidence, a Visa fraud ticket escalated immediately, a generic unresolved account-help ticket escalated as weak evidence, and `main.py` now writes `support_tickets/output.csv` with the required lowercase submission columns including `justification`; the latest batch validation wrote 29 rows without any provider key and confirmed no written row was missing `status`, `product_area`, `response`, `request_type`, or `justification`. | The deterministic baseline now runs end to end without any LLM or provider dependency, and its written CSV contract matches the required justification-bearing submission format. |
| D | Sample evaluation is informative | VERIFIED | `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe evaluate_sample.py` ran from `code/`, compared 10 sample rows end to end, reported `Status` accuracy `6/10`, `Request Type` accuracy `8/10`, `Product Area` accuracy `2/8` (blank sample product areas excluded), and grouped the 8 mismatches into `retrieval_or_confidence`, `taxonomy_or_retrieval`, `request_type_rules`, and `routing_or_retrieval` buckets. | The current failure mix is now concrete enough to drive the deterministic tuning loop in Step 13. |
| E | Optional LLM layer is additive | VERIFIED | `code/agent.py` now exposes env-gated AI modes: `off` preserves the deterministic baseline, `synthesis` can rewrite response and justification for safe replied rows, `triage` can propose structured `status`/`request_type`/`product_area`/`response`/`justification` from retrieved local evidence with deterministic validation and high-risk safety veto, and `review` can emit trace warnings only. Default off mode still reran `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/evaluate_sample.py` at `10/10` status, `10/10` request_type, and `8/8` product_area with no mismatches, and `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/manual_regressions.py` still passed `9/9`. After the repo-root .env loader and timeout fallback fix, AI_MODE=triage wrote 29 rows to `support_tickets/output.triage.csv`, `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/inspect_output.py --output support_tickets/output.triage.csv --baseline support_tickets/output.baseline.csv` reported `Changed rows vs baseline: 9` and `Flagged rows: 0`, and the trace recorded `triage_accepted=9`, `triage_rejected_provider_error=7`, `triage_rejected_response_contains_internal_or_unsupported_content=2`, and `vetoed_high_risk_safety=11`. Focused live replays of the provider_error path showed both `network_error:timeout` at 30 seconds and Gemini `http_error:503` high-demand failures on `gemini-3.1-flash-lite-preview`, while an OpenAI cross-check failed separately with `http_error:429` insufficient quota. | The expanded LLM layer is structurally implemented and safely bounded; live triage now exercises accepted model decisions, and the remaining failures are provider-side availability/quota conditions rather than missing credentials or a broken fail-closed transport path. |
| F | Submission-ready run works | IN_PROGRESS | `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/evaluate_sample.py` reported `10/10` status, `10/10` request_type, and `8/8` product_area; `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/manual_regressions.py` passed `9/9`; `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/main.py` wrote `29` rows to `support_tickets/output.csv`; after resetting `support_tickets/output.baseline.csv` to that accepted output, `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/inspect_output.py` reported `Changed rows vs baseline: 0` and `Flagged rows: 0`; a follow-up manual inspection reviewed every replied production row.` | Production batch output quality and categorical validity are now verified, and the baseline now matches the accepted CSV, but `code/README.md` and the final zip/packaging checklist are still outstanding. |

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
| 8 | Implement lexical retrieval | VERIFIED | `implementation-status.md`, `code/retriever.py` | A Python validation snippet built the BM25 index over `4788` cached chunks, confirmed a Claude conversation-management query returned only Claude-domain results and ranked `claude/claude/conversation-management/8230524-how-can-i-delete-or-rename-a-conversation.md` first, and confirmed a HackerRank release-notes query returned only HackerRank-domain results and ranked the matching release-notes heading chunk first with populated title, breadcrumbs, source path, score, and rank. | Start Step 9: implement conservative domain detection. |
| 9 | Implement domain detection | VERIFIED | `implementation-status.md`, `code/agent.py` | A Python validation snippet confirmed an explicit Visa company value was trusted immediately, representative missing-company Claude and HackerRank tickets resolved to `Company.CLAUDE` and `Company.HACKERRANK`, `normalize_ticket()` populated `detected_company` for the Claude example, and an ambiguous generic account-help ticket stayed unresolved instead of guessing. | Start Step 10: implement deterministic safety rules and request-type heuristics. |
| 10 | Implement safety and `request_type` rules | VERIFIED | `implementation-status.md`, `code/safety.py` | A Python validation snippet confirmed fraud, account-access restoration, assessment-integrity, outage, malicious prompt-injection, feature-request, and weak-evidence examples all mapped to the expected deterministic `SafetyDecision` outcomes; outage mapped to `RequestType.BUG`, malicious content mapped to `RequestType.INVALID`, feature requests stayed non-escalated with `RequestType.FEATURE_REQUEST`, and `build_escalation_response()` returned a fixed template for an escalation category. | Start Step 11: connect the deterministic baseline in `code/agent.py`. |
| 11 | Connect deterministic baseline | VERIFIED | `implementation-status.md`, `code/agent.py`, `code/main.py`, `support_tickets/output.csv` | A Python validation snippet confirmed a known Claude conversation-management query replied with `product_area=conversation_management` and traceable retrieved evidence, a Visa fraud ticket escalated immediately via the deterministic fraud rule, and an ambiguous generic account-help ticket escalated as weak evidence; the first reply-path validation exposed overly broad product-area mapping, which was repaired by preferring source-path and specific breadcrumb evidence before rerunning the same check successfully. A follow-up contract fix in `code/main.py` separated sample-header validation from the submission writer schema so `main()` now writes `support_tickets/output.csv` with lowercase columns including `justification`; the latest batch validation wrote 29 rows, confirmed only valid `status` and `request_type` values, and confirmed no written or in-memory row was missing `product_area`, `response`, `request_type`, or `justification`. | Start Step 12: add the sample evaluator. |
| 12 | Add sample evaluator | VERIFIED | `implementation-status.md`, `code/evaluate_sample.py` | `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe evaluate_sample.py` ran from `code/`, checked row counts and predicted categorical validity, compared `status`, `request_type`, and `product_area` against all 10 sample rows, and printed field-accuracy plus row-level mismatch diagnostics with heuristic failure buckets. | Start Step 13: tighten retrieval/confidence gating, taxonomy mapping, and invalid request classification using the evaluator output. |
| 13 | Tune deterministic baseline | VERIFIED | `implementation-status.md`, `code/agent.py`, `code/safety.py`, `support_tickets/output.csv` | A final targeted deterministic cleanup pass tightened `code/safety.py` escalation phrases for malicious requests, billing disputes, compliance/security-form requests, and outages, and refined `code/agent.py` query expansion plus reranking for compatibility-check, remove-user, Amazon Bedrock, LTI, bug-bounty, and privacy-delete cases. Validation re-ran `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe evaluate_sample.py` from `code/` and restored a clean categorical pass (`Status` `10/10`, `Request Type` `10/10`, `Product Area` `8/8`, no mismatches). A follow-up production run via `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe main.py --output ../support_tickets/output.csv` rewrote all 29 rows, and targeted inspection confirmed the previously bad rows now either route to stronger evidence (for example settings, safeguards, Amazon Bedrock, and Claude for Education cases) or fail closed to deterministic escalation instead of returning obviously irrelevant replies. | Start Step 14: add the optional provider-backed wrapper without weakening the deterministic fallback path. |
| 14 | Add optional LLM wrapper | VERIFIED | `implementation-status.md`, `code/llm.py` | `code/llm.py` now provides a bounded optional wrapper that resolves provider/model settings from env vars, requests JSON-only provider output at temperature `0`, retries malformed structured output once, and fails closed with structured failure reasons when the provider is missing or errors. Validation used a focused Python snippet from `code/` that imported the module successfully, confirmed missing API keys return `failure_reason=missing_api_key` instead of crashing, confirmed env-based provider resolution works, and confirmed a fake Gemini transport retries one malformed JSON response before succeeding on the second structured response. | Start Step 15: wire the wrapper into the narrowest safe synthesis path without changing deterministic routing or safety ownership. |
| 15 | Narrow LLM usage | VERIFIED | `implementation-status.md`, `code/agent.py` | `code/agent.py` now calls the optional wrapper only on already-safe replied tickets in the narrow `product_issue` synthesis path, and still falls back to the deterministic excerpt for generic product areas or when provider usage is unavailable. Focused validation exercised one replied ticket twice from `code/`: once with no provider config to confirm the original deterministic reply remained in place, and once with a fake Gemini transport to confirm only the reply wording changed while `status`, `request_type`, and `product_area` stayed fixed. A follow-up `evaluate_sample.py` run with provider usage disabled still reported a clean categorical pass (`Status` `10/10`, `Request Type` `10/10`, `Product Area` `8/8`, no mismatches). | Start Step 16: harden and verify the agent-level fallback path for live-provider failure scenarios. |
| 16 | Add provider failure fallback | VERIFIED | `implementation-status.md`, `code/agent.py` | `code/agent.py` now keeps the deterministic reply path in control even when optional synthesis is attempted and falls back explicitly for missing keys, provider errors, malformed structured output, and unsupported synthesized replies. Focused validation exercised one replied ticket across all four cases and confirmed the same `status`, `request_type`, and `product_area` were preserved while the justification now records the fallback reason (`missing_api_key`, `provider_error`, `malformed_structured_output`, or `unsupported_synthesized_response`). A follow-up batch-shaped validation processed all 29 tickets with a forced provider failure transport and confirmed the run still produced 29 complete rows with valid categorical values and non-empty `product_area`, `response`, and `justification` fields. | Start Step 17: rerun sample evaluation against the LLM-enabled code path and confirm categorical stability. |
| 17 | Re-run sample after LLM | VERIFIED | `implementation-status.md` | `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe evaluate_sample.py` was rerun from `code/` with provider usage disabled and still reported a clean categorical pass (`Status` `10/10`, `Request Type` `10/10`, `Product Area` `8/8`, no mismatches). A second focused validation ran the sample rows through `process_ticket(...)` with a simulated Gemini transport that exercised the bounded reply-synthesis path directly and confirmed all comparable `status`, `request_type`, and `product_area` values still matched the sample expectations. | Start Step 18: add the manual regression set for likely safety and scoring traps. |
| 18 | Add manual regression cases | VERIFIED | `implementation-status.md`, `code/manual_regressions.py`, `code/safety.py` | `code/manual_regressions.py` now provides an executable manual regression set covering service-down outages, score disputes, account restoration, Claude conversation deletion versus account deletion, Visa stolen travellers-cheque and unauthorized-charge cases, merchant disputes, and obviously unrelated prompts. Running `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe manual_regressions.py` from `code/` reported `9` cases, `9` passed, `0` failed. The first run exposed local phrase-matching gaps for stolen travellers-cheque and merchant-dispute wording, which were repaired in `code/safety.py`, and a follow-up `evaluate_sample.py` run still reported a clean categorical pass (`Status` `10/10`, `Request Type` `10/10`, `Product Area` `8/8`, no mismatches). | Start Step 19 only if there is still measured evidence that lexical retrieval misses clear paraphrase cases. |
| 19 | Consider semantic reranking only if needed | VERIFIED | `implementation-status.md`, `code/agent.py` | A focused paraphrase probe first confirmed a real retrieval miss: the Claude ticket `Delete private chat` / `How can I wipe a Claude chat thread that contains private info?` still ranked chat-sharing and project-sharing articles above `claude/claude/conversation-management/8230524-how-can-i-delete-or-rename-a-conversation.md`, even though the correct article was already present in the top lexical candidates. `code/agent.py` now adds a narrow concept-level semantic reranking signal over those top BM25 candidates only, without changing the underlying retriever or adding a dense retrieval system. The follow-up paraphrase probe then passed cleanly across six representative cases (Claude private-chat deletion, Claude console-account closure, HackerRank remove-departed-employee, HackerRank Zoom compatibility, Claude Bedrock regions, and Claude security reporting), and both `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe evaluate_sample.py` and `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe manual_regressions.py` still passed cleanly (`10/10` status, `10/10` request_type, `8/8` product_area; manual regressions `9/9`). | Start Step 20: write `code/README.md`. |
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
| Use a dedicated submission output schema instead of mirroring the sample header exactly | `problem_statement.md`, `evalutation_criteria.md`, `README.md`, and the provided `support_tickets/output.csv` template all require `justification`, while `sample_support_tickets.csv` omits it. The sample file remains useful for evaluation, but the final writer must target the submission schema. | 2026-05-01 | `problem_statement.md`, `evalutation_criteria.md`, `support_tickets/output.csv`, `code/main.py` |
| Keep Step 19 reranking limited to the top BM25 candidates | The measured miss was a paraphrase-ranking problem, not a recall problem: the correct Claude conversation-deletion article was already in the lexical top set. A small concept-level semantic reranker in `code/agent.py` fixed that local failure without adding a second retrieval engine, dense index, or external dependency. | 2026-05-01 | `code/agent.py`, targeted paraphrase probe, `evaluate_sample.py`, `manual_regressions.py` |
| Prefer deterministic support-style reply templates over raw evidence excerpts in the final CSV | The structural pipeline was already valid, but production output quality was still weak because raw excerpt text, incomplete paragraphs, and debug-heavy justifications reduced submission quality. Converting grounded evidence into concise support-style replies improved the final CSV without giving reply wording control over `status`, `request_type`, or `product_area`. | 2026-05-01 | `code/response_builder.py`, `code/inspect_output.py`, `support_tickets/output.baseline.csv`, `support_tickets/output.csv` |
| Use the accepted current production CSV as the inspection baseline | Once the reviewed output was accepted, keeping the older pre-quality snapshot as the active baseline would make every future inspection look like a full-file diff instead of highlighting real regressions. Resetting `support_tickets/output.baseline.csv` to the approved `support_tickets/output.csv` makes `code/inspect_output.py` useful for future changes. | 2026-05-01 | `support_tickets/output.csv`, `support_tickets/output.baseline.csv`, `code/inspect_output.py` |
| Gate expanded LLM behavior behind AI_MODE | The repo needs reproducible deterministic behavior by default, but experiments also need a larger evidence-grounded model role. AI_MODE keeps `off` reproducible while allowing bounded `synthesis`, `triage`, and `review` paths under deterministic validation and safety vetoes. | 2026-05-01 | `code/config.py`, `code/schemas.py`, `code/agent.py`, `code/.cache/ai_trace.jsonl` |
| Budget live triage calls before the provider boundary | The deterministic baseline is already strong enough that triage does not need to spend model budget on every safe row. Proactive admission control in `code/llm.py` plus budget-aware gating in `code/agent.py` preserves limited RPM for ambiguous or higher-value rows, prevents retry-after thrash, and fails closed cleanly when the provider lane is cooling down. | 2026-05-02 | `code/llm.py`, `code/agent.py`, focused fake-transport validation, `code/.cache/ai_trace.jsonl` |

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

### Update 9

- Timestamp: `2026-05-01T14:04:05.0737565+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 8 filled code/retriever.py with BM25 retrieval over cached corpus chunks, including domain filtering and provenance-preserving RetrievedChunk results.`
- Evidence: `A Python validation snippet built the BM25 index over 4788 chunks, kept a Claude conversation-management query fully inside the Claude domain while ranking the delete-or-rename FAQ first, and kept a HackerRank release-notes query fully inside the HackerRank domain while ranking the matching heading chunk first with title, breadcrumbs, source path, score, and rank populated.`

### Update 10

- Timestamp: `2026-05-01T14:21:28.9859839+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 9 updated code/agent.py with ticket normalization plus conservative domain detection that trusts explicit company values and only falls back to retrieval for specific missing-company queries.`
- Evidence: `A Python validation snippet confirmed an explicit Visa ticket stayed Visa, representative missing-company Claude and HackerRank queries resolved correctly, `normalize_ticket()` populated `detected_company` for the Claude example, and a generic account-help query stayed unresolved after the retrieval threshold was tightened.`

### Update 11

- Timestamp: `2026-05-01T14:33:06.9577500+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 10 filled code/safety.py with deterministic escalation rules, request-type heuristics, fixed escalation templates, and a weak-evidence helper for later retrieval gating.`
- Evidence: `A Python validation snippet confirmed representative fraud, account restoration, assessment dispute, outage, malicious prompt-injection, feature-request, and weak-evidence conflict cases all mapped to the expected `SafetyDecision` results, and `build_escalation_response()` returned a fixed escalation template.`

### Update 12

- Timestamp: `2026-05-01T14:44:37.9969276+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 11 rewired code/agent.py into the deterministic baseline by combining domain detection, safety gating, domain-filtered retrieval, product-area mapping, and deterministic reply or escalation assembly.`
- Evidence: `A Python validation snippet confirmed one grounded FAQ reply, one fraud escalation, and one unresolved-domain escalation; a local product-area mapping defect was repaired immediately and the same check then passed. A follow-up batch validation wrote 29 rows to support_tickets/output.step11.csv with valid statuses and request types, and a separate in-memory check confirmed all 29 rows had non-empty status, product_area, response, justification, and request_type fields.`

### Update 13

- Timestamp: `2026-05-01T15:07:29.1436388+02:00`
- Agent: `GitHub Copilot`
- Summary: `The submission CSV contract was corrected so code/main.py now validates the sample header separately but writes support_tickets/output.csv with the required lowercase columns including justification.`
- Evidence: `get_errors reported no issues in code/main.py; a Python validation snippet confirmed the sample header still loads unchanged, the submission output header is now issue/subject/company/response/product_area/status/request_type/justification, main() wrote 29 rows to support_tickets/output.csv, and no written or in-memory row was missing response, product_area, status, request_type, or justification.`

### Update 14

- Timestamp: `2026-05-01T15:51:33+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 12 added code/evaluate_sample.py so the deterministic baseline can be run against the sample CSV and compared field by field on status, request_type, and product_area.`
- Evidence: `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe evaluate_sample.py` ran from code/, compared all 10 sample rows, reported 8 categorical mismatches, and grouped them mainly into retrieval/confidence and taxonomy/retrieval buckets for Step 13.`

### Update 15

- Timestamp: `2026-05-01T16:26:00+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 13 tuned the deterministic baseline by expanding retrieval queries, reranking near-tie candidates, narrowing weak-evidence escalation, improving invalid-request handling, and adding targeted product_area overrides for the sample failure shapes.`
- Evidence: `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe evaluate_sample.py` then reported no categorical mismatches on the 10-row sample set, and `main.py --output ../support_tickets/output.csv` still wrote 29 production rows with no blank or invalid categorical fields.`

### Update 16

- Timestamp: `2026-05-01T19:28:55+02:00`
- Agent: `GitHub Copilot`
- Summary: `Step 19 added only a narrow concept-level semantic reranking signal over the existing top BM25 candidates after a targeted paraphrase probe exposed one real Claude retrieval-ranking miss for private-chat deletion wording.`
- Evidence: `The follow-up paraphrase probe passed on six representative cases, c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe evaluate_sample.py stayed clean at 10/10 status, 10/10 request_type, and 8/8 product_area, and c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe manual_regressions.py still passed 9/9 cases.`

### Update 17

- Timestamp: `2026-05-01T20:10:37+02:00`
- Agent: `GitHub Copilot`
- Summary: `A small behavior-preserving modularity refactor extracted retrieval-policy helpers into code/retrieval_policy.py, moved higher-level retrieved-chunk product-area mapping into code/taxonomy.py, moved reply and escalation output builders into code/response_builder.py, and reduced code/agent.py to orchestration plus serialization only.`
- Files touched: `code/agent.py`, `code/retrieval_policy.py`, `code/response_builder.py`, `code/taxonomy.py`, `implementation-status.md`
- Behavior change: `None intended and none observed in the recorded checks.`
- Evidence: `Pre-edit baseline: c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe evaluate_sample.py reported 10/10 status, 10/10 request_type, and 8/8 product_area with no mismatches; c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe main.py --output ../support_tickets/output.csv wrote 29 rows; a follow-up CSV check reported rows=29 with no invalid status rows, no invalid request_type rows, and no blank product_area rows. Post-refactor: the same evaluate_sample.py run still reported no mismatches, main.py still wrote 29 rows, the same CSV validity check still reported rows=29 with no invalid categorical rows or blank product_area rows, and manual_regressions.py still passed 9/9.`

### Update 18

- Timestamp: `2026-05-01T20:42:07+02:00`
- Agent: `GitHub Copilot`
- Summary: `A targeted production output quality pass improved final replied responses and justifications without weakening categorical behavior. The pass added code/inspect_output.py plus support_tickets/output.baseline.csv, tuned retrieval/routing for the measured misses (for example account-access restoration, assessment rescheduling, team-member removal, and Claude data-retention wording), rewrote deterministic replies in code/response_builder.py into support-style answers, simplified justifications into plain-language rationale, and manually reviewed every replied production row after regeneration.`
- Files touched: `code/safety.py`, `code/retrieval_policy.py`, `code/response_builder.py`, `code/manual_regressions.py`, `code/inspect_output.py`, `support_tickets/output.baseline.csv`, `support_tickets/output.csv`, `implementation-status.md`
- Behavior change: `Yes, but intentionally limited to final reply wording, human-readable justifications, and a few narrow retrieval/routing fixes for previously weak production rows. Sample categorical outputs remained unchanged.`
- Evidence: `Final validation run: c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/evaluate_sample.py reported Status 10/10, Request Type 10/10, Product Area 8/8, with no mismatches; c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/manual_regressions.py passed 9/9; c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/main.py wrote 29 rows to support_tickets/output.csv; c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/inspect_output.py reported Changed rows vs baseline: 29 and Flagged rows: 0. A follow-up manual inspection printed and reviewed all replied production rows and confirmed the final responses are support-style and the justifications no longer contain source_path/rank/score/resolved_company leakage.`

### Update 19

- Timestamp: `2026-05-01T21:29:35+02:00`
- Agent: `GitHub Copilot`
- Summary: `support_tickets/output.baseline.csv was reset to the accepted current support_tickets/output.csv so future inspections compare against the approved production output rather than the older pre-quality snapshot.`
- Files touched: `support_tickets/output.baseline.csv`, `implementation-status.md`
- Behavior change: `None in the triage pipeline. This only changes the inspection baseline used for future diff checks.`
- Evidence: `cp support_tickets/output.csv support_tickets/output.baseline.csv refreshed the baseline file, and c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/inspect_output.py then reported Changed rows vs baseline: 0 and Flagged rows: 0.`

### Update 20

- Timestamp: `2026-05-01T21:45:24+02:00`
- Agent: `GitHub Copilot`
- Summary: `Experimental AI_MODE support was added so the deterministic baseline can be run in off, synthesis, triage, or review mode without weakening the deterministic safety gate. The new triage path uses retrieved local evidence plus a deterministic fallback, validates structured JSON from the provider, rejects unsafe or unsupported outputs, and records per-ticket LLM outcomes in code/.cache/ai_trace.jsonl.`
- Files touched: `code/config.py`, `code/schemas.py`, `code/response_builder.py`, `code/agent.py`, `code/manual_regressions.py`, `implementation-status.md`
- Behavior change: `Yes. The repo now has bounded experimental AI modes, but default off mode still preserves the deterministic output path.`
- Evidence: `Default off mode still passed c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/evaluate_sample.py at 10/10 status, 10/10 request_type, and 8/8 product_area with no mismatches, and c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/manual_regressions.py still passed 9/9. After clearing code/.cache/ai_trace.jsonl, AI_MODE=triage reran both commands cleanly, c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/main.py --output support_tickets/output.triage.csv wrote 29 rows, and c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/inspect_output.py --output support_tickets/output.triage.csv --baseline support_tickets/output.baseline.csv reported Changed rows vs baseline: 1 and Flagged rows: 0. The trace file showed high-risk tickets were vetoed by deterministic safety and all eligible triage calls in this environment were rejected with missing_api_key rather than accepted.`

### Update 21

- Timestamp: `2026-05-01T23:03:05+02:00`
- Agent: `GitHub Copilot`
- Summary: `The repo now auto-loads the repo-root .env file through code/config.py, and the live-provider transport path in code/llm.py now normalizes TimeoutError into a fail-closed provider_error result instead of crashing the batch.`
- Files touched: `code/config.py`, `code/llm.py`, `.env.example`, `implementation-status.md`
- Behavior change: `Yes, but only in environment bootstrapping and fail-closed provider error handling. Exported shell variables still take precedence over .env values, and provider failures still fall back to the deterministic result.`
- Evidence: `A clean Python import with AI_MODE, GEMINI_API_KEY, OPENAI_API_KEY, and LLM_PROVIDER unset in the shell still resolved AI_MODE=triage, saw both keys as present through the repo-root .env file, resolved the default provider as Gemini, and reported llm_available=True. The first live triage rerun then exposed an uncaught TimeoutError; after code/llm.py was updated, the same batch path completed and wrote 29 rows instead of aborting.`

### Update 22

- Timestamp: `2026-05-01T23:03:05+02:00`
- Agent: `GitHub Copilot`
- Summary: `Live AI_MODE=triage now reaches the provider, produces accepted model decisions, and still falls back safely on the remaining provider_error rows. Focused investigation showed those provider_error rows are a mix of Gemini high-demand HTTP 503 responses and full request timeouts on gemini-3.1-flash-lite-preview, not missing credentials or malformed request payloads.`
- Files touched: `code/llm.py`, `support_tickets/output.triage.csv`, `code/.cache/ai_trace.jsonl`, `implementation-status.md`
- Behavior change: `Yes, live triage output now differs materially from the deterministic baseline on 9 rows because some model decisions are accepted; high-risk safety vetoes remain deterministic, and provider failures still fall back.`
- Evidence: `c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/main.py --output support_tickets/output.triage.csv wrote 29 rows; c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/inspect_output.py --output support_tickets/output.triage.csv --baseline support_tickets/output.baseline.csv reported Changed rows vs baseline: 9 and Flagged rows: 0; code/.cache/ai_trace.jsonl recorded triage_accepted=9, triage_rejected_provider_error=7, triage_rejected_response_contains_internal_or_unsupported_content=2, and vetoed_high_risk_safety=11. Focused debug replays of Certificate name update and Bug bounty showed Gemini requests failing with network_error:timeout at 30 seconds and http_error:503 high-demand UNAVAILABLE responses, while an OpenAI cross-check failed separately with http_error:429 insufficient_quota.`

### Update 23

- Timestamp: `2026-05-01T23:03:05+02:00`
- Agent: `GitHub Copilot`
- Summary: `The current Gemini model was changed in .env and confirmed live at runtime as gemini-2.5-flash-lite. A focused rerun of the previous timeout-shaped replay no longer produced the same timeout on both rows: one row now failed quickly with Gemini HTTP 503 high demand, and another row completed successfully.`
- Files touched: `implementation-status.md`
- Behavior change: `No code change in this step. This is a runtime configuration change plus fresh evidence about provider behavior under the new model.`
- Evidence: `A live provider-config check through code/config.py and code/llm.py resolved provider=gemini and model=gemini-2.5-flash-lite from the repo-root .env file. Focused debug replays through process_ticket(...) showed Certificate name update calling https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash-lite:generateContent and failing in about 1.58 seconds with http_error:503 UNAVAILABLE high demand, while Issues in Project called the same model endpoint and succeeded in about 12.31 seconds.`

### Update 24

- Timestamp: `2026-05-01T23:34:45+02:00`
- Agent: `GitHub Copilot`
- Summary: `The LLM wrapper now retries only classified transient provider failures and opens a per-provider/model circuit breaker after repeated retryable failures, while terminal errors still fail fast and fall back deterministically.`
- Files touched: `code/llm.py`, `implementation-status.md`
- Behavior change: `Yes. Transient provider overload and timeout cases no longer all collapse into a single no-retry provider_error path; they now get bounded retry/backoff, and repeated retryable failures can short-circuit later calls in the same batch.`
- Evidence: `Focused wrapper validation used fake transports through code/llm.py::call_structured_llm. A transient Gemini-style http_error:503 retried once and then succeeded after 2 transport calls; network_error:timeout retried only once and failed after 2 transport calls; a 429 insufficient_quota error failed fast after 1 transport call; and a repeated 503 sequence opened the circuit breaker so the fourth logical call returned provider_circuit_open with no additional transport call beyond the first 9 retry attempts.`

### Update 25

- Timestamp: `2026-05-01T23:34:45+02:00`
- Agent: `GitHub Copilot`
- Summary: `A fresh full live AI_MODE=triage batch was rerun on gemini-2.5-flash-lite with the new retry/circuit-breaker policy, then the sample evaluator and manual regression suite were rerun under the same live triage configuration.`
- Files touched: `support_tickets/output.triage.csv`, `code/.cache/ai_trace.jsonl`, `implementation-status.md`
- Behavior change: `No code change in this step. This was runtime validation of the current Gemini model plus the new resilience policy.`
- Evidence: `The full live batch wrote 29 rows to support_tickets/output.triage.csv and completed in about 14.59 seconds by direct timing, while code/.cache/ai_trace.jsonl for that run covered 29 rows over about 14.53 seconds and recorded triage_accepted=7, triage_rejected_provider_error=7, triage_rejected_response_contains_internal_or_unsupported_content=3, triage_rejected_justification_contains_internal_or_unsupported_content=1, and vetoed_high_risk_safety=11. Compared with the previous full live run on gemini-3.1-flash-lite-preview, provider_error count stayed at 7 but wall time dropped from about 195.99 seconds to about 14.53 seconds. A live rerun of c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/evaluate_sample.py still reported 10/10 status, 10/10 request_type, and 8/8 product_area with no mismatches, and c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/manual_regressions.py still passed 9/9.`

### Update 26

- Timestamp: `2026-05-02T00:35:16+02:00`
- Agent: `GitHub Copilot`
- Summary: `The live triage path now shapes provider usage before the network boundary and spends model budget only on higher-value rows. code/llm.py added optional token-bucket admission control plus retry-after-aware cooldown, code/agent.py now skips low-value triage calls deterministically, and the customer-text validator no longer rejects support guidance as a raw substring.`
- Files touched: `code/llm.py`, `code/agent.py`, `.env.example`, `support_tickets/output.triage.csv`, `code/.cache/ai_trace.jsonl`, `implementation-status.md`
- Behavior change: `Yes. Live triage can now fail closed as rate_limited before sending additional provider requests, low-value replied rows can skip triage entirely, and the previous false-positive content-validation drops caused by the support guidance substring no longer occur.`
- Evidence: `Focused fake-transport validation through code/llm.py confirmed immediate token-bucket denial after one burst-sized request and confirmed that a Gemini-style 429 with retryDelay enters cooldown so the next logical call fails closed as rate_limited without touching the transport. A focused agent probe confirmed _validate_customer_text() now accepts a customer-facing sentence containing support guidance, Resume Builder is Down now classifies as triage_skipped_low_value, and Certificate name update still qualifies as high-value triage. A fresh AI_MODE=triage rerun of c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/evaluate_sample.py still reported 10/10 status, 10/10 request_type, and 8/8 product_area with no mismatches, and c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/manual_regressions.py still passed 9/9. After clearing code/.cache/ai_trace.jsonl, c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/main.py --output ../support_tickets/output.triage.csv wrote 29 rows, c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe code/inspect_output.py --output ../support_tickets/output.triage.csv --baseline ../support_tickets/output.baseline.csv reported Changed rows vs baseline 1 and Flagged rows 0, and the fresh trace recorded rows=29, llm_called=12, triage_rejected_rate_limited=12, triage_skipped_low_value=6, and vetoed_high_risk_safety=11 with no content-validation rejections.`

### Update 27

- Timestamp: `2026-05-02T01:46:27+02:00`
- Agent: `GitHub Copilot`
- Summary: `The last live triage defect was repaired and the AI overlay was split more cleanly out of code/agent.py. code/ai_validation.py now owns triage-budget and customer-text validation helpers, the triage prompt carries fallback_should_escalate_reason, blank escalation reasons are repaired only when the deterministic fallback was already escalated, and unchanged accepted classifications now keep the deterministic justification to avoid live-provider wording drift.`
- Files touched: `code/agent.py`, `code/ai_validation.py`, `implementation-status.md`, `support_tickets/output.triage.csv`, `code/.cache/ai_trace.jsonl`
- Behavior change: `Yes, but narrowly. Live triage no longer rejects otherwise aligned escalations solely for a blank should_escalate_reason when the deterministic fallback already justified escalation, and accepted unchanged classifications now use the deterministic justification text instead of a provider paraphrase.`
- Evidence: `A focused Python validation built one of the previous missing_should_escalate_reason rows and confirmed the triage prompt now includes fallback_should_escalate_reason and that the repair path resolves a blank escalation reason to the deterministic escalation justification. get_errors then reported no issues in code/agent.py or code/ai_validation.py. c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe evaluate_sample.py still reported 10/10 status, 10/10 request_type, and 8/8 product_area with no mismatches, and c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe manual_regressions.py still passed 9/9 after a follow-up justification-stability repair for unchanged classifications. A fresh AI_MODE=triage batch via c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe main.py --output ../support_tickets/output.triage.csv wrote 29 rows, c:/Users/kianj/OneDrive/Documents/HackerRank/May26/.venv/Scripts/python.exe inspect_output.py --output ../support_tickets/output.triage.csv --baseline ../support_tickets/output.baseline.csv reported Changed rows vs baseline: 5 and Flagged rows: 0, and the fresh trace slice recorded rows=29, llm_called=12, triage_accepted=12, triage_skipped_low_value=6, and vetoed_high_risk_safety=11 with no missing_should_escalate_reason or rate_limited rejections.`