"""Corpus loading and normalization helpers for local markdown support content."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Final, Iterable

from config import DATA_ROOT, DEFAULT_ENCODING
from schemas import Company


DOMAIN_BY_FOLDER: Final[dict[str, Company]] = {
	"claude": Company.CLAUDE,
	"hackerrank": Company.HACKERRANK,
	"visa": Company.VISA,
}
HEADING_PATTERN: Final[re.Pattern[str]] = re.compile(r"^#{1,6}\s+")
LINK_PATTERN: Final[re.Pattern[str]] = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
IMAGE_PATTERN: Final[re.Pattern[str]] = re.compile(r"!\[[^\]]*\]\([^)]+\)")
HTML_PATTERN: Final[re.Pattern[str]] = re.compile(r"<[^>]+>")
MARKDOWN_NOISE_PATTERN: Final[re.Pattern[str]] = re.compile(r'[*_`>"]')
NUMERIC_PREFIX_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\d+-")
TABLE_SEPARATOR_PATTERN: Final[re.Pattern[str]] = re.compile(r"^\|?[-: ]+\|[-|: ]+$")
WORD_PATTERN: Final[re.Pattern[str]] = re.compile(r"\b\w+\b")
LAST_UPDATED_PATTERN: Final[re.Pattern[str]] = re.compile(r"^_Last (updated|modified):.*_$", re.IGNORECASE)
LINK_ONLY_LINE_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[-*]?\s*\[[^\]]+\]\([^)]+\)\s*$")


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


def discover_markdown_files(data_root: Path = DATA_ROOT) -> tuple[Path, ...]:
	"""Discover markdown files under the local corpus root."""

	return tuple(sorted(path for path in data_root.rglob("*.md") if path.is_file()))


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


def detect_stub_or_navigation(relative_path: Path, body_text: str, normalized_text: str) -> tuple[bool, str | None]:
	"""Return whether a page is answer-bearing versus an index, stub, or link hub."""

	non_empty_lines = [line.strip() for line in body_text.splitlines() if line.strip()]
	paragraph_lines = [line for line in normalized_text.splitlines() if len(WORD_PATTERN.findall(line)) >= 8]
	link_only_lines = sum(1 for line in non_empty_lines if LINK_ONLY_LINE_PATTERN.match(line))
	word_count = len(WORD_PATTERN.findall(normalized_text))
	has_export_banner = any(
		line.lower().startswith("exported ") and "articles" in line.lower()
		for line in non_empty_lines
	)

	if relative_path.name == "index.md" or has_export_banner:
		return False, "navigation_index"
	if non_empty_lines and link_only_lines / len(non_empty_lines) >= 0.5 and not paragraph_lines:
		return False, "navigation_links"
	if word_count < 30 and len(non_empty_lines) <= 6:
		return False, "short_stub"
	return True, None


def _domain_from_relative_path(relative_path: Path) -> Company:
	try:
		return DOMAIN_BY_FOLDER[relative_path.parts[0]]
	except KeyError as exc:
		raise ValueError(f"Unsupported corpus domain for path: {relative_path}") from exc


def parse_markdown_file(path: Path, data_root: Path = DATA_ROOT) -> CorpusRecord:
	"""Parse one markdown file into a normalized file-level corpus record."""

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

	return CorpusRecord(
		domain=_domain_from_relative_path(relative_path),
		source_path=relative_path.as_posix(),
		title=title,
		breadcrumbs=breadcrumbs,
		text=normalized_text,
		metadata=metadata,
		is_answer_bearing=is_answer_bearing,
		stub_reason=stub_reason,
	)


@lru_cache(maxsize=1)
def load_corpus(data_root: Path = DATA_ROOT) -> tuple[CorpusRecord, ...]:
	"""Load and normalize the full markdown corpus at file granularity."""

	return tuple(parse_markdown_file(path, data_root=data_root) for path in discover_markdown_files(data_root))


def filter_answer_bearing_records(records: Iterable[CorpusRecord]) -> tuple[CorpusRecord, ...]:
	"""Return only records that appear answer-bearing enough for later retrieval."""

	return tuple(record for record in records if record.is_answer_bearing)