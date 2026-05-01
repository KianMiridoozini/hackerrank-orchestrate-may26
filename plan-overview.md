## Plan

Build a small, deterministic batch pipeline instead of a complex agent system. The recommended solution is: preprocess the markdown corpus once into a clean local cache, run each ticket through explicit rule-based triage, retrieve a small set of relevant support snippets from the filtered corpus, and generate a bounded answer only when the evidence is strong enough. Everything else should escalate. This aligns directly with the scoring priorities in `evalutation_criteria.md`: clear architecture, corpus grounding, escalation logic, reproducible execution, clean code, and strong CSV outputs.

*   **Lock the submission contract first.** The agent should stay terminal-based, read the production CSV, write the final predictions CSV, read provider keys from environment variables only, and be runnable from `code/`. Do not build transcript logging into the triage agent. Instead, treat the AI-tool transcript required by `AGENTS.md` and `README.md` as an external submission artifact, and add a checklist item to confirm that shared log file exists before submission.
*   **Freeze the CSV writer from the sample file, not from assumption.** Before writing `output.csv`, inspect `support_tickets/sample_support_tickets.csv` and use its exact column names, casing, and order as the output contract. Internally, the pipeline can normalize field names, but the writer should mirror the sample header exactly. Add a startup validation that fails fast if the sample header cannot be read.
*   **Freeze the `product_area` vocabulary from the sample plus the corpus taxonomy.** Use the sample labels as seeds, then extend and validate them with folder names and breadcrumbs from `data/hackerrank/index.md`, `data/claude/index.md`, and `data/visa/index.md`. Do not let the model invent new labels.
*   **Build one normalized corpus cache.** Parse markdown under `data/`, extract frontmatter and body, normalize titles, strip image noise, keep headings and breadcrumbs, and mark stub pages as non-answer-bearing. Cache this output locally so repeated runs are stable and fast.
*   **Chunk only long documents.** Keep short FAQ-style articles whole. Split only long procedural guides and release-note-style files by headings. This is enough for this corpus size and avoids overengineering.
*   **Use one retrieval pipeline with domain filtering.** First infer or trust the domain, then filter to that slice of the corpus, then rank chunks with TF-IDF or BM25. Add semantic reranking only if the sample results clearly need it.
*   **Make the safety gate run before answer generation.** If a concrete escalation rule matches, set `status` to escalated immediately and skip free-form answering. Use fixed escalation templates instead of model-written escalation text.
*   **Keep `request_type` classification simple and rule-driven.** Use `bug` for broken behavior or downtime, `feature_request` for asks to add or change functionality, `invalid` for malicious, irrelevant, or out-of-scope content, and `product_issue` for the remaining legitimate support requests.
*   **Derive `product_area` from retrieval evidence rather than from a separate classifier.** Use the top retrieved article or the strongest consensus among the top few results and map its breadcrumbs or folder path to the final label.
*   **Answer only from top evidence.** Pass only a small evidence set into the generator, keep responses concise and support-style, and escalate if the evidence is weak, stale, or conflicting.
*   **Validate on the sample first.** Compare `status`, `request_type`, and `product_area` row by row against `support_tickets/sample_support_tickets.csv`, then inspect response and justification quality manually.
*   **Run only one focused error-analysis loop unless failures are structural.** Tune thresholds, routing rules, and retrieval cutoffs, but avoid repeated micro-optimization against the sample.
*   **Harden reproducibility.** Cache the normalized corpus, keep prompts fixed, use temperature 0 for any provider-backed generation, pin dependencies, and ensure repeat runs produce materially identical CSV output.
*   **Prepare the AI Judge explanation in parallel with implementation.** The story should stay simple: normalized corpus, rule-based safety gate, filtered lexical retrieval, bounded generation, deterministic CSV writing.

## Module Layout

