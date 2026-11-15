"""LLM adapter for an OpenAI-compatible API, configured separately for candidate extraction (OCOP_EXTRACT_*)
and for answers/routing (OCOP_ANSWER_*)."""

from __future__ import annotations
import json
import os
import time
import urllib.error
import urllib.request
from urllib.parse import urlsplit
from pathlib import Path
from ai_core.system.telemetry import traced

_ROUTER_SYSTEM = (
    "Bạn là router cho OCOP. Chỉ trả JSON với intent và slots. "
    "Không ra lệnh tools. Không suy đoán tenant_id/dossier_id."
)


def _endpoint(url: str) -> str:
    """scheme://host[:port]/path without credentials or query string."""
    parts = urlsplit(url)
    host = parts.hostname or ""
    return f"{parts.scheme}://{host}{':' + str(parts.port) if parts.port else ''}{parts.path.rstrip('/')}"


OPENAI_TEMPERATURE = 0.1
OPENAI_REASONING_BUDGET = 2048
DEFAULT_MODEL = "gpt-6-sol"


def _openai_identity(model: str, base_url: str, reasoning_budget: int, revision: str = "") -> dict:
    return {
        "provider": "openai",
        "endpoint": _endpoint(base_url),
        "model": model,
        "revision": revision,
        "params": {"temperature": OPENAI_TEMPERATURE, "reasoning_budget": reasoning_budget},
    }


class ModelOutputTruncated(RuntimeError):
    """A transport succeeded but its unfinished output must not be published."""


class _RouteMixin:
    def chat_structured(self, system: str, user: str, *, schema: dict, max_tokens: int = 1024) -> str:
        return self.chat(system, user, format_json=True, max_tokens=max_tokens, schema=schema)

    def route(self, question: str) -> dict:
        try:
            return json.loads(self.chat(_ROUTER_SYSTEM, question, format_json=True, max_tokens=180))
        except (json.JSONDecodeError, RuntimeError):
            return {}


class OpenAICompatClient(_RouteMixin):
    """Chat Completions over HTTPS. The API key is read from the environment, never logged or persisted."""

    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str,
        timeout: float = 120,
        reasoning_budget: int = OPENAI_REASONING_BUDGET,
        retries: int = 4,
    ):
        if not model or not model.strip():
            raise RuntimeError(
                "Extraction/answer model is empty; configure OCOP_EXTRACT_LLM_MODEL or OCOP_ANSWER_LLM_MODEL"
            )
        if not api_key:
            raise RuntimeError(
                "OpenAI-compatible API key is not set (OCOP_EXTRACT_OPENAI_API_KEY or OCOP_ANSWER_OPENAI_API_KEY)"
            )
        self.model = model
        self.url = base_url.rstrip("/")
        self._key = api_key
        self.timeout = timeout
        self.reasoning_budget = reasoning_budget
        self.retries = retries
        self.revision = ""

    def identity(self) -> dict:
        return _openai_identity(self.model, self.url, self.reasoning_budget, self.revision)

    def __repr__(self) -> str:
        return f"OpenAICompatClient(model={self.model!r}, base_url={self.url!r})"

    @traced("ocop.llm.openai_chat")
    def chat(
        self,
        system: str,
        user: str,
        *,
        format_json: bool = False,
        max_tokens: int = 1024,
        schema: dict | None = None,
    ) -> str:
        # Reasoning models count hidden reasoning tokens against the completion limit.
        data = {
            "model": self.model,
            "temperature": OPENAI_TEMPERATURE,
            "max_tokens": max_tokens + self.reasoning_budget,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
        }
        if schema is not None:
            data["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "ocop_extraction", "strict": True, "schema": schema},
            }
        elif format_json:
            data["response_format"] = {"type": "json_object"}
        req = urllib.request.Request(
            self.url + "/chat/completions",
            data=json.dumps(data, ensure_ascii=False).encode(),
            # Some gateways (Cloudflare 1010) reject the default Python-urllib agent.
            headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self._key,
                "User-Agent": "ocop-graphrag/1.0",
            },
            method="POST",
        )
        try:
            choice = self._post(req)["choices"][0]
            if choice.get("finish_reason") == "length":
                raise ModelOutputTruncated("Configured OpenAI-compatible response truncated")
            if choice.get("finish_reason") == "content_filter":
                raise RuntimeError("Configured OpenAI-compatible response filtered")
            content = choice["message"]["content"]
        except (
            urllib.error.URLError,
            TimeoutError,
            OSError,
            KeyError,
            IndexError,
            TypeError,
            ValueError,
        ) as exc:
            detail = (
                f"HTTP {exc.code}: {_error_message(exc)}"
                if isinstance(exc, urllib.error.HTTPError)
                else type(exc).__name__
            )
            raise RuntimeError(f"Configured OpenAI-compatible model unavailable ({detail})") from exc
        if not isinstance(content, str):
            raise RuntimeError("OpenAI-compatible model returned no text")
        return content

    def _post(self, req) -> dict:
        # Retry rate limits and transient gateway errors with short exponential backoff.
        for attempt in range(self.retries + 1):
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as response:
                    return json.load(response)
            except urllib.error.HTTPError as exc:
                if exc.code not in (429, 500, 502, 503, 504) or attempt == self.retries:
                    raise
            except (urllib.error.URLError, TimeoutError) as exc:
                # A refused connection means nothing is listening: backing off for 15 s cannot change that.
                if attempt == self.retries or isinstance(
                    getattr(exc, "reason", None), ConnectionRefusedError
                ):
                    raise
            time.sleep(2**attempt)
        raise RuntimeError("unreachable")


