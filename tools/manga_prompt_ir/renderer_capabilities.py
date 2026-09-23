"""Renderer capability flags keyed by resolved model/profile.

OpenRouter is a transport. Strategy is chosen from the capability table, not
from `if provider == "novelai"` alone. Values marked provisional are not
measured fixtures.

NovelAI aliases `v5` / `v5-full` / `nai-v5-full` / `v5-curated` resolve to
`nai-diffusion-5-*` and then to `novelai_v5`. `nai-diffusion-4-5-*` is not a
V5 alias.
"""

from __future__ import annotations

from typing import Any

BUBBLE_FRAME_MODES = ("provider", "local")

RENDERER_CAPABILITIES: dict[str, dict[str, Any]] = {
    "gpt_image_2": {
        "supports_native_bubbles": "native",
        "supports_japanese_text": "strong",
        "supports_vertical_text": "strong",
        "supports_bubble_tail_control": "strong",
        "postprocess_recommended": False,
        "supports_provider_inpaint": False,
        "provisional": True,
    },
    "grok_imagine_2": {
        "supports_native_bubbles": "native",
        "supports_japanese_text": "strong",
        "supports_vertical_text": "strong",
        "supports_bubble_tail_control": "strong",
        "postprocess_recommended": False,
        "supports_provider_inpaint": False,
        "provisional": True,
    },
    "nano_banana_2": {
        "supports_native_bubbles": "native",
        "supports_japanese_text": "strong",
        "supports_vertical_text": "strong",
        "supports_bubble_tail_control": "strong",
        "postprocess_recommended": False,
        "supports_provider_inpaint": False,
        "provisional": True,
    },
    "novelai_v5": {
        "supports_native_bubbles": "unstable",
        "supports_japanese_text": "limited",
        "supports_vertical_text": "limited",
        "supports_bubble_tail_control": "moderate",
        "postprocess_recommended": True,  # local 枠が使える印。既定経路は letter_later 空泡。
        "supports_provider_inpaint": False,
        "provisional": False,
    },
}

# Compiler-only fallbacks when the caller has not yet resolved a model.
# Batch must pass the merged model instead of relying on these.
PROVIDER_DEFAULT_MODELS = {
    "openai": "gpt-image-2",
    "grok": "grok-imagine-image-2.0",
    "grok_pro": "grok-imagine-image-2.0",
    "novelai": "nai-diffusion-5-full",
}

NOVELAI_V5_ALIASES = {
    "v5": "nai-diffusion-5-full",
    "v5-full": "nai-diffusion-5-full",
    "nai-v5-full": "nai-diffusion-5-full",
    "v5-curated": "nai-diffusion-5-curated",
    "nai-v5-curated": "nai-diffusion-5-curated",
}

GROK_IMAGINE_2_ALIASES = {
    "v2": "grok-imagine-image-2.0",
    "imagine2": "grok-imagine-image-2.0",
}

MODEL_TO_CAPABILITY = {
    "gpt-image-2": "gpt_image_2",
    "openai/gpt-image-2": "gpt_image_2",
    "grok-imagine-image-2.0": "grok_imagine_2",
    "nai-diffusion-5-full": "novelai_v5",
    "nai-diffusion-5-curated": "novelai_v5",
    "nai-diffusion-5-full-inpainting": "novelai_v5",
    "nai-diffusion-5-curated-inpainting": "novelai_v5",
    "google/gemini-3.1-flash-image": "nano_banana_2",
    "google/gemini-3.1-flash-image-preview": "nano_banana_2",
}

PROFILE_TO_CAPABILITY = {
    "gpt_image_2": "gpt_image_2",
    "nano_banana_2": "nano_banana_2",
    "nano_banana_2_preview": "nano_banana_2",
    "grok_imagine_2": "grok_imagine_2",
    "novelai_v5": "novelai_v5",
}


class RendererCapabilityError(ValueError):
    """Unknown or unverified renderer capability."""


def _normalize_token(value: str | None) -> str:
    return str(value or "").strip()


def canonicalize_resolved_model(provider: str, model: str | None) -> str:
    name = _normalize_token(provider).lower()
    token = _normalize_token(model)
    if name == "novelai" and token in NOVELAI_V5_ALIASES:
        return NOVELAI_V5_ALIASES[token]
    if name in {"grok", "grok_pro"} and token in GROK_IMAGINE_2_ALIASES:
        return GROK_IMAGINE_2_ALIASES[token]
    if token.endswith("-inpainting") and token[: -len("-inpainting")] in MODEL_TO_CAPABILITY:
        return token
    return token


def resolve_renderer_capability_key(
    *,
    provider: str,
    model: str | None = None,
    profile: str | None = None,
) -> str:
    name = _normalize_token(provider).lower()
    profile_id = _normalize_token(profile)
    if profile_id:
        key = PROFILE_TO_CAPABILITY.get(profile_id)
        if key is None:
            raise RendererCapabilityError(
                f"未登録・未検証の capability profile です: {profile_id}"
            )
        return key

    token = canonicalize_resolved_model(name, model)
    if not token:
        token = PROVIDER_DEFAULT_MODELS.get(name, "")
    if not token:
        raise RendererCapabilityError(
            f"resolved model/profile が必要です: provider={provider}"
        )
    key = MODEL_TO_CAPABILITY.get(token)
    if key is None:
        raise RendererCapabilityError(
            f"未登録・未検証の model です: provider={provider} model={token}"
        )
    return key


def lookup_renderer_capability(key: str) -> dict[str, Any]:
    record = RENDERER_CAPABILITIES.get(str(key or "").strip())
    if record is None:
        raise RendererCapabilityError(f"未登録の renderer capability です: {key}")
    return dict(record)
