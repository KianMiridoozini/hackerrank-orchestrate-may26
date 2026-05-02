"""Optional provider wrapper for bounded response synthesis."""

from __future__ import annotations

import json
import os
import random
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, Final, Generic, Mapping, TypeVar
from urllib import error, parse, request

from core.config import (
	DEFAULT_MODEL_TEMPERATURE,
	DEFAULT_PROVIDER_NAME,
	DEFAULT_PROVIDER_TIMEOUT_SECONDS,
	PROVIDER_SETTINGS,
)
from core.schemas import SupportModel


ModelT = TypeVar("ModelT", bound=SupportModel)
Transport = Callable[[str, str, Mapping[str, str], dict[str, Any], int], dict[str, Any]]

LLM_PROVIDER_ENV: Final[str] = "LLM_PROVIDER"
LLM_RATE_LIMIT_RPM_ENV: Final[str] = "LLM_RATE_LIMIT_RPM"
LLM_RATE_LIMIT_BURST_ENV: Final[str] = "LLM_RATE_LIMIT_BURST"
LLM_RATE_LIMIT_MAX_WAIT_SECONDS_ENV: Final[str] = "LLM_RATE_LIMIT_MAX_WAIT_SECONDS"
DEFAULT_MAX_OUTPUT_TOKENS: Final[int] = 320
MAX_STRUCTURED_OUTPUT_ATTEMPTS: Final[int] = 2
OPENAI_BASE_URL: Final[str] = "https://api.openai.com/v1"
GEMINI_BASE_URL: Final[str] = "https://generativelanguage.googleapis.com/v1beta"
MAX_TIMEOUT_PROVIDER_RETRIES: Final[int] = 1
MAX_TRANSIENT_PROVIDER_RETRIES: Final[int] = 2
PROVIDER_RETRY_BASE_DELAY_SECONDS: Final[float] = 0.75
PROVIDER_RETRY_JITTER_SECONDS: Final[float] = 0.35
PROVIDER_CIRCUIT_BREAKER_THRESHOLD: Final[int] = 3
PROVIDER_CIRCUIT_BREAKER_COOLDOWN_SECONDS: Final[float] = 60.0
DEFAULT_RATE_LIMIT_BURST_CAP: Final[int] = 4
DEFAULT_RATE_LIMIT_MAX_WAIT_SECONDS: Final[float] = 2.0
RETRY_DELAY_SECONDS_PATTERN: Final[re.Pattern[str]] = re.compile(r'retrydelay"\s*:\s*"([0-9]+(?:\.[0-9]+)?)s"', re.IGNORECASE)
RETRY_IN_SECONDS_PATTERN: Final[re.Pattern[str]] = re.compile(r'retry in\s+([0-9]+(?:\.[0-9]+)?)s', re.IGNORECASE)


@dataclass(frozen=True)
class StructuredLLMRequest:
	"""Bounded prompt envelope for optional synthesis or tie-break calls."""

	system_prompt: str
	user_prompt: str
	max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS


@dataclass(frozen=True)
class ResolvedProviderConfig:
	"""Provider configuration resolved from environment and repo defaults."""

	provider_name: str
	model_name: str
	api_key: str | None
	api_key_env: str
	base_url: str
	timeout_seconds: int = DEFAULT_PROVIDER_TIMEOUT_SECONDS
	rate_limit_rpm: int | None = None
	rate_limit_burst: int | None = None
	rate_limit_max_wait_seconds: float = DEFAULT_RATE_LIMIT_MAX_WAIT_SECONDS


@dataclass(frozen=True)
class LLMCallResult(Generic[ModelT]):
	"""Final result for one optional LLM call."""

	value: ModelT | None
	provider: str | None
	model: str | None
	failure_reason: str | None = None
	raw_text: str | None = None
	attempts: int = 0

	@property
	def succeeded(self) -> bool:
		return self.value is not None


class StructuredOutputError(ValueError):
	"""Raised when the provider does not return valid structured JSON."""


