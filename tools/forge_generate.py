#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Stable Diffusion WebUI / Forge 互換 API への最小 txt2img クライアント（v1）。

- POST /sdapi/v1/txt2img（save_images は使わず、返却 base64 を自前保存）
- 設定は config/forge_config.json（リポジトリルート基準）
- 仕様・運用: .rulesync/skills/forge-txt2img/SKILL.md

前提: Forge / WebUI を --api 付きで起動し、GET /sdapi/v1/samplers が 200 になること（/docs だけ 200 では不十分な場合あり）。
"""

from __future__ import annotations

import argparse
import base64
import json
import random
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


API_404_HINT = """\
A1111 互換 REST API (/sdapi/v1/...) が応答しません (HTTP 404)。
Gradio の UI 用 URL「Running on http://127.0.0.1:7860」だけでは、/sdapi が無効なことがあります。

対処: Forge / WebUI を --api 付きで再起動してください。
  例: webui-user.bat 内で set COMMANDLINE_ARGS=--api
  または launch 時に  webui.py --api --listen

確認: ブラウザで http://127.0.0.1:7860/docs を開き、/sdapi/v1/txt2img が列挙されているか見る。
"""


def check_a1111_api_ready(base_url: str, timeout: float) -> None:
    """UI の /docs ではなく /sdapi/v1/samplers で API 有効を確認する。"""
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


def run_probe(base_url: str, timeout: float) -> None:
    """接続先の疎通と API 有無を表示する。"""
    t = min(15.0, timeout)
    print(f"probe: base_url={base_url}")
    for path in ("/docs", "/sdapi/v1/samplers", "/sdapi/v1/options"):
        url = base_url.rstrip("/") + path
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=t) as resp:
                print(f"  GET {path} -> HTTP {resp.getcode()} OK")
        except urllib.error.HTTPError as e:
            print(f"  GET {path} -> HTTP {e.code} ({e.reason})")
        except urllib.error.URLError as e:
            print(f"  GET {path} -> URLError: {e}")
        except Exception as e:
            print(f"  GET {path} -> {e!r}")
    print()
    print(
        "解釈: /sdapi/v1/samplers が 404 のときは --api なし起動の可能性が高い。"
        "200 なら txt2img を POST できる状態に近い。"
    )


def http_post_json(url: str, payload: dict[str, Any], timeout: float) -> tuple[int, dict[str, Any]]:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        code = resp.getcode()
        raw = resp.read()
    return code, json.loads(raw.decode("utf-8"))


def apply_model_preset(forge_cfg: dict[str, Any]) -> dict[str, Any]:
    """
    config/forge_config.json の active_model_family に応じ、
    presets.sdxl / presets.flux の default_* を上書き適用する。
    presets が無い場合は従来どおり（後方互換）。
    """
    out = dict(forge_cfg)
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


def merge_config(
    forge_cfg: dict[str, Any],
    params: dict[str, Any],
) -> dict[str, Any]:
    out = {
        "prompt": params.get("prompt", ""),
        "negative_prompt": params.get("negative_prompt", ""),
        "seed": params.get("seed"),
        "width": int(params.get("width", forge_cfg["default_width"])),
        "height": int(params.get("height", forge_cfg["default_height"])),
        "steps": int(params.get("steps", forge_cfg["default_steps"])),
        "cfg_scale": float(params.get("cfg_scale", forge_cfg["default_cfg_scale"])),
        "sampler_name": params.get("sampler_name", forge_cfg["default_sampler_name"]),
        "output_dir": params.get("output_dir", ""),
        "file_prefix": params.get("file_prefix", "forge"),
        "count": int(params.get("count", 1)),
    }
    # Forge / Flux: UI の「Schedule type」「Distilled CFG」と揃える（未設定なら送らない）
    if "scheduler" in params or "default_scheduler" in forge_cfg:
        sched = params.get("scheduler", forge_cfg.get("default_scheduler"))
        if sched is not None:
            out["scheduler"] = str(sched)
    if "distilled_cfg_scale" in params or "default_distilled_cfg_scale" in forge_cfg:
        dcfg = params.get(
            "distilled_cfg_scale", forge_cfg.get("default_distilled_cfg_scale")
        )
        if dcfg is not None:
            out["distilled_cfg_scale"] = float(dcfg)
    return out


def build_txt2img_payload(
    merged: dict[str, Any],
    *,
    seed_for_request: int,
) -> dict[str, Any]:
    p: dict[str, Any] = {
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
        p["scheduler"] = merged["scheduler"]
    if merged.get("distilled_cfg_scale") is not None:
        p["distilled_cfg_scale"] = merged["distilled_cfg_scale"]
    return p


def validate_sampler(name: str, allowed: list[str]) -> None:
    if name not in allowed:
        raise ValueError(f"sampler_name が許可リストにありません: {name!r}。allowed: {allowed}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Forge / A1111 互換 txt2img（最小 v1）")
    parser.add_argument(
        "--config",
        type=Path,
        default=None,
        help="forge 設定 JSON（既定: リポジトリルートの config/forge_config.json）",
    )
    parser.add_argument(
        "--params",
        type=Path,
        default=None,
        help="生成パラメータ JSON。例: tools/fixtures/forge_params.example.json（省略時は標準入力）",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="HTTP を送らず payload のみ表示",
    )
    parser.add_argument(
        "--skip-health",
        action="store_true",
        help="/sdapi/v1/samplers による API 生存確認を省略（デバッグ用）",
    )
    parser.add_argument(
        "--probe",
        action="store_true",
        help="GET /docs と /sdapi/v1/* の疎通だけ表示して終了（params 不要）",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="結果を JSON で stdout に出す",
    )
    args = parser.parse_args(argv)

    root = repo_root()
    cfg_path = args.config or (root / "config" / "forge_config.json")
    if not cfg_path.is_file():
        print(f"設定が見つかりません: {cfg_path}", file=sys.stderr)
        return 2

    forge_cfg = apply_model_preset(load_json(cfg_path))
    base_url = str(forge_cfg.get("base_url", "http://127.0.0.1:7860")).rstrip("/")
    timeout = float(forge_cfg.get("timeout_sec", 180))

    if args.probe:
        run_probe(base_url, timeout)
        return 0

    if args.params:
        p = args.params
        if not p.is_file():
            ex = root / "tools" / "fixtures" / "forge_params.example.json"
            print(f"パラメータファイルが見つかりません: {p.resolve()}", file=sys.stderr)
            print(
                f"例: python tools/forge_generate.py --params {ex.as_posix()} --dry-run",
                file=sys.stderr,
            )
            return 2
        params = load_json(p)
    else:
        if sys.stdin.isatty():
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
        params = json.load(sys.stdin)

    merged = merge_config(forge_cfg, params)
    sys.stderr.write(
        "# forge: active_model_family="
        f"{forge_cfg.get('active_model_family', 'sdxl')} "
        f"cfg_scale={merged['cfg_scale']} "
        f"sampler={merged['sampler_name']}\n"
    )
    sys.stderr.flush()
    max_c = int(forge_cfg.get("max_count", 4))
    if merged["count"] < 1 or merged["count"] > max_c:
        print(f"count は 1〜{max_c} にしてください（現在: {merged['count']}）", file=sys.stderr)
        return 2

    if not merged["output_dir"]:
        print("params に output_dir を指定してください", file=sys.stderr)
        return 2

    validate_sampler(merged["sampler_name"], list(forge_cfg.get("allowed_samplers", [])))

    out_dir = Path(merged["output_dir"])
    if not out_dir.is_absolute():
        out_dir = (root / out_dir).resolve()

    log_path = root / "logs" / "forge_generate.log"

    if not args.skip_health and not args.dry_run:
        try:
            check_a1111_api_ready(base_url, timeout)
        except RuntimeError as e:
            append_log(log_path, f"HEALTH FAIL: {e}")
            print(str(e), file=sys.stderr)
            return 3

    api_url = f"{base_url}/sdapi/v1/txt2img"
    saved: list[dict[str, Any]] = []
    base_seed = merged["seed"]
    if base_seed is None:
        base_seed = random.randint(1, 2**31 - 1)

    for i in range(merged["count"]):
        seed_i = int(base_seed) + i
        payload = build_txt2img_payload(merged, seed_for_request=seed_i)

        if args.dry_run:
            print(json.dumps({"url": api_url, "payload": payload}, ensure_ascii=False, indent=2))
            continue

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        stem = f"{merged['file_prefix']}_{ts}_{seed_i}"

        try:
            _, resp = http_post_json(api_url, payload, timeout)
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", errors="replace")
            if e.code == 404:
                print(API_404_HINT, file=sys.stderr)
            msg = f"HTTP {e.code}: {body[:2000]}"
            append_log(log_path, f"FAIL seed={seed_i} prompt={merged['prompt'][:200]!r} {msg}")
            print(msg, file=sys.stderr)
            return 4
        except Exception as e:
            append_log(
                log_path,
                f"ERROR seed={seed_i} prompt={merged['prompt'][:200]!r} {e!r}",
            )
            print(f"リクエスト失敗: {e}", file=sys.stderr)
            return 5

        images = resp.get("images") or []
        if not images:
            append_log(log_path, f"EMPTY images seed={seed_i}")
            print("API が images を返しませんでした", file=sys.stderr)
            return 6

        png_bytes = base64.b64decode(images[0])
        min_png = int(forge_cfg.get("min_png_bytes", 512))
        if len(png_bytes) < min_png:
            msg = (
                f"返却PNGが異常に小さい ({len(png_bytes)} bytes)。"
                "Flux では cfg_scale≈1・Euler・distilled_cfg_scale・scheduler(Simple) を "
                "config/forge_config.json と揃え、VAE/モデルを UI と同じにしてください。"
            )
            append_log(log_path, f"TINY PNG len={len(png_bytes)} seed={seed_i}")
            print(msg, file=sys.stderr)
            return 8

        png_path = out_dir / f"{stem}.png"
        meta_path = out_dir / f"{stem}.json"
        try:
            out_dir.mkdir(parents=True, exist_ok=True)
            png_path.write_bytes(png_bytes)
        except OSError as e:
            append_log(log_path, f"SAVE FAIL {png_path}: {e!r}")
            print(f"保存失敗: {e}", file=sys.stderr)
            return 7

        meta = {
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
        saved.append({"png": str(png_path), "json": str(meta_path), "seed": seed_i})

    if args.dry_run:
        return 0

    if args.json:
        print(json.dumps({"ok": True, "saved": saved}, ensure_ascii=False, indent=2))
    else:
        for s in saved:
            print(s["png"])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
