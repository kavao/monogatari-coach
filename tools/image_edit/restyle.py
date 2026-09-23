"""NovelAI Image2Image restyle planning and execution.

This module is deliberately separate from ``image_provider_generate.py``.
The existing command remains the txt2img entry point; this module owns the
explicit restyle operation, its dry-run contract, and redacted run records.
"""

from __future__ import annotations

import base64
import hashlib
import json
import math
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps

try:  # script execution puts ``tools`` on sys.path
    import image_provider_generate as generate
    from novel_meta_yaml import resolve_novelai_portion_strict
except ModuleNotFoundError:  # pragma: no cover - package import fallback
    from .. import image_provider_generate as generate
    from ..novel_meta_yaml import resolve_novelai_portion_strict

from .contracts import (
    REFERENCE_CONTRACT_VERSION,
    validate_ordered_image_inputs,
    validate_reference_contract,
)


class RestyleError(ValueError):
    """A user-correctable restyle planning or validation error."""


_ALLOWED_OPTION_KEYS = frozenset(
    {
        "strength",
        "noise",
        "seed",
        "extra_noise_seed",
        "add_original_image",
        "quality_toggle",
        "quality_preset",
        "uc_preset",
        "steps",
        "cfg_scale",
        "sampler_name",
        "width",
        "height",
        "aspect_ratio_preset",
        "upscaled_enhance",
        "straight_alpha",
        "tag_hint_transparent_background",
        "tag_hint_qt",
        "tag_hint_uc_preset",
        "prefer_brownian",
        "v4_use_coords",
    }
)

_QUALITY_MARKERS: dict[str, tuple[str, ...]] = {
    "nai-diffusion-4-5-full": (
        "location",
        "very aesthetic",
        "masterpiece",
        "no text",
    ),
    "nai-diffusion-4-5-curated": (
        "very aesthetic",
        "location",
        "masterpiece",
        "no text",
        "rating:general",
    ),
}


@dataclass(frozen=True)
class ImageInspection:
    path: Path
    sha256: str
    format: str
    width: int
    height: int
    oriented_width: int
    oriented_height: int
    mode: str
    exif_orientation: int
    alpha_present: bool

    @property
    def has_alpha(self) -> bool:
        return self.alpha_present


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def file_sha256(path: Path) -> str:
    return _sha256_bytes(path.read_bytes())


def _parse_alpha_background(value: str | None) -> tuple[int, int, int] | None:
    if value is None:
        return None
    normalized = str(value).strip().lower()
    if normalized == "white":
        return (255, 255, 255)
    if normalized.startswith("#"):
        normalized = normalized[1:]
    if len(normalized) != 6 or any(char not in "0123456789abcdef" for char in normalized):
        raise RestyleError("alpha-background は white または #RRGGBB で指定してください")
    return tuple(int(normalized[index : index + 2], 16) for index in (0, 2, 4))  # type: ignore[return-value]


def _alpha_background_name(color: tuple[int, int, int] | None) -> str | None:
    if color is None:
        return None
    return "#%02x%02x%02x" % color


def inspect_source_image(path: Path, *, allow_alpha: bool = False) -> ImageInspection:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise RestyleError(f"元画像が見つかりません: {path}")
    try:
        raw = path.read_bytes()
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            image.load()
            fmt = str(image.format or "").upper()
            if fmt not in {"PNG", "JPEG"}:
                raise RestyleError(
                    f"元画像の形式はPNG/JPEGのみ対応です: {path} ({fmt or 'unknown'})"
                )
            exif_orientation = int(image.getexif().get(274, 1) or 1)
            oriented_width, oriented_height = image.size
            if exif_orientation in {5, 6, 7, 8}:
                oriented_width, oriented_height = image.size[1], image.size[0]
            has_alpha = image.mode in {"RGBA", "LA", "PA"} or (
                image.mode == "P" and "transparency" in image.info
            )
            if has_alpha and not allow_alpha:
                raise RestyleError(
                    "RGBA/透過入力はMVP未対応です。背景合成やRGB変換をせず停止します。"
                )
            return ImageInspection(
                path=path,
                sha256=_sha256_bytes(raw),
                format=fmt,
                width=image.width,
                height=image.height,
                oriented_width=oriented_width,
                oriented_height=oriented_height,
                mode=image.mode,
                exif_orientation=exif_orientation,
                alpha_present=has_alpha,
            )
    except RestyleError:
        raise
    except Exception as exc:
        raise RestyleError(f"元画像をデコードできません: {path}: {exc}") from exc


