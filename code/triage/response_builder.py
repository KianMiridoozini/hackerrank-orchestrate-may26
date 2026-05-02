"""Reply and escalation output builders for the support triage pipeline."""

from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Final, Sequence

from core.schemas import (
	Company,
	EscalationCategory,
	NormalizedTicket,
	OutputRow,
	RequestType,
	RetrievedChunk,
	SafetyDecision,
	TicketStatus,
)
from core.taxonomy import default_product_area_for_company, map_retrieved_chunk_to_product_area, validate_product_area
from retrieval.retrieval_policy import is_generic_product_area
from triage.safety import build_escalation_response


WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")
MARKDOWN_LINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[([^\]]+)\]\([^)]+\)")
MARKDOWN_IMAGE_PATTERN: Final[re.Pattern[str]] = re.compile(r"!\[[^\]]*\]\([^)]+\)")
PLACEHOLDER_PATTERN: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
MAX_REPLY_CHARS: Final[int] = 480
MAX_REPLY_SELECTION_LINES: Final[int] = 3
INVALID_REPLY_TEXT: Final[str] = "I am sorry, this is out of scope from my capabilities."


@dataclass(frozen=True)
class ReplyBuildResult:
	response: str
	justification_note: str
	synthesized_by_llm: bool = False
	llm_provider: str | None = None
	llm_model: str | None = None
	fallback_reason: str | None = None


def _ticket_query_text(normalized_ticket: NormalizedTicket) -> str:
	parts = [normalized_ticket.normalized_subject or "", normalized_ticket.normalized_issue]
	return " ".join(part for part in parts if part).strip()


def _ticket_query_tokens(normalized_ticket: NormalizedTicket) -> frozenset[str]:
	return frozenset(TOKEN_PATTERN.findall(_ticket_query_text(normalized_ticket)))


def _clean_markup(text: str) -> str:
	cleaned = html.unescape(text)
	cleaned = MARKDOWN_IMAGE_PATTERN.sub(" ", cleaned)
	cleaned = MARKDOWN_LINK_PATTERN.sub(r"\1", cleaned)
	cleaned = cleaned.replace("```", " ")
	cleaned = cleaned.replace("\u00a0", " ")
	return WHITESPACE_PATTERN.sub(" ", cleaned).strip()


def _normalize_support_line(raw_line: str) -> str:
	line = _clean_markup(raw_line.strip())
	line = line.lstrip("#>*- ").strip()
	return line


def _friendly_evidence_label(chunk: RetrievedChunk) -> str:
	if chunk.heading:
		label = chunk.heading.split("/")[-1].strip(" *")
		if label:
			return label
	return chunk.title.strip()


def _chunk_support_lines(chunk: RetrievedChunk) -> list[str]:
	labels = {chunk.title.lower()}
	if chunk.heading:
		labels.add(chunk.heading.lower())
	selected_lines: list[str] = []
	seen_lines: set[str] = set()
	for raw_line in chunk.text.splitlines():
		line = _normalize_support_line(raw_line)
		if not line:
			continue
		lowered_line = line.lower()
		if lowered_line in labels:
			continue
		if lowered_line.startswith("last updated") or lowered_line == "embedded media":
			continue
		if lowered_line.startswith("related articles"):
			continue
		if line in seen_lines:
			continue
		selected_lines.append(line)
		seen_lines.add(line)
	return selected_lines


def _extract_steps_after_heading(
	chunk: RetrievedChunk,
	*,
	heading_keywords: Sequence[str],
	max_steps: int = 3,
) -> list[str]:
	steps: list[str] = []
	collecting = False
	for raw_line in chunk.text.splitlines():
		line = _normalize_support_line(raw_line)
		if not line:
			continue
		lowered_line = line.lower()
		if not collecting and all(keyword in lowered_line for keyword in heading_keywords):
			collecting = True
			continue
		if not collecting:
			continue
		if raw_line.lstrip().startswith("#"):
			break
		match = re.match(r"^\d+\.\s*(.+)$", line)
		if match:
			steps.append(match.group(1).strip())
			if len(steps) >= max_steps:
				break
	return steps


def _first_chunk_matching(
	retrieved_chunks: Sequence[RetrievedChunk],
	predicate,
) -> RetrievedChunk | None:
	for chunk in retrieved_chunks:
		if predicate(chunk):
			return chunk
	return None


