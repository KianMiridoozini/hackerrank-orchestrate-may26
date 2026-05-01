"""Ticket orchestration entrypoints for deterministic triage."""

from __future__ import annotations

import re
from collections import Counter
from typing import Final

from retriever import build_query_text, retrieve_chunks
from safety import assess_ticket_safety, build_escalation_response, evaluate_retrieval_safety
from schemas import (
	Company,
	EscalationCategory,
	InputTicket,
	NormalizedTicket,
	OutputRow,
	RequestType,
	RetrievedChunk,
	SafetyDecision,
	TicketStatus,
)
from taxonomy import map_evidence_to_product_area, validate_product_area


WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")
RETRIEVAL_TOP_K: Final[int] = 8
MAX_REPLY_LINES: Final[int] = 3
MAX_REPLY_CHARS: Final[int] = 480
NON_ACTIONABLE_HEADING_TOKENS: Final[frozenset[str]] = frozenset(
	{
		"related articles",
		"see also",
	}
)
GENERIC_PRODUCT_AREAS: Final[frozenset[str]] = frozenset(
	{
		"general_support",
		"release_notes",
		"additional_resources",
	}
)
INVALID_REPLY_TEXT: Final[str] = "I am sorry, this is out of scope from my capabilities."
QUERY_EXPANSION_RULES: Final[tuple[tuple[frozenset[str], tuple[str, ...]], ...]] = (
	(frozenset({"active", "test"}), ("expiration", "expiry", "expire")),
	(frozenset({"extra", "time"}), ("accommodation", "reinvite")),
	(frozenset({"variant"}), ("variants", "screen")),
	(frozenset({"variants"}), ("variant", "screen")),
	(frozenset({"private", "conversation"}), ("privacy", "delete", "rename", "sensitive")),
	(frozenset({"private", "conversations"}), ("privacy", "delete", "rename", "sensitive")),
	(frozenset({"sensitive", "conversation"}), ("privacy", "delete", "rename", "private")),
	(frozenset({"delete", "conversation"}), ("privacy", "rename", "private", "sensitive")),
	(frozenset({"delete", "conversations"}), ("privacy", "rename", "private", "sensitive")),
	(frozenset({"traveller"}), ("travellers", "travelers", "issuer")),
	(frozenset({"travellers"}), ("traveller", "travelers", "issuer")),
	(frozenset({"traveler"}), ("travellers", "travelers", "issuer")),
	(frozenset({"travelers"}), ("traveller", "travellers", "issuer")),
	(frozenset({"cheque"}), ("cheques", "travellers", "travelers")),
	(frozenset({"cheques"}), ("cheque", "travellers", "travelers")),
	(frozenset({"compatible", "zoom"}), ("compatibility", "system", "browser", "network", "interview")),
	(frozenset({"compatible", "connectivity"}), ("compatibility", "system", "browser", "network")),
	(frozenset({"remove", "user"}), ("users", "team", "teams", "admin")),
	(frozenset({"employee", "left"}), ("remove", "user", "users", "team", "teams", "admin")),
	(frozenset({"bedrock"}), ("amazon", "aws", "support")),
	(frozenset({"lti"}), ("education", "canvas", "developer", "key")),
	(frozenset({"infosec"}), ("security", "questionnaire", "compliance")),
	(frozenset({"vulnerability"}), ("report", "reporting", "disclosure", "bounty", "security")),
	(frozenset({"bounty"}), ("report", "reporting", "disclosure", "vulnerability", "security")),
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


def _default_product_area(company: Company | None) -> str:
	return validate_product_area(
		map_evidence_to_product_area(company=company, default="general_support")
	)


def _query_token_set(query_text: str) -> frozenset[str]:
	return frozenset(TOKEN_PATTERN.findall(query_text.lower()))


def _expand_query_text(query_text: str) -> str:
	if not query_text:
		return query_text

	query_tokens = set(_query_token_set(query_text))
	expanded_terms: list[str] = []
	for trigger_tokens, added_terms in QUERY_EXPANSION_RULES:
		if not trigger_tokens <= query_tokens:
			continue
		for term in added_terms:
			if term not in query_tokens:
				expanded_terms.append(term)
				query_tokens.add(term)

	if not expanded_terms:
		return query_text
	return f"{query_text} {' '.join(expanded_terms)}"


def _chunk_metadata_tokens(chunk: RetrievedChunk) -> frozenset[str]:
	metadata_parts = [chunk.title, chunk.heading or "", " ".join(chunk.breadcrumbs), chunk.source_path]
	return frozenset(TOKEN_PATTERN.findall(" ".join(metadata_parts).lower()))


def _chunk_preference_score(chunk: RetrievedChunk, query_tokens: frozenset[str]) -> float:
	score = chunk.score or 0.0
	metadata_tokens = _chunk_metadata_tokens(chunk)
	path_text = chunk.source_path.lower()
	heading_text = (chunk.heading or "").strip().lower()
	title_text = chunk.title.strip().lower()

	if chunk.product_area_hint and chunk.product_area_hint not in GENERIC_PRODUCT_AREAS:
		score += 2.0
	score += len(query_tokens & metadata_tokens) * 1.15
	if heading_text in NON_ACTIONABLE_HEADING_TOKENS or title_text in NON_ACTIONABLE_HEADING_TOKENS:
		score -= 4.0

	if "release-notes" in path_text or "release_notes" in path_text:
		score -= 2.25
	if "/uncategorized/" in path_text:
		score -= 1.0
	if "skillup/" in path_text and ({"remove", "user"} <= query_tokens or {"employee", "left"} <= query_tokens):
		score -= 3.0

	if {"active", "test"} & query_tokens and {"expiration", "expiry", "expire"} & metadata_tokens:
		score += 3.0
	if {"extra", "time"} <= query_tokens and ({"accommodation", "reinvite", "invite"} & metadata_tokens):
		score += 3.0
	if {"variant", "variants"} & query_tokens and ("screen" in metadata_tokens or "managing" in metadata_tokens):
		score += 2.5
	if {"compatible", "zoom"} <= query_tokens or {"compatible", "connectivity"} <= query_tokens:
		if {"compatibility", "system", "browser", "network", "zoom", "interview"} & metadata_tokens:
			score += 3.5
		if "/interviews/" in path_text:
			score += 12.0
		if "/integrations/" in path_text:
			score -= 8.0
	if {"remove", "user"} <= query_tokens or {"employee", "left"} <= query_tokens:
		if {"remove", "user", "users", "team", "teams", "admin"} & metadata_tokens:
			score += 3.5
		if "/settings/teams-management/" in path_text:
			score += 6.0
		if "/integrations/" in path_text:
			score -= 2.5
	if "bedrock" in query_tokens:
		if "amazon-bedrock" in path_text or "amazon_bedrock" in path_text:
			score += 4.0
		if "team-and-enterprise-plans" in path_text:
			score -= 1.5
	if "lti" in query_tokens and {"lti", "education", "canvas", "developer", "key"} & metadata_tokens:
		score += 4.0
	if {"bug", "bounty"} <= query_tokens or "vulnerability" in query_tokens:
		if {"report", "reporting", "disclosure", "bounty", "vulnerability", "security"} & metadata_tokens:
			score += 3.0
	if {"private", "sensitive"} & query_tokens:
		if {"privacy", "private", "sensitive"} & metadata_tokens:
			score += 3.0
		if "conversation" in metadata_tokens or "delete" in metadata_tokens or "rename" in metadata_tokens:
			score += 1.5
	if {"traveller", "travellers", "traveler", "travelers", "cheque", "cheques"} & query_tokens:
		if {"traveller", "travellers", "traveler", "travelers", "cheque", "cheques", "issuer"} & metadata_tokens:
			score += 2.5

	return score


def _rerank_retrieved_chunks(
	query_text: str,
	retrieved_chunks: tuple[RetrievedChunk, ...],
) -> tuple[RetrievedChunk, ...]:
	if len(retrieved_chunks) < 2:
		return retrieved_chunks

	query_tokens = _query_token_set(query_text)
	reordered = sorted(
		retrieved_chunks,
		key=lambda chunk: (
			-_chunk_preference_score(chunk, query_tokens),
			chunk.rank or 999,
			chunk.source_path,
		),
	)
	return tuple(reordered)


def _product_area_from_chunk(chunk: RetrievedChunk, company: Company | None) -> str:
	lowered_metadata = " ".join(
		part for part in (chunk.title, chunk.heading or "", " ".join(chunk.breadcrumbs), chunk.source_path, chunk.text[:400]) if part
	).lower()
	path_text = chunk.source_path.lower()

	if any(
		keyword in lowered_metadata
		for keyword in (
			"traveller",
			"travellers",
			"traveler",
			"travelers",
			"traveller's cheque",
			"traveler's cheque",
			"cheques",
		)
	):
		return validate_product_area("travel_support")

	if (
		company is Company.HACKERRANK
		and "hackerrank_community/" in path_text
		and ("account-settings/" in path_text or "manage-account" in path_text or "delete-an-account" in path_text)
	):
		return validate_product_area("community")

	if company is Company.CLAUDE and any(
		keyword in lowered_metadata
		for keyword in (
			"privacy",
			"private info",
			"private information",
			"sensitive",
			"who can view my conversations",
			"view my conversations",
		)
	):
		return validate_product_area("privacy")

	product_area_hint = chunk.product_area_hint if chunk.product_area_hint != "general_support" else None

	path_first = map_evidence_to_product_area(
		source_path=chunk.source_path,
		product_area_hint=product_area_hint,
		default="general_support",
	)
	if path_first != "general_support":
		return validate_product_area(path_first)

	breadcrumb_first = map_evidence_to_product_area(
		breadcrumbs=tuple(reversed(chunk.breadcrumbs)),
		product_area_hint=product_area_hint,
		default="general_support",
	)
	if breadcrumb_first != "general_support":
		return validate_product_area(breadcrumb_first)

	return validate_product_area(
		map_evidence_to_product_area(
			breadcrumbs=chunk.breadcrumbs,
			source_path=chunk.source_path,
			product_area_hint=product_area_hint,
			company=company,
			default="general_support",
		)
	)


def _build_chunk_excerpt(chunk: RetrievedChunk) -> str:
	label_candidates = {chunk.title.lower()}
	if chunk.heading:
		label_candidates.add(chunk.heading.lower())

	selected_lines: list[str] = []
	seen_lines: set[str] = set()
	for raw_line in chunk.text.splitlines():
		line = WHITESPACE_PATTERN.sub(" ", raw_line.strip())
		if not line:
			continue
		if line.lower() in label_candidates:
			continue
		if line in seen_lines:
			continue
		selected_lines.append(line)
		seen_lines.add(line)
		if len(selected_lines) >= MAX_REPLY_LINES:
			break

	excerpt = " ".join(selected_lines) if selected_lines else WHITESPACE_PATTERN.sub(" ", chunk.text.strip())
	if len(excerpt) <= MAX_REPLY_CHARS:
		return excerpt
	truncated = excerpt[:MAX_REPLY_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:")
	return f"{truncated}..." if truncated else excerpt[:MAX_REPLY_CHARS]


def _build_replied_response(chunk: RetrievedChunk) -> str:
	excerpt = _build_chunk_excerpt(chunk)
	if excerpt:
		return excerpt
	label = chunk.heading or chunk.title
	return f"The most relevant support guidance I found is in {label}."


def _build_replied_justification(
	chunk: RetrievedChunk,
	*,
	product_area: str,
	resolved_company: Company | None,
) -> str:
	heading_text = f", heading={chunk.heading!r}" if chunk.heading else ""
	company_text = resolved_company.value if resolved_company is not None else "unresolved"
	score_text = f"{(chunk.score or 0.0):.2f}"
	return (
		f"Replied from retrieved support evidence in {chunk.source_path} "
		f"(title={chunk.title!r}{heading_text}, rank={chunk.rank}, score={score_text}); "
		f"resolved_company={company_text}; product_area={product_area}."
	)


def _build_escalation_justification(
	decision: SafetyDecision,
	*,
	product_area: str,
	resolved_company: Company | None,
	top_chunk: RetrievedChunk | None = None,
) -> str:
	category = decision.category.value if decision.category is not None else "unknown"
	matched_rules = ", ".join(decision.matched_rules) if decision.matched_rules else "none"
	company_text = resolved_company.value if resolved_company is not None else "unresolved"
	base = (
		f"Escalated by deterministic rule {category} ({matched_rules}); "
		f"resolved_company={company_text}; product_area={product_area}."
	)
	if top_chunk is None:
		return base
	score_text = f"{(top_chunk.score or 0.0):.2f}"
	return (
		f"{base} Top retrieved evidence was {top_chunk.source_path} "
		f"(rank={top_chunk.rank}, score={score_text})."
	)


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


def _build_escalation_result(
	decision: SafetyDecision,
	*,
	resolved_company: Company | None,
	top_chunk: RetrievedChunk | None = None,
) -> OutputRow:
	product_area = _default_product_area(resolved_company)
	if top_chunk is not None:
		product_area = _product_area_from_chunk(top_chunk, resolved_company)
	return OutputRow(
		status=TicketStatus.ESCALATED,
		product_area=product_area,
		response=build_escalation_response(decision.category, company=resolved_company),
		justification=_build_escalation_justification(
			decision,
			product_area=product_area,
			resolved_company=resolved_company,
			top_chunk=top_chunk,
		),
		request_type=decision.request_type,
	)


def _build_invalid_result(*, explicit_company: Company | None) -> OutputRow:
	product_area = (
		_default_product_area(explicit_company)
		if explicit_company is not None
		else validate_product_area("conversation_management")
	)
	return OutputRow(
		status=TicketStatus.REPLIED,
		product_area=product_area,
		response=INVALID_REPLY_TEXT,
		justification=(
			"Replied with the deterministic invalid-request template because the ticket text did not "
			"look like a supported support request."
		),
		request_type=RequestType.INVALID,
	)


def process_ticket(ticket: InputTicket) -> dict[str, str]:
	"""Run the deterministic ticket baseline without any provider dependency."""

	normalized_ticket = normalize_ticket(ticket)
	resolved_company = normalized_ticket.detected_company or _trusted_company(normalized_ticket.company)
	safety_decision = assess_ticket_safety(normalized_ticket)
	if safety_decision.should_escalate:
		return _serialize_result(
			_build_escalation_result(safety_decision, resolved_company=resolved_company)
		)

	if safety_decision.request_type is RequestType.INVALID:
		return _serialize_result(
			_build_invalid_result(explicit_company=_trusted_company(normalized_ticket.company))
		)

	if resolved_company is None:
		unresolved_domain_decision = _weak_evidence_decision(
			reason="Ticket domain could not be resolved conservatively from the available ticket fields.",
			request_type=safety_decision.request_type,
			matched_rules=("unresolved_domain",),
		)
		return _serialize_result(
			_build_escalation_result(unresolved_domain_decision, resolved_company=resolved_company)
		)

	query_text = build_query_text(normalized_ticket.normalized_subject, normalized_ticket.normalized_issue)
	expanded_query_text = _expand_query_text(query_text)
	retrieved_chunks = _rerank_retrieved_chunks(
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
			_build_escalation_result(
				weak_evidence_decision,
				resolved_company=resolved_company,
				top_chunk=retrieved_chunks[0] if retrieved_chunks else None,
			)
		)

	top_chunk = retrieved_chunks[0]
	product_area = _product_area_from_chunk(top_chunk, resolved_company)

	result = OutputRow(
		status=TicketStatus.REPLIED,
		product_area=product_area,
		response=_build_replied_response(top_chunk),
		justification=_build_replied_justification(
			top_chunk,
			product_area=product_area,
			resolved_company=resolved_company,
		),
		request_type=safety_decision.request_type,
	)

	return _serialize_result(result)