@dataclass
class _ProviderCircuitState:
	"""Track retryable provider failures for one provider/model pair."""

	consecutive_retryable_failures: int = 0
	open_until_monotonic: float = 0.0
	last_retryable_error: str | None = None


@dataclass
class _ProviderBudgetState:
	"""Track local admission-control state for one provider/model pair."""

	tokens: float = 0.0
	last_refill_monotonic: float = 0.0
	cooldown_until_monotonic: float = 0.0


_PROVIDER_CIRCUIT_BREAKERS: dict[tuple[str, str], _ProviderCircuitState] = {}
_PROVIDER_BUDGETS: dict[tuple[str, str], _ProviderBudgetState] = {}


def _response_schema_dict(response_schema: type[ModelT]) -> dict[str, Any]:
	if hasattr(response_schema, "model_json_schema"):
		return response_schema.model_json_schema()
	return response_schema.schema()


def _validate_schema_payload(response_schema: type[ModelT], payload: Any) -> ModelT:
	if hasattr(response_schema, "model_validate"):
		return response_schema.model_validate(payload)
	return response_schema.parse_obj(payload)


def _default_base_url(provider_name: str) -> str:
	if provider_name == "openai":
		return OPENAI_BASE_URL
	if provider_name == "gemini":
		return GEMINI_BASE_URL
	return ""


def _provider_circuit_key(provider_config: ResolvedProviderConfig) -> tuple[str, str]:
	return provider_config.provider_name, provider_config.model_name


def _provider_circuit_state(provider_config: ResolvedProviderConfig) -> _ProviderCircuitState:
	key = _provider_circuit_key(provider_config)
	state = _PROVIDER_CIRCUIT_BREAKERS.get(key)
	if state is None:
		state = _ProviderCircuitState()
		_PROVIDER_CIRCUIT_BREAKERS[key] = state
	return state


def _provider_budget_state(provider_config: ResolvedProviderConfig) -> _ProviderBudgetState:
	key = _provider_circuit_key(provider_config)
	state = _PROVIDER_BUDGETS.get(key)
	if state is None:
		state = _ProviderBudgetState()
		_PROVIDER_BUDGETS[key] = state
	return state


def _reset_provider_circuit(provider_config: ResolvedProviderConfig) -> None:
	state = _provider_circuit_state(provider_config)
	state.consecutive_retryable_failures = 0
	state.open_until_monotonic = 0.0
	state.last_retryable_error = None


def _record_retryable_provider_failure(
	provider_config: ResolvedProviderConfig,
	*,
	error_text: str,
) -> None:
	state = _provider_circuit_state(provider_config)
	state.consecutive_retryable_failures += 1
	state.last_retryable_error = error_text
	if state.consecutive_retryable_failures >= PROVIDER_CIRCUIT_BREAKER_THRESHOLD:
		state.open_until_monotonic = time.monotonic() + PROVIDER_CIRCUIT_BREAKER_COOLDOWN_SECONDS


def _provider_circuit_open_message(provider_config: ResolvedProviderConfig) -> str | None:
	state = _provider_circuit_state(provider_config)
	if state.open_until_monotonic <= 0.0:
		return None

	now_monotonic = time.monotonic()
	if now_monotonic >= state.open_until_monotonic:
		_reset_provider_circuit(provider_config)
		return None

	remaining_seconds = state.open_until_monotonic - now_monotonic
	last_error = state.last_retryable_error or "retryable_provider_failures"
	return (
		"provider_circuit_open:"
		f"{provider_config.provider_name}:{provider_config.model_name}:{remaining_seconds:.2f}:{last_error}"
	)


def _http_status_from_runtime_error(error_text: str) -> int | None:
	if not error_text.startswith("http_error:"):
		return None
	parts = error_text.split(":", 2)
	if len(parts) < 3:
		return None
	try:
		return int(parts[1])
	except ValueError:
		return None


