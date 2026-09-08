#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
画像 provider クライアント（Forge / NovelAI / Grok / OpenAI）。

- provider=forge:
  - POST /sdapi/v1/txt2img（save_images は使わず、返却 base64 を自前保存）
- provider=novelai:
  - POST /ai/generate-image（Bearer token は .env の NOVELAI_ACCESS_TOKEN を使用）
  - zip 応答を展開して PNG を保存
- provider=grok:
  - POST /v1/images/generations（Bearer token は .env の XAI_API_KEY を使用）
  - `b64_json` または URL 応答を保存
- provider=openai:
  - POST /v1/images/generations（Bearer token は .env の OPENAI_API_KEY を使用）
  - `b64_json` または URL 応答を保存

設定は config/image_generation.json（既定・必須。`--config` で別パスも可）。
仕様・運用: .rulesync/skills/forge-txt2img/SKILL.md（image-provider）
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
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ポーション／Vibe 以外の参照画像（PNG 等）に importInfo が無いときの内部既定
_PLAIN_IMAGE_REF_STRENGTH = 0.6
_PLAIN_IMAGE_REF_IE = 1.0
# importInfo に strength / IE が無い vibe 項目の内部既定
_VIBE_MISSING_IMPORT_STRENGTH = 1.0
_VIBE_MISSING_IMPORT_IE = 1.0

PROVIDER_CHOICES = ("forge", "novelai", "grok", "grok_pro", "openai", "openrouter")
_GROK_FAMILY = frozenset({"grok", "grok_pro"})
FORGE_MODEL_FAMILY_ENV = "MONOCRI_FORGE_MODEL_FAMILY_DEFAULT"
GROK_MODEL_TIER_ENV = "MONOCRI_GROK_MODEL_TIER_DEFAULT"


def missing_auth_message(auth_env: str) -> str:
    return (
        f"{auth_env} が見つかりません。.env または環境変数を設定してください。\n"
        "設定の不足確認: python tools/env_check.py"
    )


# NovelAI nai-diffusion-4 / 4.5 / 5 系の UC プリセット文字列（公式 Undesired Content 表）。
# 番号は Web UI の None=3 / Heavy=4 / Light=5 / Human Focus=6 / Furry Focus=7 に合わせる。
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
        "{worst quality}, distracting watermark, unfinished, bad quality, "
        "{widescreen}, upscale, {sequence}, {{grandfathered content}}, blurred foreground, chromatic aberration, "
        "sketch, everyone, [sketch background], simple, [flat colors], ych (character), outline, multiple scenes, "
        "[[horror (theme)]], comic"
    ),
}
_UC_V45_FULL: dict[int, str] = {
    3: "",
    4: (
        "lowres, artistic error, film grain, scan artifacts, worst quality, "
        "bad quality, jpeg artifacts, very displeasing, chromatic aberration, dithering, halftone, screentone, "
        "multiple views, logo, too many watermarks, negative space, blank page"
    ),
    5: (
        "lowres, artistic error, scan artifacts, worst quality, bad quality, "
        "jpeg artifacts, multiple views, very displeasing, too many watermarks, negative space, blank page"
    ),
    6: (
        "lowres, artistic error, film grain, scan artifacts, worst quality, "
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
        "blurry, lowres, error, film grain, scan artifacts, worst quality, "
        "bad quality, jpeg artifacts, very displeasing, chromatic aberration, multiple views, logo, "
        "too many watermarks, white blank page, blank page"
    ),
    5: (
        "blurry, lowres, error, worst quality, bad quality, jpeg artifacts, "
        "very displeasing, white blank page, blank page"
    ),
}
# V5 Full / Curated は公式表で同一文面。Light だけ V4.5 と違う。
_UC_V5: dict[int, str] = {
    3: "",
    4: _UC_V45_FULL[4],
    5: (
        "lowres, bad hands, bad anatomy, artistic error, sepia, white haze, "
        "worst quality, very displeasing, jpeg artifacts, 0::ai-generated::"
    ),
    6: _UC_V45_FULL[6],
    7: _UC_V45_CURATED[7],
}
_V5_QUALITY_STANDARD = ", very aesthetic, masterpiece, no text"
_V5_QUALITY_LIGHT = ", very aesthetic, amazing quality, no text"
# 公式に確認した model ID だけ v4_prompt 経路へ載せる。部分一致は使わない。
_NOVELAI_V4_CONDITION_IDS = frozenset(
    {
        "nai-diffusion-4",
        "nai-diffusion-4-full",
        "nai-diffusion-4-curated",
        "nai-diffusion-4-curated-preview",
        "nai-diffusion-4-5-full",
        "nai-diffusion-4-5-curated",
        "nai-diffusion-5-full",
        "nai-diffusion-5-curated",
    }
)
_NOVELAI_V5_IDS = frozenset({"nai-diffusion-5-full", "nai-diffusion-5-curated"})
_NOVELAI_V4_CONDITION_OPTIONAL_SUFFIX = "-inpainting"


def _novelai_model_base(model_id: str) -> str:
    mid = str(model_id).strip()
    suffix = _NOVELAI_V4_CONDITION_OPTIONAL_SUFFIX
    if mid.endswith(suffix):
        return mid[: -len(suffix)]
    return mid


def _novelai_uses_v4_condition(model_id: str) -> bool:
    """V4 / V4.5 / V5 の正式 ID（と -inpainting）だけ v4_prompt を使う。"""
    return _novelai_model_base(model_id) in _NOVELAI_V4_CONDITION_IDS


def _novelai_is_v5_model(model_id: str) -> bool:
    """V5 Full / Curated およびその ``-inpainting`` を V5 として扱う。"""
    return _novelai_model_base(model_id) in _NOVELAI_V5_IDS


