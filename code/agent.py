"""Ticket orchestration entrypoints for deterministic triage and bounded AI modes."""

from __future__ import annotations

import html
import json
import os
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Final, Mapping

from ai_validation import (
	has_hard_safety_veto,
	resolve_should_escalate_reason,
	supports_product_area_change,
	triage_budget_reasons,
	validate_customer_text,
)
from config import AI_MODE_ENV, AI_TRACE_PATH, AI_TRIAGE_AGGRESSIVE_ENV, DEFAULT_AI_MODE
from llm import Transport, call_structured_llm
from response_builder import build_escalation_result, build_invalid_result, build_replied_justification, build_reply_result
from retrieval_policy import expand_query_text, rerank_retrieved_chunks
from retriever import build_query_text, retrieve_chunks
from safety import assess_ticket_safety, evaluate_retrieval_safety
from schemas import (
	AIMode,
	Company,
	EvidenceSupport,
	EscalationCategory,
	InputTicket,
	NormalizedTicket,
	OutputRow,
	RequestType,
	RetrievedChunk,
	SafetyDecision,
	SupportModel,
	TicketStatus,
)
from taxonomy import default_product_area_for_company, get_product_area_taxonomy, map_retrieved_chunk_to_product_area, validate_product_area


WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")
MARKDOWN_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[([^\]]+)\]\([^)]+\)")
MARKDOWN_IMAGE_PATTERN: Final[re.Pattern[str]] = re.compile(r"!\[[^\]]*\]\([^)]+\)")
RETRIEVAL_TOP_K: Final[int] = 8
AI_EVIDENCE_LIMIT: Final[int] = 3
AI_SYNTHESIS_MAX_OUTPUT_TOKENS: Final[int] = 260
AI_TRIAGE_MAX_OUTPUT_TOKENS: Final[int] = 320
AI_REVIEW_MAX_OUTPUT_TOKENS: Final[int] = 220
SYNTHESIS_SYSTEM_PROMPT: Final[str] = (
	"You rewrite deterministic support responses using only the supplied local evidence. "
	"Keep the ticket status, request type, and product area fixed. "
	"Do not invent policies, URLs, account actions, or facts not present in the evidence. "
	"If you reuse fallback wording, rewrite any internal support-note phrasing into plain customer-facing language. "
	"Do not mention source paths, scores, evidence labels, or internal reasoning."
)
TRIAGE_SYSTEM_PROMPT: Final[str] = (
	"You are a bounded support-triage reasoner. Use only the supplied ticket fields, allowed label values, "
	"candidate product areas, deterministic fallback output, escalation context, and local retrieved evidence. "
	"Use only the supplied local evidence and do not use outside knowledge. "
	"Prefer the fallback status, request type, and product area unless the local evidence clearly supports a different allowed value. "
	"If the evidence is weak, partial, or conflicting, escalate or return the fallback. "
	"If hard_safety_veto=true, keep the fallback status, request type, and product area unchanged. "
	"If you reuse fallback wording, rewrite any internal support-note phrasing into plain customer-facing language. "
	"Do not mention source paths, scores, evidence labels, URLs, fallback markers, or internal reasoning in the response or justification."
)
REVIEW_SYSTEM_PROMPT: Final[str] = (
	"You review a deterministic support-ticket output against supplied local evidence. "
	"Do not rewrite the ticket output. Return only short warnings about grounding, safety, or formatting risks."
)


DOMAIN_KEYWORDS: Final[dict[Company, tuple[str, ...]]] = {
	Company.CLAUDE: (
		"claude",
		"anthropic",
		"conversation",
		"claude code",
		"max plan",
		"team plan",
	),
	Company.HACKERRANK: (
		"hackerrank",
		"assessment",
		"interview",
		"candidate",
		"proctor",
		"screen",
		"question",
	),
	Company.VISA: (
		"visa",
		"card",
		"payment",
		"merchant",
		"transaction",
		"checkout",
		"travellers cheque",
		"traveler cheque",
		"travel cheque",
	),
}
GENERIC_QUERY_TOKENS: Final[frozenset[str]] = frozenset(
	{
		"account",
		"general",
		"help",
		"issue",
		"need",
		"problem",
		"question",
		"some",
		"support",
		"with",
	}
)
MIN_KEYWORD_SCORE: Final[int] = 2
DOMAIN_RETRIEVAL_TOP_K: Final[int] = 5
MIN_RETRIEVAL_DOMAIN_SHARE: Final[float] = 0.6
MIN_RETRIEVAL_MARGIN: Final[float] = 1.15
MIN_SPECIFIC_QUERY_TOKENS: Final[int] = 2


class _SynthesizedReply(SupportModel):
	response: str
	justification: str
	evidence_support: EvidenceSupport


class _TriagedOutput(SupportModel):
	status: TicketStatus
	request_type: RequestType
	product_area: str
	response: str
	justification: str
	evidence_support: EvidenceSupport
	should_escalate_reason: str | None = None


