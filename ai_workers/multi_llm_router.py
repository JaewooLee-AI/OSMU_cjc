"""Instantiates the configured LLM vendor client and routes prompts to it.

Ported from OSMU_admin/ai_workers/multi_llm_router.py. Two substantive
changes for this build:

1. Configuration reads from SQLite (`core.repo`) instead of Supabase.
2. Every call reports back real token usage from the provider response
   (OpenAI `usage`, Anthropic `usage`, Gemini `usage_metadata`) into
   `usage_log`, so the token-minimization work in ai_workers/vision.py is
   measured rather than assumed. Providers that omit usage fall back to a
   conservative character-based estimate.
"""
from __future__ import annotations

from typing import Optional, Tuple

from core import repo
from core.crypto_utils import decrypt_api_key

VENDORS = {
    "google": {
        "label": "Google Gemini",
        "icon": "✨",
        "default_model": "gemini-2.5-flash",
        "supports_vision": True,
        "note": "이미지 분석 기본 벤더 — 이미지 토큰 단가가 가장 낮습니다.",
    },
    "openai": {
        "label": "OpenAI",
        "icon": "🤖",
        "default_model": "gpt-4o-mini",
        "supports_vision": True,
    },
    "anthropic": {
        "label": "Anthropic",
        "icon": "🧠",
        "default_model": "claude-sonnet-4-5",
        "supports_vision": True,
    },
}

# Korean averages roughly 2 characters per token across these tokenizers —
# only used when a provider doesn't return usage metadata.
_CHARS_PER_TOKEN = 2.0


def vision_capable_vendors() -> list:
    return [k for k, spec in VENDORS.items() if spec.get("supports_vision")]


def get_configured_vendor() -> str:
    """The single vendor the admin chose for writing/auditing content
    (Settings page -> brand_kit.default_generation_vendor). Every pipeline
    calls this instead of hardcoding a vendor, so switching models is a
    one-click admin action with no silent fallback to an unintended model."""
    brand_kit = repo.get_brand_kit()
    vendor = brand_kit.get("default_generation_vendor")
    if not vendor:
        raise RuntimeError("기본 생성 모델이 지정되지 않았습니다. ⚙️ 설정 페이지에서 먼저 지정하세요.")

    setting = repo.get_llm_setting(vendor)
    if not setting or not setting.get("is_active"):
        raise RuntimeError(f"지정된 기본 생성 모델('{vendor}')이 비활성 상태이거나 등록되어 있지 않습니다.")
    return vendor


def get_vision_vendor() -> str:
    """Vision can run on a different (cheaper) vendor than the writing model —
    that separation is itself a cost lever, since captioning is a small,
    high-volume task while drafting is a large, low-volume one. Falls back to
    the generation vendor when the admin hasn't picked one."""
    brand_kit = repo.get_brand_kit()
    vendor = brand_kit.get("vision_vendor")
    if vendor:
        setting = repo.get_llm_setting(vendor)
        if setting and setting.get("is_active"):
            return vendor
    return get_configured_vendor()


def test_connection(vendor: str, model_name: str, api_key: str) -> Tuple[bool, str]:
    """Sends a minimal 'Hello' prompt to verify the key/model combo works."""
    try:
        if vendor == "openai":
            from openai import OpenAI

            client = OpenAI(api_key=api_key)
            client.chat.completions.create(
                model=model_name,
                messages=[{"role": "user", "content": "Hello"}],
                max_tokens=5,
            )
        elif vendor == "anthropic":
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)
            client.messages.create(
                model=model_name,
                max_tokens=5,
                messages=[{"role": "user", "content": "Hello"}],
            )
        elif vendor == "google":
            from google import genai
            from google.genai import types

            client = genai.Client(api_key=api_key)
            client.models.generate_content(
                model=model_name,
                contents="Hello",
                config=types.GenerateContentConfig(max_output_tokens=5),
            )
        else:
            return False, f"Unsupported vendor: {vendor}"
        return True, "연결 정상"
    except Exception as exc:  # surfaced directly to the admin in the UI
        return False, str(exc)