*   `main.py`: CLI entrypoint, path resolution, sample-header inspection, batch run over all rows, and final CSV writing.
*   `config.py`: constants, provider and model settings, cache paths, environment variable names, temperature 0 default, and fallback resolution for `support_tickets` versus `support_issues`.
*   `schemas.py`: enums and Pydantic models for input tickets, normalized tickets, retrieved chunks, safety decisions, and final outputs.
*   `corpus.py`: markdown scanning, frontmatter parsing, metadata extraction, title cleanup, stub-page filtering, and heading-based chunking.
*   `retriever.py`: TF-IDF or BM25 lexical retrieval with domain filtering, top-k ranking, and provenance preservation.
*   `safety.py`: deterministic escalation rules, `request_type` heuristics, and helper checks for risky or unsupported cases.
*   `taxonomy.py`: `product_area` vocabulary from sample labels plus corpus breadcrumbs and folder structure, with mapping helpers from evidence to final labels.
*   `llm.py`: optional provider wrapper using environment variables, temperature 0, JSON-only output, and the ability to disable provider use entirely.
    *   *Note: The LLM is only used for bounded response synthesis and difficult tie-breaks. Core routing, escalation, schema validation, and retrieval should work without trusting the model.*
*   `agent.py`: orchestrates one ticket through domain detection, safety gating, retrieval, optional answer synthesis, validation, and final structured output.
*   `evaluate_sample.py`: runs the pipeline against the sample file and compares categorical outputs.
*   `README.md`: install steps, environment setup, run commands, design notes, known limitations, and submission checklist.

## Concrete Escalation Rules

*   **Fraud, lost, stolen, or unauthorized activity.** Escalate if the ticket mentions stolen cards, stolen travellers cheques, unauthorized charges, fraud claims, suspicious transactions, or identity theft.
*   **Account access restoration or identity-specific actions.** Escalate if the user asks to restore access, reverse an admin removal, regain a locked or removed account, or perform identity-specific account actions that require human verification. Only answer documented self-service flows directly.
*   **Billing disputes requiring account lookup.** Escalate if the user disputes a charge, requests a refund decision, asks for invoice-specific corrections, or needs account-specific billing investigation.
*   **Assessment score disputes or integrity and proctoring issues.** Escalate if the user wants a score changed, disputes grading, challenges integrity or proctoring outcomes, or asks to reverse an assessment result.
*   **Outages or service-wide incidents.** Escalate if the user reports that the site is down, pages are inaccessible, or the issue appears platform-wide rather than a normal support how-to question.
*   **Legal, privacy, or compliance exceptions.** Escalate if the user requests policy exceptions, special legal handling, compliance determinations, or privacy actions not explicitly covered by published self-service documentation.
*   **Prompt injection, malicious, or clearly out-of-scope content.** Escalate or mark invalid if the ticket tries to manipulate the agent, requests destructive or unrelated actions, contains adversarial instructions, or is plainly unrelated to the support domains.
*   **Weak or conflicting retrieval evidence.** Escalate if retrieval fails to produce a strong domain-consistent match, if the top results conflict on `product_area`, or if the available evidence is too thin or stale to support a grounded answer.

## Practical Safety Gate Behavior

*   Run escalation checks before any LLM call.
*   If any high-priority escalation rule matches, set `status` to escalated immediately.
*   Use a fixed escalation template tied to the matched rule category.
*   Still assign the best supported `product_area` when possible, but keep it broad and corpus-aligned if routing is uncertain.
*   Only proceed to retrieval-based answering if no escalation rule matches and the evidence is strong enough to support a grounded reply.

## Verification

*   Confirm the sample header is read successfully and that the output writer mirrors its exact structure and order.
*   Confirm the normalized corpus cache excludes stub pages and keeps the expected usable document set.
*   Confirm every emitted `product_area` comes from the allowed taxonomy list.
*   Run the sample CSV and compare categorical outputs row by row.
*   Review replied rows and verify each answer is grounded in retrieved support text.
*   Review escalated rows and verify the escalation reason matches one of the explicit rule categories.
*   Run the full production CSV and check for missing rows, invalid categorical values, or unstable formatting.
*   Re-run the same command and verify materially identical output.
*   Before submission, confirm that the external AI-tool transcript file exists and is ready to upload, without coupling that responsibility to the triage agent.