"""新規作品の検査レイヤを初期化する小さな共通部品。

既存作品の設定を推測で変更しないため、ここで行うのは「config.md がまだ
存在しない新規作品」の初回作成だけです。通常の設定読込（``inspection_flags``）
が持つ、行なし＝ METRON / CHRONOS OFF という互換性は変更しません。
"""

from __future__ import annotations

import os
from pathlib import Path

from inspection_flags import (
    InspectionConfigError,
    InspectionFlag,
    load_inspection_flags,
)


class InspectionBootstrapError(ValueError):
    """新規作品の検査レイヤ初期化に必要な値が不正。"""


DEFAULT_NEW_LAYER = InspectionFlag.ON
"""新規作品の METRON の既定（未応答のとき）。

新規作品は ON で起こし、計測しながら書く。OFF は作成時の確認で明示した
ときだけ。行なしの既存作品は inspection_flags 側で従来どおり OFF。
"""

DEFAULT_NEW_CHRONOS = InspectionFlag.OFF
"""新規作品の CHRONOS の既定。CHRONOS は休止中（再設計予定）なので OFF。

計画: _workingspace/plans/20261025_chronos-off-redesign.md。ON にできるのは
METRON も ON のときだけ（CHRONOS だけ ON は設定エラー）。既存作品の値は変えない。
"""


def default_for(name: str) -> InspectionFlag:
    """未応答のときに書く既定値。CHRONOS は OFF、それ以外（METRON）は ON。"""

    return DEFAULT_NEW_CHRONOS if name == "CHRONOS" else DEFAULT_NEW_LAYER


def validate_layer_pair(metron: InspectionFlag | str | None, chronos: InspectionFlag | str | None) -> None:
    """新規作品の組み合わせを確かめる。CHRONOS だけ ON（METRON は OFF）は認めない。"""

    metron_flag = _flag(metron, name="METRON")
    chronos_flag = _flag(chronos, name="CHRONOS")
    if chronos_flag is InspectionFlag.ON and metron_flag is InspectionFlag.OFF:
        raise InspectionBootstrapError(
            "CHRONOS を ON にするときは METRON も ON にしてください"
            f"（METRON={metron_flag.value}, CHRONOS={chronos_flag.value}）"
        )


def _flag(value: InspectionFlag | str | None, *, name: str) -> InspectionFlag:
    if value is None:
        return default_for(name)
    if isinstance(value, InspectionFlag):
        return value
    try:
        return InspectionFlag(value)
    except ValueError as error:
        raise InspectionBootstrapError(
            f"{name} must be ON or OFF: {value!r}"
        ) from error


def _cell(value: str) -> str:
    """Markdown 表を壊さない初期値用の一行化。"""

    return value.replace("|", "／").replace("\r", " ").replace("\n", " ").strip()


def decision_label(value: InspectionFlag | str | None, *, name: str = "METRON") -> str:
    """作成時の確認の記録語。None は未応答（METRON は既定 ON、CHRONOS は休止中で既定 OFF）。"""

    if value is None:
        if name == "CHRONOS":
            return f"休止中・既定 {DEFAULT_NEW_CHRONOS.value}"
        return f"未応答・既定 {DEFAULT_NEW_LAYER.value}"
    return f"ユーザー明示 {_flag(value, name='flag').value}"


def initial_config_text(
    novel_code: int,
    title: str,
    *,
    metron: InspectionFlag | str | None = None,
    chronos: InspectionFlag | str | None = None,
    audit_log: InspectionFlag | str = InspectionFlag.ON,
    confirmation: str | None = None,
) -> str:
    """新規作品用の最小 ``config.md`` を返す。

    ``confirmation`` はチャットで確認できなかった場合などの記録で、設定値
    そのものとは分けて保存する。``metron`` が ``None`` のときは未応答として既定（ON）を書き、
    「未応答・既定 ON」と記録する。``chronos`` が ``None`` のときは休止中の既定（OFF）を書く。
    CHRONOS だけ ON は ``InspectionBootstrapError``。
    """

    validate_layer_pair(metron, chronos)
    metron_value = _flag(metron, name="METRON").value
    chronos_value = _flag(chronos, name="CHRONOS").value
    audit_value = _flag(audit_log, name="AUDIT_LOG").value
    if confirmation is None:
        confirmation = "; ".join(
            [
                f"METRON={decision_label(metron)}",
                f"CHRONOS={decision_label(chronos, name='CHRONOS')}",
            ]
        )

    safe_title = _cell(title)
    safe_confirmation = _cell(confirmation)
    return (
        f"# config.md — 「{safe_title}」\n\n"
        "<!-- 初回検査レイヤ確認: "
        f"{safe_confirmation} -->\n\n"
        "## 基本情報\n\n"
        "| 項目 | 内容 |\n"
        "|------|------|\n"
        f"| novel_ID | {int(novel_code):03d} |\n"
        "| writer_code | 000_default |\n"
        f"| 作品名 | {safe_title} |\n"
        "| 作者名 | Standard Writer（000_default） |\n"
        f"| METRON | {metron_value} |\n"
        f"| CHRONOS | {chronos_value} |\n"
        f"| AUDIT_LOG | {audit_value} |\n\n"
        "## ステータス\n\n"
        "- 企画書: 未着手\n"
        "- 設計書: 未着手\n"
        "- 本文: 未着手\n"
    )


