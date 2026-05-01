"""Deterministic safety gates and request classification rules."""

from __future__ import annotations

import re
from typing import Final, Sequence

from schemas import (
	Company,
	EscalationCategory,
	InputTicket,
	NormalizedTicket,
	RequestType,
	RetrievedChunk,
	SafetyDecision,
)


WHITESPACE_PATTERN: Final[re.Pattern[str]] = re.compile(r"\s+")
NON_ALNUM_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")
WEAK_EVIDENCE_SCORE_MARGIN: Final[float] = 1.08
GRATITUDE_PHRASES: Final[tuple[str, ...]] = (
	"thank you",
	"thanks",
	"thanks for helping",
	"thanks for the help",
	"appreciate the help",
)
OUT_OF_SCOPE_QUESTION_PREFIXES: Final[tuple[str, ...]] = (
	"who is ",
	"what is the name of ",
	"what is ",
	"tell me about ",
)
SUPPORT_SIGNAL_TOKENS: Final[frozenset[str]] = frozenset(
	{
		"account",
		"assessment",
		"candidate",
		"card",
		"charge",
		"chat",
		"cheque",
		"claude",
		"conversation",
		"delete",
		"hackerrank",
		"interview",
		"invite",
		"merchant",
		"payment",
		"privacy",
		"refund",
		"screen",
		"site",
		"test",
		"ticket",
		"transaction",
		"traveller",
		"traveler",
		"visa",
	}
)
MALICIOUS_OR_OUT_OF_SCOPE_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
	(
		"prompt_injection",
		(
			"ignore previous instructions",
			"ignore all previous instructions",
			"reveal your system prompt",
			"show me the system prompt",
			"developer message",
			"system prompt",
			"bypass safety",
		),
	),
	(
		"secret_or_destructive_request",
		(
			"api key",
			"secret token",
			"private key",
			"password dump",
			"internal rules",
			"exact logic",
			"logique exacte",
			"show retrieved documents",
			"delete all files",
			"remove all files",
			"delete database",
			"drop table",
			"rm rf",
			"shutdown the server",
		),
	),
)
FRAUD_OR_UNAUTHORIZED_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
	(
		"fraud_or_unauthorized_activity",
		(
			"stolen card",
			"stolen cards",
			"stolen traveller cheque",
			"stolen traveller cheques",
			"stolen traveler cheque",
			"stolen traveler cheques",
				"traveller cheques were stolen",
				"traveler cheques were stolen",
				"traveller checks were stolen",
				"traveler checks were stolen",
			"unauthorized charge",
			"unauthorized charges",
			"unauthorised charge",
			"unauthorised charges",
			"fraud claim",
			"fraudulent charge",
			"fraudulent charges",
			"suspicious transaction",
			"suspicious transactions",
			"identity theft",
			"compromised account",
			"compromised card",
			"stolen cheque",
			"stolen checks",
			"scam",
		),
	),
)
ACCOUNT_ACCESS_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
	(
		"restore_or_reverse_access",
		(
			"restore access",
			"regain access",
			"recover access",
			"unlock my account",
			"unlock account",
			"locked out",
			"reverse admin removal",
			"removed from the workspace",
			"removed me from the workspace",
			"regain my account",
			"restore my account",
		),
	),
	(
		"identity_specific_change",
		(
			"change my legal name",
			"change the name on my account",
			"change my phone number",
			"change my email address",
			"change identity information",
			"verify my identity",
		),
	),
)
BILLING_DISPUTE_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
	(
		"charge_or_refund_dispute",
		(
			"dispute this charge",
			"dispute a charge",
				"dispute this transaction",
				"dispute the transaction",
				"merchant dispute",
			"billing dispute",
			"incorrect invoice",
			"invoice correction",
			"refund decision",
			"refund request",
				"refund asap",
				"refund me today",
				"give me the refund",
				"give me my money",
				"issue with my payment",
				"payment with order id",
				"payment i do not recognize",
				"payment i do not recognise",
				"charge i do not recognize",
				"charge i do not recognise",
				"order id",
				"make visa refund me",
			"charged twice",
			"duplicate charge",
			"billing investigation",
		),
	),
)
ASSESSMENT_INTEGRITY_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
	(
		"score_or_integrity_dispute",
		(
			"score dispute",
			"change my score",
			"wrong score",
			"reverse my score",
			"grading dispute",
			"challenge the result",
			"integrity violation",
			"proctoring issue",
			"proctoring decision",
			"cheating accusation",
			"reverse assessment result",
		),
	),
)
OUTAGE_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
	(
		"service_outage",
		(
			"site is down",
			"platform is down",
			"service is down",
				"submissions across any challenges",
			"outage",
			"everyone is affected",
			"for everyone",
			"pages are inaccessible",
			"cannot access the site",
			"nobody can log in",
		),
	),
)
LEGAL_OR_PRIVACY_RULES: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
	(
		"legal_or_compliance_request",
		(
			"legal request",
			"legal hold",
			"compliance review",
				"infosec",
				"security questionnaire",
				"vendor questionnaire",
				"security review form",
				"fill in the forms",
			"regulatory requirement",
			"policy exception",
			"privacy request",
			"gdpr",
			"ccpa",
			"data processing agreement",
		),
	),
)
TEXT_RULES_BY_CATEGORY: Final[
	dict[EscalationCategory, tuple[tuple[str, tuple[str, ...]], ...]]
] = {
	EscalationCategory.MALICIOUS_OR_OUT_OF_SCOPE: MALICIOUS_OR_OUT_OF_SCOPE_RULES,
	EscalationCategory.FRAUD_OR_UNAUTHORIZED: FRAUD_OR_UNAUTHORIZED_RULES,
	EscalationCategory.ACCOUNT_ACCESS: ACCOUNT_ACCESS_RULES,
	EscalationCategory.BILLING_DISPUTE: BILLING_DISPUTE_RULES,
	EscalationCategory.ASSESSMENT_INTEGRITY: ASSESSMENT_INTEGRITY_RULES,
	EscalationCategory.OUTAGE: OUTAGE_RULES,
	EscalationCategory.LEGAL_OR_PRIVACY: LEGAL_OR_PRIVACY_RULES,
}
SAFETY_CATEGORY_ORDER: Final[tuple[EscalationCategory, ...]] = (
	EscalationCategory.MALICIOUS_OR_OUT_OF_SCOPE,
	EscalationCategory.FRAUD_OR_UNAUTHORIZED,
	EscalationCategory.ACCOUNT_ACCESS,
	EscalationCategory.BILLING_DISPUTE,
	EscalationCategory.ASSESSMENT_INTEGRITY,
	EscalationCategory.OUTAGE,
	EscalationCategory.LEGAL_OR_PRIVACY,
)
FEATURE_REQUEST_PHRASES: Final[tuple[str, ...]] = (
	"feature request",
	"please add",
	"can you add",
	"would like to see",
	"i would like",
	"enhancement",
	"add support for",
	"allow users to",
	"it would be helpful",
	"could you support",
)
BUG_PHRASES: Final[tuple[str, ...]] = (
	"bug",
	"error",
	"not working",
	"broken",
	"fails",
	"failed",
	"cannot",
	"can t",
	"unable to",
	"issue with",
	"problem with",
	"crash",
	"crashes",
	"outage",
	"site is down",
	"platform is down",
)
CATEGORY_REASONS: Final[dict[EscalationCategory, str]] = {
	EscalationCategory.MALICIOUS_OR_OUT_OF_SCOPE: (
		"This ticket appears malicious, adversarial, or outside the supported help domains."
	),
	EscalationCategory.FRAUD_OR_UNAUTHORIZED: (
		"This ticket mentions fraud, loss, theft, or unauthorized activity that requires human review."
	),
	EscalationCategory.ACCOUNT_ACCESS: (
		"This ticket asks for account restoration or identity-specific account changes that require human verification."
	),
	EscalationCategory.BILLING_DISPUTE: (
		"This ticket needs account-specific billing investigation or a refund decision."
	),
	EscalationCategory.ASSESSMENT_INTEGRITY: (
		"This ticket disputes an assessment result, grading outcome, or integrity decision that should be escalated."
	),
	EscalationCategory.OUTAGE: (
		"This ticket describes a platform-wide outage or service incident that should be escalated."
	),
	EscalationCategory.LEGAL_OR_PRIVACY: (
		"This ticket requests legal, privacy, or compliance handling outside safe self-service support guidance."
	),
	EscalationCategory.WEAK_EVIDENCE: (
		"Available retrieval evidence is missing, conflicting, or too weak to support a grounded answer."
	),
}
ESCALATION_TEMPLATES: Final[dict[EscalationCategory, str]] = {
	EscalationCategory.MALICIOUS_OR_OUT_OF_SCOPE: (
		"Thanks for reaching out. This request cannot be handled through the automated support flow and has been routed for manual review."
	),
	EscalationCategory.FRAUD_OR_UNAUTHORIZED: (
		"Thanks for reaching out. Because this message mentions possible fraud, loss, theft, or unauthorized activity, it needs human support review for safe account handling."
	),
	EscalationCategory.ACCOUNT_ACCESS: (
		"Thanks for reaching out. This request needs human support review because it involves restoring access or changing identity-specific account details."
	),
	EscalationCategory.BILLING_DISPUTE: (
		"Thanks for reaching out. This billing or refund issue needs human support review because it requires account-specific investigation."
	),
	EscalationCategory.ASSESSMENT_INTEGRITY: (
		"Thanks for reaching out. This assessment or integrity-related issue needs human review because it involves a protected result or decision."
	),
	EscalationCategory.OUTAGE: (
		"Thanks for reaching out. This issue appears to be a wider service incident and has been routed for human support review."
	),
	EscalationCategory.LEGAL_OR_PRIVACY: (
		"Thanks for reaching out. This request needs human support review because it involves legal, privacy, or compliance handling."
	),
	EscalationCategory.WEAK_EVIDENCE: (
		"Thanks for reaching out. I could not verify a grounded answer from the available support material, so this request should be reviewed by human support."
	),
}


