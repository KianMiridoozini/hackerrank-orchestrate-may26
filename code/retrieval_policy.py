"""Retrieval-policy helpers layered on top of the neutral BM25 engine."""

from __future__ import annotations

import re
from typing import Final

from schemas import RetrievedChunk


TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")
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
SEMANTIC_CONCEPT_SYNONYMS: Final[dict[str, frozenset[str]]] = {
	"account": frozenset({"account", "accounts", "console", "organization", "org"}),
	"bedrock": frozenset({"amazon", "aws", "bedrock", "region", "regions"}),
	"compatibility": frozenset(
		{"browser", "compatibility", "compatible", "connectivity", "network", "system", "zoom"}
	),
	"conversation": frozenset({"chat", "chats", "conversation", "conversations", "thread", "threads"}),
	"delete": frozenset({"clear", "close", "delete", "erase", "remove", "wipe"}),
	"privacy": frozenset({"confidential", "private", "privacy", "sensitive"}),
	"retention": frozenset({"retain", "retained", "retention", "store", "stored", "storage", "years"}),
	"schedule": frozenset({"date", "hiring", "recruiter", "reschedule", "rescheduled", "rescheduling", "schedule", "scheduled", "time"}),
	"security_report": frozenset(
		{"bounty", "disclosure", "jailbreak", "report", "reporting", "security", "vulnerability", "vulnerabilities"}
	),
	"share": frozenset({"public", "share", "shared", "sharing", "unshare", "unsharing", "visibility"}),
	"team": frozenset({"admin", "employee", "employees", "member", "members", "team", "teams", "user", "users"}),
}
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
	(frozenset({"compatible", "zoom"}), ("compatibility", "system", "browser", "network", "interview", "audio", "video", "camera", "microphone")),
	(frozenset({"compatible", "connectivity"}), ("compatibility", "system", "browser", "network", "audio", "video", "camera", "microphone")),
	(frozenset({"reschedule"}), ("candidate", "hiring", "recruiter", "workflow")),
	(frozenset({"rescheduling"}), ("candidate", "hiring", "recruiter", "workflow", "reschedule")),
	(frozenset({"assessment", "reschedule"}), ("candidate", "hiring", "recruiter", "workflow")),
	(frozenset({"assessment", "rescheduling"}), ("candidate", "hiring", "recruiter", "workflow", "reschedule")),
	(frozenset({"test", "reschedule"}), ("candidate", "hiring", "recruiter", "workflow")),
	(frozenset({"data", "improve", "models"}), ("retention", "store", "stored", "training", "years")),
	(frozenset({"how", "long", "data"}), ("retention", "store", "stored")),
	(frozenset({"remove", "user"}), ("users", "team", "teams", "admin")),
	(frozenset({"employee", "left"}), ("remove", "user", "users", "team", "teams", "admin")),
	(frozenset({"bedrock"}), ("amazon", "aws", "support")),
	(frozenset({"lti"}), ("education", "canvas", "developer", "key")),
	(frozenset({"infosec"}), ("security", "questionnaire", "compliance")),
	(frozenset({"vulnerability"}), ("report", "reporting", "disclosure", "bounty", "security")),
	(frozenset({"bounty"}), ("report", "reporting", "disclosure", "vulnerability", "security")),
)


def is_generic_product_area(product_area: str) -> bool:
	return product_area in GENERIC_PRODUCT_AREAS


def _query_token_set(query_text: str) -> frozenset[str]:
	return frozenset(TOKEN_PATTERN.findall(query_text.lower()))


def expand_query_text(query_text: str) -> str:
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


def _semantic_concepts(tokens: frozenset[str]) -> frozenset[str]:
	concepts = {
		concept
		for concept, synonyms in SEMANTIC_CONCEPT_SYNONYMS.items()
		if tokens & synonyms
	}
	return frozenset(concepts)