def _error_message(exc) -> str:
    """Provider error text (e.g. quota exhausted), never the request or API key."""
    try:
        body = json.loads(exc.read() or b"{}")
        return str((body.get("error") or {}).get("message") or "")[:200]
    except (ValueError, OSError, AttributeError):
        return ""


def load_env_file(path: Path | None = None) -> None:
    """Minimal .env loader; existing environment variables always win."""
    path = path or Path(__file__).resolve().parents[3] / ".env"
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def extraction_provider() -> str:
    load_env_file()
    return os.getenv("OCOP_EXTRACT_LLM_PROVIDER", "openai").strip().lower()


def extraction_model_name() -> str:
    """Model id of the extraction client, without needing credentials."""
    return os.getenv("OCOP_EXTRACT_LLM_MODEL", DEFAULT_MODEL)


def extraction_workers() -> int:
    load_env_file()
    return int(os.getenv("OCOP_EXTRACT_LLM_WORKERS", "4"))


def extraction_gleanings() -> int:
    load_env_file()
    return int(os.getenv("OCOP_EXTRACT_LLM_GLEANINGS", "1"))


def extraction_revision() -> str:
    """Optional pin of the extraction model's revision/version string (when the provider exposes one)."""
    load_env_file()
    return os.getenv("OCOP_EXTRACT_LLM_REVISION", "").strip()


def extraction_identity() -> dict:
    """Identity of the configured extraction client without building it (no API key needed)."""
    _require_openai("OCOP_EXTRACT_LLM_PROVIDER", extraction_provider())
    return _openai_identity(
        extraction_model_name(),
        os.getenv("OCOP_EXTRACT_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        OPENAI_REASONING_BUDGET,
        extraction_revision(),
    )


def _require_openai(variable: str, provider: str) -> None:
    if provider != "openai":
        raise RuntimeError(f"Unsupported {variable}: {provider}; only an OpenAI-compatible API is supported")


def make_extraction_client() -> OpenAICompatClient:
    """Client used ONLY for candidate entity/feature extraction (OpenAI-compatible API)."""
    _require_openai("OCOP_EXTRACT_LLM_PROVIDER", extraction_provider())
    client = OpenAICompatClient(
        model=extraction_model_name(),
        base_url=os.getenv("OCOP_EXTRACT_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.getenv("OCOP_EXTRACT_OPENAI_API_KEY", ""),
    )
    client.revision = extraction_revision()
    return client


def answer_provider() -> str:
    load_env_file()
    return os.getenv("OCOP_ANSWER_LLM_PROVIDER", "openai").strip().lower()


def make_answer_client() -> OpenAICompatClient:
    """Client for routing and answer generation. The endpoint and key default to the extraction ones,
    so one configured API serves both."""
    _require_openai("OCOP_ANSWER_LLM_PROVIDER", answer_provider())
    return OpenAICompatClient(
        model=os.getenv("OCOP_ANSWER_LLM_MODEL") or os.getenv("OCOP_EXTRACT_LLM_MODEL", DEFAULT_MODEL),
        base_url=os.getenv("OCOP_ANSWER_OPENAI_BASE_URL")
        or os.getenv("OCOP_EXTRACT_OPENAI_BASE_URL", "https://api.openai.com/v1"),
        api_key=os.getenv("OCOP_ANSWER_OPENAI_API_KEY") or os.getenv("OCOP_EXTRACT_OPENAI_API_KEY", ""),
    )