class _ReviewedOutput(SupportModel):
	warnings: tuple[str, ...] = ()
	summary: str | None = None


def _normalize_text(value: str | None) -> str | None:
	if value is None:
		return None
	collapsed = WHITESPACE_PATTERN.sub(" ", value.strip())
	if not collapsed:
		return None
	return collapsed.lower()


def _trusted_company(company: Company | None) -> Company | None:
	if company and company is not Company.NONE:
		return company
	return None


def _resolve_ai_mode(environ: Mapping[str, str] | None = None) -> AIMode:
	resolved_environ = os.environ if environ is None else environ
	configured_value = (resolved_environ.get(AI_MODE_ENV) or DEFAULT_AI_MODE).strip().lower()
	try:
		return AIMode(configured_value)
	except ValueError:
		return AIMode.OFF


def _triage_aggressive_enabled(environ: Mapping[str, str] | None = None) -> bool:
	resolved_environ = os.environ if environ is None else environ
	configured_value = (resolved_environ.get(AI_TRIAGE_AGGRESSIVE_ENV) or "").strip().lower()
	return configured_value in {"1", "true", "yes", "on"}


def _has_specific_query_terms(query_text: str) -> bool:
	specific_tokens = {
		token
		for token in TOKEN_PATTERN.findall(query_text)
		if len(token) >= 4 and token not in GENERIC_QUERY_TOKENS
	}
	return len(specific_tokens) >= MIN_SPECIFIC_QUERY_TOKENS


def _keyword_domain_scores(query_text: str) -> Counter[Company]:
	scores: Counter[Company] = Counter()
	for domain, keywords in DOMAIN_KEYWORDS.items():
		for keyword in keywords:
			if keyword in query_text:
				scores[domain] += 1
	return scores


def _select_keyword_domain(query_text: str) -> Company | None:
	if not query_text:
		return None

	scores = _keyword_domain_scores(query_text)
	if not scores:
		return None

	top_domains = scores.most_common(2)
	top_domain, top_score = top_domains[0]
	second_score = top_domains[1][1] if len(top_domains) > 1 else 0
	if top_score >= MIN_KEYWORD_SCORE and top_score > second_score:
		return top_domain
	return None


def _select_retrieval_domain(query_text: str) -> Company | None:
	if not query_text:
		return None

	results = retrieve_chunks(query_text, top_k=DOMAIN_RETRIEVAL_TOP_K)
	if not results:
		return None

	top_score = results[0].score or 0.0
	if top_score <= 0.0:
		return None

	domain_scores: Counter[Company] = Counter()
	for result in results:
		raw_score = result.score or 0.0
		if raw_score <= 0.0:
			continue
		rank = result.rank or 1
		domain_scores[result.domain] += raw_score / top_score
		domain_scores[result.domain] += 1.0 / rank

	if not domain_scores:
		return None

	ranked_domains = domain_scores.most_common(2)
	top_domain, top_weight = ranked_domains[0]
	second_weight = ranked_domains[1][1] if len(ranked_domains) > 1 else 0.0
	total_weight = sum(domain_scores.values())
	if total_weight <= 0.0:
		return None
	if results[0].domain is not top_domain:
		return None
	if top_weight / total_weight < MIN_RETRIEVAL_DOMAIN_SHARE:
		return None
	if second_weight and top_weight < second_weight * MIN_RETRIEVAL_MARGIN:
		return None
	if len(results) == 1 or second_weight == 0.0:
		return top_domain
	if len(results) >= 2 and results[0].domain is results[1].domain:
		return top_domain
	return None


def _detect_company_from_normalized_text(
	*,
	company: Company | None,
	normalized_issue: str,
	normalized_subject: str | None,
) -> Company | None:
	trusted_company = _trusted_company(company)
	if trusted_company is not None:
		return trusted_company

	query_text = build_query_text(normalized_subject, normalized_issue)
	keyword_domain = _select_keyword_domain(query_text)
	retrieval_domain = _select_retrieval_domain(query_text) if _has_specific_query_terms(query_text) else None
	if retrieval_domain is not None and (keyword_domain is None or retrieval_domain is keyword_domain):
		return retrieval_domain
	return None


def normalize_ticket(ticket: InputTicket) -> NormalizedTicket:
	"""Normalize one ticket and attach the best conservative domain guess."""

	normalized_issue = _normalize_text(ticket.issue) or ""
	normalized_subject = _normalize_text(ticket.subject)
	detected_company = _detect_company_from_normalized_text(
		company=ticket.company,
		normalized_issue=normalized_issue,
		normalized_subject=normalized_subject,
	)
	return NormalizedTicket(
		issue=ticket.issue,
		subject=ticket.subject,
		company=ticket.company,
		normalized_issue=normalized_issue,
		normalized_subject=normalized_subject,
		detected_company=detected_company,
	)