def _fit_dimensions_preserving_aspect(width: int, height: int) -> tuple[int, int]:
    """Choose a supported canvas without needlessly upscaling the source.

    NovelAI dimensions are multiples of 64.  Rounding each edge separately
    can change a source ratio substantially (for example 200x100 ->
    192x128).  Enumerating supported canvases up to the source dimensions lets
    us choose the closest ratio and leave any remaining mismatch to the
    explicit letterbox step.
    """
    max_width = max(64, min(2048, width))
    max_height = max(64, min(2048, height))
    widths = list(range(64, max_width + 1, 64)) or [64]
    heights = list(range(64, max_height + 1, 64)) or [64]
    source_ratio = width / height
    candidates = [(candidate_w, candidate_h) for candidate_w in widths for candidate_h in heights]
    return min(
        candidates,
        key=lambda item: (
            abs(math.log((item[0] / item[1]) / source_ratio)),
            -item[0] * item[1],
        ),
    )


def dimension_proposal(
    inspection: ImageInspection,
    *,
    target_width: int | None = None,
    target_height: int | None = None,
) -> dict[str, Any] | None:
    if target_width is None and target_height is None:
        width, height = _fit_dimensions_preserving_aspect(
            inspection.oriented_width, inspection.oriented_height
        )
    else:
        width = target_width or inspection.oriented_width
        height = target_height or inspection.oriented_height
    needs = (
        inspection.exif_orientation != 1
        or inspection.oriented_width != width
        or inspection.oriented_height != height
        or width % 64 != 0
        or height % 64 != 0
        or width > 2048
        or height > 2048
    )
    if not needs:
        return None
    return {
        "kind": "letterbox_or_orientation_normalization",
        "approved": False,
        "source_dimensions": [inspection.oriented_width, inspection.oriented_height],
        "target_dimensions": [width, height],
        "preserve_aspect_ratio": True,
        "background": "white",
        "warning": "余白も再描画され得るため、承認なしに送信しない",
    }


def _write_prepared_image(
    inspection: ImageInspection,
    target: tuple[int, int],
    destination: Path,
    *,
    alpha_background: tuple[int, int, int] | None = None,
) -> ImageInspection:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with Image.open(inspection.path) as source:
        normalized = ImageOps.exif_transpose(source)
        has_alpha = normalized.mode in {"RGBA", "LA", "PA"} or (
            normalized.mode == "P" and "transparency" in normalized.info
        )
        if has_alpha:
            if alpha_background is None:
                raise RestyleError("RGBA/透過入力には明示的なalpha-backgroundが必要です")
            matte = Image.new("RGBA", normalized.size, (*alpha_background, 255))
            normalized = Image.alpha_composite(matte, normalized.convert("RGBA")).convert("RGB")
        else:
            normalized = normalized.convert("RGB")
        if normalized.size != target:
            fitted = ImageOps.contain(normalized, target)
            canvas = Image.new("RGB", target, (255, 255, 255))
            x = (target[0] - fitted.width) // 2
            y = (target[1] - fitted.height) // 2
            canvas.paste(fitted, (x, y))
            normalized = canvas
        normalized.save(destination, format="PNG")
    return inspect_source_image(destination)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RestyleError(f"JSONを読めません: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RestyleError(f"JSONのルートはobjectである必要があります: {path}")
    return data


def load_prompt_candidates(path: Path) -> dict[str, str]:
    """Read only the explicitly allowed top-level prompt keys from a sidecar."""
    data = _load_json(path)
    out: dict[str, str] = {}
    for key in ("prompt", "negative_prompt"):
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, str):
            raise RestyleError(f"同名JSONの {key} は文字列である必要があります: {path}")
        out[key] = value
    return out


def _quality_marker_state(model: str, prompt: str) -> str:
    base = generate._novelai_model_base(model)
    markers = _QUALITY_MARKERS.get(base)
    if not markers:
        return "unknown"
    lower = prompt.lower()
    present = [marker for marker in markers if marker in lower]
    if not present:
        return "absent"
    if len(present) == len(markers):
        return "complete"
    # Even one marker can be an intentional content instruction (for example
    # ``no text``), so do not silently duplicate it.  Ask for an explicit
    # quality_toggle=false or a cleaned prompt when the full suffix is unclear.
    return "partial"


def _prepare_prompt(
    model: str,
    prompt: str,
    *,
    quality_toggle: bool,
    quality_preset: str,
) -> tuple[str, str]:
    if not quality_toggle:
        return prompt, "disabled"
    state = _quality_marker_state(model, prompt)
    if state == "partial":
        raise RestyleError(
            "品質接尾辞の一部だけがpromptに含まれています。"
            "二重付加を避けるため、promptを整理するか quality_toggle=false を明示してください。"
        )
    if state == "complete":
        return prompt, "already_present"
    return (
        generate._novelai_augment_prompt(
            model, prompt, quality_toggle=True, quality_preset=quality_preset
        ),
        "appended",
    )


