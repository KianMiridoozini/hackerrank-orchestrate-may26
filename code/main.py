"""CLI entrypoint for the support triage pipeline."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from config import DEFAULT_ENCODING, OUTPUT_TICKETS_PATH, SAMPLE_TICKETS_PATH


REQUIRED_SAMPLE_COLUMNS: tuple[str, ...] = (
	"Issue",
	"Subject",
	"Company",
	"Response",
	"Product Area",
	"Status",
	"Request Type",
)


def _header_to_internal_key(column_name: str) -> str:
	return column_name.strip().lower().replace(" ", "_")


def _stringify(value: object) -> str:
	if value is None:
		return ""
	return str(value)


@lru_cache(maxsize=1)
def load_output_header(sample_path: Path = SAMPLE_TICKETS_PATH) -> tuple[str, ...]:
	"""Read the sample CSV header and preserve its exact column order."""

	try:
		with sample_path.open("r", encoding=DEFAULT_ENCODING, newline="") as handle:
			reader = csv.reader(handle)
			header = tuple(next(reader))
	except FileNotFoundError as exc:
		raise RuntimeError(
			f"Unable to load the sample CSV header because the file is missing: {sample_path}"
		) from exc
	except StopIteration as exc:
		raise RuntimeError(
			f"Unable to load the sample CSV header because the file is empty: {sample_path}"
		) from exc
	except OSError as exc:
		raise RuntimeError(
			f"Unable to load the sample CSV header because the file is unreadable: {sample_path}"
		) from exc

	if not header or not any(column.strip() for column in header):
		raise RuntimeError(
			f"Unable to load the sample CSV header because it contains no usable columns: {sample_path}"
		)

	missing_columns = tuple(
		column_name for column_name in REQUIRED_SAMPLE_COLUMNS if column_name not in header
	)
	if missing_columns:
		missing_text = ", ".join(missing_columns)
		raise RuntimeError(
			"Unable to use the sample CSV as the output contract because the header is "
			f"missing required columns: {missing_text}"
		)

	return header


def align_row_to_output_header(
	row: Mapping[str, object],
	output_header: Sequence[str],
) -> dict[str, str]:
	"""Map internal row keys onto the exact sample-header column names."""

	aligned_row: dict[str, str] = {}
	for column_name in output_header:
		if column_name in row:
			aligned_row[column_name] = _stringify(row[column_name])
			continue

		internal_key = _header_to_internal_key(column_name)
		if internal_key in row:
			aligned_row[column_name] = _stringify(row[internal_key])
			continue

		aligned_row[column_name] = ""

	return aligned_row


def write_output_csv(
	rows: Iterable[Mapping[str, object]],
	output_path: Path = OUTPUT_TICKETS_PATH,
	sample_path: Path = SAMPLE_TICKETS_PATH,
) -> Path:
	"""Write output rows using the exact column order defined by the sample CSV."""

	output_header = load_output_header(sample_path)
	output_path.parent.mkdir(parents=True, exist_ok=True)

	with output_path.open("w", encoding=DEFAULT_ENCODING, newline="") as handle:
		writer = csv.DictWriter(handle, fieldnames=list(output_header))
		writer.writeheader()
		for row in rows:
			writer.writerow(align_row_to_output_header(row, output_header))

	return output_path


def main() -> int:
	"""Validate the CSV contract at startup and surface the active header."""

	output_header = load_output_header()
	print(",".join(output_header))
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
