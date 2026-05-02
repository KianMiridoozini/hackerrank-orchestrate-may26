"""Sample-set evaluation entrypoint for categorical comparison."""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Mapping, Sequence

from core.config import DEFAULT_ENCODING, SAMPLE_TICKETS_PATH
from main import build_output_rows, load_input_tickets, load_sample_header
from core.schemas import RequestType, TicketStatus
from core.taxonomy import normalize_product_area, validate_product_area


COMPARISON_FIELDS: Final[tuple[str, ...]] = (
	"status",
	"request_type",
	"product_area",
)
FIELD_LABELS: Final[dict[str, str]] = {
	"status": "Status",
	"request_type": "Request Type",
	"product_area": "Product Area",
}
SAMPLE_COLUMN_MAP: Final[dict[str, str]] = {
	"issue": "Issue",
	"subject": "Subject",
	"company": "Company",
	"status": "Status",
	"request_type": "Request Type",
	"product_area": "Product Area",
}
NORMALIZE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")
VALID_STATUS_VALUES: Final[frozenset[str]] = frozenset(status.value for status in TicketStatus)
VALID_REQUEST_TYPE_VALUES: Final[frozenset[str]] = frozenset(
	request_type.value for request_type in RequestType
)


@dataclass(frozen=True)
class RowComparison:
	index: int
	issue: str
	subject: str
	company: str
	expected: dict[str, str]
	predicted: dict[str, str]
	mismatched_fields: tuple[str, ...]
	likely_failure_area: str


@dataclass(frozen=True)
class EvaluationSummary:
	expected_row_count: int
	predicted_row_count: int
	compared_row_count: int
	matched_counts: dict[str, int]
	comparable_counts: dict[str, int]
	failure_buckets: dict[str, int]
	mismatches: list[RowComparison]
	structural_issues: list[str]


def _normalize_text(value: str | None) -> str:
	if value is None:
		return ""
	return " ".join(value.split())


def _normalize_categorical_value(field_name: str, value: object) -> str:
	text = _normalize_text("" if value is None else str(value))
	if not text:
		return ""
	if field_name == "product_area":
		return normalize_product_area(text)
	return NORMALIZE_PATTERN.sub("_", text.lower()).strip("_")


def _load_sample_expectations(sample_path: Path) -> list[dict[str, str]]:
	load_sample_header(sample_path)
	with sample_path.open("r", encoding=DEFAULT_ENCODING, newline="") as handle:
		reader = csv.DictReader(handle)
		rows: list[dict[str, str]] = []
		for raw_row in reader:
			rows.append(
				{
					key: _normalize_text(raw_row.get(column_name, ""))
					for key, column_name in SAMPLE_COLUMN_MAP.items()
				}
			)
		return rows


def _validate_prediction_rows(rows: Sequence[Mapping[str, object]]) -> list[str]:
	issues: list[str] = []
	for index, row in enumerate(rows, start=1):
		status = _normalize_categorical_value("status", row.get("status"))
		request_type = _normalize_categorical_value("request_type", row.get("request_type"))
		product_area = _normalize_text("" if row.get("product_area") is None else str(row.get("product_area")))

		if status not in VALID_STATUS_VALUES:
			issues.append(f"Row {index} has invalid status: {row.get('status')!r}")
		if request_type not in VALID_REQUEST_TYPE_VALUES:
			issues.append(f"Row {index} has invalid request_type: {row.get('request_type')!r}")
		if not product_area:
			issues.append(f"Row {index} has blank product_area")
			continue
		try:
			validate_product_area(product_area)
		except ValueError as exc:
			issues.append(f"Row {index} has invalid product_area: {exc}")
	return issues


def _classify_failure_area(
	*,
	expected: Mapping[str, str],
	predicted: Mapping[str, str],
	mismatched_fields: Sequence[str],
) -> str:
	field_set = set(mismatched_fields)
	if "status" in field_set:
		expected_status = expected.get("status", "")
		predicted_status = predicted.get("status", "")
		if (
			expected_status == TicketStatus.ESCALATED.value
			and predicted_status == TicketStatus.REPLIED.value
		):
			return "safety"
		if (
			expected_status == TicketStatus.REPLIED.value
			and predicted_status == TicketStatus.ESCALATED.value
		):
			return "retrieval_or_confidence"
		return "routing_or_safety"
	if field_set == {"request_type"}:
		return "request_type_rules"
	if field_set == {"product_area"}:
		return "taxonomy_or_retrieval"
	if field_set == {"request_type", "product_area"}:
		return "routing_or_retrieval"
	return "mixed"