def _parse_positive_int(value: str | None) -> int | None:
	if value is None:
		return None
	try:
		parsed = int(value.strip())
	except (TypeError, ValueError):
		return None
	return parsed if parsed > 0 else None


def _parse_non_negative_float(value: str | None) -> float | None:
	if value is None:
		return None
	try:
		parsed = float(value.strip())
	except (TypeError, ValueError):
		return None
	return parsed if parsed >= 0.0 else None


def _retry_after_seconds_from_error(error_text: str) -> float | None:
	for pattern in (RETRY_DELAY_SECONDS_PATTERN, RETRY_IN_SECONDS_PATTERN):
		match = pattern.search(error_text)
		if match is None:
			continue
		try:
			parsed = float(match.group(1))
		except ValueError:
			continue
		if parsed > 0.0:
			return parsed
	return None


def _is_terminal_quota_error(error_text: str) -> bool:
	normalized_text = error_text.strip().lower()
	if "insufficient_quota" in normalized_text:
		return True
	if "billing" in normalized_text and _retry_after_seconds_from_error(error_text) is None:
		return True
	return False


def _retryable_provider_error_policy(error_text: str) -> tuple[str | None, int]:
	normalized_text = error_text.strip().lower()
	if normalized_text.startswith("network_error:timeout"):
		return "timeout", MAX_TIMEOUT_PROVIDER_RETRIES

	status_code = _http_status_from_runtime_error(error_text)
	if status_code == 503:
		return "service_unavailable", MAX_TRANSIENT_PROVIDER_RETRIES
	if status_code == 429 and not _is_terminal_quota_error(error_text):
		return "rate_limited", MAX_TRANSIENT_PROVIDER_RETRIES
	if "rate limit" in normalized_text and not _is_terminal_quota_error(error_text):
		return "rate_limited", MAX_TRANSIENT_PROVIDER_RETRIES
	if _retry_after_seconds_from_error(error_text) is not None and not _is_terminal_quota_error(error_text):
		return "rate_limited", MAX_TRANSIENT_PROVIDER_RETRIES
	return None, 0


def _provider_retry_delay_seconds(retry_number: int) -> float:
	base_delay = PROVIDER_RETRY_BASE_DELAY_SECONDS * (2 ** max(retry_number - 1, 0))
	jitter = random.uniform(0.0, PROVIDER_RETRY_JITTER_SECONDS)
	return base_delay + jitter


def _provider_budget_refill_rate(provider_config: ResolvedProviderConfig) -> float | None:
	if provider_config.rate_limit_rpm is None:
		return None
	return provider_config.rate_limit_rpm / 60.0


def _refill_provider_budget(provider_config: ResolvedProviderConfig, *, now_monotonic: float) -> _ProviderBudgetState:
	state = _provider_budget_state(provider_config)
	if provider_config.rate_limit_rpm is None or provider_config.rate_limit_burst is None:
		return state
	if state.last_refill_monotonic <= 0.0:
		state.last_refill_monotonic = now_monotonic
		state.tokens = float(provider_config.rate_limit_burst)
		return state
	replenish_rate = _provider_budget_refill_rate(provider_config)
	if replenish_rate is None:
		return state
	elapsed_seconds = max(0.0, now_monotonic - state.last_refill_monotonic)
	if elapsed_seconds > 0.0:
		state.tokens = min(
			float(provider_config.rate_limit_burst),
			state.tokens + (elapsed_seconds * replenish_rate),
		)
		state.last_refill_monotonic = now_monotonic
	return state


def _apply_provider_cooldown(
	provider_config: ResolvedProviderConfig,
	*,
	retry_after_seconds: float,
) -> None:
	state = _provider_budget_state(provider_config)
	now_monotonic = time.monotonic()
	state.cooldown_until_monotonic = max(
		state.cooldown_until_monotonic,
		now_monotonic + retry_after_seconds,
	)
	if provider_config.rate_limit_burst is not None:
		state.tokens = 0.0
		state.last_refill_monotonic = now_monotonic


