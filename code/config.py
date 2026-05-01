"""Configuration and path constants for the support triage pipeline."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Final, MutableMapping


@dataclass(frozen=True)
class ProviderSettings:
	"""Provider-level environment configuration for optional LLM use."""

	name: str
	api_key_env: str
	model_env: str
	default_model: str
	base_url_env: str | None = None


REPO_ROOT: Final[Path] = Path(__file__).resolve().parent.parent
REPO_ENV_PATH: Final[Path] = REPO_ROOT / ".env"
CODE_ROOT: Final[Path] = REPO_ROOT / "code"
DATA_ROOT: Final[Path] = REPO_ROOT / "data"


def _normalize_env_assignment(raw_line: str) -> tuple[str, str] | None:
	"""Parse one dotenv-style assignment line into a key/value pair."""

	stripped_line = raw_line.strip()
	if not stripped_line or stripped_line.startswith("#"):
		return None
	if stripped_line.startswith("export "):
		stripped_line = stripped_line[len("export ") :].lstrip()
	if "=" not in stripped_line:
		return None

	key, raw_value = stripped_line.split("=", 1)
	key = key.strip()
	if not key:
		return None

	value = raw_value.strip()
	if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
		value = value[1:-1]
	return key, value


def load_repo_env(
	env_path: Path = REPO_ENV_PATH,
	*,
	environ: MutableMapping[str, str] | None = None,
) -> None:
	"""Populate os.environ from the repo-root .env file without overriding exports."""

	target_environ = os.environ if environ is None else environ
	if not env_path.is_file():
		return

	try:
		for raw_line in env_path.read_text(encoding="utf-8").splitlines():
			assignment = _normalize_env_assignment(raw_line)
			if assignment is None:
				continue
			key, value = assignment
			if key in target_environ:
				continue
			target_environ[key] = value
	except OSError:
		# Fail closed: callers already handle missing env-based provider config.
		return


load_repo_env()

SUPPORT_INPUT_DIR_CANDIDATES: Final[tuple[str, ...]] = (
	"support_tickets",
	"support_issues",
)


def resolve_support_root(repo_root: Path = REPO_ROOT) -> Path:
	"""Prefer support_tickets/ and fall back to support_issues/ if needed."""

	for directory_name in SUPPORT_INPUT_DIR_CANDIDATES:
		candidate = repo_root / directory_name
		if candidate.exists():
			return candidate
	return repo_root / SUPPORT_INPUT_DIR_CANDIDATES[0]


SUPPORT_ROOT: Final[Path] = resolve_support_root()
SAMPLE_TICKETS_PATH: Final[Path] = SUPPORT_ROOT / "sample_support_tickets.csv"
INPUT_TICKETS_PATH: Final[Path] = SUPPORT_ROOT / "support_tickets.csv"
OUTPUT_TICKETS_PATH: Final[Path] = SUPPORT_ROOT / "output.csv"

CACHE_ROOT: Final[Path] = CODE_ROOT / ".cache"
CORPUS_CACHE_PATH: Final[Path] = CACHE_ROOT / "corpus_cache.json"
TAXONOMY_CACHE_PATH: Final[Path] = CACHE_ROOT / "taxonomy_cache.json"
RETRIEVAL_CACHE_PATH: Final[Path] = CACHE_ROOT / "retrieval_index.json"
AI_TRACE_PATH: Final[Path] = CACHE_ROOT / "ai_trace.jsonl"

DEFAULT_ENCODING: Final[str] = "utf-8"
AI_MODE_ENV: Final[str] = "AI_MODE"
DEFAULT_AI_MODE: Final[str] = "off"
DEFAULT_PROVIDER_NAME: Final[str] = "gemini"
DEFAULT_MODEL_TEMPERATURE: Final[float] = 0.0
DEFAULT_PROVIDER_TIMEOUT_SECONDS: Final[int] = 30

PROVIDER_SETTINGS: Final[dict[str, ProviderSettings]] = {
    "gemini": ProviderSettings(
        name="gemini",
        api_key_env="GEMINI_API_KEY",
        model_env="GEMINI_MODEL",
        default_model="gemini-3.1-flash-lite-preview",
    ),
    "openai": ProviderSettings(
        name="openai",
        api_key_env="OPENAI_API_KEY",
        model_env="OPENAI_MODEL",
        default_model="gpt-5.4-mini",
    ),
}