#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Check .env against .env.example and report missing Monocri settings."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any


ENV_VERSION_KEY = "MONOCRI_ENV_VERSION"
SECRET_KEYS = {
    "NOVELAI_ACCESS_TOKEN",
    "XAI_API_KEY",
    "OPENAI_API_KEY",
    "OPENROUTER_API_KEY",
}
OPTIONAL_EMPTY_KEYS = {
    "MONOCRI_FORGE_MODEL_FAMILY_DEFAULT",
    "MONOCRI_ILLUSTRATION_MODEL_DEFAULT",
    "MONOCRI_MANGA_GROK_PRO_DEFAULT_ASPECT_RATIO",
}
PROVIDER_AUTH = {
    "novelai": "NOVELAI_ACCESS_TOKEN",
    "grok": "XAI_API_KEY",
    "grok_pro": "XAI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
}
PROVIDER_DEFAULT_KEYS = {
    "MONOCRI_CHARACTER_TAG_PROVIDER_DEFAULT": "キャラクタータグ一括生成",
    "MONOCRI_MANGA_STEP1_PROVIDER_DEFAULT": "漫画コマ生成",
    "MONOCRI_MANGA_STEP1_PAGES_PROVIDER_DEFAULT": "漫画精密ページ生成",
    "MONOCRI_MANGA_STEP2_PROVIDER_DEFAULT": "漫画ページ生成",
    "MONOCRI_MANGA_BACKGROUND_PROVIDER_DEFAULT": "漫画背景概念生成",
    "MONOCRI_ILLUSTRATION_PROVIDER_DEFAULT": "挿絵・表紙生成",
}


@dataclass
class EnvCheckResult:
    env_path: str
    example_path: str
    env_version: str | None
    example_version: str | None
    version_ok: bool
    missing_keys: list[str]
    empty_keys: list[str]
    missing_auth: list[dict[str, str]]
    unknown_provider_defaults: list[dict[str, str]]

    @property
    def ok(self) -> bool:
        return (
            self.version_ok
            and not self.missing_keys
            and not self.missing_auth
            and not self.unknown_provider_defaults
        )


def repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def parse_env(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8-sig").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        values[key] = value
    return values


def effective_value(env_values: dict[str, str], key: str) -> str:
    process_value = os.environ.get(key)
    if process_value is not None:
        return process_value.strip()
    return env_values.get(key, "").strip()


def check_env(root: Path) -> EnvCheckResult:
    env_path = root / ".env"
    example_path = root / ".env.example"
    env_values = parse_env(env_path)
    example_values = parse_env(example_path)

    missing_keys = [
        key for key in example_values
        if key not in env_values and key not in SECRET_KEYS
    ]
    empty_keys = [
        key for key in example_values
        if key in env_values and not env_values[key].strip()
    ]

    missing_auth: list[dict[str, str]] = []
    unknown_provider_defaults: list[dict[str, str]] = []
    for provider_key, label in PROVIDER_DEFAULT_KEYS.items():
        provider = effective_value(env_values, provider_key)
        if not provider:
            continue
        auth_key = PROVIDER_AUTH.get(provider)
        if not auth_key:
            unknown_provider_defaults.append(
                {"key": provider_key, "value": provider, "usage": label}
            )
            continue
        if not effective_value(env_values, auth_key):
            missing_auth.append(
                {
                    "usage": label,
                    "provider_key": provider_key,
                    "provider": provider,
                    "auth_key": auth_key,
                }
            )

    env_version = effective_value(env_values, ENV_VERSION_KEY) or None
    example_version = example_values.get(ENV_VERSION_KEY) or None
    version_ok = bool(env_version and example_version and env_version == example_version)

    return EnvCheckResult(
        env_path=str(env_path),
        example_path=str(example_path),
        env_version=env_version,
        example_version=example_version,
        version_ok=version_ok,
        missing_keys=missing_keys,
        empty_keys=empty_keys,
        missing_auth=missing_auth,
        unknown_provider_defaults=unknown_provider_defaults,
    )


def print_human(result: EnvCheckResult) -> None:
    print("=== .env check ===")
    print(f".env: {result.env_path}")
    print(f".env.example: {result.example_path}")
    if result.version_ok:
        print(f"version: OK ({result.env_version})")
    else:
        print(
            "version: NG "
            f"(.env={result.env_version or '未設定'}, "
            f".env.example={result.example_version or '未設定'})"
        )

    if result.missing_keys:
        print("\n不足しているキー:")
        for key in result.missing_keys:
            print(f"- {key}")
    if result.empty_keys:
        print("\n空欄のキー:")
        for key in result.empty_keys:
            if key in SECRET_KEYS:
                note = "（必要な provider を使うときだけ入力）"
            elif key in OPTIONAL_EMPTY_KEYS:
                note = "（空欄可: provider 側の既定値を使う）"
            else:
                note = ""
            print(f"- {key}{note}")
    if result.missing_auth:
        print("\n選択中 provider に必要な認証キーが未設定です:")
        for item in result.missing_auth:
            print(
                f"- {item['usage']}: {item['provider_key']}={item['provider']} "
                f"-> {item['auth_key']} を設定してください"
            )
    if result.unknown_provider_defaults:
        print("\n不明な provider 指定があります:")
        for item in result.unknown_provider_defaults:
            print(f"- {item['usage']}: {item['key']}={item['value']}")

    if result.ok:
        print("\n結果: OK")
    else:
        print("\n結果: 要確認")
        print("次にすること: .env.example の不足キーを .env に追加し、使う provider の API キーを設定してください。")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=".env と .env.example の不足・版差分を確認する")
    parser.add_argument("--root", type=Path, default=repo_root(), help="リポジトリルート")
    parser.add_argument("--json", action="store_true", help="JSONで出力")
    parser.add_argument("--strict-empty", action="store_true", help="空欄キーも終了コード1にする")
    args = parser.parse_args(argv)

    root = args.root.resolve()
    result = check_env(root)
    if args.json:
        payload: dict[str, Any] = asdict(result)
        payload["ok"] = result.ok
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        print_human(result)

    failed = not result.ok or (args.strict_empty and bool(result.empty_keys))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