def _note(text: str) -> str:
	cleaned = text.strip()
	if cleaned.endswith("."):
		return cleaned
	return f"{cleaned}."


def _normalize_reply_text(text: str) -> str:
	collapsed = WHITESPACE_PATTERN.sub(" ", text.strip())
	if not collapsed:
		return ""
	if len(collapsed) <= MAX_REPLY_CHARS:
		return collapsed
	truncated = collapsed[:MAX_REPLY_CHARS].rsplit(" ", 1)[0].rstrip(" ,;:")
	return f"{truncated}..." if truncated else collapsed[:MAX_REPLY_CHARS]


def _build_reschedule_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if not ({"reschedule", "rescheduling"} & query_tokens) or not ({"assessment", "test", "interview"} & query_tokens):
		return None
	evidence_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "reschedule assessments or interviews" in chunk.text.lower()
		or "your recruiter or hiring team" in chunk.text.lower(),
	)
	if evidence_chunk is None:
		return None
	response = (
		"HackerRank Support can't reschedule assessments or interviews. "
		"Please contact your recruiter or hiring team for a new date and time, because they control hiring workflow changes."
	)
	return response, _note("Replied using HackerRank candidate-support guidance for assessment and interview rescheduling")


def _build_remove_user_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if not (({"remove"} <= query_tokens and {"user", "member", "interviewer"} & query_tokens) or {"employee", "left"} <= query_tokens):
		return None
	manage_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "manage-team-members" in chunk.source_path.lower(),
	)
	if manage_chunk is None:
		return None
	remove_steps = _extract_steps_after_heading(
		manage_chunk,
		heading_keywords=("removing", "team", "member"),
		max_steps=2,
	)
	response_parts = [
		"If you have Company Admin or Team Admin access, open Teams Management, choose the relevant team, and use the Users tab to manage that person."
	]
	if remove_steps:
		first_step = remove_steps[0].rstrip(".")
		second_step = remove_steps[1].rstrip(".") if len(remove_steps) > 1 else ""
		removal_text = f"To remove them from the team, {first_step[0].lower() + first_step[1:]}"
		if second_step:
			removal_text += f" and {second_step[0].lower() + second_step[1:]}"
		removal_text += "."
		response_parts.append(
			removal_text
		)
	lock_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "locking-user-access" in chunk.source_path.lower(),
	)
	if lock_chunk is not None and ({"employee", "left"} <= query_tokens or "access" in query_tokens):
		response_parts.append(
			"If you need to prevent them from signing in entirely, you can also lock the user from the Users tab; the account stays available for reuse."
		)
	return " ".join(response_parts), _note(
		"Replied using HackerRank guidance on managing team members and removing or locking user access"
	)


def _build_data_retention_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if not ({"how", "long"} <= query_tokens and "data" in query_tokens and ({"improve", "models"} <= query_tokens or "training" in query_tokens)):
		return None
	training_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "does not use the data you share when using our commercial products to train our models" in chunk.text.lower()
		or "help improve claude" in chunk.text.lower(),
	)
	dpp_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "development-partner-program" in chunk.source_path.lower()
		or "stored securely for up to two years" in chunk.text.lower(),
	)
	retention_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "custom-data-retention-controls" in chunk.source_path.lower()
		or "retained indefinitely unless a custom retention period is set" in chunk.text.lower(),
	)
	response_parts: list[str] = []
	if training_chunk is not None:
		response_parts.append(
			"For Team and Enterprise plans, Anthropic says your data is not used to train models unless your organization joins the Development Partner Program."
		)
	if dpp_chunk is not None:
		if training_chunk is None and retention_chunk is None:
			response_parts.append(
				"The available support guidance here gives a specific duration only for the Development Partner Program: shared Claude Code session data may be stored for up to two years."
			)
		else:
			response_parts.append(
				"If your organization opts into that program, shared Claude Code session data may be stored for up to two years."
			)
	if retention_chunk is not None:
		response_parts.append(
			"Enterprise admins can also set custom retention periods, and the support guidance says data is otherwise retained indefinitely unless a custom retention period is set."
		)
	if not response_parts:
		return None
	return " ".join(response_parts), _note(
		"Replied using Claude guidance on model-improvement participation and data retention"
	)


