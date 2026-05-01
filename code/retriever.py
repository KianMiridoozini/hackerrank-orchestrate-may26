"""Lexical retrieval helpers for grounded support answer selection."""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from typing import Final

from corpus import CorpusChunk, load_corpus_chunks
from schemas import Company, RetrievedChunk
from taxonomy import map_evidence_to_product_area


TOKEN_PATTERN: Final[re.Pattern[str]] = re.compile(r"[a-z0-9]+")
TITLE_WEIGHT: Final[float] = 3.0
HEADING_WEIGHT: Final[float] = 2.5
BREADCRUMB_WEIGHT: Final[float] = 1.75
PATH_WEIGHT: Final[float] = 1.5
BODY_WEIGHT: Final[float] = 1.0
BM25_K1: Final[float] = 1.4
BM25_B: Final[float] = 0.75


@dataclass(frozen=True)
class IndexedChunk:
	"""Chunk plus precomputed lexical features for BM25 ranking."""

	chunk: CorpusChunk
	term_frequencies: dict[str, float]
	document_length: float
	product_area_hint: str


@dataclass(frozen=True)
class BM25Index:
	"""In-memory BM25 index over the normalized support corpus."""

	chunks: tuple[IndexedChunk, ...]
	inverse_document_frequency: dict[str, float]
	average_document_length: float


def build_query_text(*parts: str | None) -> str:
	"""Join the available ticket text fields into one retrieval query."""

	return " ".join(part.strip() for part in parts if part and part.strip())


def _tokenize(value: str) -> tuple[str, ...]:
	return tuple(TOKEN_PATTERN.findall(value.lower()))


def _add_weighted_tokens(term_frequencies: dict[str, float], text: str | None, weight: float) -> None:
	if not text:
		return
	for token in _tokenize(text):
		term_frequencies[token] = term_frequencies.get(token, 0.0) + weight


def _build_term_frequencies(chunk: CorpusChunk) -> tuple[dict[str, float], float]:
	term_frequencies: dict[str, float] = {}
	_add_weighted_tokens(term_frequencies, chunk.title, TITLE_WEIGHT)
	_add_weighted_tokens(term_frequencies, chunk.heading, HEADING_WEIGHT)
	for breadcrumb in chunk.breadcrumbs:
		_add_weighted_tokens(term_frequencies, breadcrumb, BREADCRUMB_WEIGHT)
	_add_weighted_tokens(term_frequencies, chunk.source_path, PATH_WEIGHT)
	_add_weighted_tokens(term_frequencies, chunk.text, BODY_WEIGHT)
	return term_frequencies, sum(term_frequencies.values())


def _coerce_company(domain: Company | str | None) -> Company | None:
	if domain is None:
		return None
	if isinstance(domain, Company):
		return None if domain is Company.NONE else domain

	stripped = str(domain).strip()
	if not stripped:
		return None

	normalized = stripped.lower()
	alias_map = {
		"claude": Company.CLAUDE,
		"hackerrank": Company.HACKERRANK,
		"visa": Company.VISA,
		"none": Company.NONE,
	}
	resolved = alias_map.get(normalized)
	if resolved is not None:
		return None if resolved is Company.NONE else resolved

	return None


@lru_cache(maxsize=1)
def build_bm25_index() -> BM25Index:
	"""Build and cache the lexical BM25 index over the chunked support corpus."""

	document_frequencies: Counter[str] = Counter()
	indexed_chunks: list[IndexedChunk] = []
	total_document_length = 0.0

	for chunk in load_corpus_chunks():
		term_frequencies, document_length = _build_term_frequencies(chunk)
		if not term_frequencies:
			continue

		product_area_hint = map_evidence_to_product_area(
			breadcrumbs=chunk.breadcrumbs,
			source_path=chunk.source_path,
			company=chunk.domain,
		)
		indexed_chunks.append(
			IndexedChunk(
				chunk=chunk,
				term_frequencies=term_frequencies,
				document_length=document_length,
				product_area_hint=product_area_hint,
			)
		)
		total_document_length += document_length
		for token in term_frequencies:
			document_frequencies[token] += 1

	chunk_count = len(indexed_chunks)
	average_document_length = total_document_length / chunk_count if chunk_count else 0.0
	inverse_document_frequency = {
		token: math.log(1.0 + (chunk_count - frequency + 0.5) / (frequency + 0.5))
		for token, frequency in document_frequencies.items()
	}
	return BM25Index(
		chunks=tuple(indexed_chunks),
		inverse_document_frequency=inverse_document_frequency,
		average_document_length=average_document_length,
	)


def _score_chunk(query_terms: Counter[str], indexed_chunk: IndexedChunk, index: BM25Index) -> float:
	if not query_terms:
		return 0.0

	average_document_length = index.average_document_length or 1.0
	normalization = BM25_K1 * (
		1.0 - BM25_B + BM25_B * indexed_chunk.document_length / average_document_length
	)
	score = 0.0
	for token, query_weight in query_terms.items():
		term_frequency = indexed_chunk.term_frequencies.get(token)
		if not term_frequency:
			continue
		inverse_document_frequency = index.inverse_document_frequency.get(token)
		if inverse_document_frequency is None:
			continue
		numerator = term_frequency * (BM25_K1 + 1.0)
		denominator = term_frequency + normalization
		score += query_weight * inverse_document_frequency * (numerator / denominator)
	return score


def _to_retrieved_chunk(indexed_chunk: IndexedChunk, *, score: float, rank: int) -> RetrievedChunk:
	chunk = indexed_chunk.chunk
	return RetrievedChunk(
		chunk_id=chunk.chunk_id,
		domain=chunk.domain,
		source_path=chunk.source_path,
		title=chunk.title,
		text=chunk.text,
		breadcrumbs=chunk.breadcrumbs,
		heading=chunk.heading,
		product_area_hint=indexed_chunk.product_area_hint,
		score=score,
		rank=rank,
	)


def retrieve_chunks(
	query_text: str,
	*,
	domain: Company | str | None = None,
	top_k: int = 5,
) -> tuple[RetrievedChunk, ...]:
	"""Return the top lexical matches for a query, optionally filtered by domain."""

	if top_k <= 0:
		return ()

	query_terms = Counter(_tokenize(query_text))
	if not query_terms:
		return ()

	index = build_bm25_index()
	active_domain = _coerce_company(domain)
	scored_chunks: list[tuple[float, IndexedChunk]] = []
	for indexed_chunk in index.chunks:
		if active_domain is not None and indexed_chunk.chunk.domain is not active_domain:
			continue
		score = _score_chunk(query_terms, indexed_chunk, index)
		if score <= 0.0:
			continue
		scored_chunks.append((score, indexed_chunk))

	scored_chunks.sort(
		key=lambda item: (
			-item[0],
			item[1].chunk.source_path,
			item[1].chunk.heading or "",
			item[1].chunk.chunk_id,
		)
	)

	results: list[RetrievedChunk] = []
	for rank, (score, indexed_chunk) in enumerate(scored_chunks[:top_k], start=1):
		results.append(_to_retrieved_chunk(indexed_chunk, score=score, rank=rank))
	return tuple(results)