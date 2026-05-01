"""Ticket orchestration entrypoints for deterministic triage."""

from __future__ import annotations

from schemas import Company, InputTicket, OutputRow, RequestType, TicketStatus


PLACEHOLDER_RESPONSE = (
	"Thanks for your message. This placeholder batch run confirms the CSV pipeline "
	"only. Grounded routing and support answers will be added in later steps."
)
PLACEHOLDER_JUSTIFICATION = (
	"Placeholder agent flow used for Step 4 before safety rules, retrieval, and "
	"product-area mapping are implemented."
)


def _default_product_area(ticket: InputTicket) -> str:
	if ticket.company and ticket.company is not Company.NONE:
		return ticket.company.value
	return "General Support"


def process_ticket(ticket: InputTicket) -> dict[str, str]:
	"""Return a structurally valid placeholder result for one input ticket."""

	result = OutputRow(
		status=TicketStatus.REPLIED,
		product_area=_default_product_area(ticket),
		response=PLACEHOLDER_RESPONSE,
		justification=PLACEHOLDER_JUSTIFICATION,
		request_type=RequestType.PRODUCT_ISSUE,
	)

	return {
		"status": result.status.value,
		"product_area": result.product_area,
		"response": result.response,
		"justification": result.justification,
		"request_type": result.request_type.value,
	}