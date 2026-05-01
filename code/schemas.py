"""Structured models and enums for tickets, retrieval, and outputs."""

from __future__ import annotations

from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field

try:
	from pydantic import ConfigDict, field_validator
except ImportError:  # pragma: no cover - compatibility for older Pydantic.
	ConfigDict = None
	from pydantic import validator as field_validator  # type: ignore[assignment]


def _before_validator(*field_names: str) -> Callable[[Callable[..., Any]], Any]:
	"""Return a field validator decorator compatible with Pydantic v1 and v2."""

	if ConfigDict is None:
		return field_validator(*field_names, pre=True, allow_reuse=True)
	return field_validator(*field_names, mode="before")


class SupportModel(BaseModel):
	"""Base model with shared validation defaults across pipeline schemas."""

	if ConfigDict is None:

		class Config:
			extra = "forbid"
			anystr_strip_whitespace = True
			allow_population_by_field_name = True

	else:
		model_config = ConfigDict(
			extra="forbid",
			str_strip_whitespace=True,
			populate_by_name=True,
		)

	def to_dict(self) -> dict[str, Any]:
		if hasattr(self, "model_dump"):
			return self.model_dump()
		return self.dict()


class Company(str, Enum):
	HACKERRANK = "HackerRank"
	CLAUDE = "Claude"
	VISA = "Visa"
	NONE = "None"


class AIMode(str, Enum):
	OFF = "off"
	SYNTHESIS = "synthesis"
	TRIAGE = "triage"
	REVIEW = "review"


class EvidenceSupport(str, Enum):
	STRONG = "strong"
	PARTIAL = "partial"
	WEAK = "weak"


class TicketStatus(str, Enum):
	REPLIED = "replied"
	ESCALATED = "escalated"


class RequestType(str, Enum):
	PRODUCT_ISSUE = "product_issue"
	FEATURE_REQUEST = "feature_request"
	BUG = "bug"
	INVALID = "invalid"


class EscalationCategory(str, Enum):
	FRAUD_OR_UNAUTHORIZED = "fraud_or_unauthorized"
	ACCOUNT_ACCESS = "account_access_restoration"
	BILLING_DISPUTE = "billing_dispute"
	ASSESSMENT_INTEGRITY = "assessment_score_or_integrity"
	OUTAGE = "outage_or_incident"
	LEGAL_OR_PRIVACY = "legal_privacy_compliance"
	MALICIOUS_OR_OUT_OF_SCOPE = "malicious_or_out_of_scope"
	WEAK_EVIDENCE = "weak_or_conflicting_evidence"


class InputTicket(SupportModel):
	issue: str
	subject: str | None = None
	company: Company | None = None
	raw_row: dict[str, str] = Field(default_factory=dict)

	@_before_validator("subject")
	def empty_subject_to_none(cls, value: Any) -> Any:
		if isinstance(value, str) and not value.strip():
			return None
		return value

	@_before_validator("company")
	def empty_company_to_none(cls, value: Any) -> Any:
		if value is None:
			return None
		if isinstance(value, str):
			stripped = value.strip()
			if not stripped:
				return None
			return stripped
		return value


class NormalizedTicket(SupportModel):
	issue: str
	subject: str | None = None
	company: Company | None = None
	normalized_issue: str
	normalized_subject: str | None = None
	detected_company: Company | None = None


class RetrievedChunk(SupportModel):
	chunk_id: str
	domain: Company
	source_path: str
	title: str
	text: str
	breadcrumbs: tuple[str, ...] = ()
	heading: str | None = None
	product_area_hint: str | None = None
	score: float | None = None
	rank: int | None = None


class SafetyDecision(SupportModel):
	should_escalate: bool
	category: EscalationCategory | None = None
	reason: str
	request_type: RequestType
	matched_rules: tuple[str, ...] = ()


class OutputRow(SupportModel):
	status: TicketStatus
	product_area: str
	response: str
	justification: str
	request_type: RequestType