def _normalize_text(value: str | None) -> str:
	if not value:
		return ""
	cleaned = NON_ALNUM_PATTERN.sub(" ", value.lower())
	return WHITESPACE_PATTERN.sub(" ", cleaned).strip()


def build_ticket_text(*parts: str | None) -> str:
	"""Return one normalized ticket text string for rule matching."""

	normalized_parts = tuple(part for part in (_normalize_text(value) for value in parts) if part)
	return " ".join(normalized_parts)


def _ticket_text(ticket: InputTicket | NormalizedTicket) -> str:
	if isinstance(ticket, NormalizedTicket):
		return build_ticket_text(ticket.normalized_subject, ticket.normalized_issue)
	return build_ticket_text(ticket.subject, ticket.issue)


def _match_rule_groups(
	text: str,
	rule_groups: Sequence[tuple[str, Sequence[str]]],
) -> tuple[str, ...]:
	matched_rules: list[str] = []
	for rule_name, phrases in rule_groups:
		if any(phrase in text for phrase in phrases):
			matched_rules.append(rule_name)
	return tuple(matched_rules)


def _looks_like_invalid_non_support(text: str) -> bool:
	if not text:
		return False

	tokens = tuple(text.split())
	if any(text.startswith(phrase) for phrase in GRATITUDE_PHRASES) and len(tokens) <= 8:
		return True

	if any(prefix in text for prefix in OUT_OF_SCOPE_QUESTION_PREFIXES):
		if not any(token in SUPPORT_SIGNAL_TOKENS for token in tokens):
			return True

	return False


