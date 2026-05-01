"""Optional provider wrapper for bounded response synthesis."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Any, Callable, Final, Generic, Mapping, TypeVar
from urllib import error, parse, request

from config import (
	DEFAULT_MODEL_TEMPERATURE,
	DEFAULT_PROVIDER_NAME,
	DEFAULT_PROVIDER_TIMEOUT_SECONDS,
	PROVIDER_SETTINGS,
)
from schemas import SupportModel


ModelT = TypeVar("ModelT", bound=SupportModel)
Transport = Callable[[str, str, Mapping[str, str], dict[str, Any], int], dict[str, Any]]

LLM_PROVIDER_ENV: Final[str] = "LLM_PROVIDER"
DEFAULT_MAX_OUTPUT_TOKENS: Final[int] = 320
MAX_STRUCTURED_OUTPUT_ATTEMPTS: Final[int] = 2
OPENAI_BASE_URL: Final[str] = "https://api.openai.com/v1"
GEMINI_BASE_URL: Final[str] = "https://generativelanguage.googleapis.com/v1beta"


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

	return ResolvedProviderConfig(
		provider_name=resolved_provider,
		model_name=model_name,
		api_key=api_key,
		api_key_env=settings.api_key_env,
		base_url=base_url.rstrip("/"),
	)


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
				response_payload = request_transport(
					"POST",
					url,
					headers,
					payload,
					provider_config.timeout_seconds,
				)
				last_raw_text = _extract_openai_text(response_payload)
			else:
				url, headers, payload = _gemini_request_parts(provider_config, llm_request, response_schema)
				response_payload = request_transport(
					"POST",
					url,
					headers,
					payload,
					provider_config.timeout_seconds,
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
			return LLMCallResult(
				value=None,
				provider=provider_config.provider_name,
				model=provider_config.model_name,
				failure_reason="provider_error",
				raw_text=str(exc),
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