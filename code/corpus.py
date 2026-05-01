"""Corpus loading and normalization helpers for local markdown support content."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any, Final, Iterable, Sequence

from config import CORPUS_CACHE_PATH, DATA_ROOT, DEFAULT_ENCODING
from schemas import Company


DOMAIN_BY_FOLDER: Final[dict[str, Company]] = {
	"claude": Company.CLAUDE,
	"hackerrank": Company.HACKERRANK,
	"visa": Company.VISA,
}
CACHE_VERSION: Final[int] = 1
HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(r"^#{1,6}\s+")
HEADING_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^(#{1,6})\s+(.*\S)\s*$")
LINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
IMAGE_PATTERN: Final[re.Pattern[str]] = re.compile(r"!\[[^\]]*\]\([^)]+\)")
HTML_PATTERN: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
MARKDOWN_NOISE_PATTERN: Final[re.Pattern[str]] = re.compile(r'[*_`>"]')
NUMERIC_PREFIX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d+-")
TABLE_SEPARATOR_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\|?[-: ]+\|[-|: ]+$")
WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b\w+\b")
LAST_UPDATED_PATTERN: Final[re.Pattern[str]] = re.compile(r"^_Last (updated|modified):.*_$", re.IGNORECASE)
LINK_ONLY_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[-*]?\s*\[[^\]]+\]\([^)]+\)\s*$")
LONG_DOCUMENT_WORD_THRESHOLD: Final[int] = 350
MIN_HEADING_SPLITS: Final[int] = 3
MAX_CHUNK_HEADING_LEVEL: Final[int] = 3


@dataclass(frozen=True)
class CorpusRecord:
	"""Normalized file-level corpus record for retrieval and routing."""

	domain: Company
	source_path: str
	title: str
	breadcrumbs: tuple[str, ...]
	text: str
	metadata: dict[str, object]
	is_answer_bearing: bool
	stub_reason: str | None = None


@dataclass(frozen=True)
class CorpusChunk:
	"""Heading-aware chunk used by later retrieval steps."""

	chunk_id: str
	domain: Company
	source_path: str
	title: str
	breadcrumbs: tuple[str, ...]
	heading: str | None
	text: str
	metadata: dict[str, object]


def discover_markdown_files(data_root: Path = DATA_ROOT) -> tuple[Path, ...]:
	"""Discover markdown files under the local corpus root."""

	return tuple(sorted(path for path in data_root.rglob("*.md") if path.is_file()))


def build_corpus_manifest(paths: Sequence[Path], data_root: Path = DATA_ROOT) -> dict[str, dict[str, int]]:
	"""Build a simple manifest to detect when the markdown corpus has changed."""

	manifest: dict[str, dict[str, int]] = {}
	for path in paths:
		relative = path.relative_to(data_root).as_posix()
		stats = path.stat()
		manifest[relative] = {
			"size": stats.st_size,
			"mtime_ns": stats.st_mtime_ns,
		}
	return manifest


def _strip_quotes(value: str) -> str:
	cleaned = value.strip()
	if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {'"', "'"}:
		return cleaned[1:-1]
	return cleaned


def parse_frontmatter(raw_text: str) -> tuple[dict[str, object], str]:
	"""Parse a simple YAML-style frontmatter block when present."""

	lines = raw_text.splitlines()
	if not lines or lines[0].strip() != "---":
		return {}, raw_text

	metadata: dict[str, object] = {}
	current_list_key: str | None = None
	end_index: int | None = None

	for index, line in enumerate(lines[1:], start=1):
		stripped = line.strip()
		if stripped == "---":
			end_index = index
			break
		if current_list_key and stripped.startswith("- "):
			items = list(metadata.get(current_list_key, []))
			items.append(_strip_quotes(stripped[2:].strip()))
			metadata[current_list_key] = tuple(items)
			continue
		if not stripped or ":" not in line:
			current_list_key = None
			continue

		key, value = line.split(":", 1)
		key = key.strip()
		value = value.strip()
		if not value:
			metadata[key] = tuple()
			current_list_key = key
			continue

		metadata[key] = _strip_quotes(value)
		current_list_key = None

	if end_index is None:
		return {}, raw_text

	body = "\n".join(lines[end_index + 1 :])
	return metadata, body


def _serialize_metadata(metadata: dict[str, object]) -> dict[str, object]:
	serialized: dict[str, object] = {}
	for key, value in metadata.items():
		if isinstance(value, tuple):
			serialized[key] = list(value)
		else:
			serialized[key] = value
	return serialized


def _deserialize_metadata(metadata: dict[str, object]) -> dict[str, object]:
	deserialized: dict[str, object] = {}
	for key, value in metadata.items():
		if isinstance(value, list):
			deserialized[key] = tuple(value)
		else:
			deserialized[key] = value
	return deserialized


def _prettify_segment(value: str) -> str:
	cleaned = NUMERIC_PREFIX_PATTERN.sub("", value.strip())
	cleaned = cleaned.replace("_", " ").replace("-", " ")
	cleaned = re.sub(r"\s+", " ", cleaned).strip()
	if not cleaned:
		return ""
	return cleaned.title()


def derive_title(metadata: dict[str, object], body_text: str, relative_path: Path) -> str:
	"""Resolve the best title from metadata, body headings, or the filename."""

	frontmatter_title = metadata.get("title")
	if isinstance(frontmatter_title, str) and frontmatter_title.strip():
		return frontmatter_title.strip()

	for raw_line in body_text.splitlines():
		line = raw_line.strip()
		if HEADING_PATTERN.match(line):
			return HEADING_PATTERN.sub("", line).strip()

	return _prettify_segment(relative_path.stem)


def derive_breadcrumbs(metadata: dict[str, object], relative_path: Path) -> tuple[str, ...]:
	"""Resolve breadcrumbs from frontmatter or from the relative path."""

	breadcrumbs = metadata.get("breadcrumbs")
	if isinstance(breadcrumbs, tuple) and breadcrumbs:
		return tuple(str(item).strip() for item in breadcrumbs if str(item).strip())

	parts = relative_path.parts[1:-1]
	return tuple(part for part in (_prettify_segment(part) for part in parts) if part)


def normalize_markdown_text(body_text: str) -> str:
	"""Strip obvious markdown noise while preserving readable support content."""

	normalized_lines: list[str] = []
	for raw_line in body_text.splitlines():
		line = raw_line.strip()
		if not line:
			continue
		if set(line) == {"-"}:
			continue
		if LAST_UPDATED_PATTERN.match(line):
			continue

		line = IMAGE_PATTERN.sub("", line)
		line = LINK_PATTERN.sub(r"\1", line)
		line = HTML_PATTERN.sub(" ", line)
		line = HEADING_PATTERN.sub("", line)
		line = MARKDOWN_NOISE_PATTERN.sub("", line)
		line = line.replace("\\", " ")
		line = re.sub(r"\s+", " ", line).strip()

		if not line or TABLE_SEPARATOR_PATTERN.match(line):
			continue

		normalized_lines.append(line)

	return "\n".join(normalized_lines).strip()


def word_count(text: str) -> int:
	"""Count words in normalized content."""

	return len(WORD_PATTERN.findall(text))


def detect_stub_or_navigation(relative_path: Path, body_text: str, normalized_text: str) -> tuple[bool, str | None]:
	"""Return whether a page is answer-bearing versus an index, stub, or link hub."""

	non_empty_lines = [line.strip() for line in body_text.splitlines() if line.strip()]
	paragraph_lines = [line for line in normalized_text.splitlines() if len(WORD_PATTERN.findall(line)) >= 8]
	link_only_lines = sum(1 for line in non_empty_lines if LINK_ONLY_LINE_PATTERN.match(line))
	words = word_count(normalized_text)
	has_export_banner = any(
		line.lower().startswith("exported ") and "articles" in line.lower()
		for line in non_empty_lines
	)

	if relative_path.name == "index.md" or has_export_banner:
		return False, "navigation_index"
	if non_empty_lines and link_only_lines / len(non_empty_lines) >= 0.5 and not paragraph_lines:
		return False, "navigation_links"
	if words < 30 and len(non_empty_lines) <= 6:
		return False, "short_stub"
	return True, None


def _domain_from_relative_path(relative_path: Path) -> Company:
	try:
		return DOMAIN_BY_FOLDER[relative_path.parts[0]]
	except KeyError as exc:
		raise ValueError(f"Unsupported corpus domain for path: {relative_path}") from exc


def _parse_markdown_components(path: Path, data_root: Path = DATA_ROOT) -> tuple[CorpusRecord, str]:
	"""Parse one markdown file and also return the raw body for chunking."""

	relative_path = path.relative_to(data_root)
	raw_text = path.read_text(encoding=DEFAULT_ENCODING)
	metadata, body_text = parse_frontmatter(raw_text)
	title = derive_title(metadata, body_text, relative_path)
	breadcrumbs = derive_breadcrumbs(metadata, relative_path)
	normalized_text = normalize_markdown_text(body_text)
	is_answer_bearing, stub_reason = detect_stub_or_navigation(
		relative_path,
		body_text,
		normalized_text,
	)

	record = CorpusRecord(
		domain=_domain_from_relative_path(relative_path),
		source_path=relative_path.as_posix(),
		title=title,
		breadcrumbs=breadcrumbs,
		text=normalized_text,
		metadata=metadata,
		is_answer_bearing=is_answer_bearing,
		stub_reason=stub_reason,
	)
	return record, body_text


def parse_markdown_file(path: Path, data_root: Path = DATA_ROOT) -> CorpusRecord:
	"""Parse one markdown file into a normalized file-level corpus record."""

	return _parse_markdown_components(path, data_root=data_root)[0]


def should_chunk_record(record: CorpusRecord, body_text: str) -> bool:
	"""Return whether a record should be split by headings instead of kept whole."""

	if not record.is_answer_bearing:
		return False
	if word_count(record.text) < LONG_DOCUMENT_WORD_THRESHOLD:
		return False

	heading_matches = [
		match
		for line in body_text.splitlines()
		if (match := HEADING_LINE_PATTERN.match(line.strip()))
	]
	return len(heading_matches) >= MIN_HEADING_SPLITS


def _build_chunk(
	*,
	record: CorpusRecord,
	chunk_index: int,
	heading_path: Sequence[str],
	raw_lines: Sequence[str],
) -> CorpusChunk | None:
	normalized_text = normalize_markdown_text("\n".join(raw_lines))
	if not normalized_text:
		return None
	heading = " / ".join(heading_path) if heading_path else None
	chunk_suffix = heading or "whole"
	chunk_slug = re.sub(r"[^a-z0-9]+", "-", chunk_suffix.lower()).strip("-")
	chunk_id = f"{record.source_path}::chunk-{chunk_index}"
	if chunk_slug:
		chunk_id = f"{chunk_id}-{chunk_slug}"
	return CorpusChunk(
		chunk_id=chunk_id,
		domain=record.domain,
		source_path=record.source_path,
		title=record.title,
		breadcrumbs=record.breadcrumbs,
		heading=heading,
		text=normalized_text,
		metadata=record.metadata,
	)


def chunk_corpus_record(record: CorpusRecord, body_text: str) -> tuple[CorpusChunk, ...]:
	"""Split long answer-bearing records by headings and keep short pages whole."""

	if not record.is_answer_bearing:
		return ()
	if not should_chunk_record(record, body_text):
		whole_chunk = CorpusChunk(
			chunk_id=f"{record.source_path}::chunk-0-whole",
			domain=record.domain,
			source_path=record.source_path,
			title=record.title,
			breadcrumbs=record.breadcrumbs,
			heading=None,
			text=record.text,
			metadata=record.metadata,
		)
		return (whole_chunk,)

	chunks: list[CorpusChunk] = []
	current_heading_path: list[str] = []
	current_lines: list[str] = []
	chunk_index = 0
	primary_title_seen = False

	for raw_line in body_text.splitlines():
		stripped = raw_line.strip()
		heading_match = HEADING_LINE_PATTERN.match(stripped)
		if heading_match:
			level = len(heading_match.group(1))
			heading_text = heading_match.group(2).strip()
			if not primary_title_seen and level == 1 and heading_text == record.title:
				primary_title_seen = True
				continue

			effective_level = level - 1 if primary_title_seen and level > 1 else level
			if effective_level <= MAX_CHUNK_HEADING_LEVEL:
				chunk = _build_chunk(
					record=record,
					chunk_index=chunk_index,
					heading_path=current_heading_path,
					raw_lines=current_lines,
				)
				if chunk is not None:
					chunks.append(chunk)
					chunk_index += 1
				current_heading_path = current_heading_path[: max(effective_level - 1, 0)]
				current_heading_path.append(heading_text)
				current_lines = []
				continue
			current_lines.append(heading_text)
			continue

		current_lines.append(raw_line)

	final_chunk = _build_chunk(
		record=record,
		chunk_index=chunk_index,
		heading_path=current_heading_path,
		raw_lines=current_lines,
	)
	if final_chunk is not None:
		chunks.append(final_chunk)

	if not chunks:
		return chunk_corpus_record(
			CorpusRecord(
				domain=record.domain,
				source_path=record.source_path,
				title=record.title,
				breadcrumbs=record.breadcrumbs,
				text=record.text,
				metadata=record.metadata,
				is_answer_bearing=record.is_answer_bearing,
				stub_reason=record.stub_reason,
			),
			"",
		)

	return tuple(chunks)


def _record_to_dict(record: CorpusRecord) -> dict[str, object]:
	return {
		"domain": record.domain.value,
		"source_path": record.source_path,
		"title": record.title,
		"breadcrumbs": list(record.breadcrumbs),
		"text": record.text,
		"metadata": _serialize_metadata(record.metadata),
		"is_answer_bearing": record.is_answer_bearing,
		"stub_reason": record.stub_reason,
	}


def _record_from_dict(payload: dict[str, object]) -> CorpusRecord:
	return CorpusRecord(
		domain=Company(payload["domain"]),
		source_path=str(payload["source_path"]),
		title=str(payload["title"]),
		breadcrumbs=tuple(str(item) for item in payload.get("breadcrumbs", [])),
		text=str(payload["text"]),
		metadata=_deserialize_metadata(dict(payload.get("metadata", {}))),
		is_answer_bearing=bool(payload["is_answer_bearing"]),
		stub_reason=str(payload["stub_reason"]) if payload.get("stub_reason") else None,
	)


def _chunk_to_dict(chunk: CorpusChunk) -> dict[str, object]:
	return {
		"chunk_id": chunk.chunk_id,
		"domain": chunk.domain.value,
		"source_path": chunk.source_path,
		"title": chunk.title,
		"breadcrumbs": list(chunk.breadcrumbs),
		"heading": chunk.heading,
		"text": chunk.text,
		"metadata": _serialize_metadata(chunk.metadata),
	}


def _chunk_from_dict(payload: dict[str, object]) -> CorpusChunk:
	return CorpusChunk(
		chunk_id=str(payload["chunk_id"]),
		domain=Company(payload["domain"]),
		source_path=str(payload["source_path"]),
		title=str(payload["title"]),
		breadcrumbs=tuple(str(item) for item in payload.get("breadcrumbs", [])),
		heading=str(payload["heading"]) if payload.get("heading") else None,
		text=str(payload["text"]),
		metadata=_deserialize_metadata(dict(payload.get("metadata", {}))),
	)


def _load_cached_corpus(
	cache_path: Path,
	manifest: dict[str, dict[str, int]],
) -> tuple[tuple[CorpusRecord, ...], tuple[CorpusChunk, ...]] | None:
	try:
		payload = json.loads(cache_path.read_text(encoding=DEFAULT_ENCODING))
	except (FileNotFoundError, OSError, json.JSONDecodeError):
		return None

	if payload.get("version") != CACHE_VERSION:
		return None
	if payload.get("manifest") != manifest:
		return None

	records = tuple(_record_from_dict(item) for item in payload.get("records", []))
	chunks = tuple(_chunk_from_dict(item) for item in payload.get("chunks", []))
	return records, chunks


def _write_corpus_cache(
	cache_path: Path,
	*,
	manifest: dict[str, dict[str, int]],
	records: Sequence[CorpusRecord],
	chunks: Sequence[CorpusChunk],
) -> None:
	cache_path.parent.mkdir(parents=True, exist_ok=True)
	payload = {
		"version": CACHE_VERSION,
		"manifest": manifest,
		"records": [_record_to_dict(record) for record in records],
		"chunks": [_chunk_to_dict(chunk) for chunk in chunks],
	}
	cache_path.write_text(
		json.dumps(payload, ensure_ascii=True, indent=2),
		encoding=DEFAULT_ENCODING,
	)


def build_corpus_artifact(
	data_root: Path = DATA_ROOT,
	cache_path: Path = CORPUS_CACHE_PATH,
) -> tuple[tuple[CorpusRecord, ...], tuple[CorpusChunk, ...]]:
	"""Build or reuse the normalized corpus records and chunk cache."""

	paths = discover_markdown_files(data_root)
	manifest = build_corpus_manifest(paths, data_root=data_root)
	cached = _load_cached_corpus(cache_path, manifest)
	if cached is not None:
		return cached

	records: list[CorpusRecord] = []
	chunks: list[CorpusChunk] = []
	for path in paths:
		record, body_text = _parse_markdown_components(path, data_root=data_root)
		records.append(record)
		chunks.extend(chunk_corpus_record(record, body_text))

	result = (tuple(records), tuple(chunks))
	_write_corpus_cache(
		cache_path,
		manifest=manifest,
		records=result[0],
		chunks=result[1],
	)
	return result


@lru_cache(maxsize=1)
def load_corpus(
	data_root: Path = DATA_ROOT,
	cache_path: Path = CORPUS_CACHE_PATH,
) -> tuple[CorpusRecord, ...]:
	"""Load and normalize the full markdown corpus at file granularity."""

	return build_corpus_artifact(data_root=data_root, cache_path=cache_path)[0]


@lru_cache(maxsize=1)
def load_corpus_chunks(
	data_root: Path = DATA_ROOT,
	cache_path: Path = CORPUS_CACHE_PATH,
) -> tuple[CorpusChunk, ...]:
	"""Load the heading-aware corpus chunks, reusing the local cache when possible."""

	return build_corpus_artifact(data_root=data_root, cache_path=cache_path)[1]


def filter_answer_bearing_records(records: Iterable[CorpusRecord]) -> tuple[CorpusRecord, ...]:
	"""Return only records that appear answer-bearing enough for later retrieval."""

	return tuple(record for record in records if record.is_answer_bearing)


def filter_answer_bearing_chunks(chunks: Iterable[CorpusChunk]) -> tuple[CorpusChunk, ...]:
	"""Return only chunks with non-empty normalized text."""

	return tuple(chunk for chunk in chunks if chunk.text.strip())