def detect_ticket_domain(ticket: InputTicket | NormalizedTicket) -> Company | None:
	"""Resolve the ticket domain conservatively from company, keywords, and retrieval."""

	if isinstance(ticket, NormalizedTicket):
		return _detect_company_from_normalized_text(
			company=ticket.company,
			normalized_issue=ticket.normalized_issue,
			normalized_subject=ticket.normalized_subject,
		)
	return normalize_ticket(ticket).detected_company


def _weak_evidence_decision(
	*,
	reason: str,
	request_type: RequestType,
	matched_rules: tuple[str, ...],
) -> SafetyDecision:
	return SafetyDecision(
		should_escalate=True,
		category=EscalationCategory.WEAK_EVIDENCE,
		reason=reason,
		request_type=request_type,
		matched_rules=matched_rules,
	)


def _normalize_output_text(value: str) -> str:
	return WHITESPACE_PATTERN.sub(" ", value.strip())


def _clean_evidence_line(raw_line: str) -> str:
	line = html.unescape(raw_line.strip())
	line = MARKDOWN_IMAGE_PATTERN.sub(" ", line)
	line = MARKDOWN_LINK_PATTERN.sub(r"\1", line)
	line = line.replace("```", " ").replace("\u00a0", " ")
	line = line.lstrip("#>*- ").strip()
	return WHITESPACE_PATTERN.sub(" ", line).strip()


def _evidence_label(chunk: RetrievedChunk) -> str:
	if chunk.heading:
		label = chunk.heading.split("/")[-1].strip(" *")
		if label:
			return label
	return chunk.title.strip()


def _evidence_topic(chunk: RetrievedChunk) -> str:
	title = chunk.title.strip()
	label = _evidence_label(chunk)
	if title and label and label.lower() != title.lower():
		return f"{title} - {label}"
	return label or title


def _chunk_support_lines(chunk: RetrievedChunk) -> list[str]:
	labels = {chunk.title.lower()}
	if chunk.heading:
		labels.add(chunk.heading.lower())
	selected_lines: list[str] = []
	seen_lines: set[str] = set()
	for raw_line in chunk.text.splitlines():
		line = _clean_evidence_line(raw_line)
		if not line:
			continue
		lowered_line = line.lower()
		if lowered_line in labels:
			continue
		if lowered_line.startswith("last updated") or lowered_line.startswith("related articles"):
			continue
		if line in seen_lines:
			continue
		selected_lines.append(line)
		seen_lines.add(line)
	return selected_lines


def _build_evidence_prompt(
	*,
	retrieved_chunks: tuple[RetrievedChunk, ...],
	resolved_company: Company | None,
) -> str:
	blocks: list[str] = []
	for index, chunk in enumerate(retrieved_chunks[:AI_EVIDENCE_LIMIT], start=1):
		summary_lines = _chunk_support_lines(chunk)[:3]
		summary_text = " ".join(summary_lines) if summary_lines else _evidence_topic(chunk)
		candidate_product_area = map_retrieved_chunk_to_product_area(chunk, resolved_company)
		blocks.append(
			f"Evidence snippet {index}:\n"
			f"topic: {_evidence_topic(chunk)}\n"
			f"candidate_product_area: {candidate_product_area}\n"
			f"content: {_normalize_output_text(summary_text)}"
		)
	return "\n\n".join(blocks) if blocks else "No retrieved evidence was available."


def _deterministic_escalation_kind(
	*,
	deterministic_result: OutputRow,
	hard_safety_veto: bool,
) -> str:
	if deterministic_result.status is not TicketStatus.ESCALATED:
		return "none"
	return "hard" if hard_safety_veto else "soft"


def _candidate_product_areas(
	*,
	retrieved_chunks: tuple[RetrievedChunk, ...],
	resolved_company: Company | None,
	deterministic_product_area: str,
) -> tuple[str, ...]:
	taxonomy = get_product_area_taxonomy()
	candidates: list[str] = []

	def add_candidate(value: str) -> None:
		try:
			canonical = validate_product_area(value, taxonomy)
		except ValueError:
			return
		if canonical not in candidates:
			candidates.append(canonical)

	for chunk in retrieved_chunks[:AI_EVIDENCE_LIMIT]:
		add_candidate(map_retrieved_chunk_to_product_area(chunk, resolved_company))
	add_candidate(deterministic_product_area)
	add_candidate(default_product_area_for_company(resolved_company))
	if not candidates:
		add_candidate("general_support")
	return tuple(candidates)


def _build_synthesis_prompt(
	*,
	normalized_ticket: NormalizedTicket,
	resolved_company: Company | None,
	deterministic_result: OutputRow,
	retrieved_chunks: tuple[RetrievedChunk, ...],
) -> str:
	company_text = resolved_company.value if resolved_company is not None else "unresolved"
	subject_text = normalized_ticket.normalized_subject or "(none)"
	evidence_text = _build_evidence_prompt(retrieved_chunks=retrieved_chunks, resolved_company=resolved_company)
	return (
		f"company: {company_text}\n"
		f"status: {deterministic_result.status.value}\n"
		f"request_type: {deterministic_result.request_type.value}\n"
		f"product_area: {deterministic_result.product_area}\n"
		f"subject: {subject_text}\n"
		f"issue: {normalized_ticket.normalized_issue}\n"
		f"fallback_response: {deterministic_result.response}\n"
		f"fallback_justification: {deterministic_result.justification}\n\n"
		"Rewrite the response and justification only if the evidence supports them. "
		"If the evidence is weak or conflicting, return the fallback response and fallback justification exactly.\n\n"
		f"{evidence_text}"
	)