def _consume_provider_budget(provider_config: ResolvedProviderConfig) -> None:
	now_monotonic = time.monotonic()
	state = _provider_budget_state(provider_config)
	if state.cooldown_until_monotonic > now_monotonic:
		wait_seconds = state.cooldown_until_monotonic - now_monotonic
		if wait_seconds > provider_config.rate_limit_max_wait_seconds:
			raise RuntimeError(
				"provider_rate_limited_cooldown:"
				f"{provider_config.provider_name}:{provider_config.model_name}:{wait_seconds:.2f}"
			)
		time.sleep(wait_seconds)
		now_monotonic = time.monotonic()

	if provider_config.rate_limit_rpm is None or provider_config.rate_limit_burst is None:
		return

	state = _refill_provider_budget(provider_config, now_monotonic=now_monotonic)

	if state.tokens >= 1.0:
		state.tokens -= 1.0
		return

	replenish_rate = _provider_budget_refill_rate(provider_config)
	if replenish_rate is None or replenish_rate <= 0.0:
		raise RuntimeError(
			"provider_rate_limited_budget:"
			f"{provider_config.provider_name}:{provider_config.model_name}:0.00"
		)
	wait_seconds = max(0.0, (1.0 - state.tokens) / replenish_rate)
	if wait_seconds > provider_config.rate_limit_max_wait_seconds:
		raise RuntimeError(
			"provider_rate_limited_budget:"
			f"{provider_config.provider_name}:{provider_config.model_name}:{wait_seconds:.2f}"
		)
	time.sleep(wait_seconds)
	now_monotonic = time.monotonic()
	state = _refill_provider_budget(provider_config, now_monotonic=now_monotonic)
	if state.tokens < 1.0:
		raise RuntimeError(
			"provider_rate_limited_budget:"
			f"{provider_config.provider_name}:{provider_config.model_name}:{wait_seconds:.2f}"
		)
	state.tokens -= 1.0


def _send_json_request_with_resilience(
	provider_config: ResolvedProviderConfig,
	request_transport: Transport,
	*,
	method: str,
	url: str,
	headers: Mapping[str, str],
	payload: dict[str, Any],
) -> dict[str, Any]:
	circuit_open_message = _provider_circuit_open_message(provider_config)
	if circuit_open_message is not None:
		raise RuntimeError(circuit_open_message)

	retry_attempt = 0
	while True:
		try:
			_consume_provider_budget(provider_config)
			response_payload = request_transport(
				method,
				url,
				headers,
				payload,
				provider_config.timeout_seconds,
			)
			_reset_provider_circuit(provider_config)
			return response_payload
		except RuntimeError as exc:
			error_text = str(exc)
			if error_text.startswith("provider_rate_limited"):
				raise
			retryable_category, max_retries = _retryable_provider_error_policy(error_text)
			if retryable_category is None:
				_reset_provider_circuit(provider_config)
				raise
			retry_after_seconds = _retry_after_seconds_from_error(error_text)
			if retryable_category == "rate_limited" and retry_after_seconds is not None:
				_apply_provider_cooldown(
					provider_config,
					retry_after_seconds=retry_after_seconds,
				)
			if retry_attempt >= max_retries:
				_record_retryable_provider_failure(provider_config, error_text=error_text)
				if retryable_category == "rate_limited":
					raise RuntimeError(
						"provider_rate_limited:"
						f"{provider_config.provider_name}:{provider_config.model_name}:{retry_after_seconds or 0.0:.2f}"
					)
				raise
			retry_attempt += 1
			if retryable_category == "rate_limited" and retry_after_seconds is not None:
				if retry_after_seconds > provider_config.rate_limit_max_wait_seconds:
					_record_retryable_provider_failure(provider_config, error_text=error_text)
					raise RuntimeError(
						"provider_rate_limited:"
						f"{provider_config.provider_name}:{provider_config.model_name}:{retry_after_seconds:.2f}"
					)
				time.sleep(retry_after_seconds)
				continue
			time.sleep(_provider_retry_delay_seconds(retry_attempt))