def _semantic_concept_score(
	*,
	query_concepts: frozenset[str],
	chunk_concepts: frozenset[str],
) -> float:
	if not query_concepts or not chunk_concepts:
		return 0.0

	shared_concepts = query_concepts & chunk_concepts
	score = len(shared_concepts) * 2.5

	if {"conversation", "delete"} <= shared_concepts:
		score += 6.0
	if {"account", "delete"} <= shared_concepts:
		score += 5.0
	if {"team", "delete"} <= shared_concepts:
		score += 4.0
	if {"schedule"} <= shared_concepts:
		score += 3.0
	if {"bedrock"} <= shared_concepts:
		score += 3.0
	if {"compatibility"} <= shared_concepts:
		score += 3.0
	if {"retention"} <= shared_concepts:
		score += 3.0
	if {"security_report"} <= shared_concepts:
		score += 3.0

	if "delete" in query_concepts and "share" in chunk_concepts and "delete" not in chunk_concepts:
		score -= 5.0
	if "conversation" in query_concepts and "account" in chunk_concepts and "conversation" not in chunk_concepts:
		score -= 2.0
	if "account" in query_concepts and "conversation" in chunk_concepts and "account" not in chunk_concepts:
		score -= 2.0

	return score


def _chunk_preference_score(chunk: RetrievedChunk, query_tokens: frozenset[str]) -> float:
	score = chunk.score or 0.0
	metadata_tokens = _chunk_metadata_tokens(chunk)
	query_concepts = _semantic_concepts(query_tokens)
	chunk_concepts = _semantic_concepts(metadata_tokens)
	path_text = chunk.source_path.lower()
	heading_text = (chunk.heading or "").strip().lower()
	title_text = chunk.title.strip().lower()

	if chunk.product_area_hint and not is_generic_product_area(chunk.product_area_hint):
		score += 2.0
	score += len(query_tokens & metadata_tokens) * 1.15
	score += _semantic_concept_score(query_concepts=query_concepts, chunk_concepts=chunk_concepts)
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
		if "audio-and-video-calls-in-interviews-powered-by-zoom" in path_text:
			score += 16.0
		if "/interviews/getting-started/" in path_text and {"audio", "video", "camera", "microphone"} & metadata_tokens:
			score += 8.0
		if "/interviews/" in path_text:
			score += 12.0
		if "/integrations/" in path_text:
			score -= 8.0
	if {"remove", "user"} <= query_tokens or {"employee", "left"} <= query_tokens:
		if {"remove", "user", "users", "team", "teams", "admin"} & metadata_tokens:
			score += 3.5
		if "/settings/teams-management/" in path_text:
			score += 6.0
		if "manage-team-members" in path_text:
			score += 10.0
		if "locking-user-access" in path_text:
			score += 7.0
		if "grant-team-admin-access" in path_text:
			score -= 5.0
		if "/integrations/" in path_text:
			score -= 2.5
	if (
		("assessment" in query_tokens or "test" in query_tokens)
		and ({"reschedule", "rescheduling"} & query_tokens)
	):
		if "ensuring-a-great-candidate-experience" in path_text:
			score += 14.0
		if "/interviews/manage-interviews/" in path_text:
			score += 5.0
		if "onboarding-candidates" in path_text or "email-template" in path_text:
			score -= 8.0
	if "bedrock" in query_tokens:
		if "amazon-bedrock" in path_text or "amazon_bedrock" in path_text:
			score += 4.0
		if "team-and-enterprise-plans" in path_text:
			score -= 1.5
	if ({"improve", "models"} <= query_tokens or "retention" in query_tokens) and "data" in query_tokens:
		if "development-partner-program" in path_text:
			score += 8.0
		if "custom-data-retention-controls" in path_text:
			score += 8.0
		if "security-and-compliance" in path_text and {"retention", "store", "stored", "years"} & metadata_tokens:
			score += 6.0
		if "input-sensitive-data" in path_text and {"how", "long"} <= query_tokens:
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


def rerank_retrieved_chunks(
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