def _build_triage_prompt(
	*,
	normalized_ticket: NormalizedTicket,
	resolved_company: Company | None,
	candidate_product_areas: tuple[str, ...],
	deterministic_result: OutputRow,
	hard_safety_veto: bool,
	retrieved_chunks: tuple[RetrievedChunk, ...],
) -> str:
	company_text = resolved_company.value if resolved_company is not None else "unresolved"
	subject_text = normalized_ticket.normalized_subject or "(none)"
	evidence_text = _build_evidence_prompt(retrieved_chunks=retrieved_chunks, resolved_company=resolved_company)
	fallback_should_escalate_reason = (
		deterministic_result.justification
		if deterministic_result.status is TicketStatus.ESCALATED
		else "(none)"
	)
	deterministic_escalation_kind = _deterministic_escalation_kind(
		deterministic_result=deterministic_result,
		hard_safety_veto=hard_safety_veto,
	)
	status_values = ", ".join(status.value for status in TicketStatus)
	request_type_values = ", ".join(request_type.value for request_type in RequestType)
	product_area_values = ", ".join(candidate_product_areas)
	return (
		f"company_or_domain: {company_text}\n"
		f"subject: {subject_text}\n"
		f"issue: {normalized_ticket.normalized_issue}\n"
		f"allowed_status_values: {status_values}\n"
		f"allowed_request_type_values: {request_type_values}\n"
		f"candidate_product_areas: {product_area_values}\n"
		f"hard_safety_veto: {'true' if hard_safety_veto else 'false'}\n"
		f"deterministic_escalation_kind: {deterministic_escalation_kind}\n"
		f"fallback_status: {deterministic_result.status.value}\n"
		f"fallback_request_type: {deterministic_result.request_type.value}\n"
		f"fallback_product_area: {deterministic_result.product_area}\n"
		f"fallback_response: {deterministic_result.response}\n"
		f"fallback_justification: {deterministic_result.justification}\n"
		f"fallback_should_escalate_reason: {fallback_should_escalate_reason}\n\n"
		"Rules:\n"
		"1. Use only the supplied local evidence snippets below. Do not use outside knowledge.\n"
		"2. Return only allowed_status_values, allowed_request_type_values, and candidate_product_areas.\n"
		"3. Only change fallback_status, fallback_request_type, or fallback_product_area when the local evidence clearly and specifically supports a better allowed value.\n"
		"4. If multiple statuses are plausible, keep fallback_status. If multiple product areas are plausible, keep fallback_product_area.\n"
		"5. If evidence is insufficient, partial, or conflicting, either return the fallback or choose status=escalated with a concise should_escalate_reason.\n"
		"6. If hard_safety_veto=true, keep the fallback status, request_type, and product_area unchanged and do not change escalated to replied.\n"
		"7. deterministic_escalation_kind=hard means the deterministic escalation came from a hard safety rule; deterministic_escalation_kind=soft means it came from repairable or weak-evidence conditions.\n"
		"8. If you choose status=escalated, you must provide should_escalate_reason. If the fallback is already escalated and you agree with it, reuse or rewrite fallback_should_escalate_reason concisely.\n"
		"9. Rewrite any reused fallback wording into plain customer-facing language.\n"
		"10. Do not mention source paths, scores, evidence labels, URLs, or internal reasoning.\n\n"
		"Evidence snippets:\n"
		f"{evidence_text}"
	)


def _build_review_prompt(
	*,
	normalized_ticket: NormalizedTicket,
	resolved_company: Company | None,
	deterministic_result: OutputRow,
	retrieved_chunks: tuple[RetrievedChunk, ...],
) -> str:
	company_text = resolved_company.value if resolved_company is not None else "unresolved"
	subject_text = normalized_ticket.normalized_subject or "(none)"
	evidence_text = _build_evidence_prompt(retrieved_chunks=retrieved_chunks, resolved_company=resolved_company)
	return (
		f"company: {company_text}\n"
		f"subject: {subject_text}\n"
		f"issue: {normalized_ticket.normalized_issue}\n"
		f"status: {deterministic_result.status.value}\n"
		f"request_type: {deterministic_result.request_type.value}\n"
		f"product_area: {deterministic_result.product_area}\n"
		f"response: {deterministic_result.response}\n"
		f"justification: {deterministic_result.justification}\n\n"
		"List only real risks. Return warnings only when the deterministic output appears weakly grounded, too internal, unsafe, or inconsistent with the evidence.\n\n"
		f"{evidence_text}"
	)


