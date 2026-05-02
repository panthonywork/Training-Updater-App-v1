"""
AI provider abstraction layer.

All AI calls flow through this module. Adding a new provider means
implementing BaseAIProvider and registering it in PROVIDER_REGISTRY.

Model allocation per provider:
  classify task → cheap/fast model (yes/no decisions)
  rewrite task  → high-quality model (multi-sentence generation)
"""

from __future__ import annotations

import json
import os
import re
import time
from abc import ABC, abstractmethod
from enum import Enum
from pathlib import Path
from typing import Callable, Generator, TypeVar

_T = TypeVar("_T")

from src.models import ChangeType, Section

# ── Retry helper ──────────────────────────────────────────────────────────────

_TRANSIENT_SIGNALS = ("503", "unavailable", "429", "rate_limit", "resource_exhausted", "retry")


def _is_transient(exc: Exception) -> bool:
    msg = str(exc).lower()
    return any(s in msg for s in _TRANSIENT_SIGNALS)


def _section_error_label(exc: Exception) -> str:
    """Short plain-English label for a per-section processing failure."""
    msg = str(exc).lower()
    if "429" in msg or "rate_limit" in msg or "resource_exhausted" in msg:
        return "rate limit reached"
    if "context" in msg or "too long" in msg or "token" in msg:
        return "section text is too long for the model"
    if "content" in msg and ("filter" in msg or "block" in msg or "safety" in msg):
        return "blocked by content filter"
    return "unexpected API error"


def _with_retry(fn: Callable[[], _T], max_attempts: int = 3, base_delay: float = 5.0) -> _T:
    for attempt in range(max_attempts):
        try:
            return fn()
        except Exception as exc:
            if _is_transient(exc) and attempt < max_attempts - 1:
                time.sleep(base_delay * (2 ** attempt))
                continue
            raise


# ── Prompt loading ─────────────────────────────────────────────────────────────

_PROMPTS_DIR = Path(__file__).parent.parent / "prompts"


def _load_prompt(name: str) -> str:
    return (_PROMPTS_DIR / name).read_text()


# ── Provider enum & metadata ───────────────────────────────────────────────────

class AIProvider(Enum):
    GEMINI       = "gemini"
    OPENAI       = "openai"
    ANTHROPIC    = "anthropic"
    AZURE_OPENAI = "azure_openai"


PROVIDER_LABELS: dict[AIProvider, str] = {
    AIProvider.GEMINI:       "Google Gemini",
    AIProvider.OPENAI:       "OpenAI",
    AIProvider.ANTHROPIC:    "Anthropic Claude",
    AIProvider.AZURE_OPENAI: "Azure OpenAI (Copilot)",
}

# classify model = cheap/fast; rewrite model = high quality
PROVIDER_MODELS: dict[AIProvider, dict[str, str]] = {
    AIProvider.GEMINI: {
        "classify": "gemini-2.5-flash-lite",
        "rewrite":  "gemini-2.5-pro",
    },
    AIProvider.OPENAI: {
        "classify": "gpt-4o-mini",
        "rewrite":  "gpt-4o",
    },
    AIProvider.ANTHROPIC: {
        "classify": "claude-haiku-4-5-20251001",
        "rewrite":  "claude-sonnet-4-6",
    },
    AIProvider.AZURE_OPENAI: {
        "classify": os.getenv("AZURE_CLASSIFY_DEPLOYMENT", "gpt-4o-mini"),
        "rewrite":  os.getenv("AZURE_REWRITE_DEPLOYMENT",  "gpt-4o"),
    },
}

# Selectable models per provider (shown as dropdowns in the sidebar)
# Azure deployment names are user-defined, so those lists are empty (text input used instead)
PROVIDER_KNOWN_MODELS: dict[AIProvider, dict[str, list[str]]] = {
    AIProvider.GEMINI: {
        "classify": [
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-2.0-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
        ],
        "rewrite": [
            "gemini-1.5-flash",
            "gemini-1.5-pro",
            "gemini-2.0-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.5-pro",
        ],
    },
    AIProvider.OPENAI: {
        "classify": ["gpt-4o-mini", "gpt-4o", "gpt-3.5-turbo"],
        "rewrite":  ["gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-3.5-turbo"],
    },
    AIProvider.ANTHROPIC: {
        "classify": ["claude-haiku-4-5-20251001", "claude-sonnet-4-6"],
        "rewrite":  ["claude-sonnet-4-6", "claude-opus-4-7", "claude-haiku-4-5-20251001"],
    },
    AIProvider.AZURE_OPENAI: {
        "classify": [],
        "rewrite":  [],
    },
}