def _novelai_apply_vibe_model_pin(
    *,
    model_id: str,
    model_explicit: bool,
    has_refs: bool,
    provider_cfg: dict[str, Any],
) -> str:
    """Vibe / 参照画像があるとき、未指定モデルを V4.5 に残す。V5 明示は拒否。"""
    if not has_refs:
        return model_id
    vibe_raw = provider_cfg.get("vibe_model", "nai-diffusion-4-5-full")
    vibe_model = str(
        resolve_named_value(vibe_raw, provider_cfg.get("model_aliases"))
    )
    if model_explicit:
        if _novelai_is_v5_model(model_id):
            raise ValueError(
                "Vibe Transfer は NovelAI V5 では未提供です。"
                " model を v4-5-full にするか、reference_image_paths を外してください。"
            )
        return model_id
    return vibe_model


def _novelai_is_diffusion_v4_family(model_id: str) -> bool:
    return _novelai_uses_v4_condition(model_id)


def _novelai_is_diffusion_v5(model_id: str) -> bool:
    return _novelai_model_base(model_id) in _NOVELAI_V5_IDS


def _novelai_uc_table(model_id: str) -> dict[int, str]:
    base = _novelai_model_base(model_id)
    if base in _NOVELAI_V5_IDS:
        return _UC_V5
    if base == "nai-diffusion-4-5-curated":
        return _UC_V45_CURATED
    if base == "nai-diffusion-4-5-full":
        return _UC_V45_FULL
    if base == "nai-diffusion-4-full":
        return _UC_V4_FULL
    if base in {
        "nai-diffusion-4",
        "nai-diffusion-4-curated",
        "nai-diffusion-4-curated-preview",
    }:
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


def _novelai_augment_prompt(
    model_id: str,
    prompt: str,
    *,
    quality_toggle: bool = True,
    quality_preset: str = "standard",
) -> str:
    """novelai_api HighLevel.generate_image に合わせた品質接尾辞。

    プロンプトに区切り記号 ``|`` が含まれる場合は NovelAI の
    「ベース | キャラ …」構造として**最初の ``|`` の左**（ベース）のみへ追接尾する。
    （``ベース | キャラA | キャラB`` のような複数区切りでも同様）
    ``quality_toggle=False`` のときは接尾しない（吹き出し試験向け）。
    """
    if not quality_toggle:
        return prompt
    pipe_split = "|" in prompt
    if pipe_split:
        left, sep, right = prompt.partition("|")
        left_augmented = _novelai_augment_prompt_segment(
            model_id, left.strip(), quality_preset=quality_preset
        )
        return f"{left_augmented}{sep}{right}" if sep else left_augmented
    return _novelai_augment_prompt_segment(
        model_id, prompt, quality_preset=quality_preset
    )


def _novelai_augment_prompt_segment(
    model_id: str,
    segment: str,
    *,
    quality_preset: str = "standard",
) -> str:
    """単一セグメントへ品質接尾辞を付与（pipe 分割後の左または全体）。"""
    prompt = segment
    base = _novelai_model_base(model_id)
    if base in _NOVELAI_V5_IDS:
        suffix = (
            _V5_QUALITY_LIGHT
            if quality_preset == "light"
            else _V5_QUALITY_STANDARD
        )
        return f"{prompt}{suffix}"
    if base == "nai-diffusion-4-5-curated":
        return (
            f"{prompt}, very aesthetic, location, masterpiece, no text, "
            f"-0.8::feet::, rating:general"
        )
    if base == "nai-diffusion-4-5-full":
        return f"{prompt}, location, very aesthetic, masterpiece, no text"
    if base == "nai-diffusion-4-full":
        return f"{prompt}, no text, best quality, very aesthetic, absurdres"
    if _novelai_uses_v4_condition(model_id):
        return f"{prompt}, rating:general, best quality, very aesthetic, absurdres"
    return prompt


_NOVELAI_DEFAULT_CENTER = {"x": 0.5, "y": 0.5}
_NOVELAI_GRID_COLS = "ABCDE"


def _novelai_validate_xy(x: float, y: float) -> dict[str, float]:
    if not (0.0 <= x <= 1.0 and 0.0 <= y <= 1.0):
        raise ValueError(f"center は 0〜1 です: x={x}, y={y}")
    return {"x": x, "y": y}


def _novelai_parse_center(raw: Any) -> dict[str, float]:
    """V5 の自由座標（0–1）または V4 互換グリッド A1〜E5 を {x, y} にする。"""
    if raw is None:
        return dict(_NOVELAI_DEFAULT_CENTER)
    if isinstance(raw, str):
        token = raw.strip().upper()
        if len(token) == 2 and token[0] in _NOVELAI_GRID_COLS and token[1] in "12345":
            col = _NOVELAI_GRID_COLS.index(token[0])
            row = int(token[1]) - 1
            return {"x": (col + 0.5) / 5.0, "y": (row + 0.5) / 5.0}
        raise ValueError(f"center のグリッド指定は A1〜E5 です: {raw!r}")
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        return _novelai_validate_xy(float(raw[0]), float(raw[1]))
    if isinstance(raw, dict) and "x" in raw and "y" in raw:
        return _novelai_validate_xy(float(raw["x"]), float(raw["y"]))
    raise ValueError(f"center の形式が不正です: {raw!r}")


def _novelai_split_pipe_segments(prompt: str) -> tuple[str, list[str]]:
    parts = [p.strip() for p in str(prompt).split("|")]
    if not parts:
        return "", []
    return parts[0], [p for p in parts[1:] if p]


def _novelai_item_center_raw(item: dict[str, Any]) -> Any:
    if "center" in item:
        return item["center"]
    if "centers" in item:
        raw_c = item["centers"]
        if isinstance(raw_c, list) and raw_c:
            return raw_c[0]
        return raw_c
    return None


def _novelai_bind_character_centers(
    prompts: list[str],
    ucs: list[str],
    item_centers: list[Any],
    merged: dict[str, Any],
) -> list[dict[str, Any]]:
    top_centers = merged.get("centers")
    if top_centers is not None:
        if not isinstance(top_centers, list):
            raise ValueError("centers は配列である必要があります")
        if len(top_centers) != len(prompts):
            raise ValueError(
                f"centers の件数({len(top_centers)})がキャラ数({len(prompts)})と一致しません"
            )
    entries: list[dict[str, Any]] = []
    for i, prompt in enumerate(prompts):
        raw_center = item_centers[i]
        if raw_center is None and top_centers is not None:
            raw_center = top_centers[i]
        entries.append(
            {
                "prompt": prompt,
                "uc": ucs[i],
                "center": _novelai_parse_center(raw_center),
            }
        )
    return entries


