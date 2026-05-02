"""Product area taxonomy helpers derived from the sample and corpus structure."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Iterable, Sequence

from core.config import DATA_ROOT, DEFAULT_ENCODING, SAMPLE_TICKETS_PATH
from core.schemas import Company, RetrievedChunk


NORMALIZE_PATTERN: Final[re.Pattern[str]] = re.compile(r"[^a-z0-9]+")
RAW_LABEL_ALIASES: Final[dict[str, str]] = {
	"claude": "general_support",
	"consumer": "general_support",
	"general_help": "general_support",
	"hackerrank": "general_support",
	"hackerrank_community": "community",
	"merchant": "general_support",
	"privacy_and_legal": "privacy",
	"root": "general_support",
	"small_business": "general_support",
	"support": "general_support",
	"uncategorized": "general_support",
	"visa": "general_support",
}


@dataclass(frozen=True)
class ProductAreaTaxonomy:
	"""Resolved product-area vocabulary and canonical aliases."""

	sample_labels: frozenset[str]
	corpus_labels: frozenset[str]
	allowed_labels: frozenset[str]
	aliases: dict[str, str]

	def canonicalize(self, value: str | None) -> str | None:
		if value is None:
			return None
		normalized = normalize_product_area(value)
		if not normalized:
			return None
		return self.aliases.get(normalized, normalized)


def normalize_product_area(value: str) -> str:
	"""Normalize a product-area label to the canonical snake_case form."""

	lowered = value.strip().lower()
	if not lowered:
		return ""
	normalized = NORMALIZE_PATTERN.sub("_", lowered).strip("_")
	return re.sub(r"_+", "_", normalized)


def _canonicalize_raw_label(value: str) -> str:
	normalized = normalize_product_area(value)
	if not normalized:
		return ""
	return RAW_LABEL_ALIASES.get(normalized, normalized)


def load_sample_product_areas(
	sample_path: Path = SAMPLE_TICKETS_PATH,
) -> frozenset[str]:
	"""Load the canonical product-area labels that appear in the sample CSV."""

	with sample_path.open("r", encoding=DEFAULT_ENCODING, newline="") as handle:
		reader = csv.DictReader(handle)
		labels = {
			normalize_product_area(row.get("Product Area", ""))
			for row in reader
			if row.get("Product Area", "").strip()
		}
	return frozenset(label for label in labels if label)


def _iter_index_labels(index_path: Path) -> Iterable[str]:
	with index_path.open("r", encoding=DEFAULT_ENCODING) as handle:
		for raw_line in handle:
			line = raw_line.strip()
			if not line.startswith("## "):
				continue
			breadcrumb = line[3:]
			for segment in breadcrumb.split("/"):
				normalized = _canonicalize_raw_label(segment)
				if normalized:
					yield normalized


def _iter_directory_labels(data_root: Path) -> Iterable[str]:
	for directory in data_root.rglob("*"):
		if not directory.is_dir():
			continue
		normalized = _canonicalize_raw_label(directory.name)
		if normalized:
			yield normalized


def collect_corpus_product_areas(data_root: Path = DATA_ROOT) -> frozenset[str]:
	"""Collect candidate product-area labels from corpus folders and index breadcrumbs."""

	labels = set(_iter_directory_labels(data_root))
	for index_path in data_root.glob("*/index.md"):
		labels.update(_iter_index_labels(index_path))
	return frozenset(label for label in labels if label)


def build_product_area_taxonomy(
	sample_path: Path = SAMPLE_TICKETS_PATH,
	data_root: Path = DATA_ROOT,
) -> ProductAreaTaxonomy:
	"""Build the allowed product-area set from the sample CSV and corpus structure."""

	sample_labels = load_sample_product_areas(sample_path)
	corpus_labels = collect_corpus_product_areas(data_root)
	allowed_labels = frozenset(sample_labels | corpus_labels)

	aliases = {
		normalize_product_area(raw_label): canonical_label
		for raw_label, canonical_label in RAW_LABEL_ALIASES.items()
	}
	for label in allowed_labels:
		aliases.setdefault(label, label)

	return ProductAreaTaxonomy(
		sample_labels=sample_labels,
		corpus_labels=corpus_labels,
		allowed_labels=allowed_labels,
		aliases=aliases,
	)


@lru_cache(maxsize=1)
def get_product_area_taxonomy() -> ProductAreaTaxonomy:
	"""Return the shared product-area taxonomy for the current workspace."""

	return build_product_area_taxonomy()


def is_valid_product_area(
	product_area: str,
	taxonomy: ProductAreaTaxonomy | None = None,
) -> bool:
	"""Return whether a product area resolves to an allowed taxonomy label."""

	active_taxonomy = taxonomy or get_product_area_taxonomy()
	canonical = active_taxonomy.canonicalize(product_area)
	return canonical in active_taxonomy.allowed_labels if canonical else False


def validate_product_area(
	product_area: str,
	taxonomy: ProductAreaTaxonomy | None = None,
) -> str:
	"""Return the canonical product-area label or raise when it is unknown."""

	active_taxonomy = taxonomy or get_product_area_taxonomy()
	canonical = active_taxonomy.canonicalize(product_area)
	if canonical and canonical in active_taxonomy.allowed_labels:
		return canonical
	raise ValueError(f"Unknown product_area: {product_area!r}")


def _iter_evidence_candidates(
	breadcrumbs: Sequence[str],
	source_path: str | Path | None,
	product_area_hint: str | None,
	company: Company | str | None,
) -> Iterable[str]:
	if product_area_hint:
		yield product_area_hint

	for breadcrumb in breadcrumbs:
		yield breadcrumb
		parts = [segment.strip() for segment in breadcrumb.split("/") if segment.strip()]
		for segment in reversed(parts):
			yield segment

	if source_path:
		path = Path(str(source_path))
		parts = list(path.parts)
		if path.suffix:
			parts = parts[:-1]
		for part in reversed(parts):
			yield part

	if company:
		if isinstance(company, Company):
			yield company.value
		else:
			yield str(company)


def map_evidence_to_product_area(
	*,
	breadcrumbs: Sequence[str] = (),
	source_path: str | Path | None = None,
	product_area_hint: str | None = None,
	company: Company | str | None = None,
	taxonomy: ProductAreaTaxonomy | None = None,
	default: str = "general_support",
) -> str:
	"""Map retrieval evidence back to a canonical allowed product-area label."""

	active_taxonomy = taxonomy or get_product_area_taxonomy()
	for candidate in _iter_evidence_candidates(
		breadcrumbs=breadcrumbs,
		source_path=source_path,
		product_area_hint=product_area_hint,
		company=company,
	):
		canonical = active_taxonomy.canonicalize(candidate)
		if canonical and canonical in active_taxonomy.allowed_labels:
			return canonical
	return validate_product_area(default, active_taxonomy)


def default_product_area_for_company(company: Company | None) -> str:
	"""Return the default broad product area for a resolved company."""

	return validate_product_area(
		map_evidence_to_product_area(company=company, default="general_support")
	)


def map_retrieved_chunk_to_product_area(chunk: RetrievedChunk, company: Company | None) -> str:
	"""Map a retrieved chunk to the final product-area label with local override rules."""

	lowered_metadata = " ".join(
		part for part in (chunk.title, chunk.heading or "", " ".join(chunk.breadcrumbs), chunk.source_path, chunk.text[:400]) if part
	).lower()
	path_text = chunk.source_path.lower()

	if any(
		keyword in lowered_metadata
		for keyword in (
			"traveller",
			"travellers",
			"traveler",
			"travelers",
			"traveller's cheque",
			"traveler's cheque",
			"cheques",
		)
	):
		return validate_product_area("travel_support")

	if (
		company is Company.HACKERRANK
		and "hackerrank_community/" in path_text
		and ("account-settings/" in path_text or "manage-account" in path_text or "delete-an-account" in path_text)
	):
		return validate_product_area("community")

	if company is Company.CLAUDE and any(
		keyword in lowered_metadata
		for keyword in (
			"privacy",
			"private info",
			"private information",
			"sensitive",
			"who can view my conversations",
			"view my conversations",
		)
	):
		return validate_product_area("privacy")

	product_area_hint = chunk.product_area_hint if chunk.product_area_hint != "general_support" else None

	path_first = map_evidence_to_product_area(
		source_path=chunk.source_path,
		product_area_hint=product_area_hint,
		default="general_support",
	)
	if path_first != "general_support":
		return validate_product_area(path_first)

	breadcrumb_first = map_evidence_to_product_area(
		breadcrumbs=tuple(reversed(chunk.breadcrumbs)),
		product_area_hint=product_area_hint,
		default="general_support",
	)
	if breadcrumb_first != "general_support":
		return validate_product_area(breadcrumb_first)

	return validate_product_area(
		map_evidence_to_product_area(
			breadcrumbs=chunk.breadcrumbs,
			source_path=chunk.source_path,
			product_area_hint=product_area_hint,
			company=company,
			default="general_support",
		)
	)