"""AI overlay validation and triage-budget policy helpers."""

from __future__ import annotations

from collections import Counter
import re
from typing import Final

from schemas import Company, EscalationCategory, OutputRow, RequestType, RetrievedChunk, TicketStatus
from taxonomy import map_retrieved_chunk_to_product_area


WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
TRIAGE_NEAR_TIE_SCORE_RATIO: Final[float] = 0.92
PRODUCT_AREA_SUPPORT_LIMIT: Final[int] = 5
FORBIDDEN_OUTPUT_MARKERS: Final[tuple[str, ...]] = (
	"source_path",
	"rank=",
	"score=",
	"resolved_company",
	"retrieved evidence",
	"evidence snippet",
	"fallback_response",
	"fallback_justification",
	"fallback_status",
	"fallback_request_type",
	"fallback_product_area",
	"fallback_should_escalate_reason",
	"candidate_product_area",
	"candidate_product_areas",
	"allowed_status_values",
	"allowed_request_type_values",
	"company_or_domain",
	"deterministic_escalation_kind",
	"title:",
	"heading:",
	"topic:",
	"content:",
)
HARD_SAFETY_VETO_CATEGORIES: Final[frozenset[EscalationCategory]] = frozenset(
	{
		EscalationCategory.FRAUD_OR_UNAUTHORIZED,
		EscalationCategory.ACCOUNT_ACCESS,
		EscalationCategory.BILLING_DISPUTE,
		EscalationCategory.ASSESSMENT_INTEGRITY,
		EscalationCategory.OUTAGE,
		EscalationCategory.LEGAL_OR_PRIVACY,
		EscalationCategory.MALICIOUS_OR_OUT_OF_SCOPE,
	}
)


def _normalize_text(value: str | None) -> str:
	if value is None:
		return ""
	return WHITESPACE_PATTERN.sub(" ", value.strip())


def has_hard_safety_veto(category: EscalationCategory | None) -> bool:
	return category in HARD_SAFETY_VETO_CATEGORIES


def _specific_alternative_candidate_product_areas(
	*,
	candidate_product_areas: tuple[str, ...],
	deterministic_product_area: str,
) -> tuple[str, ...]:
	return tuple(
		product_area
		for product_area in candidate_product_areas
		if product_area not in {deterministic_product_area, "general_support"}
	)


def _retrieval_near_tie(retrieved_chunks: tuple[RetrievedChunk, ...]) -> bool:
	if len(retrieved_chunks) < 2:
		return False
	top_score = retrieved_chunks[0].score or 0.0
	second_score = retrieved_chunks[1].score or 0.0
	if top_score <= 0.0 or second_score <= 0.0:
		return False
	return second_score >= (top_score * TRIAGE_NEAR_TIE_SCORE_RATIO)


def _top_chunk_source_diversity(retrieved_chunks: tuple[RetrievedChunk, ...]) -> bool:
	if len(retrieved_chunks) < 2:
		return False
	first_source = (retrieved_chunks[0].source_path or "").lower()
	second_source = (retrieved_chunks[1].source_path or "").lower()
	return bool(first_source and second_source and first_source != second_source)


def _top_chunk_product_area_conflict(
	*,
	retrieved_chunks: tuple[RetrievedChunk, ...],
	resolved_company: Company | None,
) -> bool:
	if len(retrieved_chunks) < 2:
		return False
	first_area = map_retrieved_chunk_to_product_area(retrieved_chunks[0], resolved_company)
	second_area = map_retrieved_chunk_to_product_area(retrieved_chunks[1], resolved_company)
	return first_area != second_area


def triage_budget_reasons(
	*,
	resolved_company: Company | None,
	deterministic_result: OutputRow,
	retrieved_chunks: tuple[RetrievedChunk, ...],
	candidate_product_areas: tuple[str, ...],
) -> tuple[str, ...]:
	if deterministic_result.request_type is RequestType.INVALID:
		return ()

	reasons: list[str] = []
	if resolved_company is None:
		reasons.append("unresolved_company")
	if deterministic_result.status is TicketStatus.ESCALATED:
		reasons.append("deterministic_escalation")
	if deterministic_result.product_area == "general_support":
		reasons.append("broad_product_area")
	specific_alternatives = _specific_alternative_candidate_product_areas(
		candidate_product_areas=candidate_product_areas,
		deterministic_product_area=deterministic_result.product_area,
	)
	if specific_alternatives:
		reasons.append("alternative_specific_product_area")
	if _top_chunk_product_area_conflict(
		retrieved_chunks=retrieved_chunks,
		resolved_company=resolved_company,
	):
		reasons.append("conflicting_top_chunk_product_area")
	elif _retrieval_near_tie(retrieved_chunks) and (
		specific_alternatives or _top_chunk_source_diversity(retrieved_chunks)
	):
		reasons.append("near_tie_retrieval")
	return tuple(reasons)


def _product_area_support_counts(
	*,
	retrieved_chunks: tuple[RetrievedChunk, ...],
	resolved_company: Company | None,
) -> Counter[str]:
	counts: Counter[str] = Counter()
	for chunk in retrieved_chunks[:PRODUCT_AREA_SUPPORT_LIMIT]:
		counts[map_retrieved_chunk_to_product_area(chunk, resolved_company)] += 1
	return counts


def supports_product_area_change(
	*,
	deterministic_product_area: str,
	proposed_product_area: str,
	retrieved_chunks: tuple[RetrievedChunk, ...],
	resolved_company: Company | None,
) -> bool:
	if proposed_product_area == deterministic_product_area:
		return True
	support_counts = _product_area_support_counts(
		retrieved_chunks=retrieved_chunks,
		resolved_company=resolved_company,
	)
	proposed_count = support_counts.get(proposed_product_area, 0)
	deterministic_count = support_counts.get(deterministic_product_area, 0)
	if proposed_count <= deterministic_count:
		return False
	if proposed_count <= 0:
		return False
	max_support = max(support_counts.values(), default=0)
	if proposed_count != max_support:
		return False
	best_supported_areas = [area for area, count in support_counts.items() if count == max_support]
	return len(best_supported_areas) == 1 and best_supported_areas[0] == proposed_product_area


def contains_forbidden_output_content(text: str, *, retrieved_chunks: tuple[RetrievedChunk, ...]) -> bool:
	lowered_text = text.lower()
	if any(marker in lowered_text for marker in FORBIDDEN_OUTPUT_MARKERS):
		return True
	if "http://" in lowered_text or "https://" in lowered_text:
		return True
	for chunk in retrieved_chunks[:3]:
		if chunk.source_path and chunk.source_path.lower() in lowered_text:
			return True
	return False


def validate_customer_text(
	label: str,
	text: str,
	*,
	retrieved_chunks: tuple[RetrievedChunk, ...],
) -> str | None:
	normalized_text = _normalize_text(text)
	if not normalized_text:
		return f"{label}_blank"
	if contains_forbidden_output_content(normalized_text, retrieved_chunks=retrieved_chunks):
		return f"{label}_contains_internal_or_unsupported_content"
	return None


def resolve_should_escalate_reason(
	*,
	proposed_status: TicketStatus,
	proposed_reason: str | None,
	deterministic_result: OutputRow,
) -> str | None:
	if proposed_status is not TicketStatus.ESCALATED:
		return None

	normalized_reason = _normalize_text(proposed_reason)
	if normalized_reason:
		return normalized_reason
	if deterministic_result.status is TicketStatus.ESCALATED:
		fallback_reason = _normalize_text(deterministic_result.justification)
		if fallback_reason:
			return fallback_reason
	return None