def _build_deterministic_result(
	*,
	normalized_ticket: NormalizedTicket,
	resolved_company: Company | None,
	safety_decision: SafetyDecision,
	retrieved_chunks: tuple[RetrievedChunk, ...],
) -> tuple[OutputRow, RetrievedChunk | None]:
	top_chunk = retrieved_chunks[0] if retrieved_chunks else None
	if safety_decision.request_type is RequestType.INVALID:
		return build_invalid_result(explicit_company=_trusted_company(normalized_ticket.company)), top_chunk

	if resolved_company is None:
		unresolved_domain_decision = _weak_evidence_decision(
			reason="Ticket domain could not be resolved conservatively from the available ticket fields.",
			request_type=safety_decision.request_type,
			matched_rules=("unresolved_domain",),
		)
		return (
			build_escalation_result(
				unresolved_domain_decision,
				resolved_company=resolved_company,
				top_chunk=top_chunk,
			),
			top_chunk,
		)

	weak_evidence = evaluate_retrieval_safety(retrieved_chunks, expected_domain=resolved_company)
	if weak_evidence is not None:
		weak_evidence_decision = _weak_evidence_decision(
			reason=weak_evidence.reason,
			request_type=safety_decision.request_type,
			matched_rules=weak_evidence.matched_rules,
		)
		return (
			build_escalation_result(
				weak_evidence_decision,
				resolved_company=resolved_company,
				top_chunk=top_chunk,
			),
			top_chunk,
		)

	if top_chunk is None:
		no_results_decision = _weak_evidence_decision(
			reason="Available retrieval evidence is missing, conflicting, or too weak to support a grounded answer.",
			request_type=safety_decision.request_type,
			matched_rules=("no_retrieval_results",),
		)
		return (
			build_escalation_result(
				no_results_decision,
				resolved_company=resolved_company,
			),
			top_chunk,
		)

	product_area = map_retrieved_chunk_to_product_area(top_chunk, resolved_company)
	reply_result = build_reply_result(
		normalized_ticket=normalized_ticket,
		resolved_company=resolved_company,
		request_type=safety_decision.request_type,
		product_area=product_area,
		top_chunk=top_chunk,
		retrieved_chunks=retrieved_chunks,
	)
	return (
		OutputRow(
			status=TicketStatus.REPLIED,
			product_area=product_area,
			response=reply_result.response,
			justification=build_replied_justification(
				top_chunk,
				product_area=product_area,
				resolved_company=resolved_company,
				reply_result=reply_result,
			),
			request_type=safety_decision.request_type,
		),
		top_chunk,
	)


def _apply_synthesis_mode(
	*,
	normalized_ticket: NormalizedTicket,
	resolved_company: Company | None,
	deterministic_result: OutputRow,
	retrieved_chunks: tuple[RetrievedChunk, ...],
	environ: Mapping[str, str] | None,
	transport: Transport | None,
) -> tuple[OutputRow, dict[str, Any]]:
	if deterministic_result.status is not TicketStatus.REPLIED:
		return deterministic_result, {"outcome": "synthesis_skipped_non_replied", "llm_called": False}
	if deterministic_result.request_type is RequestType.INVALID:
		return deterministic_result, {"outcome": "synthesis_skipped_invalid", "llm_called": False}
	if not retrieved_chunks:
		return deterministic_result, {"outcome": "synthesis_skipped_no_evidence", "llm_called": False}

	llm_result = call_structured_llm(
		response_schema=_SynthesizedReply,
		system_prompt=SYNTHESIS_SYSTEM_PROMPT,
		user_prompt=_build_synthesis_prompt(
			normalized_ticket=normalized_ticket,
			resolved_company=resolved_company,
			deterministic_result=deterministic_result,
			retrieved_chunks=retrieved_chunks,
		),
		max_output_tokens=AI_SYNTHESIS_MAX_OUTPUT_TOKENS,
		environ=environ,
		transport=transport,
	)
	trace: dict[str, Any] = {
		"llm_called": True,
		"provider": llm_result.provider,
		"model": llm_result.model,
		"failure_reason": llm_result.failure_reason,
	}
	if not llm_result.succeeded or llm_result.value is None:
		trace["outcome"] = f"synthesis_rejected_{llm_result.failure_reason or 'llm_unavailable'}"
		return deterministic_result, trace

	response_reason = validate_customer_text(
		"response",
		llm_result.value.response,
		retrieved_chunks=retrieved_chunks,
	)
	if response_reason is not None:
		trace["outcome"] = f"synthesis_rejected_{response_reason}"
		return deterministic_result, trace
	justification_reason = validate_customer_text(
		"justification",
		llm_result.value.justification,
		retrieved_chunks=retrieved_chunks,
	)
	if justification_reason is not None:
		trace["outcome"] = f"synthesis_rejected_{justification_reason}"
		return deterministic_result, trace
	if llm_result.value.evidence_support is EvidenceSupport.WEAK:
		trace["outcome"] = "synthesis_rejected_weak_evidence"
		return deterministic_result, trace

	trace["outcome"] = "synthesis_accepted"
	return (
		OutputRow(
			status=deterministic_result.status,
			product_area=deterministic_result.product_area,
			response=_normalize_output_text(llm_result.value.response),
			justification=_normalize_output_text(llm_result.value.justification),
			request_type=deterministic_result.request_type,
		),
		trace,
	)