# Which env vars are required for each provider
PROVIDER_REQUIRED_KEYS: dict[AIProvider, list[str]] = {
    AIProvider.GEMINI:       ["GEMINI_API_KEY"],
    AIProvider.OPENAI:       ["OPENAI_API_KEY"],
    AIProvider.ANTHROPIC:    ["ANTHROPIC_API_KEY"],
    AIProvider.AZURE_OPENAI: ["AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT"],
}


def provider_is_configured(provider: AIProvider, user_key: str = "") -> bool:
    """Return True if a usable key exists — either entered by the user or set in the environment."""
    if provider != AIProvider.AZURE_OPENAI and user_key.strip():
        return True
    return all(os.getenv(k) for k in PROVIDER_REQUIRED_KEYS[provider])


def configured_providers() -> list[AIProvider]:
    return [p for p in AIProvider if provider_is_configured(p)]


# ── Prompt builder ─────────────────────────────────────────────────────────────

def _build_prompt(template: str, heading: str, original_text: str,
                  reference_text: str, context_note: str) -> str:
    context_note_block = (
        f"ADDITIONAL CONTEXT FROM USER:\n{context_note}\n" if context_note.strip() else ""
    )
    # Use plain replace() instead of str.format() so that literal braces in
    # the prompt (e.g. the example JSON {"change_type": ...}) are never
    # mistaken for format placeholders.
    result = template
    result = result.replace("{reference_text}", reference_text)
    result = result.replace("{context_note_block}", context_note_block)
    result = result.replace("{heading}", heading)
    result = result.replace("{original_text}", original_text)
    return result


def _parse_classify_response(raw: str) -> tuple[ChangeType, str]:
    """Extract change_type and reason from a JSON response string."""
    # Strip markdown fences if model wrapped the JSON
    cleaned = re.sub(r"```(?:json)?|```", "", raw).strip()
    try:
        data = json.loads(cleaned)
        ct_str = data.get("change_type", "no_change")
        reason = data.get("reason", "")
        change_type = {
            "no_change": ChangeType.NO_CHANGE,
            "update":    ChangeType.UPDATE,
            "gap":       ChangeType.GAP,
        }.get(ct_str, ChangeType.NO_CHANGE)
        return change_type, reason
    except (json.JSONDecodeError, AttributeError):
        # If the model returns malformed JSON, default to no_change
        return ChangeType.NO_CHANGE, "Could not parse classification response."


# ── Abstract base ──────────────────────────────────────────────────────────────

class BaseAIProvider(ABC):
    @abstractmethod
    def classify(self, heading: str, original_text: str,
                 reference_text: str, context_note: str) -> tuple[ChangeType, str]:
        """Return (ChangeType, reason_string)."""

    @abstractmethod
    def rewrite(self, heading: str, original_text: str,
                reference_text: str, context_note: str) -> str:
        """Return the rewritten section text."""


# ── Gemini ─────────────────────────────────────────────────────────────────────

class GeminiProvider(BaseAIProvider):
    def __init__(self, api_key: str = "") -> None:
        from google import genai
        key = api_key.strip() or os.environ.get("GEMINI_API_KEY", "")
        if not key:
            raise ValueError("No Gemini API key provided. Enter your key in the sidebar.")
        self._client = genai.Client(api_key=key)
        self._models = PROVIDER_MODELS[AIProvider.GEMINI]
        self._classify_tmpl = _load_prompt("classify.txt")
        self._rewrite_tmpl  = _load_prompt("rewrite.txt")

    def classify(self, heading, original_text, reference_text, context_note):
        prompt = _build_prompt(self._classify_tmpl, heading, original_text,
                               reference_text, context_note)
        response = self._client.models.generate_content(
            model=self._models["classify"],
            contents=prompt,
        )
        return _parse_classify_response(response.text)

    def rewrite(self, heading, original_text, reference_text, context_note):
        prompt = _build_prompt(self._rewrite_tmpl, heading, original_text,
                               reference_text, context_note)
        response = self._client.models.generate_content(
            model=self._models["rewrite"],
            contents=prompt,
        )
        return response.text.strip()