def _schema_guard_prompt(system_prompt: str, response_schema: type[ModelT]) -> str:
	schema_text = json.dumps(_response_schema_dict(response_schema), sort_keys=True)
	return (
		f"{system_prompt.strip()}\n\n"
		"Return only one JSON object. Do not include markdown, code fences, or extra prose. "
		f"The JSON must match this schema exactly: {schema_text}"
	)


def resolve_provider_config(
	provider_name: str | None = None,
	*,
	environ: Mapping[str, str] | None = None,
) -> ResolvedProviderConfig | None:
	"""Resolve provider, model, timeout, and credentials from the environment."""

	resolved_environ = os.environ if environ is None else environ
	resolved_provider = (
		(provider_name or resolved_environ.get(LLM_PROVIDER_ENV) or DEFAULT_PROVIDER_NAME)
		.strip()
		.lower()
	)
	settings = PROVIDER_SETTINGS.get(resolved_provider)
	if settings is None:
		return None

	configured_model = (resolved_environ.get(settings.model_env) or "").strip()
	model_name = configured_model or settings.default_model
	api_key = (resolved_environ.get(settings.api_key_env) or "").strip() or None
	base_url = _default_base_url(resolved_provider)
	if settings.base_url_env:
		override_base_url = (resolved_environ.get(settings.base_url_env) or "").strip()
		if override_base_url:
			base_url = override_base_url

	rate_limit_rpm = _parse_positive_int(resolved_environ.get(LLM_RATE_LIMIT_RPM_ENV))
	rate_limit_burst = _parse_positive_int(resolved_environ.get(LLM_RATE_LIMIT_BURST_ENV))
	rate_limit_max_wait_seconds = _parse_non_negative_float(
		resolved_environ.get(LLM_RATE_LIMIT_MAX_WAIT_SECONDS_ENV)
	)
	if rate_limit_rpm is not None and rate_limit_burst is None:
		rate_limit_burst = min(rate_limit_rpm, DEFAULT_RATE_LIMIT_BURST_CAP)
	if rate_limit_max_wait_seconds is None:
		rate_limit_max_wait_seconds = DEFAULT_RATE_LIMIT_MAX_WAIT_SECONDS

	return ResolvedProviderConfig(
		provider_name=resolved_provider,
		model_name=model_name,
		api_key=api_key,
		api_key_env=settings.api_key_env,
		base_url=base_url.rstrip("/"),
		rate_limit_rpm=rate_limit_rpm,
		rate_limit_burst=rate_limit_burst,
		rate_limit_max_wait_seconds=rate_limit_max_wait_seconds,
	)


def _runtime_failure_reason(error_text: str) -> str:
	if error_text.startswith("provider_circuit_open:"):
		return "provider_circuit_open"
	if error_text.startswith("provider_rate_limited"):
		return "rate_limited"
	return "provider_error"


def llm_available(provider_name: str | None = None, *, environ: Mapping[str, str] | None = None) -> bool:
	"""Report whether a configured provider is available for optional use."""

	provider_config = resolve_provider_config(provider_name, environ=environ)
	return provider_config is not None and bool(provider_config.api_key)


def _openai_request_parts(
	provider_config: ResolvedProviderConfig,
	llm_request: StructuredLLMRequest,
	response_schema: type[ModelT],
) -> tuple[str, dict[str, str], dict[str, Any]]:
	response_schema_dict = _response_schema_dict(response_schema)
	return (
		f"{provider_config.base_url}/chat/completions",
		{
			"Authorization": f"Bearer {provider_config.api_key}",
			"Content-Type": "application/json",
		},
		{
			"model": provider_config.model_name,
			"temperature": DEFAULT_MODEL_TEMPERATURE,
			"messages": [
				{
					"role": "system",
					"content": _schema_guard_prompt(llm_request.system_prompt, response_schema),
				},
				{
					"role": "user",
					"content": llm_request.user_prompt,
				},
			],
			"response_format": {
				"type": "json_schema",
				"json_schema": {
					"name": response_schema.__name__.lower(),
					"schema": response_schema_dict,
					"strict": True,
				},
			},
			"max_completion_tokens": llm_request.max_output_tokens,
		},
	)