def evaluate_sample(sample_path: Path = SAMPLE_TICKETS_PATH) -> EvaluationSummary:
	expected_rows = _load_sample_expectations(sample_path)
	predicted_rows = build_output_rows(load_input_tickets(sample_path))
	structural_issues = _validate_prediction_rows(predicted_rows)

	if len(expected_rows) != len(predicted_rows):
		structural_issues.append(
			"Row count mismatch: "
			f"sample has {len(expected_rows)} rows but the evaluator produced {len(predicted_rows)} rows."
		)

	matched_counts: Counter[str] = Counter()
	comparable_counts: Counter[str] = Counter()
	failure_buckets: Counter[str] = Counter()
	mismatches: list[RowComparison] = []

	for index, (expected_row, predicted_row) in enumerate(zip(expected_rows, predicted_rows), start=1):
		normalized_expected = {
			field_name: _normalize_categorical_value(field_name, expected_row.get(field_name, ""))
			for field_name in COMPARISON_FIELDS
		}
		normalized_predicted = {
			field_name: _normalize_categorical_value(field_name, predicted_row.get(field_name, ""))
			for field_name in COMPARISON_FIELDS
		}

		mismatched_fields: list[str] = []
		for field_name in COMPARISON_FIELDS:
			expected_value = normalized_expected[field_name]
			if not expected_value:
				continue
			comparable_counts[field_name] += 1
			if normalized_predicted[field_name] == expected_value:
				matched_counts[field_name] += 1
			else:
				mismatched_fields.append(field_name)

		if not mismatched_fields:
			continue

		likely_failure_area = _classify_failure_area(
			expected=normalized_expected,
			predicted=normalized_predicted,
			mismatched_fields=mismatched_fields,
		)
		failure_buckets[likely_failure_area] += 1
		mismatches.append(
			RowComparison(
				index=index,
				issue=expected_row["issue"],
				subject=expected_row["subject"],
				company=expected_row["company"],
				expected=normalized_expected,
				predicted=normalized_predicted,
				mismatched_fields=tuple(mismatched_fields),
				likely_failure_area=likely_failure_area,
			)
		)

	return EvaluationSummary(
		expected_row_count=len(expected_rows),
		predicted_row_count=len(predicted_rows),
		compared_row_count=min(len(expected_rows), len(predicted_rows)),
		matched_counts=dict(matched_counts),
		comparable_counts=dict(comparable_counts),
		failure_buckets=dict(failure_buckets),
		mismatches=mismatches,
		structural_issues=structural_issues,
	)


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--sample", type=Path, default=SAMPLE_TICKETS_PATH)
	parser.add_argument("--max-mismatches", type=int, default=20)
	return parser.parse_args(argv)


def _print_summary(summary: EvaluationSummary, *, max_mismatches: int) -> None:
	print(f"Sample rows: {summary.expected_row_count}")
	print(f"Predicted rows: {summary.predicted_row_count}")
	print(f"Compared rows: {summary.compared_row_count}")

	print("\nField accuracy:")
	for field_name in COMPARISON_FIELDS:
		matched = summary.matched_counts.get(field_name, 0)
		comparable = summary.comparable_counts.get(field_name, 0)
		if comparable <= 0:
			accuracy_text = "n/a"
		else:
			accuracy_text = f"{(matched / comparable) * 100:.1f}%"
		print(f"- {FIELD_LABELS[field_name]}: {matched}/{comparable} matched ({accuracy_text})")

	print("\nFailure buckets:")
	if summary.failure_buckets:
		for bucket_name, count in sorted(
			summary.failure_buckets.items(),
			key=lambda item: (-item[1], item[0]),
		):
			print(f"- {bucket_name}: {count}")
	else:
		print("- none")

	if summary.structural_issues:
		print("\nStructural issues:")
		for issue in summary.structural_issues:
			print(f"- {issue}")

	if not summary.mismatches:
		print("\nCategorical comparison: no mismatches found.")
		return

	visible_mismatches = summary.mismatches[: max(0, max_mismatches)]
	print(
		f"\nMismatches ({len(summary.mismatches)} total, showing {len(visible_mismatches)}):"
	)
	for comparison in visible_mismatches:
		label = comparison.subject or comparison.issue
		print(f"- Row {comparison.index}: {label}")
		print(f"  company={comparison.company or 'None'}")
		print(
			"  expected: "
			+ ", ".join(
				f"{field}={comparison.expected.get(field, '') or '<blank>'}"
				for field in COMPARISON_FIELDS
			)
		)
		print(
			"  predicted: "
			+ ", ".join(
				f"{field}={comparison.predicted.get(field, '') or '<blank>'}"
				for field in COMPARISON_FIELDS
			)
		)
		print(
			"  mismatched_fields="
			+ ",".join(comparison.mismatched_fields)
			+ f"; likely_failure_area={comparison.likely_failure_area}"
		)

	remaining = len(summary.mismatches) - len(visible_mismatches)
	if remaining > 0:
		print(f"- ... {remaining} additional mismatches not shown")


def main(argv: Sequence[str] | None = None) -> int:
	args = parse_args(argv)
	summary = evaluate_sample(args.sample)
	_print_summary(summary, max_mismatches=args.max_mismatches)
	return 1 if summary.structural_issues else 0


if __name__ == "__main__":
	raise SystemExit(main())