def _novelai_resolve_character_entries(
    merged: dict[str, Any],
) -> list[dict[str, Any]]:
    """characterPrompts / char_captions 用エントリ。

    優先: ``character_prompts`` 明示 > ``split_pipe_characters`` による pipe 分割。
    どちらも無ければ空（現行の ``input`` 連結）。
    """
    explicit = merged.get("character_prompts")
    if isinstance(explicit, list) and explicit:
        prompts: list[str] = []
        ucs: list[str] = []
        item_centers: list[Any] = []
        for i, item in enumerate(explicit):
            if not isinstance(item, dict):
                raise ValueError(
                    f"character_prompts[{i}] はオブジェクトである必要があります"
                )
            prompt = str(
                item.get("prompt") or item.get("char_caption") or ""
            ).strip()
            if not prompt:
                raise ValueError(f"character_prompts[{i}].prompt が空です")
            prompts.append(prompt)
            ucs.append(str(item.get("uc") or item.get("negative") or "").strip())
            item_centers.append(_novelai_item_center_raw(item))
        return _novelai_bind_character_centers(prompts, ucs, item_centers, merged)

    if not merged.get("split_pipe_characters"):
        return []
    _base, chars = _novelai_split_pipe_segments(str(merged.get("prompt", "")))
    if not chars:
        return []
    return _novelai_bind_character_centers(
        chars, [""] * len(chars), [None] * len(chars), merged
    )


def _novelai_resolve_use_coords(merged: dict[str, Any]) -> bool:
    """centers または character の center を明示したとき、未指定なら use_coords を True。"""
    if merged.get("_use_coords_explicit"):
        return bool(merged["use_coords"])
    if merged.get("centers") is not None:
        return True
    explicit = merged.get("character_prompts") or []
    if any(
        isinstance(item, dict) and ("center" in item or "centers" in item)
        for item in explicit
    ):
        return True
    return bool(merged.get("use_coords", False))


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


def _strip_data_url(value: str) -> str:
    if value.startswith("data:") and "," in value:
        return value.split(",", 1)[1]
    return value


def _is_probably_base64(value: str) -> bool:
    text = _strip_data_url(value).strip()
    if len(text) < 24:
        return False
    allowed = set("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/=\n\r")
    return all(ch in allowed for ch in text)


def _find_image_b64_in_json(data: Any) -> list[str]:
    found: list[str] = []
    preferred_keys = {
        "image",
        "original_image",
        "source_image",
        "reference_image",
        "referenceImage",
        "dataURL",
        "data_url",
    }

    def walk(node: Any, key_hint: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, str(k))
            return
        if isinstance(node, list):
            for item in node:
                walk(item, key_hint)
            return
        if not isinstance(node, str):
            return
        text = node.strip()
        if text.startswith("data:image/"):
            found.append(_strip_data_url(text))
        elif key_hint in preferred_keys and _is_probably_base64(text):
            found.append(_strip_data_url(text))

    walk(data)
    return found


@dataclass(frozen=True)
class NovelaiVibeRefItem:
  """1 参照スロット分（encoding + バンドル内 strength / IE）。"""

  encoding_b64: str
  strength: float
  information_extracted: float
  from_bundle_meta: bool = False


def _clamp_reference_coefficient(value: float) -> float:
  # NovelAI API は 0 を送ると不定挙動の可能性があるため下限を 0.01 にする
  return max(0.01, min(1.0, float(value)))


def _import_info_from_vibe_dict(vibe: dict[str, Any]) -> tuple[float, float]:
  info = vibe.get("importInfo") or vibe.get("import_info") or {}
  if not isinstance(info, dict):
    info = {}
  raw_s = info.get("strength")
  raw_ie = info.get("information_extracted", info.get("informationExtracted"))
  strength = (
    float(raw_s) if raw_s is not None else _VIBE_MISSING_IMPORT_STRENGTH
  )
  information_extracted = (
    float(raw_ie) if raw_ie is not None else _VIBE_MISSING_IMPORT_IE
  )
  return strength, information_extracted


def _encoding_b64_from_vibe_dict(vibe: dict[str, Any]) -> str | None:
  encodings = vibe.get("encodings")
  if encodings is None:
    return None

  def walk(node: Any) -> str | None:
    if isinstance(node, dict):
      enc = node.get("encoding")
      if isinstance(enc, str) and _is_probably_base64(enc):
        return _strip_data_url(enc).strip()
      for value in node.values():
        found = walk(value)
        if found:
          return found
    elif isinstance(node, list):
      for item in node:
        found = walk(item)
        if found:
          return found
    return None

  return walk(encodings)


def _extract_vibe_ref_items_from_json(data: Any) -> list[NovelaiVibeRefItem]:
  out: list[NovelaiVibeRefItem] = []
  if isinstance(data, dict):
    vibes = data.get("vibes")
    if isinstance(vibes, list):
      for vibe in vibes:
        if not isinstance(vibe, dict):
          continue
        strength, ie = _import_info_from_vibe_dict(vibe)
        enc = _encoding_b64_from_vibe_dict(vibe)
        if enc:
          out.append(
            NovelaiVibeRefItem(
              encoding_b64=enc,
              strength=strength,
              information_extracted=ie,
              from_bundle_meta=True,
            )
          )
      if out:
        return out
    if data.get("encodings"):
      strength, ie = _import_info_from_vibe_dict(data)
      enc = _encoding_b64_from_vibe_dict(data)
      if enc:
        return [
          NovelaiVibeRefItem(
            encoding_b64=enc,
            strength=strength,
            information_extracted=ie,
            from_bundle_meta=True,
          )
        ]

  encodings = _find_vibe_encoding_b64_in_json(data)
  return [
    NovelaiVibeRefItem(
      encoding_b64=enc,
      strength=_PLAIN_IMAGE_REF_STRENGTH,
      information_extracted=_PLAIN_IMAGE_REF_IE,
      from_bundle_meta=False,
    )
    for enc in encodings
  ]


