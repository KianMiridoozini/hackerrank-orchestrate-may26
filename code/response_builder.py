"""Reply and escalation output builders for the support triage pipeline."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final, Mapping

from llm import Transport, call_structured_llm
from retrieval_policy import is_generic_product_area
from safety import build_escalation_response
from schemas import (
	Company,
	NormalizedTicket,
	OutputRow,
	RequestType,
	RetrievedChunk,
	SafetyDecision,
	SupportModel,
	TicketStatus,
)
from taxonomy import default_product_area_for_company, map_retrieved_chunk_to_product_area, validate_product_area


WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
MAX_REPLY_LINES: Final[int] = 3
MAX_REPLY_CHARS: Final[int] = 480
LLM_REPLY_EVIDENCE_LIMIT: Final[int] = 2
LLM_REPLY_MAX_OUTPUT_TOKENS: Final[int] = 220
LLM_REPLY_SYSTEM_PROMPT: Final[str] = (
	"You write concise customer-support replies grounded strictly in the supplied help-center evidence. "
	"Do not invent steps, policies, URLs, or account-specific actions. Keep the reply short, direct, and useful."
)
INVALID_REPLY_TEXT: Final[str] = "I am sorry, this is out of scope from my capabilities."


@dataclass(frozen=True)
class ReplyBuildResult:
	response: str
	synthesized_by_llm: bool = False
	llm_provider: str | None = None
	llm_model: str | None = None
	fallback_reason: str | None = None


class _SynthesizedReply(SupportModel):
	response: str


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


def _normalize_reply_text(text: str) -> str:
	collapsed = WHITESPACE_PATTERN.sub(" ", text.strip())
	if not collapsed:
		return ""
	if len(collapsed) <= MAX_REPLY_CHARS:
		return collapsed
	truncated = collapsed[:MAX_REPLY_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:")
	return f"{truncated}..." if truncated else collapsed[:MAX_REPLY_CHARS]


def _is_supported_synthesized_reply(
	response_text: str,
	*,
	top_chunk: RetrievedChunk,
	retrieved_chunks: tuple[RetrievedChunk, ...],
) -> bool:
	lowered_response = response_text.lower()
	if not lowered_response:
		return False
	for forbidden_marker in (
		"source_path",
		"retrieved evidence",
		"evidence 1",
		"evidence 2",
		"fallback_response",
		"title:",
		"heading:",
	):
		if forbidden_marker in lowered_response:
			return False

	metadata_leaks = {
		top_chunk.source_path.lower(),
		top_chunk.title.lower(),
	}
	if top_chunk.heading:
		metadata_leaks.add(top_chunk.heading.lower())
	for chunk in retrieved_chunks[:LLM_REPLY_EVIDENCE_LIMIT]:
		metadata_leaks.add(chunk.source_path.lower())
	for metadata_text in metadata_leaks:
		if metadata_text and metadata_text in lowered_response:
			return False

	return True


def _build_llm_evidence_block(chunk: RetrievedChunk, *, index: int) -> str:
	heading_text = f"\nheading: {chunk.heading}" if chunk.heading else ""
	return (
		f"Evidence {index}:\n"
		f"title: {chunk.title}"
		f"{heading_text}\n"
		f"source_path: {chunk.source_path}\n"
		f"excerpt: {_build_chunk_excerpt(chunk)}"
	)


def _build_reply_synthesis_prompt(
	*,
	normalized_ticket: NormalizedTicket,
	resolved_company: Company,
	product_area: str,
	deterministic_response: str,
	retrieved_chunks: tuple[RetrievedChunk, ...],
) -> str:
	subject_text = normalized_ticket.normalized_subject or "(none)"
	evidence_text = "\n\n".join(
		_build_llm_evidence_block(chunk, index=index)
		for index, chunk in enumerate(retrieved_chunks[:LLM_REPLY_EVIDENCE_LIMIT], start=1)
	)
	return (
		f"company: {resolved_company.value}\n"
		f"product_area: {product_area}\n"
		f"subject: {subject_text}\n"
		f"issue: {normalized_ticket.normalized_issue}\n"
		f"fallback_response: {deterministic_response}\n\n"
		"Use only the evidence below. If the evidence is insufficient or conflicting, return the fallback_response exactly. "
		"Do not mention document titles, source paths, or that you used retrieved evidence.\n\n"
		f"{evidence_text}"
	)


def build_reply_result(
	*,
	normalized_ticket: NormalizedTicket,
	resolved_company: Company,
	request_type: RequestType,
	product_area: str,
	top_chunk: RetrievedChunk,
	retrieved_chunks: tuple[RetrievedChunk, ...],
	llm_environ: Mapping[str, str] | None = None,
	llm_transport: Transport | None = None,
) -> ReplyBuildResult:
	deterministic_response = _build_replied_response(top_chunk)
	if request_type is not RequestType.PRODUCT_ISSUE:
		return ReplyBuildResult(response=deterministic_response, fallback_reason="request_type_not_eligible")
	if is_generic_product_area(product_area):
		return ReplyBuildResult(response=deterministic_response, fallback_reason="generic_product_area")

	llm_result = call_structured_llm(
		response_schema=_SynthesizedReply,
		system_prompt=LLM_REPLY_SYSTEM_PROMPT,
		user_prompt=_build_reply_synthesis_prompt(
			normalized_ticket=normalized_ticket,
			resolved_company=resolved_company,
			product_area=product_area,
			deterministic_response=deterministic_response,
			retrieved_chunks=retrieved_chunks,
		),
		max_output_tokens=LLM_REPLY_MAX_OUTPUT_TOKENS,
		environ=llm_environ,
		transport=llm_transport,
	)
	if not llm_result.succeeded or llm_result.value is None:
		return ReplyBuildResult(
			response=deterministic_response,
			fallback_reason=llm_result.failure_reason or "llm_unavailable",
		)

	synthesized_response = _normalize_reply_text(llm_result.value.response)
	if not synthesized_response:
		return ReplyBuildResult(
			response=deterministic_response,
			fallback_reason="unsupported_synthesized_response",
		)
	if not _is_supported_synthesized_reply(
		synthesized_response,
		top_chunk=top_chunk,
		retrieved_chunks=retrieved_chunks,
	):
		return ReplyBuildResult(
			response=deterministic_response,
			fallback_reason="unsupported_synthesized_response",
		)

	return ReplyBuildResult(
		response=synthesized_response,
		synthesized_by_llm=True,
		llm_provider=llm_result.provider,
		llm_model=llm_result.model,
	)


def build_replied_justification(
	chunk: RetrievedChunk,
	*,
	product_area: str,
	resolved_company: Company | None,
	reply_result: ReplyBuildResult,
) -> str:
	heading_text = f", heading={chunk.heading!r}" if chunk.heading else ""
	company_text = resolved_company.value if resolved_company is not None else "unresolved"
	score_text = f"{(chunk.score or 0.0):.2f}"
	base = (
		f"Replied from retrieved support evidence in {chunk.source_path} "
		f"(title={chunk.title!r}{heading_text}, rank={chunk.rank}, score={score_text}); "
		f"resolved_company={company_text}; product_area={product_area}."
	)
	if not reply_result.synthesized_by_llm:
		if reply_result.fallback_reason is None:
			return base
		return (
			f"{base} Response wording fell back to the deterministic reply because "
			f"optional synthesis was not used ({reply_result.fallback_reason})."
		)
	provider_text = "/".join(
		part for part in (reply_result.llm_provider, reply_result.llm_model) if part
	) or "configured_provider"
	return (
		f"{base} Response wording was synthesized via optional {provider_text} "
		"using the retrieved evidence only while categorical fields remained deterministic."
	)


def build_escalation_justification(
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


def build_escalation_result(
	decision: SafetyDecision,
	*,
	resolved_company: Company | None,
	top_chunk: RetrievedChunk | None = None,
) -> OutputRow:
	product_area = default_product_area_for_company(resolved_company)
	if top_chunk is not None:
		product_area = map_retrieved_chunk_to_product_area(top_chunk, resolved_company)
	return OutputRow(
		status=TicketStatus.ESCALATED,
		product_area=product_area,
		response=build_escalation_response(decision.category, company=resolved_company),
		justification=build_escalation_justification(
			decision,
			product_area=product_area,
			resolved_company=resolved_company,
			top_chunk=top_chunk,
		),
		request_type=decision.request_type,
	)


def build_invalid_result(*, explicit_company: Company | None) -> OutputRow:
	product_area = (
		default_product_area_for_company(explicit_company)
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