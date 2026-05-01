"""CLI entrypoint for the support triage pipeline."""

from __future__ import annotations

import argparse
import csv
from functools import lru_cache
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from agent import process_ticket
from config import DEFAULT_ENCODING, INPUT_TICKETS_PATH, OUTPUT_TICKETS_PATH, SAMPLE_TICKETS_PATH
from schemas import InputTicket


REQUIRED_SAMPLE_COLUMNS: tuple[str, ...] = (
	"Issue",
	"Subject",
	"Company",
	"Response",
	"Product Area",
	"Status",
	"Request Type",
)

REQUIRED_INPUT_COLUMNS: tuple[str, ...] = (
	"Issue",
	"Subject",
	"Company",
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


def load_input_tickets(input_path: Path = INPUT_TICKETS_PATH) -> list[InputTicket]:
	"""Read the input CSV into shared ticket models."""

	try:
		with input_path.open("r", encoding=DEFAULT_ENCODING, newline="") as handle:
			reader = csv.DictReader(handle)
			fieldnames = tuple(reader.fieldnames or ())
			missing_columns = tuple(
				column_name for column_name in REQUIRED_INPUT_COLUMNS if column_name not in fieldnames
			)
			if missing_columns:
				missing_text = ", ".join(missing_columns)
				raise RuntimeError(
					"Unable to load the input CSV because the header is missing required "
					f"columns: {missing_text}"
				)

			tickets: list[InputTicket] = []
			for raw_row in reader:
				ticket = InputTicket(
					issue=raw_row.get("Issue", ""),
					subject=raw_row.get("Subject"),
					company=raw_row.get("Company"),
					raw_row=dict(raw_row),
				)
				tickets.append(ticket)
			return tickets
	except FileNotFoundError as exc:
		raise RuntimeError(
			f"Unable to load the input CSV because the file is missing: {input_path}"
		) from exc
	except OSError as exc:
		raise RuntimeError(
			f"Unable to load the input CSV because the file is unreadable: {input_path}"
		) from exc


def build_output_rows(tickets: Sequence[InputTicket]) -> list[dict[str, object]]:
	"""Run the placeholder agent flow for each ticket and preserve input columns."""

	rows: list[dict[str, object]] = []
	for ticket in tickets:
		output_row = dict(ticket.raw_row)
		output_row.update(process_ticket(ticket))
		rows.append(output_row)
	return rows


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
	"""Parse CLI arguments for the batch run."""

	parser = argparse.ArgumentParser(description=__doc__)
	parser.add_argument("--input", type=Path, default=INPUT_TICKETS_PATH)
	parser.add_argument("--output", type=Path, default=OUTPUT_TICKETS_PATH)
	parser.add_argument("--sample", type=Path, default=SAMPLE_TICKETS_PATH)
	return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
	"""Run the minimal batch pipeline over the input CSV."""

	args = parse_args(argv)
	output_header = load_output_header(args.sample)
	tickets = load_input_tickets(args.input)
	rows = build_output_rows(tickets)
	write_output_csv(rows, output_path=args.output, sample_path=args.sample)

	print(f"Resolved support directory: {args.input.parent}")
	print(f"Loaded {len(tickets)} tickets from {args.input}")
	print(f"Wrote {len(rows)} rows to {args.output}")
	print(f"Output header: {','.join(output_header)}")
	return 0


if __name__ == "__main__":
	raise SystemExit(main())
