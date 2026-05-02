"""Inspect production output quality and compare it against a baseline snapshot."""

from __future__ import annotations

import argparse
import csv
from pathlib import Path
from typing import Final


VALID_STATUSES: Final[frozenset[str]] = frozenset({"replied", "escalated"})
VALID_REQUEST_TYPES: Final[frozenset[str]] = frozenset({"bug", "feature_request", "invalid", "product_issue"})
INTERNAL_MARKERS: Final[tuple[str, ...]] = (
	"source_path",
	"rank=",
	"score=",
	"resolved_company",
	"fallback_reason",
	"deterministic rule",
)
RAW_RESPONSE_MARKERS: Final[tuple[str, ...]] = (
	"subject:",
	"email body:",
	"<candidate",
	"<company",
)


def _load_rows(path: Path) -> list[dict[str, str]]:
	with path.open(encoding="utf-8", newline="") as handle:
		return list(csv.DictReader(handle))


def _response_flags(row: dict[str, str]) -> list[str]:
	response = (row.get("response") or "").strip()
	lowered = response.lower()
	flags: list[str] = []
	if len(response) < 60:
		flags.append("short_response")
	if any(marker in lowered for marker in RAW_RESPONSE_MARKERS):
		flags.append("raw_template_text")
	if response.endswith(":") or response.endswith("-"):
		flags.append("possibly_truncated")
	if response.count("<") >= 2 and response.count(">") >= 2:
		flags.append("placeholder_leak")
	return flags


def _justification_flags(row: dict[str, str]) -> list[str]:
	justification = (row.get("justification") or "").lower()
	flags: list[str] = []
	if any(marker in justification for marker in INTERNAL_MARKERS):
		flags.append("internal_metadata_in_justification")
	return flags


def _categorical_flags(row: dict[str, str]) -> list[str]:
	flags: list[str] = []
	status = (row.get("status") or "").strip()
	request_type = (row.get("request_type") or "").strip()
	product_area = (row.get("product_area") or "").strip()
	if status not in VALID_STATUSES:
		flags.append("invalid_status")
	if request_type not in VALID_REQUEST_TYPES:
		flags.append("invalid_request_type")
	if not product_area:
		flags.append("blank_product_area")
	return flags


def inspect_rows(
	*,
	output_rows: list[dict[str, str]],
	baseline_rows: list[dict[str, str]] | None,
) -> list[str]:
	baseline_by_index = {
		index: row
		for index, row in enumerate(baseline_rows or [], start=1)
	}
	report_lines: list[str] = []
	changed_rows = 0
	flagged_rows = 0
	for index, row in enumerate(output_rows, start=1):
		flags = _response_flags(row) + _justification_flags(row) + _categorical_flags(row)
		baseline_row = baseline_by_index.get(index)
		if baseline_row is not None and (
			baseline_row.get("response") != row.get("response")
			or baseline_row.get("justification") != row.get("justification")
		):
			changed_rows += 1
		if flags:
			flagged_rows += 1
			subject = (row.get("subject") or row.get("issue") or "").strip()
			report_lines.append(f"Row {index}: {subject or '(no subject)'} -> {', '.join(flags)}")
	report_lines.insert(0, f"Changed rows vs baseline: {changed_rows}")
	report_lines.insert(1, f"Flagged rows: {flagged_rows}")
	return report_lines


def main() -> int:
	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument(
		"--output",
		type=Path,
		default=Path("support_tickets/output.csv"),
		help="Path to the current output CSV.",
	)
	parser.add_argument(
		"--baseline",
		type=Path,
		default=Path("support_tickets/output.baseline.csv"),
		help="Optional baseline CSV for comparison.",
	)
	args = parser.parse_args()

	output_rows = _load_rows(args.output)
	baseline_rows = _load_rows(args.baseline) if args.baseline.exists() else None
	for line in inspect_rows(output_rows=output_rows, baseline_rows=baseline_rows):
		print(line)
	return 0


if __name__ == "__main__":
	raise SystemExit(main())