def _build_lti_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if "lti" not in query_tokens:
		return None
	lti_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "set-up-the-claude-lti-in-canvas" in chunk.source_path.lower(),
	)
	if lti_chunk is None:
		return None
	response = (
		"To set up the Claude LTI in Canvas, create a Claude LTI developer key in Canvas Admin > Developer Keys, "
		"install the app by Client ID under Admin > Settings > Apps, then enable Canvas under Claude for Education "
		"Organization settings > Connectors using your Canvas domain, Client ID, and Deployment ID."
	)
	return response, _note("Replied using Claude for Education guidance on setting up the Canvas LTI integration")


def _build_bedrock_support_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if "bedrock" not in query_tokens:
		return None
	bedrock_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "customer support inquiries" in chunk.title.lower(),
	)
	if bedrock_chunk is None:
		return None
	response = (
		"For Claude in Amazon Bedrock issues, contact AWS Support or your AWS account manager. "
		"If you want community help, the support guidance also points to AWS re:Post."
	)
	return response, _note("Replied using Claude in Amazon Bedrock support guidance")


def _build_urgent_cash_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if "cash" not in query_tokens or "visa" not in query_tokens:
		return None
	travel_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "travel-support" in chunk.source_path.lower(),
	)
	if travel_chunk is None:
		return None
	response = (
		"You can use Visa's ATM locator to find cash withdrawal options worldwide. "
		"Before traveling, Visa also recommends checking with your bank that your card is activated for overseas use and confirming your daily ATM withdrawal limit."
	)
	return response, _note("Replied using Visa travel support guidance about ATM access and travel card use")


def _build_security_report_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if not ({"bug", "bounty"} <= query_tokens or "vulnerability" in query_tokens):
		return None
	security_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "vulnerability-reporting" in chunk.source_path.lower() or "security vulnerability" in chunk.text.lower(),
	)
	if security_chunk is None:
		return None
	response = (
		"Please submit the issue through Anthropic's public vulnerability reporting process. "
		"The support guidance points to the security reporting form for universal jailbreaks and related vulnerability disclosures."
	)
	return response, _note("Replied using Anthropic's public vulnerability reporting guidance")


def _build_website_crawl_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if "crawl" not in query_tokens and "crawler" not in query_tokens:
		return None
	crawl_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "block-the-crawler" in chunk.source_path.lower(),
	)
	if crawl_chunk is None:
		return None
	response = (
		"Anthropic says site owners can control which of its web robots may access their content. "
		"Update your site preferences or robots settings to allow the robots you want and block the ones you don't."
	)
	return response, _note("Replied using Anthropic guidance for site owners who want to control crawler access")


def _build_certificate_name_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if not ({"certificate", "name"} <= query_tokens):
		return None
	certificate_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "certifications-faqs" in chunk.source_path.lower(),
	)
	if certificate_chunk is None:
		return None
	response = (
		"You can update the name on your certificate once per account. "
		"That change applies to all of your certificates, and after you make it, you can't change it again."
	)
	return response, _note("Replied using HackerRank certification guidance on certificate name updates")


def _build_minimum_spend_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if not ({"minimum", "spend"} <= query_tokens and "visa" in query_tokens):
		return None
	visa_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "support.md" in chunk.source_path.lower() and "minimum" in chunk.text.lower() and "visa card" in chunk.text.lower(),
	)
	if visa_chunk is None:
		return None
	response = (
		"In the U.S. and U.S. territories such as the U.S. Virgin Islands, merchants may require a minimum transaction amount of up to US$10 for credit cards only. "
		"If a merchant applies a minimum to a Visa debit card or asks for more than US$10 on a credit card, notify your card issuer."
	)
	return response, _note("Replied using Visa consumer support guidance on minimum transaction amounts")


def _build_subscription_pause_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if not ({"pause", "subscription"} <= query_tokens):
		return None
	pause_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "pause-subscription" in chunk.source_path.lower(),
	)
	if pause_chunk is None:
		return None
	response = (
		"If you're on an eligible monthly self-serve plan, you can pause the subscription instead of canceling it and resume it later when needed. "
		"The support guidance notes that this feature is for individual self-serve subscribers and requires a supported monthly plan."
	)
	return response, _note("Replied using HackerRank guidance on pausing an eligible self-serve subscription")