def load_vendor_config(vendor: str) -> Tuple[str, str]:
    setting = repo.get_llm_setting(vendor)
    if not setting:
        raise RuntimeError(f"'{vendor}' 벤더의 설정이 없습니다. ⚙️ 설정 페이지에서 먼저 등록하세요.")
    api_key = decrypt_api_key(setting["encrypted_api_key"])
    return setting["model_name"], api_key


def _estimate_tokens(text: str) -> int:
    return int(len(text or "") / _CHARS_PER_TOKEN)


def generate_text(
    vendor: str,
    prompt: str,
    system: Optional[str] = None,
    max_tokens: int = 2000,
    note: Optional[str] = None,
) -> str:
    """Routes a prompt to the configured vendor and returns the text response.
    Records real token usage against `usage_log`."""
    model_name, api_key = load_vendor_config(vendor)
    text, usage_in, usage_out = "", 0, 0

    if vendor == "openai":
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        res = client.chat.completions.create(model=model_name, messages=messages, max_tokens=max_tokens)
        text = res.choices[0].message.content or ""
        if getattr(res, "usage", None):
            usage_in, usage_out = res.usage.prompt_tokens, res.usage.completion_tokens

    elif vendor == "anthropic":
        from anthropic import Anthropic

        client = Anthropic(api_key=api_key)
        kwargs = {"model": model_name, "max_tokens": max_tokens, "messages": [{"role": "user", "content": prompt}]}
        if system:
            kwargs["system"] = system
        res = client.messages.create(**kwargs)
        text = "".join(block.text for block in res.content if hasattr(block, "text"))
        if getattr(res, "usage", None):
            usage_in, usage_out = res.usage.input_tokens, res.usage.output_tokens

    elif vendor == "google":
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        # Without an explicit config, generate_content ignores max_tokens
        # entirely and falls back to the model's own (much larger) default —
        # every caller's cost ceiling would silently be a no-op for Gemini.
        config = types.GenerateContentConfig(max_output_tokens=max_tokens)
        if system:
            config.system_instruction = system
        res = client.models.generate_content(model=model_name, contents=prompt, config=config)
        text = res.text or ""
        meta = getattr(res, "usage_metadata", None)
        if meta:
            usage_in = getattr(meta, "prompt_token_count", 0) or 0
            usage_out = getattr(meta, "candidates_token_count", 0) or 0

    else:
        raise ValueError(f"Unsupported vendor: {vendor}")

    if not usage_in:
        usage_in = _estimate_tokens((system or "") + prompt)
    if not usage_out:
        usage_out = _estimate_tokens(text)

    repo.log_usage(
        kind="text",
        vendor=vendor,
        model=model_name,
        est_input_tokens=usage_in,
        est_output_tokens=usage_out,
        note=note,
    )
    return text


_EMBEDDING_DIMENSIONS = 1536


def generate_embedding(vendor: str, text: str) -> list:
    """Vector embedding, kept for parity with the original RAG path.

    Embeddings are a distinct endpoint, not a capability every chat model
    exposes (Anthropic has no embedding API at all), so this routes per
    vendor rather than assuming OpenAI regardless of what's configured.
    """
    if vendor == "openai":
        _model, api_key = load_vendor_config("openai")
        from openai import OpenAI

        client = OpenAI(api_key=api_key)
        res = client.embeddings.create(model="text-embedding-3-small", input=text)
        return res.data[0].embedding

    if vendor == "google":
        _model, api_key = load_vendor_config("google")
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=api_key)
        res = client.models.embed_content(
            model="gemini-embedding-001",
            contents=text,
            config=types.EmbedContentConfig(output_dimensionality=_EMBEDDING_DIMENSIONS),
        )
        return res.embeddings[0].values

    raise ValueError(f"Embeddings are not supported for vendor: {vendor}")