def load_reference_vibe_items_from_file(path: Path) -> list[NovelaiVibeRefItem]:
  suffix = path.suffix.lower()
  raw = path.read_bytes()
  image_suffixes = {".png", ".jpg", ".jpeg", ".webp"}
  if suffix in image_suffixes:
    return [
      NovelaiVibeRefItem(
        encoding_b64=base64.b64encode(raw).decode("ascii"),
        strength=_PLAIN_IMAGE_REF_STRENGTH,
        information_extracted=_PLAIN_IMAGE_REF_IE,
        from_bundle_meta=False,
      )
    ]
  if suffix in {".naiv4vibe", ".naiv4vibebundle"}:
    items: list[NovelaiVibeRefItem] = []
    if zipfile.is_zipfile(io.BytesIO(raw)):
      with zipfile.ZipFile(io.BytesIO(raw)) as zf:
        for info in zf.infolist():
          if Path(info.filename).suffix.lower() != ".json":
            continue
          try:
            items.extend(
              _extract_vibe_ref_items_from_json(
                json.loads(zf.read(info).decode("utf-8"))
              )
            )
          except Exception:
            continue
        if items:
          return items
        for info in zf.infolist():
          name = info.filename.lower()
          if Path(name).suffix in image_suffixes:
            items.append(
              NovelaiVibeRefItem(
                encoding_b64=base64.b64encode(zf.read(info)).decode("ascii"),
                strength=_PLAIN_IMAGE_REF_STRENGTH,
                information_extracted=_PLAIN_IMAGE_REF_IE,
                from_bundle_meta=False,
              )
            )
        if items:
          return items
    try:
      data = json.loads(raw.decode("utf-8"))
    except Exception:
      data = None
    if data is not None:
      items = _extract_vibe_ref_items_from_json(data)
      if items:
        return items
    raise ValueError(
      f"{path} から Vibe Transfer 用画像を抽出できませんでした。"
      ".naiv4vibe/.naiv4vibeBundle の encoding または元画像を確認してください。"
    )
  raise ValueError(
    f"参照画像として未対応の拡張子です: {path} "
    "(対応: .png, .jpg, .jpeg, .webp, .naiv4vibe, .naiv4vibeBundle)"
  )


def build_novelai_reference_coefficients(
  paths: list[str],
  root: Path,
  *,
  strength_multiplier: float = 1.0,
  information_extracted_multiplier: float = 1.0,
) -> tuple[list[float], list[float], bool]:
  """パス列から参照スロットごとの strength / IE を組み立てる。

  ``strength_multiplier`` / ``information_extracted_multiplier`` は
  バンドル内 ``importInfo``（無い項目は PNG 既定 0.6 / 1.0）への**乗数**。
  比率維持のため、バンドルメタ由来または strength が複数値のときは
  ``normalize_reference_strength_multiple`` を False にする。
  """
  items: list[NovelaiVibeRefItem] = []
  for raw in paths:
    path = Path(str(raw))
    if not path.is_absolute():
      path = (root / path).resolve()
    if not path.is_file():
      raise ValueError(f"参照画像ファイルが見つかりません: {path}")
    items.extend(load_reference_vibe_items_from_file(path))

  strengths = [
    _clamp_reference_coefficient(item.strength * strength_multiplier)
    for item in items
  ]
  ies = [
    _clamp_reference_coefficient(
      item.information_extracted * information_extracted_multiplier
    )
    for item in items
  ]
  has_varying_strength = len({round(s, 8) for s in strengths}) > 1
  uses_bundle_meta = any(item.from_bundle_meta for item in items)
  normalize = not (uses_bundle_meta or has_varying_strength)
  return strengths, ies, normalize


def _find_vibe_encoding_b64_in_json(data: Any) -> list[str]:
    found: list[str] = []

    def walk(node: Any, key_hint: str = "") -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                walk(v, str(k))
            return
        if isinstance(node, list):
            for item in node:
                walk(item, key_hint)
            return
        if key_hint == "encoding" and isinstance(node, str) and _is_probably_base64(node):
            found.append(_strip_data_url(node).strip())

    walk(data)
    return found


def _load_reference_image_file(path: Path) -> list[str]:
    return [item.encoding_b64 for item in load_reference_vibe_items_from_file(path)]


def _coerce_float_list(value: Any, *, count: int, default: float) -> list[float]:
    if value is None:
        items: list[float] = []
    elif isinstance(value, list):
        items = [float(v) for v in value]
    else:
        items = [float(value)]
    if len(items) > count:
        return items[:count]
    return items + [default for _ in range(count - len(items))]


def load_novelai_reference_images(params: dict[str, Any], root: Path) -> list[str]:
    refs: list[str] = []
    raw_refs = params.get("reference_image_multiple", [])
    if isinstance(raw_refs, str):
        raw_refs = [raw_refs]
    if isinstance(raw_refs, list):
        for item in raw_refs:
            if isinstance(item, str) and _is_probably_base64(item):
                refs.append(_strip_data_url(item).strip())
            elif item:
                raise ValueError("reference_image_multiple は base64 文字列の配列で指定してください。")
    raw_paths = params.get("reference_image_paths", params.get("reference_image_path", []))
    if isinstance(raw_paths, str):
        raw_paths = [raw_paths]
    if isinstance(raw_paths, list):
        for raw_path in raw_paths:
            path = Path(str(raw_path))
            if not path.is_absolute():
                path = root / path
            if not path.is_file():
                raise ValueError(f"参照画像ファイルが見つかりません: {path}")
            refs.extend(_load_reference_image_file(path))
    return refs


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
        if raw_tier:
            out["default_model"] = str(
                resolve_named_value(raw_tier, out.get("model_aliases"))
            )
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