def _build_cowork_failure_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if not ({"claude", "failing"} <= query_tokens or {"stopped", "working"} <= query_tokens):
		return None
	cowork_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "claude-cowork" in chunk.source_path.lower() and "stopped working on my task" in (chunk.heading or "").lower(),
	)
	if cowork_chunk is None:
		return None
	response = (
		"If this happened while using Claude Cowork, keep the Claude Desktop app open for the entire task. "
		"If the app closed or your computer went to sleep, the Cowork session may have ended."
	)
	return response, _note("Replied using Claude Cowork troubleshooting guidance for interrupted tasks")


def _build_resume_builder_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if not ({"resume", "builder"} <= query_tokens):
		return None
	resume_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "resume-builder" in chunk.source_path.lower(),
	)
	if resume_chunk is None:
		return None
	response = (
		"The available support guidance explains that Resume Builder lets you start from a template or import an existing .doc, .docx, or .pdf resume, "
		"but it does not include a specific outage fix."
	)
	return response, _note("Replied using the available HackerRank Resume Builder guidance, which only covers supported creation flows")


def _build_conversation_deletion_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if not ({"delete", "conversation"} <= query_tokens):
		return None
	conversation_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "how-can-i-delete-or-rename-a-conversation" in chunk.source_path.lower(),
	)
	if conversation_chunk is None:
		return None
	response = (
		"To delete or rename an individual conversation, open that conversation, click its name at the top of the screen, "
		"and choose Delete or Rename. If you need to remove several at once, go to Chats, select the conversations, and use Delete Selected."
	)
	return response, _note("Replied using Claude conversation-management guidance for deleting or renaming conversations")


def _build_account_deletion_reply(
	*,
	query_tokens: frozenset[str],
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str] | None:
	if not ({"delete", "account"} <= query_tokens):
		return None
	console_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "how-can-i-delete-my-claude-console-account" in chunk.source_path.lower(),
	)
	if console_chunk is not None:
		response = (
			"For a Claude Console organization, only Console Admins can delete it from Settings > Organization. "
			"If you have an outstanding balance, you must pay it first in Settings > Billing before the deletion flow can continue."
		)
		return response, _note("Replied using Claude Console account-deletion guidance")
	account_chunk = _first_chunk_matching(
		retrieved_chunks,
		lambda chunk: "how-can-i-delete-my-claude-account" in chunk.source_path.lower(),
	)
	if account_chunk is None:
		return None
	response = (
		"To delete your Claude account, open Settings > Account and use the Delete account option. "
		"If the account has a paid subscription, cancel it from Billing settings, wait for the current period to end, and then complete the deletion flow."
	)
	return response, _note("Replied using Claude account-deletion guidance")


def _chunk_response_score(chunk: RetrievedChunk, query_tokens: frozenset[str]) -> float:
	metadata_text = " ".join(part for part in (chunk.title, chunk.heading or "", chunk.source_path) if part).lower()
	metadata_tokens = frozenset(TOKEN_PATTERN.findall(metadata_text))
	lines = _chunk_support_lines(chunk)[:MAX_REPLY_SELECTION_LINES]
	score = float(len(query_tokens & metadata_tokens) * 2)
	score += sum(len(query_tokens & frozenset(TOKEN_PATTERN.findall(line.lower()))) for line in lines)
	if any(PLACEHOLDER_PATTERN.search(line) for line in lines[:2]):
		score -= 6.0
	if "invitation template" in metadata_text:
		score -= 6.0
	if "related articles" in metadata_text:
		score -= 4.0
	if "/uncategorized/" in chunk.source_path.lower():
		score -= 1.0
	if chunk.product_area_hint and not is_generic_product_area(chunk.product_area_hint):
		score += 1.5
	score -= (chunk.rank or 1) * 0.1
	return score


def _select_generic_reply_chunk(
	*,
	normalized_ticket: NormalizedTicket,
	retrieved_chunks: Sequence[RetrievedChunk],
) -> RetrievedChunk:
	query_tokens = _ticket_query_tokens(normalized_ticket)
	return max(retrieved_chunks, key=lambda chunk: _chunk_response_score(chunk, query_tokens))