def _apply_triage_mode(
	*,
	normalized_ticket: NormalizedTicket,
	resolved_company: Company | None,
	deterministic_result: OutputRow,
	hard_safety_veto: bool,
	aggressive_mode: bool,
	retrieved_chunks: tuple[RetrievedChunk, ...],
	environ: Mapping[str, str] | None,
	transport: Transport | None,
) -> tuple[OutputRow, dict[str, Any]]:
	if deterministic_result.request_type is RequestType.INVALID:
		return deterministic_result, {"outcome": "triage_skipped_invalid", "llm_called": False}
	if not retrieved_chunks:
		return deterministic_result, {"outcome": "triage_skipped_no_evidence", "llm_called": False}

	candidate_product_areas = _candidate_product_areas(
		retrieved_chunks=retrieved_chunks,
		resolved_company=resolved_company,
		deterministic_product_area=deterministic_result.product_area,
	)
	budget_reasons = triage_budget_reasons(
		resolved_company=resolved_company,
		deterministic_result=deterministic_result,
		retrieved_chunks=retrieved_chunks,
		candidate_product_areas=candidate_product_areas,
	)
	if aggressive_mode:
		budget_reasons = ("aggressive_mode",)
	elif not budget_reasons:
		return (
			deterministic_result,
			{
				"outcome": "triage_skipped_low_value",
				"llm_called": False,
				"candidate_product_areas": list(candidate_product_areas),
			},
		)
	llm_result = call_structured_llm(
		response_schema=_TriagedOutput,
		system_prompt=TRIAGE_SYSTEM_PROMPT,
		user_prompt=_build_triage_prompt(
			normalized_ticket=normalized_ticket,
			resolved_company=resolved_company,
			candidate_product_areas=candidate_product_areas,
			deterministic_result=deterministic_result,
			hard_safety_veto=hard_safety_veto,
			retrieved_chunks=retrieved_chunks,
		),
		max_output_tokens=AI_TRIAGE_MAX_OUTPUT_TOKENS,
		environ=environ,
		transport=transport,
	)
	trace: dict[str, Any] = {
		"llm_called": True,
		"provider": llm_result.provider,
		"model": llm_result.model,
		"failure_reason": llm_result.failure_reason,
		"candidate_product_areas": list(candidate_product_areas),
		"details": {
			"budget_reasons": list(budget_reasons),
			"hard_safety_veto": hard_safety_veto,
			"aggressive_mode": aggressive_mode,
		},
	}
	if not llm_result.succeeded or llm_result.value is None:
		trace["outcome"] = f"triage_rejected_{llm_result.failure_reason or 'llm_unavailable'}"
		return deterministic_result, trace

	if hard_safety_veto and llm_result.value.status is not TicketStatus.ESCALATED:
		trace["outcome"] = "triage_rejected_hard_safety_veto_status_change"
		return deterministic_result, trace

	try:
		canonical_product_area = validate_product_area(llm_result.value.product_area)
	except ValueError:
		trace["outcome"] = "triage_rejected_invalid_product_area"
		return deterministic_result, trace
	if hard_safety_veto and llm_result.value.request_type is not deterministic_result.request_type:
		trace["outcome"] = "triage_rejected_hard_safety_veto_request_type_change"
		return deterministic_result, trace
	if hard_safety_veto and canonical_product_area != deterministic_result.product_area:
		trace["outcome"] = "triage_rejected_hard_safety_veto_product_area_change"
		return deterministic_result, trace
	if canonical_product_area not in candidate_product_areas:
		trace["outcome"] = "triage_rejected_product_area_outside_candidates"
		return deterministic_result, trace
	if not supports_product_area_change(
		deterministic_product_area=deterministic_result.product_area,
		proposed_product_area=canonical_product_area,
		retrieved_chunks=retrieved_chunks,
		resolved_company=resolved_company,
	):
		trace["outcome"] = "triage_rejected_ambiguous_product_area_change"
		return deterministic_result, trace

	response_reason = validate_customer_text(
		"response",
		llm_result.value.response,
		retrieved_chunks=retrieved_chunks,
	)
	if response_reason is not None:
		trace["outcome"] = f"triage_rejected_{response_reason}"
		return deterministic_result, trace
	justification_reason = validate_customer_text(
		"justification",
		llm_result.value.justification,
		retrieved_chunks=retrieved_chunks,
	)
	if justification_reason is not None:
		trace["outcome"] = f"triage_rejected_{justification_reason}"
		return deterministic_result, trace

	resolved_should_escalate_reason = resolve_should_escalate_reason(
		proposed_status=llm_result.value.status,
		proposed_reason=llm_result.value.should_escalate_reason,
		deterministic_result=deterministic_result,
	)
	if (
		llm_result.value.status is TicketStatus.ESCALATED
		and not _normalize_output_text(llm_result.value.should_escalate_reason or "")
		and resolved_should_escalate_reason is not None
	):
		trace.setdefault("details", {})["repaired_should_escalate_reason"] = True

	if llm_result.value.evidence_support is EvidenceSupport.WEAK:
		if llm_result.value.status is not TicketStatus.ESCALATED:
			trace["outcome"] = "triage_rejected_weak_replied_evidence"
			return deterministic_result, trace
		if resolved_should_escalate_reason is None:
			trace["outcome"] = "triage_rejected_missing_should_escalate_reason"
			return deterministic_result, trace

	if llm_result.value.status is TicketStatus.ESCALATED and resolved_should_escalate_reason is None:
		trace["outcome"] = "triage_rejected_missing_should_escalate_reason"
		return deterministic_result, trace

	accepted_justification = _normalize_output_text(llm_result.value.justification)
	if (
		llm_result.value.status is deterministic_result.status
		and llm_result.value.request_type is deterministic_result.request_type
		and canonical_product_area == deterministic_result.product_area
	):
		accepted_justification = deterministic_result.justification

	trace["outcome"] = "triage_accepted"
	return (
		OutputRow(
			status=deterministic_result.status if hard_safety_veto else llm_result.value.status,
			product_area=deterministic_result.product_area if hard_safety_veto else canonical_product_area,
			response=_normalize_output_text(llm_result.value.response),
			justification=accepted_justification,
			request_type=deterministic_result.request_type if hard_safety_veto else llm_result.value.request_type,
		),
		trace,
	)


