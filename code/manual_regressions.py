"""Executable manual regression checks for high-risk safety and routing cases."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Final, Sequence

from agent import process_ticket
from schemas import InputTicket


@dataclass(frozen=True)
class ManualRegressionCase:
	case_id: str
	description: str
	ticket: InputTicket
	expected_status: str
	expected_request_type: str
	expected_product_area: str | None = None
	justification_contains: tuple[str, ...] = ()
	response_contains: tuple[str, ...] = ()


@dataclass(frozen=True)
class ManualRegressionResult:
	case: ManualRegressionCase
	output: dict[str, str]
	failures: tuple[str, ...]

	@property
	def passed(self) -> bool:
		return not self.failures


MANUAL_REGRESSION_CASES: Final[tuple[ManualRegressionCase, ...]] = (
	ManualRegressionCase(
		case_id="service_down_outage",
		description="Platform-wide outage reports should escalate as bugs.",
		ticket=InputTicket(
			issue="The site is down for everyone and no one can submit challenges right now.",
			subject="Platform outage",
			company="HackerRank",
		),
		expected_status="escalated",
		expected_request_type="bug",
		expected_product_area="general_support",
		justification_contains=("outage_or_incident", "service_outage"),
		response_contains=("wider service incident",),
	),
	ManualRegressionCase(
		case_id="score_dispute",
		description="Assessment score disputes should escalate.",
		ticket=InputTicket(
			issue="Please change my interview score because the grading was unfair.",
			subject="Score dispute",
			company="HackerRank",
		),
		expected_status="escalated",
		expected_request_type="product_issue",
		expected_product_area="general_support",
		justification_contains=("assessment_score_or_integrity", "score_or_integrity_dispute"),
		response_contains=("assessment or integrity-related issue",),
	),
	ManualRegressionCase(
		case_id="account_restoration",
		description="Account restoration requests should escalate.",
		ticket=InputTicket(
			issue="I was removed as an admin. Please restore my account access immediately.",
			subject="Restore access",
			company="HackerRank",
		),
		expected_status="escalated",
		expected_request_type="product_issue",
		expected_product_area="general_support",
		justification_contains=("account_access_restoration", "restore_or_reverse_access"),
		response_contains=("restoring access",),
	),
	ManualRegressionCase(
		case_id="claude_conversation_deletion",
		description="Conversation deletion should stay a grounded self-service reply.",
		ticket=InputTicket(
			issue="How do I delete a conversation that has sensitive information in Claude?",
			subject="Delete conversation",
			company="Claude",
		),
		expected_status="replied",
		expected_request_type="product_issue",
		expected_product_area="conversation_management",
		justification_contains=("8230524-how-can-i-delete-or-rename-a-conversation.md",),
		response_contains=("delete or rename an individual conversation",),
	),
	ManualRegressionCase(
		case_id="claude_account_deletion",
		description="Account deletion should route differently from conversation deletion.",
		ticket=InputTicket(
			issue="Delete my Claude account permanently and remove all billing history.",
			subject="Delete account",
			company="Claude",
		),
		expected_status="replied",
		expected_request_type="product_issue",
		expected_product_area="claude_api_and_console",
		justification_contains=("10366376-how-can-i-delete-my-claude-console-account.md",),
		response_contains=("outstanding balance",),
	),
	ManualRegressionCase(
		case_id="visa_stolen_traveller_cheques",
		description="Stolen travellers-cheque cases should escalate as fraud/unauthorized activity.",
		ticket=InputTicket(
			issue="My traveler cheques were stolen while traveling abroad.",
			subject="Stolen instrument",
			company="Visa",
		),
		expected_status="escalated",
		expected_request_type="product_issue",
		expected_product_area="general_support",
		justification_contains=("fraud_or_unauthorized", "fraud_or_unauthorized_activity"),
		response_contains=("possible fraud, loss, theft, or unauthorized activity",),
	),
	ManualRegressionCase(
		case_id="visa_unauthorized_charge",
		description="Unauthorized charge cases should escalate immediately.",
		ticket=InputTicket(
			issue="Someone used my Visa card for an unauthorized charge yesterday.",
			subject="Unauthorized charge",
			company="Visa",
		),
		expected_status="escalated",
		expected_request_type="product_issue",
		expected_product_area="general_support",
		justification_contains=("fraud_or_unauthorized", "fraud_or_unauthorized_activity"),
		response_contains=("possible fraud, loss, theft, or unauthorized activity",),
	),
	ManualRegressionCase(
		case_id="merchant_dispute",
		description="Merchant disputes should escalate for account-specific billing review.",
		ticket=InputTicket(
			issue="A merchant charged me for a payment I do not recognize and I need this disputed.",
			subject="Merchant dispute",
			company="Visa",
		),
		expected_status="escalated",
		expected_request_type="product_issue",
		expected_product_area="general_support",
		justification_contains=("billing_dispute", "charge_or_refund_dispute"),
		response_contains=("billing or refund issue",),
	),
	ManualRegressionCase(
		case_id="obviously_unrelated_prompt",
		description="Clearly unrelated prompts should be treated as invalid.",
		ticket=InputTicket(
			issue="What is the capital of France?",
			subject="General knowledge",
		),
		expected_status="replied",
		expected_request_type="invalid",
		justification_contains=("invalid-request template",),
		response_contains=("out of scope from my capabilities",),
	),
)


def evaluate_manual_regressions(
	cases: Sequence[ManualRegressionCase] = MANUAL_REGRESSION_CASES,
) -> list[ManualRegressionResult]:
	results: list[ManualRegressionResult] = []
	for case in cases:
		output = process_ticket(case.ticket, llm_environ={})
		failures: list[str] = []

		if output.get("status") != case.expected_status:
			failures.append(
				f"status expected {case.expected_status!r} but got {output.get('status')!r}"
			)
		if output.get("request_type") != case.expected_request_type:
			failures.append(
				f"request_type expected {case.expected_request_type!r} but got {output.get('request_type')!r}"
			)
		if case.expected_product_area is not None and output.get("product_area") != case.expected_product_area:
			failures.append(
				f"product_area expected {case.expected_product_area!r} but got {output.get('product_area')!r}"
			)

		justification = output.get("justification", "")
		for expected_text in case.justification_contains:
			if expected_text not in justification:
				failures.append(f"justification missing {expected_text!r}")

		response = output.get("response", "")
		for expected_text in case.response_contains:
			if expected_text not in response:
				failures.append(f"response missing {expected_text!r}")

		results.append(
			ManualRegressionResult(
				case=case,
				output=output,
				failures=tuple(failures),
			)
		)
	return results


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--show-passed", action="store_true")
	return parser.parse_args(argv)


def _print_results(results: Sequence[ManualRegressionResult], *, show_passed: bool) -> None:
	passed_count = sum(1 for result in results if result.passed)
	print(f"Manual regression cases: {len(results)}")
	print(f"Passed: {passed_count}")
	print(f"Failed: {len(results) - passed_count}")

	for result in results:
		if result.passed and not show_passed:
			continue
		status_text = "PASS" if result.passed else "FAIL"
		print(f"\n[{status_text}] {result.case.case_id}: {result.case.description}")
		print(
			f"status={result.output.get('status')} request_type={result.output.get('request_type')} "
			f"product_area={result.output.get('product_area')}"
		)
		if result.failures:
			for failure in result.failures:
				print(f"- {failure}")
		print(f"justification={result.output.get('justification')}")
		print(f"response={result.output.get('response')}")


def main(argv: Sequence[str] | None = None) -> int:
	args = parse_args(argv)
	results = evaluate_manual_regressions()
	_print_results(results, show_passed=args.show_passed)
	return 0 if all(result.passed for result in results) else 1


if __name__ == "__main__":
	raise SystemExit(main())