def _select_generic_reply_lines(
	*,
	normalized_ticket: NormalizedTicket,
	chunk: RetrievedChunk,
) -> list[str]:
	query_tokens = _ticket_query_tokens(normalized_ticket)
	lines = _chunk_support_lines(chunk)
	if not lines:
		return []
	indexed_scores = []
	for index, line in enumerate(lines):
		line_tokens = frozenset(TOKEN_PATTERN.findall(line.lower()))
		score = float(len(query_tokens & line_tokens))
		if line.endswith("?"):
			score -= 0.5
		if PLACEHOLDER_PATTERN.search(line):
			score -= 6.0
		if line.lower().startswith(("subject:", "email body:")):
			score -= 6.0
		indexed_scores.append((score, index, line))

	best_lines = [
		line
		for score, _, line in sorted(indexed_scores, key=lambda item: (-item[0], item[1]))
		if score > 0.0
	][:MAX_REPLY_SELECTION_LINES]
	if best_lines:
		return best_lines
	return lines[:MAX_REPLY_SELECTION_LINES]


def _build_generic_reply(
	*,
	normalized_ticket: NormalizedTicket,
	retrieved_chunks: Sequence[RetrievedChunk],
) -> tuple[str, str]:
	selected_chunk = _select_generic_reply_chunk(
		normalized_ticket=normalized_ticket,
		retrieved_chunks=retrieved_chunks,
	)
	selected_lines = _select_generic_reply_lines(
		normalized_ticket=normalized_ticket,
		chunk=selected_chunk,
	)
	response = _normalize_reply_text(" ".join(selected_lines))
	if not response:
		response = f"The most relevant support guidance I found is about {_friendly_evidence_label(selected_chunk).lower()}."
	return response, _note(
		f"Replied using retrieved support guidance about {_friendly_evidence_label(selected_chunk).lower()}"
	)


def _build_replied_response(
	*,
	normalized_ticket: NormalizedTicket,
	retrieved_chunks: tuple[RetrievedChunk, ...],
) -> tuple[str, str]:
	query_tokens = _ticket_query_tokens(normalized_ticket)
	for builder in (
		_build_reschedule_reply,
		_build_remove_user_reply,
		_build_conversation_deletion_reply,
		_build_account_deletion_reply,
		_build_data_retention_reply,
		_build_subscription_pause_reply,
		_build_cowork_failure_reply,
		_build_lti_reply,
		_build_bedrock_support_reply,
		_build_urgent_cash_reply,
		_build_security_report_reply,
		_build_website_crawl_reply,
		_build_certificate_name_reply,
		_build_minimum_spend_reply,
		_build_resume_builder_reply,
	):
		result = builder(query_tokens=query_tokens, retrieved_chunks=retrieved_chunks)
		if result is not None:
			return result
	return _build_generic_reply(normalized_ticket=normalized_ticket, retrieved_chunks=retrieved_chunks)


def build_reply_result(
	*,
	normalized_ticket: NormalizedTicket,
	resolved_company: Company,
	request_type: RequestType,
	product_area: str,
	top_chunk: RetrievedChunk,
	retrieved_chunks: tuple[RetrievedChunk, ...],
) -> ReplyBuildResult:
	deterministic_response, justification_note = _build_replied_response(
		normalized_ticket=normalized_ticket,
		retrieved_chunks=retrieved_chunks,
	)
	return ReplyBuildResult(response=deterministic_response, justification_note=justification_note)


def build_replied_justification(
	chunk: RetrievedChunk,
	*,
	product_area: str,
	resolved_company: Company | None,
	reply_result: ReplyBuildResult,
) -> str:
	base = reply_result.justification_note
	if not reply_result.synthesized_by_llm:
		return base
	return f"{base} Wording was smoothed from the same retrieved support guidance without changing the categorical fields."


def build_escalation_justification(
	decision: SafetyDecision,
	*,
	product_area: str,
	resolved_company: Company | None,
	top_chunk: RetrievedChunk | None = None,
) -> str:
	if decision.category is EscalationCategory.WEAK_EVIDENCE:
		if top_chunk is None:
			return "Escalated because the available support material did not provide a reliable grounded answer."
		return (
			"Escalated because the available support material did not provide a reliable grounded answer. "
			f"The closest match was about {_friendly_evidence_label(top_chunk).lower()}, but it did not clearly resolve this request."
		)
	return _note(decision.reason)


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
			"Replied with the out-of-scope template because the ticket text did not look like a supported support request."
		),
		request_type=RequestType.INVALID,
	)