"""Ticket orchestration entrypoints for deterministic triage."""

from __future__ import annotations

import re
from collections import Counter
from typing import Final, Mapping

from llm import Transport
from response_builder import build_escalation_result, build_invalid_result, build_replied_justification, build_reply_result
from retrieval_policy import expand_query_text, rerank_retrieved_chunks
from retriever import build_query_text, retrieve_chunks
from safety import assess_ticket_safety, evaluate_retrieval_safety
from schemas import (
	Company,
	EscalationCategory,
	InputTicket,
	NormalizedTicket,
	OutputRow,
	RequestType,
	SafetyDecision,
	TicketStatus,
)
from taxonomy import map_retrieved_chunk_to_product_area


WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")
RETRIEVAL_TOP_K: Final[int] = 8


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
	"""Run the deterministic ticket baseline without any provider dependency."""

	normalized_ticket = normalize_ticket(ticket)
	resolved_company = normalized_ticket.detected_company or _trusted_company(normalized_ticket.company)
	safety_decision = assess_ticket_safety(normalized_ticket)
	if safety_decision.should_escalate:
		return _serialize_result(
			build_escalation_result(safety_decision, resolved_company=resolved_company)
		)

	if safety_decision.request_type is RequestType.INVALID:
		return _serialize_result(
			build_invalid_result(explicit_company=_trusted_company(normalized_ticket.company))
		)

	if resolved_company is None:
		unresolved_domain_decision = _weak_evidence_decision(
			reason="Ticket domain could not be resolved conservatively from the available ticket fields.",
			request_type=safety_decision.request_type,
			matched_rules=("unresolved_domain",),
		)
		return _serialize_result(
			build_escalation_result(unresolved_domain_decision, resolved_company=resolved_company)
		)

	query_text = build_query_text(normalized_ticket.normalized_subject, normalized_ticket.normalized_issue)
	expanded_query_text = expand_query_text(query_text)
	retrieved_chunks = rerank_retrieved_chunks(
		expanded_query_text,
		retrieve_chunks(expanded_query_text, domain=resolved_company, top_k=RETRIEVAL_TOP_K),
	)
	weak_evidence = evaluate_retrieval_safety(retrieved_chunks, expected_domain=resolved_company)
	if weak_evidence is not None:
		weak_evidence_decision = _weak_evidence_decision(
			reason=weak_evidence.reason,
			request_type=safety_decision.request_type,
			matched_rules=weak_evidence.matched_rules,
		)
		return _serialize_result(
			build_escalation_result(
				weak_evidence_decision,
				resolved_company=resolved_company,
				top_chunk=retrieved_chunks[0] if retrieved_chunks else None,
			)
		)

	top_chunk = retrieved_chunks[0]
	product_area = map_retrieved_chunk_to_product_area(top_chunk, resolved_company)
	reply_result = build_reply_result(
		normalized_ticket=normalized_ticket,
		resolved_company=resolved_company,
		request_type=safety_decision.request_type,
		product_area=product_area,
		top_chunk=top_chunk,
		retrieved_chunks=retrieved_chunks,
		llm_environ=llm_environ,
		llm_transport=llm_transport,
	)

	result = OutputRow(
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
	)

	return _serialize_result(result)