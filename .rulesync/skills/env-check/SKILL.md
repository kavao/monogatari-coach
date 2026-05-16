---
name: env-check
description: >-
  .env と .env.example の版差分、不足キー、選択中 provider に必要な API キー不足を
  tools/env_check.py で確認し、画像生成や初回セットアップ前の設定漏れを明確にする。
targets: ["*"]
---

## 目的

`.env.example` が更新されたあと、手元の `.env` に新しい環境変数が足りない状態を見落とさないようにする。特に画像生成では、provider の既定値だけが入っていて API キーが空のままだと実行時に分かりづらく失敗するため、事前に不足を一覧化する。

## 実行

リポジトリルートで実行する。

```bash
python tools/env_check.py
```

機械処理や CI では JSON を使う。

```bash
python tools/env_check.py --json
```

## 判定対象

- `.env.example` にある通常キーが `.env` に存在するか。
- `MONOCRI_ENV_VERSION` が `.env.example` と `.env` で一致するか。
- `MONOCRI_*_PROVIDER_DEFAULT` で選ばれている provider に対応する認証キーが入っているか。
- 空欄のキーがあるか。ただし API キーは該当 provider を使う場合だけ必須、`MONOCRI_ILLUSTRATION_MODEL_DEFAULT` などの上書き用キーは空欄可として扱う。

## 不足時のメッセージ方針

- まず不足しているキー名をそのまま出す。
- provider 由来の認証不足は「用途」「provider default のキー」「必要な auth key」を1行で示す。
- 末尾に `python tools/env_check.py` を再実行するよう案内する。

## `.env` バージョン

`.env.example` の `MONOCRI_ENV_VERSION` は、環境変数テンプレートを更新した日付または運用版を表す。新しい環境変数を追加したら、この値を更新する。既存ユーザーの `.env` は自動更新しないため、本スキルで差分を確認して手動で追記する。

## 関連

- `image-provider`: 画像生成 provider 実行前の `.env` 確認
- `docs/image-generation/index.md`: 環境変数の用途一覧