def _validate_number(name: str, value: Any, *, minimum: float = 0.0, maximum: float = 1.0) -> float:
    if isinstance(value, bool):
        raise RestyleError(f"{name} は数値で指定してください")
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RestyleError(f"{name} は数値で指定してください") from exc
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise RestyleError(f"{name} は {minimum}〜{maximum} の有限数で指定してください: {value!r}")
    return number


def _validate_options(options: dict[str, Any]) -> dict[str, Any]:
    unknown = sorted(set(options) - _ALLOWED_OPTION_KEYS)
    if unknown:
        raise RestyleError(f"NovelAI restyleの未知オプションです: {', '.join(unknown)}")
    out = dict(options)
    out["strength"] = _validate_number("strength", out.get("strength", 0.5))
    out["noise"] = _validate_number("noise", out.get("noise", 0.0))
    for key in (
        "quality_toggle",
        "upscaled_enhance",
        "straight_alpha",
        "tag_hint_transparent_background",
        "prefer_brownian",
        "v4_use_coords",
    ):
        if key in out and not isinstance(out[key], bool):
            raise RestyleError(f"{key} はbooleanで指定してください")
    if "quality_preset" in out and str(out["quality_preset"]).lower() not in {"standard", "light"}:
        raise RestyleError("quality_preset は standard / light のみです")
    if "add_original_image" in out and not isinstance(out["add_original_image"], bool):
        raise RestyleError("add_original_image はbooleanで指定してください")
    for key in ("seed", "extra_noise_seed"):
        if key in out:
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError) as exc:
                raise RestyleError(f"{key} は整数で指定してください") from exc
            if out[key] < 0:
                raise RestyleError(f"{key} は0以上で指定してください")
    if "width" in out or "height" in out:
        if "width" not in out or "height" not in out:
            raise RestyleError("width と height は同時に指定してください")
        for key in ("width", "height"):
            try:
                out[key] = int(out[key])
            except (TypeError, ValueError) as exc:
                raise RestyleError(f"{key} は整数で指定してください") from exc
    return out