def classify_request_type(
	ticket: InputTicket | NormalizedTicket | str,
	*,
	matched_category: EscalationCategory | None = None,
) -> RequestType:
	"""Classify a ticket into the constrained request_type taxonomy."""

	text = ticket if isinstance(ticket, str) else _ticket_text(ticket)
	if matched_category is EscalationCategory.MALICIOUS_OR_OUT_OF_SCOPE:
		return RequestType.INVALID
	if matched_category is EscalationCategory.OUTAGE:
		return RequestType.BUG
	if matched_category is not None:
		return RequestType.PRODUCT_ISSUE
	if _looks_like_invalid_non_support(text):
		return RequestType.INVALID
	if any(phrase in text for phrase in FEATURE_REQUEST_PHRASES):
		return RequestType.FEATURE_REQUEST
	if any(phrase in text for phrase in BUG_PHRASES):
		return RequestType.BUG
	return RequestType.PRODUCT_ISSUE


def assess_ticket_safety(ticket: InputTicket | NormalizedTicket) -> SafetyDecision:
	"""Apply deterministic escalation rules to one normalized or raw ticket."""

	text = _ticket_text(ticket)
	for category in SAFETY_CATEGORY_ORDER:
		matched_rules = _match_rule_groups(text, TEXT_RULES_BY_CATEGORY[category])
		if matched_rules:
			return SafetyDecision(
				should_escalate=True,
				category=category,
				reason=CATEGORY_REASONS[category],
				request_type=classify_request_type(text, matched_category=category),
				matched_rules=matched_rules,
			)

	return SafetyDecision(
		should_escalate=False,
		category=None,
		reason="No deterministic escalation rule matched the current ticket text.",
		request_type=classify_request_type(text),
		matched_rules=(),
	)


