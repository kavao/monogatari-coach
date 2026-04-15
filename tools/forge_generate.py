#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画像生成クライアント（Forge / NovelAI）。

- provider=forge:
  - POST /sdapi/v1/txt2img（save_images は使わず、返却 base64 を自前保存）
- provider=novelai:
  - POST /ai/generate-image（Bearer token は .env の NOVELAI_ACCESS_TOKEN を使用）
  - zip 応答を展開して PNG を保存
- provider=grok:
  - POST /v1/images/generations（Bearer token は .env の XAI_API_KEY を使用）
  - `b64_json` または URL 応答を保存

設定は config/image_generation.json（既定・必須。`--config` で別パスも可）。
仕様・運用: .rulesync/skills/forge-txt2img/SKILL.md
"""

from __future__ import annotations

import argparse
import base64
import io
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PROVIDER_CHOICES = ("forge", "novelai", "grok")
FORGE_MODEL_FAMILY_ENV = "MONOCRI_FORGE_MODEL_FAMILY_DEFAULT"
GROK_MODEL_TIER_ENV = "MONOCRI_GROK_MODEL_TIER_DEFAULT"


# NovelAI nai-diffusion-4 / 4.5 系の UC プリセット文字列（参考用）。
_UC_V45_CURATED: dict[int, str] = {
    3: "",
    4: (
        "blurry, lowres, upscaled, artistic error, film grain, scan artifacts, "
        "worst quality, bad quality, jpeg artifacts, very displeasing, chromatic aberration, halftone, "
        "multiple views, logo, too many watermarks, negative space, blank page"
    ),
    5: (
        "blurry, lowres, upscaled, artistic error, scan artifacts, jpeg artifacts, logo, "
        "too many watermarks, negative space, blank page"
    ),
    6: (
        "blurry, lowres, upscaled, artistic error, film grain, scan artifacts, "
        "bad anatomy, bad hands, worst quality, bad quality, jpeg artifacts, very displeasing, "
        "chromatic aberration, halftone, multiple views, logo, too many watermarks, @_@, mismatched pupils, "
        "glowing eyes, negative space, blank page"
    ),
    7: (
        "nsfw, {worst quality}, distracting watermark, unfinished, bad quality, "
        "{widescreen}, upscale, {sequence}, {{grandfathered content}}, blurred foreground, chromatic aberration, "
        "sketch, everyone, [sketch background], simple, [flat colors], ych (character), outline, multiple scenes, "
        "[[horror (theme)]], comic"
    ),
}
_UC_V45_FULL: dict[int, str] = {
    3: "",
    4: (
        "nsfw, lowres, artistic error, film grain, scan artifacts, worst quality, "
        "bad quality, jpeg artifacts, very displeasing, chromatic aberration, dithering, halftone, screentone, "
        "multiple views, logo, too many watermarks, negative space, blank page"
    ),
    5: (
        "nsfw, lowres, artistic error, scan artifacts, worst quality, bad quality, "
        "jpeg artifacts, multiple views, very displeasing, too many watermarks, negative space, blank page"
    ),
    6: (
        "nsfw, lowres, artistic error, film grain, scan artifacts, worst quality, "
        "bad quality, jpeg artifacts, very displeasing, chromatic aberration, dithering, halftone, screentone, "
        "multiple views, logo, too many watermarks, negative space, blank page, @_@, mismatched pupils, "
        "glowing eyes, bad anatomy"
    ),
    7: _UC_V45_CURATED[7],
}
_UC_V4_CURATED: dict[int, str] = {
    3: "",
    4: (
        "blurry, lowres, error, film grain, scan artifacts, worst quality, bad quality, "
        "jpeg artifacts, very displeasing, chromatic aberration, logo, dated, signature, multiple views, "
        "gigantic breasts, white blank page, blank page"
    ),
    5: (
        "blurry, lowres, error, worst quality, bad quality, jpeg artifacts, "
        "very displeasing, logo, dated, signature"
    ),
}
_UC_V4_FULL: dict[int, str] = {
    3: "",
    4: (
        "nsfw, blurry, lowres, error, film grain, scan artifacts, worst quality, "
        "bad quality, jpeg artifacts, very displeasing, chromatic aberration, multiple views, logo, "
        "too many watermarks, white blank page, blank page"
    ),
    5: (
        "nsfw, blurry, lowres, error, worst quality, bad quality, jpeg artifacts, "
        "very displeasing, white blank page, blank page"
    ),
}


def _novelai_is_diffusion_v4_family(model_id: str) -> bool:
    return "nai-diffusion-4" in model_id


def _novelai_uc_table(model_id: str) -> dict[int, str]:
    if "nai-diffusion-4-5-curated" in model_id:
        return _UC_V45_CURATED
    if "nai-diffusion-4-5-full" in model_id:
        return _UC_V45_FULL
    if "nai-diffusion-4-full" in model_id:
        return _UC_V4_FULL
    if "nai-diffusion-4" in model_id:
        return _UC_V4_CURATED
    return {}


def _novelai_effective_uc_preset(model_id: str, uc_preset: int) -> int:
    """明示値を優先し、未指定や不正値だけ安全側の 0 に寄せる。"""
    if uc_preset < 0:
        return 0
    return uc_preset


def _novelai_resolve_uc_string(model_id: str, uc_preset: int) -> str:
    table = _novelai_uc_table(model_id)
    if not table:
        return ""
    ucp = _novelai_effective_uc_preset(model_id, uc_preset)
    if ucp not in table:
        ucp = 4 if 4 in table else 3
    return table.get(ucp, "")


def _novelai_combine_uc(model_id: str, uc_preset: int, user_negative: str) -> str:
    base = _novelai_resolve_uc_string(model_id, uc_preset)
    user = (user_negative or "").strip()
    if base and user:
        return f"{base}, {user}"
    return base or user


def _novelai_augment_prompt(model_id: str, prompt: str) -> str:
    """novelai_api HighLevel.generate_image に合わせた品質接尾辞。"""
    if "nai-diffusion-4-5-curated" in model_id:
        return (
            f"{prompt}, very aesthetic, location, masterpiece, no text, "
            f"-0.8::feet::, rating:general"
        )
    if "nai-diffusion-4-5-full" in model_id:
        return f"{prompt}, location, very aesthetic, masterpiece, no text"
    if "nai-diffusion-4-full" in model_id:
        return f"{prompt}, no text, best quality, very aesthetic, absurdres"
    if _novelai_is_diffusion_v4_family(model_id):
        return f"{prompt}, rating:general, best quality, very aesthetic, absurdres"
    return prompt


API_404_HINT = """\
A1111 互換 REST API (/sdapi/v1/...) が応答しません (HTTP 404)。
Gradio の UI 用 URL「Running on http://127.0.0.1:7860」だけでは、/sdapi が無効なことがあります。