def _run_review_mode(
	*,
	normalized_ticket: NormalizedTicket,
	resolved_company: Company | None,
	deterministic_result: OutputRow,
	retrieved_chunks: tuple[RetrievedChunk, ...],
	environ: Mapping[str, str] | None,
	transport: Transport | None,
) -> dict[str, Any]:
	llm_result = call_structured_llm(
		response_schema=_ReviewedOutput,
		system_prompt=REVIEW_SYSTEM_PROMPT,
		user_prompt=_build_review_prompt(
			normalized_ticket=normalized_ticket,
			resolved_company=resolved_company,
			deterministic_result=deterministic_result,
			retrieved_chunks=retrieved_chunks,
		),
		max_output_tokens=AI_REVIEW_MAX_OUTPUT_TOKENS,
		environ=environ,
		transport=transport,
	)
	trace: dict[str, Any] = {
		"llm_called": True,
		"provider": llm_result.provider,
		"model": llm_result.model,
		"failure_reason": llm_result.failure_reason,
	}
	if not llm_result.succeeded or llm_result.value is None:
		trace["outcome"] = f"review_rejected_{llm_result.failure_reason or 'llm_unavailable'}"
		return trace

	warnings = tuple(_normalize_output_text(warning) for warning in llm_result.value.warnings if _normalize_output_text(warning))
	trace["warnings"] = list(warnings)
	trace["summary"] = _normalize_output_text(llm_result.value.summary or "") if llm_result.value.summary else ""
	trace["outcome"] = "review_called_warnings" if warnings else "review_called_clean"
	return trace


def _enum_value(value: Any) -> Any:
	if hasattr(value, "value"):
		return value.value
	return value


def _append_ai_trace(
	*,
	ai_mode: AIMode,
	normalized_ticket: NormalizedTicket,
	resolved_company: Company | None,
	deterministic_result: OutputRow,
	final_result: OutputRow,
	trace: Mapping[str, Any],
) -> None:
	entry = {
		"timestamp": datetime.now(timezone.utc).isoformat(),
		"mode": ai_mode.value,
		"company": (resolved_company or _trusted_company(normalized_ticket.company) or Company.NONE).value,
		"subject": normalized_ticket.subject or "",
		"issue_preview": normalized_ticket.issue[:160],
		"outcome": trace.get("outcome", "unknown"),
		"llm_called": bool(trace.get("llm_called", False)),
		"provider": trace.get("provider"),
		"model": trace.get("model"),
		"failure_reason": trace.get("failure_reason"),
		"warnings": trace.get("warnings", []),
		"details": {key: _enum_value(value) for key, value in (trace.get("details") or {}).items()},
		"candidate_product_areas": trace.get("candidate_product_areas", []),
		"deterministic": {
			"status": deterministic_result.status.value,
			"request_type": deterministic_result.request_type.value,
			"product_area": deterministic_result.product_area,
		},
		"final": {
			"status": final_result.status.value,
			"request_type": final_result.request_type.value,
			"product_area": final_result.product_area,
		},
	}
	AI_TRACE_PATH.parent.mkdir(parents=True, exist_ok=True)
	with AI_TRACE_PATH.open("a", encoding="utf-8") as handle:
		handle.write(json.dumps(entry, ensure_ascii=True) + "\n")