# ── OpenAI ─────────────────────────────────────────────────────────────────────

class OpenAIProvider(BaseAIProvider):
    def __init__(self, api_key: str = "") -> None:
        from openai import OpenAI
        key = api_key.strip() or os.environ.get("OPENAI_API_KEY", "")
        if not key:
            raise ValueError("No OpenAI API key provided. Enter your key in the sidebar.")
        self._client = OpenAI(api_key=key)
        self._models = PROVIDER_MODELS[AIProvider.OPENAI]
        self._classify_tmpl = _load_prompt("classify.txt")
        self._rewrite_tmpl  = _load_prompt("rewrite.txt")

    def _chat(self, model: str, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    def classify(self, heading, original_text, reference_text, context_note):
        system = "You are a precise document reviewer. Always respond with valid JSON only."
        user   = _build_prompt(self._classify_tmpl, heading, original_text,
                               reference_text, context_note)
        raw = self._chat(self._models["classify"], system, user)
        return _parse_classify_response(raw)

    def rewrite(self, heading, original_text, reference_text, context_note):
        system = "You are a professional document editor. Return only the rewritten text."
        user   = _build_prompt(self._rewrite_tmpl, heading, original_text,
                               reference_text, context_note)
        return self._chat(self._models["rewrite"], system, user).strip()


# ── Anthropic ──────────────────────────────────────────────────────────────────

class AnthropicProvider(BaseAIProvider):
    def __init__(self, api_key: str = "") -> None:
        import anthropic
        key = api_key.strip() or os.environ.get("ANTHROPIC_API_KEY", "")
        if not key:
            raise ValueError("No Anthropic API key provided. Enter your key in the sidebar.")
        self._client = anthropic.Anthropic(api_key=key)
        self._models = PROVIDER_MODELS[AIProvider.ANTHROPIC]
        self._classify_tmpl = _load_prompt("classify.txt")
        self._rewrite_tmpl  = _load_prompt("rewrite.txt")

    def _message(self, model: str, system: str, user: str) -> str:
        response = self._client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        return response.content[0].text

    def classify(self, heading, original_text, reference_text, context_note):
        system = "You are a precise document reviewer. Always respond with valid JSON only."
        user   = _build_prompt(self._classify_tmpl, heading, original_text,
                               reference_text, context_note)
        raw = self._message(self._models["classify"], system, user)
        return _parse_classify_response(raw)

    def rewrite(self, heading, original_text, reference_text, context_note):
        system = "You are a professional document editor. Return only the rewritten text."
        user   = _build_prompt(self._rewrite_tmpl, heading, original_text,
                               reference_text, context_note)
        return self._message(self._models["rewrite"], system, user).strip()


# ── Azure OpenAI (Copilot) ─────────────────────────────────────────────────────

class AzureOpenAIProvider(BaseAIProvider):
    def __init__(self) -> None:
        from openai import AzureOpenAI
        self._client = AzureOpenAI(
            api_key=os.environ["AZURE_OPENAI_API_KEY"],
            azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
            api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
        )
        self._models = PROVIDER_MODELS[AIProvider.AZURE_OPENAI]
        self._classify_tmpl = _load_prompt("classify.txt")
        self._rewrite_tmpl  = _load_prompt("rewrite.txt")

    def _chat(self, deployment: str, system: str, user: str) -> str:
        response = self._client.chat.completions.create(
            model=deployment,
            messages=[
                {"role": "system", "content": system},
                {"role": "user",   "content": user},
            ],
        )
        return response.choices[0].message.content or ""

    def classify(self, heading, original_text, reference_text, context_note):
        system = "You are a precise document reviewer. Always respond with valid JSON only."
        user   = _build_prompt(self._classify_tmpl, heading, original_text,
                               reference_text, context_note)
        raw = self._chat(self._models["classify"], system, user)
        return _parse_classify_response(raw)

    def rewrite(self, heading, original_text, reference_text, context_note):
        system = "You are a professional document editor. Return only the rewritten text."
        user   = _build_prompt(self._rewrite_tmpl, heading, original_text,
                               reference_text, context_note)
        return self._chat(self._models["rewrite"], system, user).strip()


# ── Factory ────────────────────────────────────────────────────────────────────

_REGISTRY: dict[AIProvider, type[BaseAIProvider]] = {
    AIProvider.GEMINI:       GeminiProvider,
    AIProvider.OPENAI:       OpenAIProvider,
    AIProvider.ANTHROPIC:    AnthropicProvider,
    AIProvider.AZURE_OPENAI: AzureOpenAIProvider,
}


def get_provider(provider: AIProvider, api_key: str = "") -> BaseAIProvider:
    cls = _REGISTRY.get(provider)
    if cls is None:
        raise ValueError(f"Unknown provider: {provider}")
    if provider == AIProvider.AZURE_OPENAI:
        return cls()
    return cls(api_key=api_key)


# ── Boilerplate detection (no API call) ────────────────────────────────────────

_BOILERPLATE_HEADINGS = {
    "table of contents", "contents", "copyright", "legal", "disclaimer",
    "page", "header", "footer", "revision history", "document control",
}

def _is_boilerplate(section: Section) -> bool:
    heading_lower = section.heading.lower()
    if any(kw in heading_lower for kw in _BOILERPLATE_HEADINGS):
        return True
    if len(section.original_text.strip()) < 60:
        return True
    return False


# ── Document processing pipeline ───────────────────────────────────────────────

def process_document(
    sections: list[Section],
    reference_text: str,
    context_note: str,
    provider: AIProvider,
    api_key: str = "",
) -> Generator[tuple[str, str], None, None]:
    """
    Run the two-pass AI pipeline over all sections.
    Yields (phase, message) tuples for the UI to display.
      phase = "classify" | "rewrite" | "summary" | "done"
    Mutates each Section in-place (change_type, proposed_text, classify_reason).
    """
    ai = get_provider(provider, api_key=api_key)
    total = len(sections)
    flagged: list[Section] = []

    # Pass 1 — classify
    for i, section in enumerate(sections, 1):
        if _is_boilerplate(section):
            section.change_type = ChangeType.NO_CHANGE
            section.classify_reason = "Skipped — boilerplate or structural element."
            section.processing_failed = False
            yield ("classify", f"{i} / {total} — skipped: *{section.heading}*")
            continue

        yield ("classify", f"{i} / {total} — *{section.heading}*")
        try:
            change_type, reason = _with_retry(
                lambda s=section: ai.classify(s.heading, s.original_text, reference_text, context_note)
            )
            section.change_type = change_type
            section.classify_reason = reason
            section.processing_failed = False
            if change_type != ChangeType.NO_CHANGE:
                flagged.append(section)
        except Exception as exc:
            section.processing_failed = True
            section.change_type = ChangeType.NO_CHANGE
            section.classify_reason = f"Could not analyze — {_section_error_label(exc)}"
            yield ("error", f"{i} / {total} — failed: *{section.heading}*")

    failed_count = sum(1 for s in sections if s.processing_failed)
    no_change_count = total - len(flagged) - failed_count

    if flagged:
        summary = f"{len(flagged)} section(s) flagged · {no_change_count} unchanged"
        if failed_count:
            summary += f" · ⚠️ {failed_count} failed"
        yield ("summary", summary)
    else:
        if failed_count:
            yield ("summary", f"⚠️ {failed_count} section(s) could not be analyzed. All others are up to date.")
        else:
            yield ("summary", "All sections are already up to date — no rewrites needed.")
        yield ("done", "")
        return

    # Pass 2 — rewrite
    for i, section in enumerate(flagged, 1):
        yield ("rewrite", f"{i} / {len(flagged)} — *{section.heading}*")
        try:
            proposed = _with_retry(
                lambda s=section: ai.rewrite(s.heading, s.original_text, reference_text, context_note)
            )
            section.proposed_text = proposed
            section.processing_failed = False
        except Exception as exc:
            section.processing_failed = True
            section.proposed_text = None
            yield ("error", f"{i} / {len(flagged)} — rewrite failed: *{section.heading}*")

    yield ("done", "")