対処: Forge / WebUI を --api 付きで再起動してください。
  例: webui-user.bat 内で set COMMANDLINE_ARGS=--api
  または launch 時に  webui.py --api --listen

確認: ブラウザで http://127.0.0.1:7860/docs を開き、/sdapi/v1/txt2img が列挙されているか見る。
"""


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def append_log(log_path: Path, message: str) -> None:
    log_path.parent.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    with open(log_path, "a", encoding="utf-8") as f:
        f.write(f"[{ts}] {message}\n")


def load_dotenv(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if not path.is_file():
        return env
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value.startswith(("'", '"')) and value.endswith(("'", '"')) and len(value) >= 2:
            value = value[1:-1]
        env[key] = value
    return env


def resolve_env_value(name: str, dotenv_map: dict[str, str]) -> str | None:
    value = os.environ.get(name)
    if value:
        return value
    value = dotenv_map.get(name)
    if value:
        return value
    return None


def load_root_config(path: Path) -> dict[str, Any]:
    raw = load_json(path)
    if "providers" in raw:
        return raw
    return {"default_provider": "forge", "providers": {"forge": raw}}


def apply_forge_model_preset(provider_cfg: dict[str, Any]) -> dict[str, Any]:
    out = dict(provider_cfg)
    presets = out.get("presets")
    if not isinstance(presets, dict) or not presets:
        return out
    family = str(out.get("active_model_family", "sdxl")).lower()
    key = "flux" if family in ("flux", "flux.1", "flux1") else "sdxl"
    preset = presets.get(key) or presets.get("sdxl") or {}
    for k, v in preset.items():
        if not isinstance(k, str):
            continue
        if k.startswith("_") or k in ("comment", "description"):
            continue
        out[k] = v
    return out


def normalize_forge_family(raw_value: Any, *, source: str) -> str:
    family = str(raw_value).strip().lower()
    if family in ("flux", "flux.1", "flux1"):
        return "flux"
    if family == "sdxl":
        return "sdxl"
    raise ValueError(f"{source} の Forge モデル族 {raw_value!r} は未対応です。available: sdxl, flux")


def normalize_grok_model_tier(raw_value: Any, *, source: str) -> str:
    tier = str(raw_value).strip().lower()
    if tier in ("standard", "std", "default", "normal"):
        return "standard"
    if tier in ("pro",):
        return "pro"
    raise ValueError(f"{source} の Grok モデル種別 {raw_value!r} は未対応です。available: standard, pro")


def apply_provider_env_overrides(
    provider: str,
    provider_cfg: dict[str, Any],
    dotenv_map: dict[str, str],
) -> dict[str, Any]:
    out = dict(provider_cfg)
    if provider == "forge":
        raw_family = resolve_env_value(FORGE_MODEL_FAMILY_ENV, dotenv_map)
        if raw_family:
            out["active_model_family"] = normalize_forge_family(
                raw_family,
                source=f".env/{FORGE_MODEL_FAMILY_ENV}",
            )
        return apply_forge_model_preset(out)

    if provider == "grok":
        raw_tier = resolve_env_value(GROK_MODEL_TIER_ENV, dotenv_map)
        if not raw_tier:
            return out
        tier = normalize_grok_model_tier(
            raw_tier,
            source=f".env/{GROK_MODEL_TIER_ENV}",
        )
        aliases = out.get("model_aliases")
        if isinstance(aliases, dict):
            alias_model = aliases.get(tier)
            if alias_model:
                out["default_model"] = str(alias_model)
        out["default_model_tier"] = tier
        return out

    return out


def resolve_provider_name(
    *,
    root_cfg: dict[str, Any],
    args_provider: str | None,
    params_provider: str | None,
) -> str:
    provider = args_provider or params_provider or root_cfg.get("default_provider", "forge")
    return str(provider).strip().lower()


def get_provider_cfg(
    root_cfg: dict[str, Any],
    provider: str,
    *,
    dotenv_map: dict[str, str] | None = None,
) -> dict[str, Any]:
    providers = root_cfg.get("providers") or {}
    if provider not in providers:
        raise KeyError(
            f"provider {provider!r} が config にありません。available: {sorted(providers.keys())}"
        )
    cfg = dict(providers[provider])
    return apply_provider_env_overrides(provider, cfg, dotenv_map or {})


def resolve_named_value(
    raw_value: Any,
    presets: dict[str, Any] | None,
) -> Any:
    if not isinstance(raw_value, str) or not isinstance(presets, dict):
        return raw_value
    return presets.get(raw_value, raw_value)


def forge_family_key(provider_cfg: dict[str, Any]) -> str:
    family = str(provider_cfg.get("active_model_family", "sdxl")).lower()
    return "flux" if family in ("flux", "flux.1", "flux1") else "sdxl"


def resolve_forge_dimensions(
    provider_cfg: dict[str, Any],
    params: dict[str, Any],
) -> tuple[int, int]:
    if "width" in params or "height" in params:
        return (
            int(params.get("width", provider_cfg["default_width"])),
            int(params.get("height", provider_cfg["default_height"])),
        )

    raw_preset = params.get("aspect_ratio_preset", params.get("aspect_ratio"))
    if raw_preset is None:
        return int(provider_cfg["default_width"]), int(provider_cfg["default_height"])
    if str(raw_preset) == "auto":
        return int(provider_cfg["default_width"]), int(provider_cfg["default_height"])

    presets = provider_cfg.get("aspect_ratio_presets")
    if not isinstance(presets, dict):
        return int(provider_cfg["default_width"]), int(provider_cfg["default_height"])
    family_presets = presets.get(forge_family_key(provider_cfg))
    if not isinstance(family_presets, dict):
        return int(provider_cfg["default_width"]), int(provider_cfg["default_height"])
    resolved = resolve_named_value(raw_preset, family_presets)
    if isinstance(resolved, dict) and "width" in resolved and "height" in resolved:
        return int(resolved["width"]), int(resolved["height"])
    raise ValueError(
        f"Forge の aspect_ratio_preset が不明です: {raw_preset!r}。"
        f"available: {sorted(family_presets.keys())}"
    )


def check_a1111_api_ready(base_url: str, timeout: float) -> None:
    url = base_url.rstrip("/") + "/sdapi/v1/samplers"
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=min(20.0, timeout)) as resp:
            if resp.getcode() != 200:
                raise RuntimeError(f"GET /sdapi/v1/samplers が HTTP {resp.getcode()}")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RuntimeError(API_404_HINT) from e
        raise RuntimeError(
            f"GET /sdapi/v1/samplers が HTTP {e.code}: {e.reason}"
        ) from e
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Forge に接続できません ({url})。起動中か base_url を確認: {e}"
        ) from e


def run_probe(provider: str, provider_cfg: dict[str, Any], timeout: float) -> None:
    base_url = str(provider_cfg.get("base_url", "")).rstrip("/")
    print(f"probe: provider={provider} base_url={base_url}")
    if provider == "forge":
        for path in ("/docs", "/sdapi/v1/samplers", "/sdapi/v1/options"):
            url = base_url + path
            try:
                req = urllib.request.Request(url, method="GET")
                with urllib.request.urlopen(req, timeout=min(15.0, timeout)) as resp:
                    print(f"  GET {path} -> HTTP {resp.getcode()} OK")
            except urllib.error.HTTPError as e:
                print(f"  GET {path} -> HTTP {e.code} ({e.reason})")
            except urllib.error.URLError as e:
                print(f"  GET {path} -> URLError: {e}")
        print()
        print(
            "解釈: /sdapi/v1/samplers が 404 のときは --api なし起動の可能性が高い。"
            "200 なら txt2img を POST できる状態に近い。"
        )
        return

    if provider == "novelai":
        print(
            "NovelAI は公開 health endpoint 前提にしていないため、"
            "dry-run または実際の生成で疎通確認してください。"
        )
        generate_path = str(provider_cfg.get("generate_path", "/ai/generate-image"))
        print(f"  configured generate_path={generate_path}")
        return

    if provider == "grok":
        print(
            "Grok / xAI Images API は probe 用の専用 health endpoint を前提にしていないため、"
            "dry-run または実際の生成で疎通確認してください。"
        )
        generate_path = str(provider_cfg.get("generate_path", "/images/generations"))
        print(f"  configured generate_path={generate_path}")
        return

    raise ValueError(f"未対応 provider: {provider}")


def http_post_json(
    url: str,
    payload: dict[str, Any],
    timeout: float,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    body = json.dumps(payload).encode("utf-8")
    req_headers = {"Content-Type": "application/json"}
    if headers:
        req_headers.update(headers)
    req = urllib.request.Request(url, data=body, method="POST", headers=req_headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        code = resp.getcode()
        raw = resp.read()
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
    return code, raw, hdrs


def http_get_bytes(
    url: str,
    timeout: float,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[int, bytes, dict[str, str]]:
    req = urllib.request.Request(url, method="GET", headers=headers or {})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        code = resp.getcode()
        raw = resp.read()
        hdrs = {k.lower(): v for k, v in resp.headers.items()}
    return code, raw, hdrs


def validate_sampler(name: str, allowed: list[str]) -> None:
    if allowed and name not in allowed:
        raise ValueError(
            f"sampler_name が許可リストにありません: {name!r}。allowed: {allowed}"
        )


def merge_provider_defaults(
    provider: str,
    provider_cfg: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    width_default = provider_cfg["default_width"]
    height_default = provider_cfg["default_height"]
    if provider == "forge":
        width_default, height_default = resolve_forge_dimensions(provider_cfg, params)
    out = {
        "provider": provider,
        "prompt": params.get("prompt", ""),
        "negative_prompt": params.get("negative_prompt", ""),
        "seed": params.get("seed"),
        "width": int(params.get("width", width_default)),
        "height": int(params.get("height", height_default)),
        "steps": int(params.get("steps", provider_cfg["default_steps"])),
        "cfg_scale": float(params.get("cfg_scale", provider_cfg["default_cfg_scale"])),
        "sampler_name": params.get(
            "sampler_name", provider_cfg["default_sampler_name"]
        ),
        "output_dir": params.get("output_dir", ""),
        "file_prefix": params.get("file_prefix", provider),
        "count": int(params.get("count", 1)),
    }
    if provider == "forge":
        if "scheduler" in params or "default_scheduler" in provider_cfg:
            sched = params.get("scheduler", provider_cfg.get("default_scheduler"))
            if sched is not None:
                out["scheduler"] = str(sched)
        if "distilled_cfg_scale" in params or "default_distilled_cfg_scale" in provider_cfg:
            dcfg = params.get(
                "distilled_cfg_scale",
                provider_cfg.get("default_distilled_cfg_scale"),
            )
            if dcfg is not None:
                out["distilled_cfg_scale"] = float(dcfg)
        return out

    if provider == "novelai":
        out["model"] = params.get("model", provider_cfg["default_model"])
        out["action"] = params.get("action", provider_cfg.get("default_action", "generate"))
        out["uc_preset"] = int(
            params.get("uc_preset", provider_cfg.get("default_uc_preset", 0))
        )
        out["quality_toggle"] = bool(
            params.get(
                "quality_toggle",
                provider_cfg.get("default_quality_toggle", True),
            )
        )
        out["params_version"] = int(
            params.get("params_version", provider_cfg.get("default_params_version", 3))
        )
        out["sm"] = bool(params.get("sm", provider_cfg.get("default_sm", True)))
        out["sm_dyn"] = bool(
            params.get("sm_dyn", provider_cfg.get("default_sm_dyn", True))
        )
        out["cfg_rescale"] = float(
            params.get("cfg_rescale", provider_cfg.get("default_cfg_rescale", 0))
        )
        out["noise_schedule"] = str(
            params.get("noise_schedule", provider_cfg.get("default_noise_schedule", "native"))
        )
        out["dynamic_thresholding"] = bool(
            params.get(
                "dynamic_thresholding",
                provider_cfg.get("default_dynamic_thresholding", False),
            )
        )
        out["add_original_image"] = bool(
            params.get(
                "add_original_image",
                provider_cfg.get("default_add_original_image", False),
            )
        )
        out["controlnet_strength"] = float(
            params.get(
                "controlnet_strength",
                provider_cfg.get("default_controlnet_strength", 1),
            )
        )
        out["normalize_reference_strength_multiple"] = bool(
            params.get(
                "normalize_reference_strength_multiple",
                provider_cfg.get(
                    "default_normalize_reference_strength_multiple", True
                ),
            )
        )
        out["use_coords"] = bool(
            params.get("use_coords", provider_cfg.get("default_use_coords", False))
        )
        out["legacy"] = bool(
            params.get("legacy", provider_cfg.get("default_legacy", False))
        )
        out["legacy_uc"] = bool(
            params.get("legacy_uc", provider_cfg.get("default_legacy_uc", False))
        )
        out["legacy_v3_extend"] = bool(
            params.get(
                "legacy_v3_extend",
                provider_cfg.get("default_legacy_v3_extend", False),
            )
        )
        out["deliberate_euler_ancestral_bug"] = bool(
            params.get(
                "deliberate_euler_ancestral_bug",
                provider_cfg.get("default_deliberate_euler_ancestral_bug", False),
            )
        )
        if "extra_noise_seed" in params:
            out["extra_noise_seed"] = int(params["extra_noise_seed"])
        if "noise_schedule" in params:
            out["noise_schedule"] = str(params["noise_schedule"])
        if "prefer_brownian" in params:
            out["prefer_brownian"] = bool(params["prefer_brownian"])
        if "v4_use_coords" in params:
            out["v4_use_coords"] = bool(params["v4_use_coords"])
        return out

    if provider == "grok":
        out["model"] = params.get("model", provider_cfg["default_model"])
        out["response_format"] = params.get(
            "response_format", provider_cfg.get("default_response_format", "b64_json")
        )
        raw_aspect_ratio = params.get(
            "aspect_ratio_preset",
            params.get("aspect_ratio", provider_cfg.get("default_aspect_ratio", "1:1")),
        )
        out["aspect_ratio"] = str(
            resolve_named_value(
                raw_aspect_ratio,
                provider_cfg.get("aspect_ratio_presets"),
            )
        )
        out["resolution"] = params.get(
            "resolution", provider_cfg.get("default_resolution", "1k")
        )
        return out

    raise ValueError(f"未対応 provider: {provider}")


def build_forge_payload(
    merged: dict[str, Any],
    *,
    seed_for_request: int,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "prompt": merged["prompt"],
        "negative_prompt": merged["negative_prompt"],
        "seed": seed_for_request,
        "steps": merged["steps"],
        "cfg_scale": merged["cfg_scale"],
        "width": merged["width"],
        "height": merged["height"],
        "sampler_name": merged["sampler_name"],
        "batch_size": 1,
        "n_iter": 1,
        "save_images": False,
        "send_images": True,
    }
    if merged.get("scheduler") is not None:
        payload["scheduler"] = merged["scheduler"]
    if merged.get("distilled_cfg_scale") is not None:
        payload["distilled_cfg_scale"] = merged["distilled_cfg_scale"]
    return payload


def build_novelai_payload(
    merged: dict[str, Any],
    *,
    seed_for_request: int,
) -> dict[str, Any]:
    model_id = str(merged["model"])
    uc_eff = _novelai_effective_uc_preset(model_id, int(merged["uc_preset"]))

    parameters: dict[str, Any] = {
        "params_version": merged["params_version"],
        "width": merged["width"],
        "height": merged["height"],
        "scale": merged["cfg_scale"],
        "sampler": merged["sampler_name"],
        "steps": merged["steps"],
        "n_samples": 1,
        "seed": seed_for_request,
        "ucPreset": uc_eff,
        "cfg_rescale": merged["cfg_rescale"],
        "controlnet_strength": merged["controlnet_strength"],
        "dynamic_thresholding": merged["dynamic_thresholding"],
        "legacy": merged["legacy"],
        "legacy_uc": merged["legacy_uc"],
        "legacy_v3_extend": merged["legacy_v3_extend"],
        "qualityToggle": merged["quality_toggle"],
        "negative_prompt": merged["negative_prompt"],
        "noise_schedule": merged["noise_schedule"],
        "sm": merged["sm"],
        "sm_dyn": merged["sm_dyn"],
        "add_original_image": merged["add_original_image"],
        "characterPrompts": [],
        "use_coords": merged["use_coords"],
        "deliberate_euler_ancestral_bug": merged["deliberate_euler_ancestral_bug"],
        "reference_strength_multiple": [],
        "normalize_reference_strength_multiple": merged[
            "normalize_reference_strength_multiple"
        ],
    }
    if "extra_noise_seed" in merged:
        parameters["extra_noise_seed"] = merged["extra_noise_seed"]

    input_text = str(merged["prompt"])
    if _novelai_is_diffusion_v4_family(model_id):
        combined_uc = _novelai_combine_uc(model_id, uc_eff, str(merged["negative_prompt"]))
        parameters["negative_prompt"] = combined_uc
        parameters["uc"] = combined_uc
        # v4.5 既定 preset は karras（novelai_api presets_v45）。config が native のままだと 500 になり得る。
        _ns = str(merged.get("noise_schedule", "karras"))
        if _ns == "native":
            _ns = "karras"
        parameters["noise_schedule"] = _ns
        parameters["prefer_brownian"] = bool(merged.get("prefer_brownian", True))
        augmented = _novelai_augment_prompt(model_id, str(merged["prompt"]))
        input_text = augmented
        parameters["v4_prompt"] = {
            "caption": {
                "base_caption": augmented,
                "char_captions": [],
            },
            "use_coords": bool(merged.get("v4_use_coords", merged["use_coords"])),
            "use_order": True,
        }
        parameters["v4_negative_prompt"] = {
            "caption": {"base_caption": combined_uc, "char_captions": []}
        }

    return {
        "input": input_text,
        "model": model_id,
        "action": merged["action"],
        "parameters": parameters,
    }


def build_grok_payload(merged: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": merged["model"],
        "prompt": merged["prompt"],
        "n": merged["count"],
        "response_format": merged["response_format"],
    }
    if merged.get("aspect_ratio"):
        payload["aspect_ratio"] = merged["aspect_ratio"]
    if merged.get("resolution"):
        payload["resolution"] = merged["resolution"]
    return payload


def parse_json_response(raw: bytes) -> dict[str, Any]:
    return json.loads(raw.decode("utf-8"))


def ensure_output_dir(root: Path, output_dir: str) -> Path:
    out_dir = Path(output_dir)
    if not out_dir.is_absolute():
        out_dir = (root / out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir


def save_forge_response(
    *,
    resp: dict[str, Any],
    merged: dict[str, Any],
    payload: dict[str, Any],
    seed_i: int,
    provider_cfg: dict[str, Any],
    out_dir: Path,
) -> list[dict[str, Any]]:
    images = resp.get("images") or []
    if not images:
        raise RuntimeError("API が images を返しませんでした")

    png_bytes = base64.b64decode(images[0])
    min_png = int(provider_cfg.get("min_png_bytes", 512))
    if len(png_bytes) < min_png:
        raise RuntimeError(
            f"返却PNGが異常に小さい ({len(png_bytes)} bytes)。"
            " Flux では cfg_scale≈1・Euler・distilled_cfg_scale・scheduler(Simple) を"
            " config と揃え、VAE/モデルを UI と同じにしてください。"
        )

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = f"{merged['file_prefix']}_{ts}_{seed_i}"
    png_path = out_dir / f"{stem}.png"
    meta_path = out_dir / f"{stem}.json"
    png_path.write_bytes(png_bytes)
    meta = {
        "provider": "forge",
        "forge_payload_request": payload,
        "api_response_keys": list(resp.keys()),
        "saved_png": str(png_path),
        "param_merged": {k: v for k, v in merged.items() if k != "prompt"},
        "prompt": merged["prompt"],
        "negative_prompt": merged["negative_prompt"],
    }
    if "info" in resp:
        meta["info"] = resp["info"]
    write_json(meta_path, meta)
    return [{"png": str(png_path), "json": str(meta_path), "seed": seed_i}]


def extract_zip_images(raw: bytes) -> list[tuple[str, bytes]]:
    with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        images: list[tuple[str, bytes]] = []
        for info in zf.infolist():
            if info.is_dir():
                continue
            suffix = Path(info.filename).suffix.lower()
            if suffix not in (".png", ".jpg", ".jpeg", ".webp"):
                continue
            images.append((Path(info.filename).name, zf.read(info)))
        return images


def save_novelai_response(
    *,
    raw: bytes,
    headers: dict[str, str],
    merged: dict[str, Any],
    payload: dict[str, Any],
    seed_i: int,
    provider_cfg: dict[str, Any],
    out_dir: Path,
) -> list[dict[str, Any]]:
    content_type = headers.get("content-type", "").lower()
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    saved: list[dict[str, Any]] = []

    if "application/json" in content_type:
        resp = parse_json_response(raw)
        images = resp.get("images") or resp.get("data") or []
        if not images:
            raise RuntimeError("NovelAI JSON 応答から images/data を取得できませんでした")
        first = images[0]
        if isinstance(first, str):
            png_bytes = base64.b64decode(first)
            images_bin = [(f"{merged['file_prefix']}_{ts}_{seed_i}.png", png_bytes)]
        else:
            raise RuntimeError("NovelAI JSON 応答の images/data の形式が未対応です")
    else:
        images_bin = extract_zip_images(raw)
        if not images_bin:
            raise RuntimeError("NovelAI zip 応答から画像を抽出できませんでした")

    min_png = int(provider_cfg.get("min_png_bytes", 512))
    for idx, (name, png_bytes) in enumerate(images_bin, start=1):
        if len(png_bytes) < min_png:
            raise RuntimeError(f"返却画像が異常に小さい ({len(png_bytes)} bytes)")
        stem = f"{merged['file_prefix']}_{ts}_{seed_i}"
        if len(images_bin) > 1:
            stem += f"_{idx:02d}"
        suffix = Path(name).suffix or ".png"
        png_path = out_dir / f"{stem}{suffix}"
        meta_path = out_dir / f"{stem}.json"
        png_path.write_bytes(png_bytes)
        meta = {
            "provider": "novelai",
            "novelai_payload_request": payload,
            "saved_png": str(png_path),
            "param_merged": {k: v for k, v in merged.items() if k != "prompt"},
            "prompt": merged["prompt"],
            "negative_prompt": merged["negative_prompt"],
            "response_content_type": content_type,
        }
        write_json(meta_path, meta)
        saved.append({"png": str(png_path), "json": str(meta_path), "seed": seed_i})
    return saved


def save_grok_response(
    *,
    resp: dict[str, Any],
    merged: dict[str, Any],
    payload: dict[str, Any],
    provider_cfg: dict[str, Any],
    out_dir: Path,
    timeout: float,
) -> list[dict[str, Any]]:
    data = resp.get("data") or []
    if not data:
        raise RuntimeError("Grok 応答から data を取得できませんでした")

    min_png = int(provider_cfg.get("min_png_bytes", 512))
    saved: list[dict[str, Any]] = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise RuntimeError("Grok 応答 data の形式が未対応です")
        png_bytes: bytes
        source: str
        if item.get("b64_json"):
            png_bytes = base64.b64decode(str(item["b64_json"]))
            source = "b64_json"
        elif item.get("url"):
            source = str(item["url"])
            _, png_bytes, _ = http_get_bytes(source, timeout)
        else:
            raise RuntimeError("Grok 応答 item に b64_json/url がありません")
        if len(png_bytes) < min_png:
            raise RuntimeError(f"Grok の返却画像が異常に小さい ({len(png_bytes)} bytes)")
        stem = f"{merged['file_prefix']}_{ts}_{idx:02d}"
        png_path = out_dir / f"{stem}.png"
        meta_path = out_dir / f"{stem}.json"
        png_path.write_bytes(png_bytes)
        meta = {
            "provider": "grok",
            "grok_payload_request": payload,
            "saved_png": str(png_path),
            "param_merged": {k: v for k, v in merged.items() if k != "prompt"},
            "prompt": merged["prompt"],
            "response_item": item,
            "image_source": source,
        }
        write_json(meta_path, meta)
        saved.append({"png": str(png_path), "json": str(meta_path), "index": idx})
    return saved


def print_dry_run(provider: str, api_url: str, payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            {"provider": provider, "url": api_url, "payload": payload},
            ensure_ascii=False,
            indent=2,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="画像生成（Forge / NovelAI）")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="設定 JSON（既定: config/image_generation.json）",
    )
    parser.add_argument(
        "--provider",
        choices=PROVIDER_CHOICES,
        default=None,
        help="生成プロバイダ（省略時は config または params の provider）",
    )
    parser.add_argument(
        "--params",
        type=Path,
        default=None,
        help="生成パラメータ JSON。例: tools/fixtures/forge_params.example.json",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="HTTP を送らず payload のみ表示",
    )
    parser.add_argument(
        "--skip-health",
        action="store_true",
        help="Forge の API 生存確認を省略（NovelAI では既定で health probe なし）",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="接続先の簡易疎通だけ表示して終了（params 不要）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="結果を JSON で stdout に出す",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    default_cfg_path = root / "config" / "image_generation.json"
    cfg_path = args.config or default_cfg_path
    if not cfg_path.is_file():
        print(
            f"設定が見つかりません: {cfg_path}（リポジトリ直下に config/image_generation.json を置く）",
            file=sys.stderr,
        )
        return 2

    if args.params:
        p = args.params
        if not p.is_file():
            print(f"パラメータファイルが見つかりません: {p.resolve()}", file=sys.stderr)
            return 2
        params = load_json(p)
    else:
        if args.probe:
            params = {}
        elif sys.stdin.isatty():
            ex = (root / "tools" / "fixtures" / "forge_params.example.json").as_posix()
            print(
                "使い方: --params に JSON を指定するか、パラメータを標準入力に流し込んでください。",
                file=sys.stderr,
            )
            print(
                f"  例: python tools/forge_generate.py --params {ex} --dry-run",
                file=sys.stderr,
            )
            return 2
        else:
            params = json.load(sys.stdin)

    root_cfg = load_root_config(cfg_path)
    dotenv_map = load_dotenv(root / ".env")
    provider = resolve_provider_name(
        root_cfg=root_cfg,
        args_provider=args.provider,
        params_provider=params.get("provider"),
    )
    try:
        provider_cfg = get_provider_cfg(root_cfg, provider, dotenv_map=dotenv_map)
    except (KeyError, ValueError) as e:
        print(str(e), file=sys.stderr)
        return 2

    timeout = float(provider_cfg.get("timeout_sec", 180))
    if args.probe:
        run_probe(provider, provider_cfg, timeout)
        return 0

    try:
        merged = merge_provider_defaults(provider, provider_cfg, params)
    except KeyError as e:
        print(f"config に必要キーがありません: {e}", file=sys.stderr)
        return 2

    sys.stderr.write(
        f"# image_gen: provider={provider} "
        f"cfg_scale={merged['cfg_scale']} sampler={merged['sampler_name']}\n"
    )
    sys.stderr.flush()

    max_c = int(provider_cfg.get("max_count", 4))
    if merged["count"] < 1 or merged["count"] > max_c:
        print(f"count は 1〜{max_c} にしてください（現在: {merged['count']}）", file=sys.stderr)
        return 2

    if not merged["output_dir"]:
        print("params に output_dir を指定してください", file=sys.stderr)
        return 2

    try:
        validate_sampler(merged["sampler_name"], list(provider_cfg.get("allowed_samplers", [])))
    except ValueError as e:
        print(str(e), file=sys.stderr)
        return 2

    out_dir = ensure_output_dir(root, merged["output_dir"])
    log_path = root / "logs" / "forge_generate.log"
    base_seed = merged["seed"] if merged["seed"] is not None else random.randint(1, 2**31 - 1)
    saved: list[dict[str, Any]] = []

    if provider == "forge":
        base_url = str(provider_cfg.get("base_url", "http://127.0.0.1:7860")).rstrip("/")
        api_url = f"{base_url}/sdapi/v1/txt2img"
        if not args.skip_health and not args.dry_run:
            try:
                check_a1111_api_ready(base_url, timeout)
            except RuntimeError as e:
                append_log(log_path, f"HEALTH FAIL: {e}")
                print(str(e), file=sys.stderr)
                return 3

        for i in range(merged["count"]):
            seed_i = int(base_seed) + i
            payload = build_forge_payload(merged, seed_for_request=seed_i)
            if args.dry_run:
                print_dry_run(provider, api_url, payload)
                continue
            try:
                _, raw, _ = http_post_json(api_url, payload, timeout)
                resp = parse_json_response(raw)
                saved.extend(
                    save_forge_response(
                        resp=resp,
                        merged=merged,
                        payload=payload,
                        seed_i=seed_i,
                        provider_cfg=provider_cfg,
                        out_dir=out_dir,
                    )
                )
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                if e.code == 404:
                    print(API_404_HINT, file=sys.stderr)
                msg = f"HTTP {e.code}: {body[:2000]}"
                append_log(log_path, f"FAIL provider=forge seed={seed_i} {msg}")
                print(msg, file=sys.stderr)
                return 4
            except Exception as e:
                append_log(log_path, f"ERROR provider=forge seed={seed_i} {e!r}")
                print(f"リクエスト失敗: {e}", file=sys.stderr)
                return 5
    elif provider == "novelai":
        auth_env = str(provider_cfg.get("auth_env", "NOVELAI_ACCESS_TOKEN"))
        token = resolve_env_value(auth_env, dotenv_map)
        if not token and not args.dry_run:
            print(
                f"{auth_env} が見つかりません。.env または環境変数を設定してください。",
                file=sys.stderr,
            )
            return 2

        base_url = str(provider_cfg.get("base_url", "https://image.novelai.net")).rstrip("/")
        generate_path = str(provider_cfg.get("generate_path", "/ai/generate-image"))
        api_url = f"{base_url}{generate_path}"
        # Cloudflare が Python urllib の既定 User-Agent 等を弾くことがあるため、
        # config の default_request_headers でブラウザ相当ヘッダを付与する。
        headers: dict[str, str] = {"Accept": "*/*"}
        extra_h = provider_cfg.get("default_request_headers")
        if isinstance(extra_h, dict):
            for k, v in extra_h.items():
                if isinstance(k, str) and v is not None:
                    headers[k] = str(v)
        if token:
            headers["Authorization"] = f"Bearer {token}"

        for i in range(merged["count"]):
            seed_i = int(base_seed) + i
            payload = build_novelai_payload(merged, seed_for_request=seed_i)
            if args.dry_run:
                print_dry_run(provider, api_url, payload)
                continue
            try:
                _, raw, resp_headers = http_post_json(
                    api_url,
                    payload,
                    timeout,
                    headers=headers,
                )
                saved.extend(
                    save_novelai_response(
                        raw=raw,
                        headers=resp_headers,
                        merged=merged,
                        payload=payload,
                        seed_i=seed_i,
                        provider_cfg=provider_cfg,
                        out_dir=out_dir,
                    )
                )
            except urllib.error.HTTPError as e:
                body = e.read().decode("utf-8", errors="replace")
                msg = f"HTTP {e.code}: {body[:2000]}"
                append_log(log_path, f"FAIL provider=novelai seed={seed_i} {msg}")
                print(msg, file=sys.stderr)
                return 4
            except zipfile.BadZipFile as e:
                append_log(log_path, f"ERROR provider=novelai seed={seed_i} bad zip: {e!r}")
                print("NovelAI 応答の zip 展開に失敗しました", file=sys.stderr)
                return 5
            except Exception as e:
                append_log(log_path, f"ERROR provider=novelai seed={seed_i} {e!r}")
                print(f"リクエスト失敗: {e}", file=sys.stderr)
                return 5
    elif provider == "grok":
        auth_env = str(provider_cfg.get("auth_env", "XAI_API_KEY"))
        token = resolve_env_value(auth_env, dotenv_map)
        if not token and not args.dry_run:
            print(
                f"{auth_env} が見つかりません。.env または環境変数を設定してください。",
                file=sys.stderr,
            )
            return 2
        base_url = str(provider_cfg.get("base_url", "https://api.x.ai/v1")).rstrip("/")
        generate_path = str(provider_cfg.get("generate_path", "/images/generations"))
        api_url = f"{base_url}{generate_path}"
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        payload = build_grok_payload(merged)
        if args.dry_run:
            print_dry_run(provider, api_url, payload)
            return 0
        try:
            _, raw, _ = http_post_json(api_url, payload, timeout, headers=headers)
            resp = parse_json_response(raw)
            saved.extend(
                save_grok_response(
                    resp=resp,
                    merged=merged,
                    payload=payload,
                    provider_cfg=provider_cfg,
                    out_dir=out_dir,
                    timeout=timeout,
                )
            )
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            msg = f"HTTP {e.code}: {body[:2000]}"
            append_log(log_path, f"FAIL provider=grok {msg}")
            print(msg, file=sys.stderr)
            return 4
        except Exception as e:
            append_log(log_path, f"ERROR provider=grok {e!r}")
            print(f"リクエスト失敗: {e}", file=sys.stderr)
            return 5
    else:
        print(f"未対応 provider: {provider}", file=sys.stderr)
        return 2

    if args.dry_run:
        return 0

    if args.json:
        print(json.dumps({"ok": True, "provider": provider, "saved": saved}, ensure_ascii=False, indent=2))
    else:
        for s in saved:
            print(s["png"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