def _gemini_request_parts(
	provider_config: ResolvedProviderConfig,
	llm_request: StructuredLLMRequest,
	response_schema: type[ModelT],
) -> tuple[str, dict[str, str], dict[str, Any]]:
	model_name = parse.quote(provider_config.model_name, safe="-._")
	api_key = parse.quote(provider_config.api_key or "", safe="")
	return (
		f"{provider_config.base_url}/models/{model_name}:generateContent?key={api_key}",
		{"Content-Type": "application/json"},
		{
			"systemInstruction": {
				"parts": [
					{
						"text": _schema_guard_prompt(llm_request.system_prompt, response_schema),
					}
				]
			},
			"contents": [
				{
					"role": "user",
					"parts": [
						{
							"text": llm_request.user_prompt,
						}
					],
				}
			],
			"generationConfig": {
				"temperature": DEFAULT_MODEL_TEMPERATURE,
				"candidateCount": 1,
				"maxOutputTokens": llm_request.max_output_tokens,
				"responseMimeType": "application/json",
			},
		},
	)


def _send_json_request(
	method: str,
	url: str,
	headers: Mapping[str, str],
	payload: dict[str, Any],
	timeout_seconds: int,
) -> dict[str, Any]:
	data = json.dumps(payload).encode("utf-8")
	request_object = request.Request(url, data=data, headers=dict(headers), method=method)
	try:
		with request.urlopen(request_object, timeout=timeout_seconds) as response:
			response_bytes = response.read()
	except TimeoutError as exc:  # pragma: no cover - depends on live provider behavior.
		raise RuntimeError("network_error:timeout") from exc
	except error.HTTPError as exc:  # pragma: no cover - depends on live provider behavior.
		detail = exc.read().decode("utf-8", errors="replace")
		raise RuntimeError(f"http_error:{exc.code}:{detail}") from exc
	except error.URLError as exc:  # pragma: no cover - depends on local network behavior.
		raise RuntimeError(f"network_error:{exc.reason}") from exc

	try:
		return json.loads(response_bytes.decode("utf-8"))
	except json.JSONDecodeError as exc:
		raise RuntimeError("invalid_provider_payload") from exc


def _flatten_openai_content(content: Any) -> str:
	if isinstance(content, str):
		return content.strip()
	if isinstance(content, list):
		parts: list[str] = []
		for part in content:
			if isinstance(part, dict):
				text = part.get("text")
				if isinstance(text, str) and text.strip():
					parts.append(text.strip())
		if parts:
			return "\n".join(parts)
	return ""


def _extract_openai_text(payload: dict[str, Any]) -> str:
	choices = payload.get("choices")
	if not isinstance(choices, list) or not choices:
		raise StructuredOutputError("openai_missing_choices")
	message = choices[0].get("message") if isinstance(choices[0], dict) else None
	if not isinstance(message, dict):
		raise StructuredOutputError("openai_missing_message")
	content = _flatten_openai_content(message.get("content"))
	if not content:
		raise StructuredOutputError("openai_empty_content")
	return content


def _extract_gemini_text(payload: dict[str, Any]) -> str:
	candidates = payload.get("candidates")
	if not isinstance(candidates, list) or not candidates:
		raise StructuredOutputError("gemini_missing_candidates")
	first_candidate = candidates[0]
	if not isinstance(first_candidate, dict):
		raise StructuredOutputError("gemini_invalid_candidate")
	content = first_candidate.get("content")
	if not isinstance(content, dict):
		raise StructuredOutputError("gemini_missing_content")
	parts = content.get("parts")
	if not isinstance(parts, list) or not parts:
		raise StructuredOutputError("gemini_missing_parts")
	texts = [part.get("text", "").strip() for part in parts if isinstance(part, dict)]
	raw_text = "\n".join(text for text in texts if text)
	if not raw_text:
		raise StructuredOutputError("gemini_empty_content")
	return raw_text