def build_escalation_response(
	category: EscalationCategory | None,
	*,
	company: Company | None = None,
) -> str:
	"""Return the fixed escalation response template for a category."""

	if category is None:
		return ""
	return ESCALATION_TEMPLATES[category]


def evaluate_retrieval_safety(
	retrieved_chunks: Sequence[RetrievedChunk],
	*,
	expected_domain: Company | None = None,
) -> SafetyDecision | None:
	"""Return a weak-evidence escalation when retrieval support is missing or conflicted."""

	if not retrieved_chunks:
		return SafetyDecision(
			should_escalate=True,
			category=EscalationCategory.WEAK_EVIDENCE,
			reason=CATEGORY_REASONS[EscalationCategory.WEAK_EVIDENCE],
			request_type=RequestType.PRODUCT_ISSUE,
			matched_rules=("no_retrieval_results",),
		)

	top_chunk = retrieved_chunks[0]
	top_score = top_chunk.score or 0.0
	if top_score <= 0.0:
		return SafetyDecision(
			should_escalate=True,
			category=EscalationCategory.WEAK_EVIDENCE,
			reason=CATEGORY_REASONS[EscalationCategory.WEAK_EVIDENCE],
			request_type=RequestType.PRODUCT_ISSUE,
			matched_rules=("non_positive_top_score",),
		)

	if expected_domain is not None and top_chunk.domain is not expected_domain:
		return SafetyDecision(
			should_escalate=True,
			category=EscalationCategory.WEAK_EVIDENCE,
			reason=CATEGORY_REASONS[EscalationCategory.WEAK_EVIDENCE],
			request_type=RequestType.PRODUCT_ISSUE,
			matched_rules=("top_chunk_domain_mismatch",),
		)

	if len(retrieved_chunks) < 2:
		return None

	second_chunk = retrieved_chunks[1]
	second_score = second_chunk.score or 0.0
	if second_score <= 0.0:
		return None

	if expected_domain is not None and second_chunk.domain is not expected_domain:
		if second_score >= top_score / WEAK_EVIDENCE_SCORE_MARGIN:
			return SafetyDecision(
				should_escalate=True,
				category=EscalationCategory.WEAK_EVIDENCE,
				reason=CATEGORY_REASONS[EscalationCategory.WEAK_EVIDENCE],
				request_type=RequestType.PRODUCT_ISSUE,
				matched_rules=("near_tie_domain_conflict",),
			)

	if (
		top_chunk.product_area_hint
		and second_chunk.product_area_hint
		and top_chunk.product_area_hint != second_chunk.product_area_hint
		and "general_support" not in {top_chunk.product_area_hint, second_chunk.product_area_hint}
		and second_score >= top_score / WEAK_EVIDENCE_SCORE_MARGIN
	):
		return SafetyDecision(
			should_escalate=True,
			category=EscalationCategory.WEAK_EVIDENCE,
			reason=CATEGORY_REASONS[EscalationCategory.WEAK_EVIDENCE],
			request_type=RequestType.PRODUCT_ISSUE,
			matched_rules=("near_tie_product_area_conflict",),
		)

	return None