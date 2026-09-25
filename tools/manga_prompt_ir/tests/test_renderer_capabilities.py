from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.renderer_capabilities import (  # noqa: E402
    RendererCapabilityError,
    lookup_renderer_capability,
    resolve_renderer_capability_key,
)


def test_capability_keys_are_model_profile_not_transport() -> None:
    assert resolve_renderer_capability_key(provider="openai", model="gpt-image-2") == "gpt_image_2"
    assert (
        resolve_renderer_capability_key(
            provider="openrouter",
            model="openai/gpt-image-2",
            profile="gpt_image_2",
        )
        == "gpt_image_2"
    )
    assert (
        resolve_renderer_capability_key(
            provider="openrouter",
            model="google/gemini-3.1-flash-image",
            profile="nano_banana_2",
        )
        == "nano_banana_2"
    )
    assert resolve_renderer_capability_key(provider="grok", model="grok-imagine-image-2.0") == "grok_imagine_2"
    assert resolve_renderer_capability_key(provider="grok_pro", model="v2") == "grok_imagine_2"
    assert resolve_renderer_capability_key(provider="novelai", model="v5-full") == "novelai_v5"
    assert resolve_renderer_capability_key(provider="novelai", model="nai-diffusion-5-full") == "novelai_v5"


def test_unregistered_models_stop() -> None:
    with pytest.raises(RendererCapabilityError, match="未登録"):
        resolve_renderer_capability_key(provider="openrouter", model="unknown-flux")
    with pytest.raises(RendererCapabilityError, match="未登録"):
        resolve_renderer_capability_key(provider="openai", model="gpt-image-1.5")
    with pytest.raises(RendererCapabilityError, match="未登録"):
        resolve_renderer_capability_key(provider="grok", model="grok-imagine-image")
    with pytest.raises(RendererCapabilityError, match="未登録"):
        resolve_renderer_capability_key(provider="grok", model="standard")
    with pytest.raises(RendererCapabilityError, match="未登録"):
        resolve_renderer_capability_key(provider="novelai", model="nai-diffusion-4-5-full")
    with pytest.raises(RendererCapabilityError, match="未登録"):
        lookup_renderer_capability("not_a_key")
    with pytest.raises(RendererCapabilityError, match="resolved model"):
        resolve_renderer_capability_key(provider="openrouter")


def test_strong_flags_are_provisional() -> None:
    for key in ("gpt_image_2", "grok_imagine_2", "nano_banana_2"):
        caps = lookup_renderer_capability(key)
        assert caps["provisional"] is True
        assert caps["supports_japanese_text"] == "strong"
        assert caps["postprocess_recommended"] is False
    novelai = lookup_renderer_capability("novelai_v5")
    assert novelai["postprocess_recommended"] is True
    assert novelai["provisional"] is False