def create_initial_config(
    novel_dir: Path,
    novel_code: int,
    title: str,
    *,
    metron: InspectionFlag | str | None = None,
    chronos: InspectionFlag | str | None = None,
    audit_log: InspectionFlag | str = InspectionFlag.ON,
    confirmation: str | None = None,
) -> tuple[Path, str]:
    """config.md を新規作成する。既存ファイルは決して上書きしない。"""

    path = novel_dir / "config.md"
    if path.exists():
        if not path.is_file():
            raise InspectionBootstrapError(f"config.md is not a file: {path}")
        return path, "skip (exists)"

    novel_dir.mkdir(parents=True, exist_ok=True)
    body = initial_config_text(
        novel_code,
        title,
        metron=metron,
        chronos=chronos,
        audit_log=audit_log,
        confirmation=confirmation,
    )
    fd: int | None = None
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o666)
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            fd = None
            stream.write(body)
            stream.flush()
            os.fsync(stream.fileno())
    except FileExistsError:
        # 別プロセスが先に作成した場合も、その内容を上書きせず採用する。
        return path, "skip (created concurrently)"
    except Exception:
        if fd is not None:
            os.close(fd)
        try:
            path.unlink()
        except OSError:
            pass
        raise
    return path, "created (inspection defaults recorded)"


def initialize_new_layers(
    novel_dir: Path,
    novel_code: int,
    title: str,
    *,
    metron: InspectionFlag | str | None = None,
    chronos: InspectionFlag | str | None = None,
    audit_log: InspectionFlag | str = InspectionFlag.ON,
    confirmation: str | None = None,
) -> list[tuple[str, str]]:
    """新規作品の config と ON レイヤ保存先を準備する。"""

    # 値の検証を先に済ませてから、config.md の実値を正として扱う。
    validate_layer_pair(metron, chronos)
    requested_metron = _flag(metron, name="METRON")
    requested_chronos = _flag(chronos, name="CHRONOS")
    actions: list[tuple[str, str]] = []

    if confirmation is None:
        confirmation = "; ".join(
            [f"METRON={decision_label(metron)}", f"CHRONOS={decision_label(chronos, name='CHRONOS')}"]
        )
    config, status = create_initial_config(
        novel_dir,
        novel_code,
        title,
        metron=requested_metron,
        chronos=requested_chronos,
        audit_log=audit_log,
        confirmation=confirmation,
    )
    actions.append((str(config.relative_to(novel_dir)), status))

    # 競合時に他プロセスが先に作った設定を上書きしない。保存先も、要求値では
    # なく、実際に正本へ記録された値に従って準備する。
    try:
        actual_flags = load_inspection_flags(config)
    except InspectionConfigError as error:
        raise InspectionBootstrapError(str(error)) from error
    metron_flag = actual_flags.metron
    chronos_flag = actual_flags.chronos

    if metron_flag is InspectionFlag.ON:
        # METRON の場面の置き場は、新しい作品では _work/metron/。以前からある _metron/ はそのまま使う
        # （場面ごとの置き場は tools/work_paths.py が決める）。
        legacy_dir = novel_dir / "_metron"
        new_dir = novel_dir / "_work" / "metron"
        for label, existing in (("_metron/", legacy_dir), ("_work/metron/", new_dir)):
            if existing.exists() and not existing.is_dir():
                raise InspectionBootstrapError(f"{label} is not a directory: {existing}")
        if legacy_dir.is_dir():
            actions.append(("_metron/", "skip (exists)"))
        elif new_dir.is_dir():
            actions.append(("_work/metron/", "skip (exists)"))
        else:
            new_dir.mkdir(parents=True)
            actions.append(("_work/metron/", "created (METRON ON)"))

    if chronos_flag is InspectionFlag.ON:
        from chronos.scaffold import init_chronos

        chronos_dir = init_chronos(novel_dir)
        actions.append(
            (
                str(chronos_dir.relative_to(novel_dir)) + "/",
                "created (CHRONOS ON)",
            )
        )

    return actions