def _new_run_id() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def _redact_value(value: Any, *, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: _redact_value(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, list):
        if key in {"reference_image_multiple", "images"}:
            return [
                {"redacted": True, "length": len(v)} if isinstance(v, str) else _redact_value(v)
                for v in value
            ]
        return [_redact_value(v, key=key) for v in value]
    if isinstance(value, str) and (key == "image" or len(value) > 240 and generate._is_probably_base64(value)):
        return {
            "redacted": True,
            "length": len(value),
            "sha256": _sha256_bytes(value.encode("ascii", errors="ignore")),
        }
    return value


def redact_payload(payload: dict[str, Any]) -> dict[str, Any]:
    return _redact_value(payload)  # type: ignore[return-value]


def _reference_records(
    paths: list[Path],
    *,
    role: str,
    start_order: int,
) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for offset, path in enumerate(paths):
        resolved = path.expanduser().resolve()
        if not resolved.is_file():
            raise RestyleError(f"画像参照ファイルが見つかりません: {resolved}")
        records.append(
            {
                "path": str(resolved),
                "sha256": file_sha256(resolved),
                "role": role,
                "order": start_order + offset,
                "kind": "novelai_vibe" if resolved.suffix.lower() in {".naiv4vibe", ".naiv4vibebundle"} else "image",
            }
        )
    return records


def _style_reference_records(paths: list[Path], *, start_order: int = 2) -> list[dict[str, Any]]:
    return _reference_records(paths, role="style", start_order=start_order)


def _source_json_default(source: Path) -> Path | None:
    candidate = source.with_suffix(".json")
    return candidate if candidate.is_file() else None


def _resolve_output_dir(root: Path, raw: str) -> Path:
    value = Path(raw)
    resolved = (root / value).resolve() if not value.is_absolute() else value.resolve()
    if not any(part.lower() == "_restyle" for part in resolved.parts):
        resolved = resolved / "_restyle"
    return resolved


def _load_capabilities(root: Path) -> dict[str, Any]:
    path = root / "tools" / "image_edit" / "novelai_capabilities.yaml"
    try:
        import yaml

        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise RestyleError(f"NovelAI capability表を読めません: {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise RestyleError(f"NovelAI capability表の形式が不正です: {path}")
    return data


def _safe_artifact_filename(value: str, *, label: str) -> str:
    name = str(value)
    if not name or Path(name).name != name or name in {".", ".."}:
        raise RestyleError(f"{label}は単純なファイル名で指定してください")
    if Path(name).suffix.lower() != ".json" and label.endswith("計画"):
        raise RestyleError(f"{label}は.jsonで指定してください")
    return name


def save_restyle_plan(plan: dict[str, Any], *, filename: str = "restyle_plan.json") -> Path:
    """Persist a redacted dry-run plan in its isolated run directory."""
    run_dir = Path(str(plan.get("output_dir", ""))).expanduser().resolve()
    if not any(part.lower() == "_restyle" for part in run_dir.parts):
        raise RestyleError("restyle計画の出力先は _restyle/ 配下である必要があります")
    filename = _safe_artifact_filename(filename, label="restyle計画")
    plan_path = run_dir / filename
    plan["plan_path"] = str(plan_path)
    _save_json(plan_path, plan)
    return plan_path


def load_restyle_plan(path: Path) -> dict[str, Any]:
    """Load and validate the exact plan produced by a dry-run."""
    plan_path = path.expanduser().resolve()
    plan = _load_json(plan_path)
    required = {
        "schema_version": "1.0",
        "operation": "image_to_image",
        "intent": "restyle",
        "provider": "novelai",
        "action": "img2img",
    }
    for key, expected in required.items():
        if plan.get(key) != expected:
            raise RestyleError(f"承認済みrestyle計画の {key} が不正です")
    output_dir = Path(str(plan.get("output_dir", ""))).expanduser().resolve()
    if not any(part.lower() == "_restyle" for part in output_dir.parts):
        raise RestyleError("承認済みrestyle計画の出力先は _restyle/ 配下である必要があります")
    try:
        plan_path.relative_to(output_dir)
    except ValueError as exc:
        raise RestyleError("restyle計画のパスがoutput_dir配下にありません") from exc
    if not isinstance(plan.get("source_image"), dict) or not plan["source_image"].get("sha256"):
        raise RestyleError("承認済みrestyle計画に元画像hashがありません")
    if not isinstance(plan.get("payload"), dict):
        raise RestyleError("承認済みrestyle計画にpayloadがありません")
    request = plan.get("request")
    if not isinstance(request, dict):
        raise RestyleError("承認済みrestyle計画に共通request contractがありません")
    contract_version = str(request.get("reference_contract_version", "1.0"))
    if contract_version == REFERENCE_CONTRACT_VERSION:
        try:
            ordered = validate_reference_contract(
                source_images=request.get("source_images"),
                style_references=request.get("style_references"),
                ordered_image_inputs=request.get("ordered_image_inputs"),
            )
        except ValueError as exc:
            raise RestyleError(str(exc)) from exc
        expected_guided = len(ordered) > 1
        if request.get("reference_guided_generation") is not expected_guided:
            raise RestyleError(
                "画像参照契約のreference_guided_generationが入力件数と一致しません"
            )
    elif contract_version != "1.0":
        raise RestyleError(f"未知の参照契約versionです: {contract_version!r}")
    alpha_handling = plan.get("alpha_handling", {"kind": "none"})
    if not isinstance(alpha_handling, dict) or alpha_handling.get("kind") not in {
        "none",
        "flatten_to_rgb",
    }:
        raise RestyleError("承認済みrestyle計画のalpha-handlingが不正です")
    if alpha_handling.get("kind") == "flatten_to_rgb":
        alpha_color = _parse_alpha_background(str(alpha_handling.get("background", "")))
        transform = plan.get("transformation") or {"kind": "none"}
        if transform.get("kind") != "none" and alpha_color != (255, 255, 255):
            raise RestyleError(
                "承認済みrestyle計画の非白alpha-backgroundと寸法変換の併用は未検証です"
            )
    plan["plan_path"] = str(plan_path)
    return plan


def build_restyle_plan(
    *,
    root: Path,
    source_path: Path,
    model: str,
    prompt: str,
    negative_prompt: str = "",
    style_reference_paths: list[Path] | None = None,
    reference_paths: list[tuple[str, Path]] | None = None,
    options: dict[str, Any] | None = None,
    output_dir: str,
    run_id: str | None = None,
    target_size: tuple[int, int] | None = None,
    allow_transform: bool = False,
    alpha_background: str | None = None,
    run_dir: Path | None = None,
    prepared_filename: str | None = None,
) -> dict[str, Any]:
    if not model:
        raise RestyleError("restyle先のmodelは明示指定が必要です")
    model_id = str(generate.resolve_named_value(model, {"v4-5-full": "nai-diffusion-4-5-full"}))
    if model_id != "nai-diffusion-4-5-full":
        raise RestyleError(
            "MVPのNovelAI restyle modelは nai-diffusion-4-5-full のみです。"
            "V5や未検証modelへ黙って切り替えません。"
        )
    alpha_color = _parse_alpha_background(alpha_background)
    source = inspect_source_image(source_path, allow_alpha=alpha_color is not None)
    opts = _validate_options(options or {})
    quality_toggle = bool(opts.get("quality_toggle", True))
    quality_preset = str(opts.get("quality_preset", "standard"))
    effective_prompt, prompt_action = _prepare_prompt(
        model_id,
        prompt,
        quality_toggle=quality_toggle,
        quality_preset=quality_preset,
    )
    style_paths = [Path(p) for p in (style_reference_paths or [])]
    style_records = _style_reference_records(style_paths)
    if not style_paths and opts.get("style_reference"):
        raise RestyleError("style_referenceはCLIの参照指定で渡してください")
    other_records: list[dict[str, Any]] = []
    for role, path in reference_paths or []:
        normalized_role = str(role).strip().lower()
        if normalized_role != "style":
            raise RestyleError(
                "NovelAI restyleで現在送信できる参照roleはstyleだけです: "
                f"{normalized_role!r}"
            )
        other_records.extend(
            _reference_records(
                [Path(path)], role=normalized_role, start_order=2 + len(style_records) + len(other_records)
            )
        )
    if other_records:
        style_records.extend(other_records)
    ordered_inputs = [
        {
            "path": str(source.path),
            "sha256": source.sha256,
            "role": "source",
            "order": 1,
            "dimensions": [source.oriented_width, source.oriented_height],
        },
        *style_records,
    ]
    try:
        validate_ordered_image_inputs(ordered_inputs, label="restyle.ordered_image_inputs")
    except ValueError as exc:
        raise RestyleError(str(exc)) from exc

    width = opts.get("width")
    height = opts.get("height")
    requested_width = int(width) if width is not None else (target_size[0] if target_size else None)
    requested_height = int(height) if height is not None else (target_size[1] if target_size else None)
    if requested_width is not None or requested_height is not None:
        if requested_width is None or requested_height is None:
            raise RestyleError("変換先のwidthとheightは同時に指定してください")
        if (
            requested_width < 64
            or requested_height < 64
            or requested_width > 2048
            or requested_height > 2048
            or requested_width % 64
            or requested_height % 64
        ):
            raise RestyleError("NovelAIの変換先寸法は64の倍数、64〜2048の範囲で指定してください")
    transform = dimension_proposal(
        source,
        target_width=requested_width,
        target_height=requested_height,
    )
    if transform and source.has_alpha and alpha_color not in {None, (255, 255, 255)}:
        raise RestyleError(
            "非白のalpha-backgroundと寸法変換の併用は未検証です。"
            "白で再計画するか、寸法変換なしで指定してください。"
        )
    if transform and allow_transform:
        transform = dict(transform)
        transform["approved"] = True
    elif transform:
        transform = dict(transform)
        transform["approved"] = False

    run = run_id or _new_run_id()
    out_root = _resolve_output_dir(root, output_dir)
    resolved_run_dir = Path(run_dir).expanduser().resolve() if run_dir is not None else out_root / run
    if not any(part.lower() == "_restyle" for part in resolved_run_dir.parts):
        raise RestyleError("restyleの出力先は _restyle/ 配下である必要があります")
    prepared_name = prepared_filename or "prepared_source.png"
    if Path(prepared_name).name != prepared_name or Path(prepared_name).suffix.lower() != ".png":
        raise RestyleError("前処理画像のファイル名は単純なPNG名で指定してください")
    alpha_handling: dict[str, Any] = {
        "kind": "flatten_to_rgb" if source.has_alpha else "none",
        "approved": True,
    }
    prepared_info: ImageInspection | None = None
    prepared_path = source.path
    if source.has_alpha:
        alpha_handling["background"] = _alpha_background_name(alpha_color)
        alpha_handling["source_mode"] = source.mode
        prepared_path = resolved_run_dir / prepared_name
        target = (
            (int(transform["target_dimensions"][0]), int(transform["target_dimensions"][1]))
            if transform
            else (source.oriented_width, source.oriented_height)
        )
        prepared_info = _write_prepared_image(
            source,
            target,
            prepared_path,
            alpha_background=alpha_color,
        )

    cfg = generate.load_root_config(root / "config" / "image_generation.json")
    provider_cfg = cfg.get("providers", {}).get("novelai", {})
    params: dict[str, Any] = {
        "prompt": prompt,
        "negative_prompt": negative_prompt,
        "model": model_id,
        "action": "img2img",
        "reference_image_paths": [str(p.resolve()) for p in style_paths],
        "quality_toggle": quality_toggle and prompt_action == "appended",
    }
    for key, value in opts.items():
        if key not in {"strength", "noise", "quality_toggle", "width", "height"}:
            params[key] = value
    if transform:
        params["width"], params["height"] = (
            int(transform["target_dimensions"][0]),
            int(transform["target_dimensions"][1]),
        )
    else:
        params["width"], params["height"] = source.oriented_width, source.oriented_height
    merged = generate.merge_provider_defaults("novelai", provider_cfg, params, root=root)
    # If the source already contained the suffix, preserve it without asking
    # the existing txt2img augmenter to append it again.
    merged["prompt"] = prompt if prompt_action == "already_present" else prompt
    seed = int(opts.get("seed", 0))
    payload = generate.build_novelai_payload(merged, seed_for_request=seed)
    payload["action"] = "img2img"
    payload["parameters"]["image"] = base64.b64encode(prepared_path.read_bytes()).decode("ascii")
    payload["parameters"]["strength"] = opts["strength"]
    payload["parameters"]["noise"] = opts["noise"]
    if "add_original_image" not in opts:
        payload["parameters"].pop("add_original_image", None)
    if transform and not transform["approved"]:
        sendable = False
    else:
        sendable = True

    request_contract = {
        "schema_version": "1.0",
        "reference_contract_version": REFERENCE_CONTRACT_VERSION,
        "operation": "image_to_image",
        "intent": "restyle",
        "provider": "novelai",
        "model": model_id,
        "source_images": [
            {
                "path": str(source.path),
                "sha256": source.sha256,
                "dimensions": [source.oriented_width, source.oriented_height],
            }
        ],
        "instruction": effective_prompt,
        "style_references": style_records,
        "ordered_image_inputs": ordered_inputs,
        "reference_guided_generation": bool(style_records),
        "size_policy": transform or {"kind": "same_dimensions"},
        "output_dir": str(resolved_run_dir),
        "provider_options": {
            key: value for key, value in opts.items() if key != "quality_toggle"
        },
    }
    return {
        "schema_version": "1.0",
        "operation": "image_to_image",
        "intent": "restyle",
        "provider": "novelai",
        "model": model_id,
        "action": "img2img",
        "run_id": run,
        "request": request_contract,
        "source_image": {
            "path": str(source.path),
            "sha256": source.sha256,
            "format": source.format,
            "dimensions": [source.oriented_width, source.oriented_height],
            "exif_orientation": source.exif_orientation,
        },
        "preprocessed_image": (
            {
                "status": "prepared",
                "path": str(prepared_info.path),
                "sha256": prepared_info.sha256,
                "dimensions": [prepared_info.oriented_width, prepared_info.oriented_height],
                "alpha_handling": alpha_handling,
            }
            if prepared_info
            else (
                {
                    "status": "same_as_source",
                    "sha256": source.sha256,
                    "dimensions": [source.oriented_width, source.oriented_height],
                }
                if not transform
                else {
                    "status": "pending_transform_approval",
                    "target_dimensions": transform["target_dimensions"],
                }
            )
        ),
        "style_references": style_records,
        "ordered_image_inputs": ordered_inputs,
        "reference_contract_version": REFERENCE_CONTRACT_VERSION,
        "reference_guided_generation": bool(style_records),
        "prompt": {
            "source_value": prompt,
            "value": effective_prompt,
            "negative_prompt": negative_prompt,
            "quality_suffix": prompt_action,
            "source": "explicit",
        },
        "provider_options": {
            key: value for key, value in opts.items() if key not in {"quality_toggle"}
        },
        "transformation": transform or {"kind": "none", "approved": True},
        "alpha_handling": alpha_handling,
        "prepared_image": (
            {
                "path": str(prepared_info.path),
                "sha256": prepared_info.sha256,
                "dimensions": [prepared_info.oriented_width, prepared_info.oriented_height],
            }
            if prepared_info
            else None
        ),
        "capabilities": _load_capabilities(root),
        "output_dir": str(resolved_run_dir),
        "sendable": sendable,
        "payload": redact_payload(payload),
        "approval": {
            "dry_run_required": True,
            "network_sent": False,
            "provider_switch": False,
        },
        "notes": [
            "元画像とVibe参照は別payload項目",
            "RGBA入力は明示したalpha-backgroundで作業用RGBへ合成し、元画像を変更しない",
            "保存JSONにはbase64・Vibe encoding・認証ヘッダーを含めない",
            "再描画結果を次の入力へ自動連鎖しない",
            "画像参照のroleと送信順は共通contractへ固定し、provider adapterで再検証する",
        ],
    }


def _payload_with_source_image(plan: dict[str, Any], source_path: Path) -> dict[str, Any]:
    payload = json.loads(json.dumps(plan["payload"]))
    # The plan payload is redacted, so rebuild the request through the source
    # metadata only at execute time. The caller replaces the redacted field.
    raw = source_path.read_bytes()
    payload.setdefault("parameters", {})["image"] = base64.b64encode(raw).decode("ascii")
    return payload


def _save_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _response_images(raw: bytes, headers: dict[str, str]) -> list[tuple[str, bytes]]:
    if "application/json" in headers.get("content-type", "").lower():
        response = generate.parse_json_response(raw)
        images = response.get("images") or response.get("data") or []
        return generate._novelai_json_images_to_bytes(images)
    return generate.extract_zip_images(raw)


def execute_restyle(
    *,
    root: Path,
    plan: dict[str, Any],
    provider_cfg: dict[str, Any],
    allow_transform: bool = False,
) -> dict[str, Any]:
    if not plan.get("sendable"):
        raise RestyleError("寸法変換案が未承認です。dry-runを確認し、明示的に変換を承認してください")
    source_path = Path(plan["source_image"]["path"])
    alpha_handling = plan.get("alpha_handling") or {"kind": "none"}
    alpha_color = _parse_alpha_background(alpha_handling.get("background"))
    allow_alpha = alpha_handling.get("kind") == "flatten_to_rgb"
    current_source = inspect_source_image(source_path, allow_alpha=allow_alpha)
    if current_source.sha256 != plan["source_image"]["sha256"]:
        raise RestyleError("元画像のhashがdry-run後に変わっています。再計画してください")
    for reference in plan.get("style_references", []):
        reference_path = Path(str(reference["path"]))
        if file_sha256(reference_path) != reference["sha256"]:
            raise RestyleError(
                f"絵柄参照のhashがdry-run後に変わっています。再計画してください: {reference_path}"
            )
    ordered_inputs = plan.get("ordered_image_inputs") or []
    if ordered_inputs:
        try:
            normalized_inputs = validate_ordered_image_inputs(
                ordered_inputs,
                label="restyle.ordered_image_inputs",
            )
        except ValueError as exc:
            raise RestyleError(str(exc)) from exc
        for record in normalized_inputs:
            input_path = Path(str(record["path"])).expanduser().resolve()
            if not input_path.is_file():
                raise RestyleError(f"参照画像ファイルが見つかりません: {input_path}")
            if file_sha256(input_path) != str(record["sha256"]):
                raise RestyleError(
                    "画像参照のhashがdry-run後に変わっています。再計画してください: "
                    f"{input_path}"
                )
    run_dir = Path(plan["output_dir"]).expanduser().resolve()
    if not any(part.lower() == "_restyle" for part in run_dir.parts):
        raise RestyleError("restyleの出力先は _restyle/ 配下である必要があります")
    run_dir.mkdir(parents=True, exist_ok=True)
    plan_path = Path(str(plan.get("plan_path") or (run_dir / "restyle_plan.json"))).expanduser().resolve()
    try:
        plan_path.relative_to(run_dir)
    except ValueError as exc:
        raise RestyleError("restyle計画のパスがoutput_dir配下にありません") from exc
    if not plan_path.is_file():
        raise RestyleError("executeにはdry-runで保存した restyle_plan.json が必要です")

    prepared_path = source_path
    transform = plan.get("transformation") or {}
    needs_preparation = transform.get("kind") != "none" or allow_alpha
    if needs_preparation:
        if not transform.get("approved"):
            raise RestyleError("寸法変換は明示承認なしに実行できません")
        if transform.get("kind") != "none":
            raw_target = transform["target_dimensions"]
            target = (int(raw_target[0]), int(raw_target[1]))
        else:
            target = (current_source.oriented_width, current_source.oriented_height)
        prepared_value = (plan.get("prepared_image") or {}).get("path")
        prepared = (
            Path(str(prepared_value)).expanduser().resolve()
            if prepared_value
            else run_dir / "prepared_source.png"
        )
        try:
            prepared.relative_to(run_dir)
        except ValueError as exc:
            raise RestyleError("前処理画像のパスがoutput_dir配下にありません") from exc
        prepared_info = _write_prepared_image(
            current_source,
            target,
            prepared,
            alpha_background=alpha_color,
        )
        expected_prepared = plan.get("prepared_image")
        if isinstance(expected_prepared, dict) and expected_prepared.get("sha256"):
            if prepared_info.sha256 != str(expected_prepared["sha256"]):
                raise RestyleError(
                    "前処理済み画像のhashがdry-run後に変わっています。再計画してください"
                )
        plan["prepared_image"] = {
            "path": str(prepared),
            "sha256": prepared_info.sha256,
            "dimensions": [prepared_info.oriented_width, prepared_info.oriented_height],
        }
        plan["preprocessed_image"] = {
            "status": "prepared",
            "sha256": prepared_info.sha256,
            "dimensions": [prepared_info.oriented_width, prepared_info.oriented_height],
        }
        _save_json(plan_path, plan)
        prepared_path = prepared

    payload = _payload_with_source_image(plan, prepared_path)
    payload["parameters"]["reference_image_multiple"] = []
    # Rebuild the unredacted provider payload through the normal helper so Vibe
    # encodings and coefficients are loaded only for the actual request.
    opts = dict(plan.get("provider_options") or {})
    params = {
        "prompt": str(plan["prompt"].get("source_value", plan["prompt"]["value"])),
        "negative_prompt": str(plan["prompt"].get("negative_prompt", "")),
        "model": str(plan["model"]),
        "action": "img2img",
        "reference_image_paths": [item["path"] for item in plan.get("style_references", [])],
        **opts,
    }
    params["quality_toggle"] = plan["prompt"].get("quality_suffix") == "appended"
    merged = generate.merge_provider_defaults("novelai", provider_cfg, params, root=root)
    unredacted = generate.build_novelai_payload(merged, seed_for_request=int(opts.get("seed", 0)))
    unredacted["action"] = "img2img"
    unredacted["parameters"]["image"] = base64.b64encode(prepared_path.read_bytes()).decode("ascii")
    unredacted["parameters"]["strength"] = float(opts.get("strength", 0.5))
    unredacted["parameters"]["noise"] = float(opts.get("noise", 0.0))
    if "add_original_image" not in opts:
        unredacted["parameters"].pop("add_original_image", None)

    auth_env = str(provider_cfg.get("auth_env", "NOVELAI_ACCESS_TOKEN"))
    token = generate.resolve_env_value(auth_env, generate.load_dotenv(root / ".env"))
    if not token:
        raise RestyleError(f"{auth_env} が見つかりません。実行前に認証を設定してください")
    base_url = str(provider_cfg.get("base_url", "https://image.novelai.net")).rstrip("/")
    path = str(provider_cfg.get("generate_path", "/ai/generate-image"))
    headers = {"Accept": "application/json", "Authorization": f"Bearer {token}"}
    extra_headers = provider_cfg.get("default_request_headers")
    if isinstance(extra_headers, dict):
        headers.update({str(k): str(v) for k, v in extra_headers.items() if v is not None})
    _, raw, response_headers = generate.http_post_json(
        f"{base_url}{path}",
        unredacted,
        float(provider_cfg.get("timeout_sec", 300)),
        headers=headers,
    )
    saved: list[dict[str, Any]] = []
    images = _response_images(raw, response_headers)
    for idx, (name, image_bytes) in enumerate(images, start=1):
        candidate_id = f"candidate_{idx:02d}"
        suffix = Path(name).suffix or ".png"
        image_path = run_dir / f"{source_path.stem}_restyle_{plan['run_id']}_{candidate_id}{suffix}"
        meta_path = image_path.with_suffix(".json")
        image_path.write_bytes(image_bytes)
        meta = {
            "schema_version": "1.0",
            "provider": "novelai",
            "operation": "image_to_image",
            "intent": "restyle",
            "run_id": plan["run_id"],
            "candidate_id": candidate_id,
            "source_image": plan["source_image"],
            "prepared_image": plan.get("prepared_image"),
            "style_references": plan.get("style_references", []),
            "model": plan["model"],
            "prompt": plan["prompt"],
            "provider_options": plan.get("provider_options", {}),
            "payload": redact_payload(unredacted),
            "saved_image": str(image_path),
            "status": "success",
            "adoption": {"status": "unadopted"},
        }
        _save_json(meta_path, meta)
        saved.append({"candidate_id": candidate_id, "image": str(image_path), "json": str(meta_path)})

    manifest = {
        "schema_version": "1.0",
        "run_id": plan["run_id"],
        "status": "success" if saved else "failed",
        "provider": "novelai",
        "model": plan["model"],
        "source_image": plan["source_image"],
        "style_references": plan.get("style_references", []),
        "candidates": saved,
        "adoption": {"status": "unadopted"},
    }
    result_filename = str(plan.get("result_manifest_filename") or "restyle_run.json")
    if Path(result_filename).name != result_filename or Path(result_filename).suffix.lower() != ".json":
        raise RestyleError("結果manifestのファイル名は単純なJSON名で指定してください")
    _save_json(run_dir / result_filename, manifest)
    return manifest
