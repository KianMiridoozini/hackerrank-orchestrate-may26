I want to strengthen AI_MODE=triage so the LLM acts as an evidence-grounded triage advisor, not just wording polish.

Current goal:
The deterministic pipeline should still do safety, retrieval, taxonomy validation, and fallback. But for AI_MODE=triage, the LLM should get a meaningful chance to propose the final output row from retrieved local evidence.

Do not change the output CSV schema.

Implement this as a controlled, validated overlay.

Definitions:
- Hard safety categories are:
  - fraud_or_unauthorized
  - account_access_restoration
  - billing_dispute
  - assessment_score_or_integrity
  - outage_or_incident
  - legal_privacy_compliance
  - malicious_or_out_of_scope
- Soft/repairable cases are:
  - weak_or_conflicting_evidence
  - broad/general_support product area
  - near-tie retrieval
  - conflicting top product areas
  - generic deterministic response
  - alternative specific product_area candidate available

Required changes:

1. Add a hard-safety-veto helper.
If deterministic safety matched a hard safety category, AI_MODE=triage must not allow the LLM to change status from escalated to replied.
For hard-veto rows, the LLM may only improve the wording of response and justification, and only if validation passes.

2. Loosen triage call budgeting.
Currently triage is too selective. Add an experimental mode or env flag:
- AI_MODE=triage keeps current budgeted behavior.
- AI_MODE=triage_all or AI_TRIAGE_AGGRESSIVE=1 calls the LLM for every non-invalid row with retrieved evidence.
If adding a new enum is too invasive, use AI_TRIAGE_AGGRESSIVE=1 with the existing AIMode.TRIAGE.

3. Improve the triage prompt.
The prompt should include:
- issue
- subject
- company/domain
- allowed status values
- allowed request_type values
- candidate product_area values only
- deterministic fallback status/request_type/product_area/response/justification
- hard_safety_veto boolean
- whether deterministic escalation is hard or soft
- top 3 to 5 evidence snippets
- each evidence snippet should include a readable topic, candidate product_area, and cleaned content
The prompt must explicitly say:
- use only the supplied local evidence
- do not use outside knowledge
- do not mention source paths, scores, evidence labels, or internal reasoning
- if evidence is insufficient, choose escalated or return the fallback
- if hard_safety_veto=true, do not change escalated to replied

4. Improve acceptance validation.
Accept the LLM triage result only if:
- status is valid
- request_type is valid
- product_area validates and is in candidate_product_areas
- response passes validate_customer_text()
- justification passes validate_customer_text()
- if evidence_support is weak, status must be escalated
- if status is escalated, should_escalate_reason must be present or repairable from fallback
- if hard_safety_veto is true, proposed status must remain escalated
- invalid deterministic request_type cannot be changed by the LLM
- no source paths, rank/score, evidence labels, URLs, or fallback markers appear in response/justification

5. Improve traceability.
Add or extend AI trace output so each row records:
- ai_mode
- llm_called
- accepted/rejected/skipped
- rejection reason
- hard_safety_veto true/false
- budget reasons
- candidate_product_areas
- evidence_support
- categorical changes, if accepted
Do not add these fields to output.csv.

6. Keep deterministic fallback.
If the provider is missing, fails, times out, returns invalid JSON, or fails validation, return deterministic output exactly.

7. Validation after implementation:
Run:
- evaluate_sample.py
- manual_regressions.py
- main.py with AI_MODE=off
- main.py with AI_MODE=triage
- if implemented, main.py with AI_TRIAGE_AGGRESSIVE=1
- inspect_output.py on each generated output
Compare:
- categorical changes
- response quality changes
- justification quality changes
- number of accepted LLM rows
- number of rejected/vetoed LLM rows

Do not make triage mode the final default unless it improves output quality without breaking sample/manual regressions.
Update implementation-status.md with files touched, command evidence, and whether AI triage is safer/better than deterministic output.