def _parse_structured_output(response_schema: type[ModelT], raw_text: str) -> ModelT:
	try:
		parsed_payload = json.loads(raw_text)
	except json.JSONDecodeError as exc:
		raise StructuredOutputError("malformed_json") from exc

	try:
		return _validate_schema_payload(response_schema, parsed_payload)
	except Exception as exc:  # pragma: no cover - exact exception depends on Pydantic version.
		raise StructuredOutputError("schema_validation_failed") from exc


def call_structured_llm(
	*,
	response_schema: type[ModelT],
	system_prompt: str,
	user_prompt: str,
	provider_name: str | None = None,
	max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
	environ: Mapping[str, str] | None = None,
	transport: Transport | None = None,
) -> LLMCallResult[ModelT]:
	"""Run one optional structured provider call and fail closed on any problem."""

	resolved_environ = os.environ if environ is None else environ
	provider_config = resolve_provider_config(provider_name, environ=resolved_environ)
	resolved_provider = (
		(provider_name or resolved_environ.get(LLM_PROVIDER_ENV) or DEFAULT_PROVIDER_NAME)
		.strip()
		.lower()
	)
	if provider_config is None:
		return LLMCallResult(
			value=None,
			provider=resolved_provider or None,
			model=None,
			failure_reason="unknown_provider",
		)
	if not provider_config.api_key:
		return LLMCallResult(
			value=None,
			provider=provider_config.provider_name,
			model=provider_config.model_name,
			failure_reason="missing_api_key",
		)

	llm_request = StructuredLLMRequest(
		system_prompt=system_prompt,
		user_prompt=user_prompt,
		max_output_tokens=max_output_tokens,
	)
	request_transport = transport or _send_json_request
	last_raw_text: str | None = None

	for attempt in range(1, MAX_STRUCTURED_OUTPUT_ATTEMPTS + 1):
		try:
			if provider_config.provider_name == "openai":
				url, headers, payload = _openai_request_parts(provider_config, llm_request, response_schema)
				response_payload = _send_json_request_with_resilience(
					provider_config,
					request_transport,
					method="POST",
					url=url,
					headers=headers,
					payload=payload,
				)
				last_raw_text = _extract_openai_text(response_payload)
			else:
				url, headers, payload = _gemini_request_parts(provider_config, llm_request, response_schema)
				response_payload = _send_json_request_with_resilience(
					provider_config,
					request_transport,
					method="POST",
					url=url,
					headers=headers,
					payload=payload,
				)
				last_raw_text = _extract_gemini_text(response_payload)

			validated_output = _parse_structured_output(response_schema, last_raw_text)
			return LLMCallResult(
				value=validated_output,
				provider=provider_config.provider_name,
				model=provider_config.model_name,
				raw_text=last_raw_text,
				attempts=attempt,
			)
		except StructuredOutputError:
			if attempt >= MAX_STRUCTURED_OUTPUT_ATTEMPTS:
				return LLMCallResult(
					value=None,
					provider=provider_config.provider_name,
					model=provider_config.model_name,
					failure_reason="malformed_structured_output",
					raw_text=last_raw_text,
					attempts=attempt,
				)
			continue
		except RuntimeError as exc:
			error_text = str(exc)
			failure_reason = _runtime_failure_reason(error_text)
			return LLMCallResult(
				value=None,
				provider=provider_config.provider_name,
				model=provider_config.model_name,
				failure_reason=failure_reason,
				raw_text=error_text,
				attempts=attempt,
			)

	return LLMCallResult(
		value=None,
		provider=provider_config.provider_name,
		model=provider_config.model_name,
		failure_reason="unexpected_fallback",
		raw_text=last_raw_text,
		attempts=MAX_STRUCTURED_OUTPUT_ATTEMPTS,
	)