def _serialize_result(result: OutputRow) -> dict[str, str]:
	return {
		"status": result.status.value,
		"product_area": result.product_area,
		"response": result.response,
		"justification": result.justification,
		"request_type": result.request_type.value,
	}


def process_ticket(
	ticket: InputTicket,
	*,
	llm_environ: Mapping[str, str] | None = None,
	llm_transport: Transport | None = None,
) -> dict[str, str]:
	"""Run the deterministic baseline with optional bounded AI overlays."""

	ai_mode = _resolve_ai_mode(llm_environ)
	aggressive_mode = _triage_aggressive_enabled(llm_environ)
	normalized_ticket = normalize_ticket(ticket)
	resolved_company = normalized_ticket.detected_company or _trusted_company(normalized_ticket.company)
	safety_decision = assess_ticket_safety(normalized_ticket)
	hard_safety_veto = has_hard_safety_veto(safety_decision.category)

	retrieved_chunks: tuple[RetrievedChunk, ...] = ()
	if resolved_company is not None or ai_mode is AIMode.TRIAGE:
		query_text = build_query_text(normalized_ticket.normalized_subject, normalized_ticket.normalized_issue)
		expanded_query_text = expand_query_text(query_text)
		retrieved_chunks = tuple(
			rerank_retrieved_chunks(
				expanded_query_text,
				retrieve_chunks(
					expanded_query_text,
					domain=resolved_company,
					top_k=RETRIEVAL_TOP_K,
				),
			)
		)

	if safety_decision.should_escalate:
		deterministic_result = build_escalation_result(safety_decision, resolved_company=resolved_company)
	else:
		deterministic_result, _ = _build_deterministic_result(
			normalized_ticket=normalized_ticket,
			resolved_company=resolved_company,
			safety_decision=safety_decision,
			retrieved_chunks=retrieved_chunks,
		)
	final_result = deterministic_result

	if safety_decision.should_escalate and hard_safety_veto:
		if ai_mode is AIMode.TRIAGE:
			final_result, trace = _apply_triage_mode(
				normalized_ticket=normalized_ticket,
				resolved_company=resolved_company,
				deterministic_result=deterministic_result,
				hard_safety_veto=True,
				aggressive_mode=aggressive_mode,
				retrieved_chunks=retrieved_chunks,
				environ=llm_environ,
				transport=llm_transport,
			)
		elif ai_mode is AIMode.REVIEW:
			trace = _run_review_mode(
				normalized_ticket=normalized_ticket,
				resolved_company=resolved_company,
				deterministic_result=deterministic_result,
				retrieved_chunks=retrieved_chunks,
				environ=llm_environ,
				transport=llm_transport,
			)
		else:
			trace = {
				"outcome": "vetoed_high_risk_safety",
				"llm_called": False,
				"details": {
					"category": safety_decision.category.value if safety_decision.category is not None else "none",
					"hard_safety_veto": True,
				},
			}
		if "details" not in trace:
			trace["details"] = {}
		trace["details"]["category"] = (
			safety_decision.category.value if safety_decision.category is not None else "none"
		)
		trace["details"]["hard_safety_veto"] = True
		_append_ai_trace(
			ai_mode=ai_mode,
			normalized_ticket=normalized_ticket,
			resolved_company=resolved_company,
			deterministic_result=deterministic_result,
			final_result=final_result,
			trace=trace,
		)
		return _serialize_result(final_result)

	if ai_mode is AIMode.OFF:
		trace = {"outcome": "skipped_off", "llm_called": False}
	elif ai_mode is AIMode.SYNTHESIS:
		final_result, trace = _apply_synthesis_mode(
			normalized_ticket=normalized_ticket,
			resolved_company=resolved_company,
			deterministic_result=deterministic_result,
			retrieved_chunks=retrieved_chunks,
			environ=llm_environ,
			transport=llm_transport,
		)
	elif ai_mode is AIMode.TRIAGE:
		final_result, trace = _apply_triage_mode(
			normalized_ticket=normalized_ticket,
			resolved_company=resolved_company,
			deterministic_result=deterministic_result,
			hard_safety_veto=False,
			aggressive_mode=aggressive_mode,
			retrieved_chunks=retrieved_chunks,
			environ=llm_environ,
			transport=llm_transport,
		)
	else:
		trace = _run_review_mode(
			normalized_ticket=normalized_ticket,
			resolved_company=resolved_company,
			deterministic_result=deterministic_result,
			retrieved_chunks=retrieved_chunks,
			environ=llm_environ,
			transport=llm_transport,
		)

	_append_ai_trace(
		ai_mode=ai_mode,
		normalized_ticket=normalized_ticket,
		resolved_company=resolved_company,
		deterministic_result=deterministic_result,
		final_result=final_result,
		trace=trace,
	)
	return _serialize_result(final_result)