def resolve_novelai_dimensions(
    provider_cfg: dict[str, Any],
    params: dict[str, Any],
) -> tuple[int, int]:
    """NovelAI: aspect_ratio_preset → width/height（Forge sdxl と同型の flat preset 表）。"""
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
    resolved = resolve_named_value(raw_preset, presets)
    if isinstance(resolved, dict) and "width" in resolved and "height" in resolved:
        return int(resolved["width"]), int(resolved["height"])
    raise ValueError(
        f"NovelAI の aspect_ratio_preset が不明です: {raw_preset!r}。"
        f"available: {sorted(presets.keys())}"
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

    if provider in _GROK_FAMILY:
        print(
            "Grok / xAI Images API は probe 用の専用 health endpoint を前提にしていないため、"
            "dry-run または実際の生成で疎通確認してください。"
        )
        generate_path = str(provider_cfg.get("generate_path", "/images/generations"))
        print(f"  configured generate_path={generate_path}")
        return

    if provider == "openai":
        print(
            "OpenAI Images API は probe 用の専用 health endpoint を前提にしていないため、"
            "dry-run または実際の生成で疎通確認してください。"
        )
        generate_path = str(provider_cfg.get("generate_path", "/images/generations"))
        print(f"  configured generate_path={generate_path}")
        print(f"  auth_env={provider_cfg.get('auth_env', 'OPENAI_API_KEY')}")
        return

    if provider == "openrouter":
        print(
            "OpenRouter の画像生成は /api/v1/chat/completions を使うため、"
            "dry-run または実際の生成で payload と応答形式を確認してください。"
        )
        generate_path = str(provider_cfg.get("generate_path", "/chat/completions"))
        print(f"  configured generate_path={generate_path}")
        print(f"  auth_env={provider_cfg.get('auth_env', 'OPENROUTER_API_KEY')}")
        print("  models endpoint: https://openrouter.ai/api/v1/models?output_modalities=image")
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
    root: Path | None = None,
) -> dict[str, Any]:
    width_default = provider_cfg["default_width"]
    height_default = provider_cfg["default_height"]
    if provider == "forge":
        width_default, height_default = resolve_forge_dimensions(provider_cfg, params)
    elif provider == "novelai":
        width_default, height_default = resolve_novelai_dimensions(provider_cfg, params)
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
    if "metadata" in params:
        out["metadata"] = params["metadata"]
    for meta_key in ("prompt_formatter", "negative_mode"):
        if meta_key in params:
            out[meta_key] = params[meta_key]
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
        raw_model = params.get("model", provider_cfg["default_model"])
        out["model"] = str(
            resolve_named_value(raw_model, provider_cfg.get("model_aliases"))
        )
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
        if "use_coords" in params:
            out["_use_coords_explicit"] = True
        out["split_pipe_characters"] = bool(
            params.get(
                "split_pipe_characters",
                provider_cfg.get("default_split_pipe_characters", False),
            )
        )
        if "character_prompts" in params:
            raw_chars = params["character_prompts"]
            if raw_chars is None:
                out["character_prompts"] = []
            elif not isinstance(raw_chars, list):
                raise ValueError("character_prompts は配列である必要があります")
            else:
                out["character_prompts"] = raw_chars
        if "centers" in params:
            out["centers"] = params["centers"]
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
            out["_v4_use_coords_explicit"] = True
        if "quality_preset" in params:
            preset = str(params["quality_preset"]).strip().lower()
            if preset not in {"standard", "light"}:
                raise ValueError(
                    f"quality_preset は standard / light のみです: {params['quality_preset']!r}"
                )
            out["quality_preset"] = preset
        for opt_bool in (
            "straight_alpha",
            "tag_hint_transparent_background",
            "upscaled_enhance",
        ):
            if opt_bool in params:
                out[opt_bool] = bool(params[opt_bool])
        for opt_int in ("tag_hint_qt", "tag_hint_uc_preset"):
            if opt_int in params:
                out[opt_int] = int(params[opt_int])
        root_path = root or repo_root()
        refs = load_novelai_reference_images(params, root_path)
        if refs:
            out["reference_image_multiple"] = refs
            raw_paths = params.get(
                "reference_image_paths", params.get("reference_image_path", [])
            )
            if isinstance(raw_paths, str):
                raw_paths = [raw_paths]
            resolved_paths: list[str] = []
            if isinstance(raw_paths, list):
                for raw_path in raw_paths:
                    path = Path(str(raw_path))
                    if not path.is_absolute():
                        path = root_path / path
                    resolved_paths.append(path.as_posix())
            raw_strength = params.get("reference_strength_multiple")
            raw_ie = params.get("reference_information_extracted_multiple")
            explicit_strength = (
                isinstance(raw_strength, list) and len(raw_strength) == len(refs)
            )
            explicit_ie = isinstance(raw_ie, list) and len(raw_ie) == len(refs)
            if explicit_strength and explicit_ie:
                strength_list = raw_strength if isinstance(raw_strength, list) else []
                ie_list = raw_ie if isinstance(raw_ie, list) else []
                out["reference_strength_multiple"] = [float(v) for v in strength_list]
                out["reference_information_extracted_multiple"] = [
                    float(v) for v in ie_list
                ]
                out["normalize_reference_strength_multiple"] = bool(
                    params.get(
                        "normalize_reference_strength_multiple",
                        provider_cfg.get(
                            "default_normalize_reference_strength_multiple", True
                        ),
                    )
                )
            else:
                strength_mult = (
                    float(raw_strength)
                    if raw_strength is not None
                    and not isinstance(raw_strength, list)
                    else 1.0
                )
                ie_mult = (
                    float(raw_ie)
                    if raw_ie is not None and not isinstance(raw_ie, list)
                    else 1.0
                )
                strengths, ies, normalize = build_novelai_reference_coefficients(
                    resolved_paths,
                    root_path,
                    strength_multiplier=strength_mult,
                    information_extracted_multiplier=ie_mult,
                )
                # base64 直指定時は resolved_paths が空になり strengths/ies が空になる。
                # refs がある（direct base64）のに strengths が空なら PNG 既定値で件数補完する。
                if not strengths and refs:
                    strengths = [
                        _clamp_reference_coefficient(
                            _PLAIN_IMAGE_REF_STRENGTH * strength_mult
                        )
                        for _ in refs
                    ]
                    ies = [
                        _clamp_reference_coefficient(_PLAIN_IMAGE_REF_IE * ie_mult)
                        for _ in refs
                    ]
                    normalize = True
                out["reference_strength_multiple"] = strengths
                out["reference_information_extracted_multiple"] = ies
                if "normalize_reference_strength_multiple" in params:
                    out["normalize_reference_strength_multiple"] = bool(
                        params["normalize_reference_strength_multiple"]
                    )
                else:
                    out["normalize_reference_strength_multiple"] = normalize
        out["model"] = _novelai_apply_vibe_model_pin(
            model_id=str(out["model"]),
            model_explicit="model" in params,
            has_refs=bool(out.get("reference_image_multiple")),
            provider_cfg=provider_cfg,
        )
        return out

    if provider in _GROK_FAMILY:
        raw_model = params.get("model", provider_cfg["default_model"])
        out["model"] = str(resolve_named_value(raw_model, provider_cfg.get("model_aliases")))
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

    if provider == "openai":
        out["model"] = params.get("model", provider_cfg["default_model"])
        size = params.get("size")
        if not size:
            size = f"{out['width']}x{out['height']}"
        out["size"] = str(size)
        out["quality"] = str(params.get("quality", provider_cfg.get("default_quality", "high")))
        out["background"] = str(
            params.get("background", provider_cfg.get("default_background", "auto"))
        )
        out["output_format"] = str(
            params.get("output_format", provider_cfg.get("default_output_format", "png"))
        )
        response_format = params.get("response_format", provider_cfg.get("default_response_format"))
        if response_format is not None:
            out["response_format"] = str(response_format)
        if "moderation" in params or "default_moderation" in provider_cfg:
            moderation = params.get("moderation", provider_cfg.get("default_moderation"))
            if moderation is not None:
                out["moderation"] = str(moderation)
        return out

    if provider == "openrouter":
        model = str(params.get("model", provider_cfg["default_model"]))
        aliases = provider_cfg.get("model_aliases")
        if isinstance(aliases, dict) and model in aliases:
            model = str(aliases[model])
        out["model"] = model
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
        out["image_size"] = str(
            params.get(
                "image_size",
                params.get("resolution", provider_cfg.get("default_image_size", "1K")),
            )
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
        "reference_image_multiple": merged.get("reference_image_multiple", []),
        "reference_information_extracted_multiple": merged.get(
            "reference_information_extracted_multiple", []
        ),
        "reference_strength_multiple": merged.get("reference_strength_multiple", []),
        "normalize_reference_strength_multiple": merged[
            "normalize_reference_strength_multiple"
        ],
    }
    if "extra_noise_seed" in merged:
        parameters["extra_noise_seed"] = merged["extra_noise_seed"]
    action = str(merged.get("action", "generate"))
    if merged.get("upscaled_enhance") and action == "generate":
        raise ValueError(
            "upscaled_enhance は img2img 専用です。txt2img（action=generate）では送れません。"
        )
    for opt_bool in (
        "straight_alpha",
        "tag_hint_transparent_background",
        "upscaled_enhance",
    ):
        if opt_bool in merged:
            parameters[opt_bool] = bool(merged[opt_bool])
    for opt_int in ("tag_hint_qt", "tag_hint_uc_preset"):
        if opt_int in merged:
            parameters[opt_int] = int(merged[opt_int])

    input_text = str(merged["prompt"])
    if _novelai_uses_v4_condition(model_id):
        combined_uc = _novelai_combine_uc(model_id, uc_eff, str(merged["negative_prompt"]))
        parameters["negative_prompt"] = combined_uc
        parameters["uc"] = combined_uc
        # v4.5 / v5 既定 preset は karras（novelai_api presets_v45）。config が native のままだと 500 になり得る。
        _ns = str(merged.get("noise_schedule", "karras"))
        if _ns == "native":
            _ns = "karras"
        parameters["noise_schedule"] = _ns
        parameters["prefer_brownian"] = bool(merged.get("prefer_brownian", True))
        entries = _novelai_resolve_character_entries(merged)
        raw_prompt = str(merged["prompt"])
        if entries:
            if "|" in raw_prompt:
                prompt_for_augment, _ = _novelai_split_pipe_segments(raw_prompt)
            else:
                prompt_for_augment = raw_prompt
        else:
            prompt_for_augment = raw_prompt
        augmented = _novelai_augment_prompt(
            model_id,
            prompt_for_augment,
            quality_toggle=bool(merged.get("quality_toggle", True)),
            quality_preset=str(merged.get("quality_preset", "standard")),
        )
        input_text = augmented
        use_coords = _novelai_resolve_use_coords(merged)
        if merged.get("_v4_use_coords_explicit"):
            v4_use_coords = bool(merged["v4_use_coords"])
        else:
            v4_use_coords = use_coords
        parameters["use_coords"] = use_coords
        char_captions: list[dict[str, Any]] = []
        neg_char_captions: list[dict[str, Any]] = []
        character_prompts: list[dict[str, Any]] = []
        for entry in entries:
            center = entry["center"]
            char_captions.append(
                {"char_caption": entry["prompt"], "centers": [center]}
            )
            neg_char_captions.append(
                {"char_caption": entry["uc"], "centers": [center]}
            )
            character_prompts.append(
                {
                    "prompt": entry["prompt"],
                    "uc": entry["uc"],
                    "center": center,
                }
            )
        parameters["characterPrompts"] = character_prompts
        parameters["v4_prompt"] = {
            "caption": {
                "base_caption": augmented,
                "char_captions": char_captions,
            },
            "use_coords": v4_use_coords,
            "use_order": True,
        }
        parameters["v4_negative_prompt"] = {
            "caption": {
                "base_caption": combined_uc,
                "char_captions": neg_char_captions,
            }
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


def build_openai_payload(merged: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "model": merged["model"],
        "prompt": merged["prompt"],
        "n": merged["count"],
        "size": merged["size"],
        "quality": merged["quality"],
    }
    if merged.get("background") and merged["background"] != "auto":
        payload["background"] = merged["background"]
    if merged.get("output_format"):
        payload["output_format"] = merged["output_format"]
    if merged.get("response_format"):
        payload["response_format"] = merged["response_format"]
    if merged.get("moderation"):
        payload["moderation"] = merged["moderation"]
    return payload


def build_openrouter_payload(merged: dict[str, Any]) -> dict[str, Any]:
    return {
        "model": merged["model"],
        "messages": [
            {
                "role": "user",
                "content": merged["prompt"],
            }
        ],
        "modalities": ["image", "text"],
        "image_config": {
            "aspect_ratio": merged["aspect_ratio"],
            "image_size": merged["image_size"],
        },
    }


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


def _novelai_decode_image_entry(entry: Any) -> bytes:
    """Decode one NovelAI image entry (legacy base64 str or object with image key)."""
    if isinstance(entry, str):
        return base64.b64decode(entry)
    if isinstance(entry, dict):
        for key in ("image", "b64_json", "data"):
            raw_b64 = entry.get(key)
            if isinstance(raw_b64, str) and raw_b64.strip():
                return base64.b64decode(raw_b64)
    raise RuntimeError("NovelAI JSON 応答の images/data の形式が未対応です")


def _novelai_json_images_to_bytes(images: list[Any]) -> list[tuple[str, bytes]]:
    out: list[tuple[str, bytes]] = []
    for idx, entry in enumerate(images, start=1):
        png_bytes = _novelai_decode_image_entry(entry)
        suffix = ".png"
        if isinstance(entry, dict):
            fname = entry.get("filename") or entry.get("name")
            if isinstance(fname, str) and fname.strip():
                suffix = Path(fname).suffix or suffix
        out.append((f"image_{idx:02d}{suffix}", png_bytes))
    return out


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
        images_bin = _novelai_json_images_to_bytes(images)
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
        image_bytes: bytes
        source: str
        if item.get("b64_json"):
            image_bytes = base64.b64decode(str(item["b64_json"]))
            source = "b64_json"
        elif item.get("url"):
            source = str(item["url"])
            _, image_bytes, _ = http_get_bytes(source, timeout)
        else:
            raise RuntimeError("Grok 応答 item に b64_json/url がありません")
        if len(image_bytes) < min_png:
            raise RuntimeError(f"Grok の返却画像が異常に小さい ({len(image_bytes)} bytes)")
        stem = f"{merged['file_prefix']}_{ts}_{idx:02d}"
        mime_type = str(item.get("mime_type") or "").lower()
        if "jpeg" in mime_type or "jpg" in mime_type or image_bytes.startswith(b"\xff\xd8\xff"):
            suffix = ".jpg"
        elif "webp" in mime_type or image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
            suffix = ".webp"
        else:
            suffix = ".png"
        image_path = out_dir / f"{stem}{suffix}"
        meta_path = out_dir / f"{stem}.json"
        image_path.write_bytes(image_bytes)
        meta = {
            "provider": "grok",
            "grok_payload_request": payload,
            "saved_image": str(image_path),
            "param_merged": {k: v for k, v in merged.items() if k != "prompt"},
            "prompt": merged["prompt"],
            "response_item": item,
            "image_source": source,
        }
        write_json(meta_path, meta)
        saved.append({"png": str(image_path), "json": str(meta_path), "index": idx})
    return saved


def save_openai_response(
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
        raise RuntimeError("OpenAI 応答から data を取得できませんでした")

    min_png = int(provider_cfg.get("min_png_bytes", 512))
    saved: list[dict[str, Any]] = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_format = str(merged.get("output_format") or "png").lower()
    suffix = ".jpg" if output_format in {"jpeg", "jpg"} else f".{output_format}"
    for idx, item in enumerate(data, start=1):
        if not isinstance(item, dict):
            raise RuntimeError("OpenAI 応答 data の形式が未対応です")
        image_bytes: bytes
        source: str
        if item.get("b64_json"):
            image_bytes = base64.b64decode(str(item["b64_json"]))
            source = "b64_json"
        elif item.get("url"):
            source = str(item["url"])
            _, image_bytes, _ = http_get_bytes(source, timeout)
        else:
            raise RuntimeError("OpenAI 応答 item に b64_json/url がありません")
        if len(image_bytes) < min_png:
            raise RuntimeError(f"OpenAI の返却画像が異常に小さい ({len(image_bytes)} bytes)")
        stem = f"{merged['file_prefix']}_{ts}_{idx:02d}"
        image_path = out_dir / f"{stem}{suffix}"
        meta_path = out_dir / f"{stem}.json"
        image_path.write_bytes(image_bytes)
        meta = {
            "provider": "openai",
            "openai_payload_request": payload,
            "saved_image": str(image_path),
            "param_merged": {k: v for k, v in merged.items() if k != "prompt"},
            "prompt": merged["prompt"],
            "response_item": item,
            "image_source": source,
        }
        write_json(meta_path, meta)
        saved.append({"png": str(image_path), "json": str(meta_path), "index": idx})
    return saved


def decode_openrouter_image_url(raw_url: str, timeout: float) -> tuple[bytes, str, str]:
    if raw_url.startswith("data:"):
        header, sep, data = raw_url.partition(",")
        if not sep or ";base64" not in header:
            raise RuntimeError("OpenRouter image_url が base64 data URL ではありません")
        mime = header[5:].split(";", 1)[0] or "image/png"
        suffix = ".jpg" if mime in {"image/jpeg", "image/jpg"} else ".webp" if mime == "image/webp" else ".png"
        return base64.b64decode(data), "data_url", suffix
    _, image_bytes, headers = http_get_bytes(raw_url, timeout)
    ctype = headers.get("Content-Type", "")
    suffix = ".jpg" if "jpeg" in ctype or "jpg" in ctype else ".webp" if "webp" in ctype else ".png"
    return image_bytes, raw_url, suffix


def diagnose_openrouter_auth_error(token: str, base_url: str, timeout: float) -> str:
    """Return a short hint when a key works for management APIs but not inference."""
    try:
        _, raw, _ = http_get_bytes(
            f"{base_url}/keys",
            min(timeout, 30),
            headers={"Authorization": f"Bearer {token}"},
        )
    except Exception:
        return ""
    try:
        data = parse_json_response(raw)
    except Exception:
        data = {}
    if isinstance(data, dict) and "data" in data:
        return (
            "\nOpenRouter 診断: このキーは /api/v1/keys には通るため、"
            "Management API Key の可能性があります。Management key は "
            "chat/completions には使えません。OpenRouter の通常の API Key を"
            "発行して OPENROUTER_API_KEY に設定してください。"
        )
    return ""


def save_openrouter_response(
    *,
    resp: dict[str, Any],
    merged: dict[str, Any],
    payload: dict[str, Any],
    provider_cfg: dict[str, Any],
    out_dir: Path,
    timeout: float,
) -> list[dict[str, Any]]:
    choices = resp.get("choices") or []
    if not choices:
        raise RuntimeError("OpenRouter 応答から choices を取得できませんでした")
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        raise RuntimeError("OpenRouter 応答 choices[0].message の形式が未対応です")
    images = message.get("images") or []
    if not images:
        raise RuntimeError("OpenRouter 応答 message.images が空です。model の output_modalities と modalities を確認してください")

    min_png = int(provider_cfg.get("min_png_bytes", 512))
    saved: list[dict[str, Any]] = []
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    for idx, item in enumerate(images, start=1):
        if not isinstance(item, dict):
            raise RuntimeError("OpenRouter 応答 images の形式が未対応です")
        image_url = item.get("image_url") or {}
        raw_url = image_url.get("url") if isinstance(image_url, dict) else None
        if not raw_url:
            raise RuntimeError("OpenRouter 応答 image_url.url がありません")
        image_bytes, source, suffix = decode_openrouter_image_url(str(raw_url), timeout)
        if len(image_bytes) < min_png:
            raise RuntimeError(f"OpenRouter の返却画像が異常に小さい ({len(image_bytes)} bytes)")
        stem = f"{merged['file_prefix']}_{ts}_{idx:02d}"
        image_path = out_dir / f"{stem}{suffix}"
        meta_path = out_dir / f"{stem}.json"
        image_path.write_bytes(image_bytes)
        meta = {
            "provider": "openrouter",
            "openrouter_payload_request": payload,
            "saved_image": str(image_path),
            "param_merged": {k: v for k, v in merged.items() if k != "prompt"},
            "prompt": merged["prompt"],
            "response_message_content": message.get("content"),
            "response_image": item,
            "image_source": source,
        }
        write_json(meta_path, meta)
        saved.append({"png": str(image_path), "json": str(meta_path), "index": idx})
    return saved


def _redact_large_payload_values(value: Any) -> Any:
    if isinstance(value, dict):
        return {k: _redact_large_payload_values(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_redact_large_payload_values(v) for v in value]
    if isinstance(value, str) and len(value) > 240 and _is_probably_base64(value):
        return f"{value[:80]}...(base64 {len(value)} chars)"
    return value


def print_dry_run(provider: str, api_url: str, payload: dict[str, Any]) -> None:
    print(
        json.dumps(
            {
                "provider": provider,
                "url": api_url,
                "payload": _redact_large_payload_values(payload),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="画像 provider 実行（Forge / NovelAI / Grok / OpenAI）")
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
                f"  例: python tools/image_provider_generate.py --params {ex} --dry-run",
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
        merged = merge_provider_defaults(provider, provider_cfg, params, root=root)
    except KeyError as e:
        print(f"config に必要キーがありません: {e}", file=sys.stderr)
        return 2
    except ValueError as e:
        print(str(e), file=sys.stderr)
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
    log_path = root / "logs" / "image_provider_generate.log"
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
            print(missing_auth_message(auth_env), file=sys.stderr)
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
    elif provider in _GROK_FAMILY:
        auth_env = str(provider_cfg.get("auth_env", "XAI_API_KEY"))
        token = resolve_env_value(auth_env, dotenv_map)
        if not token and not args.dry_run:
            print(missing_auth_message(auth_env), file=sys.stderr)
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
    elif provider == "openai":
        auth_env = str(provider_cfg.get("auth_env", "OPENAI_API_KEY"))
        token = resolve_env_value(auth_env, dotenv_map)
        if not token and not args.dry_run:
            print(missing_auth_message(auth_env), file=sys.stderr)
            return 2
        base_url = str(provider_cfg.get("base_url", "https://api.openai.com/v1")).rstrip("/")
        generate_path = str(provider_cfg.get("generate_path", "/images/generations"))
        api_url = f"{base_url}{generate_path}"
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        payload = build_openai_payload(merged)
        if args.dry_run:
            print_dry_run(provider, api_url, payload)
            return 0
        try:
            _, raw, _ = http_post_json(api_url, payload, timeout, headers=headers)
            resp = parse_json_response(raw)
            saved.extend(
                save_openai_response(
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
            append_log(log_path, f"FAIL provider=openai {msg}")
            print(msg, file=sys.stderr)
            return 4
        except Exception as e:
            append_log(log_path, f"ERROR provider=openai {e!r}")
            print(f"リクエスト失敗: {e}", file=sys.stderr)
            return 5
    elif provider == "openrouter":
        auth_env = str(provider_cfg.get("auth_env", "OPENROUTER_API_KEY"))
        token = resolve_env_value(auth_env, dotenv_map)
        if not token and not args.dry_run:
            print(missing_auth_message(auth_env), file=sys.stderr)
            return 2
        base_url = str(provider_cfg.get("base_url", "https://openrouter.ai/api/v1")).rstrip("/")
        generate_path = str(provider_cfg.get("generate_path", "/chat/completions"))
        api_url = f"{base_url}{generate_path}"
        headers = {"Authorization": f"Bearer {token}"} if token else {}
        payload = build_openrouter_payload(merged)
        if args.dry_run:
            print_dry_run(provider, api_url, payload)
            return 0
        try:
            _, raw, _ = http_post_json(api_url, payload, timeout, headers=headers)
            resp = parse_json_response(raw)
            saved.extend(
                save_openrouter_response(
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
            if e.code == 401 and token:
                msg += diagnose_openrouter_auth_error(token, base_url, timeout)
            append_log(log_path, f"FAIL provider=openrouter {msg}")
            print(msg, file=sys.stderr)
            return 4
        except Exception as e:
            append_log(log_path, f"ERROR provider=openrouter {e!r}")
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
