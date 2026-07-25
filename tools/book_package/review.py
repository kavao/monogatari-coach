"""Deterministic Phase 1 publishing-readiness review."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, cast

from .cover import CoverComposeError, has_cover_layout, load_package_cover, resolve_layer_text
from .fonts import FontError, resolve_font_path
from .paths import resolve_package_path
from .references import extract_illustration_directives, extract_scene_anchors
from .schemas import (
    BookPackage,
    CoverLayer,
    CoverLayout,
    RightsPackage,
    load_book_package,
    load_rights_package,
)


Gate = Literal["writing", "export"]
Target = Literal["paper", "ebook", "web"]


@dataclass(frozen=True)
class Finding:
    rule: str
    severity: Literal["error", "warning", "info"]
    message: str
    suggested_action: str


@dataclass(frozen=True)
class ReviewResult:
    package_root: Path
    gate: Gate
    target: Target
    findings: tuple[Finding, ...]
    exportable: dict[str, bool]

    @property
    def has_errors(self) -> bool:
        return any(finding.severity == "error" for finding in self.findings)

    def to_dict(self) -> dict:
        return {
            "review_type": "publishing_readiness",
            "mode": "export_gate" if self.gate == "export" else "writing",
            "target": self.target,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "derived_status": {
                "manuscript": _status_for_rules(self.findings, ("P-M",)),
                "illustrations": _status_for_rules(self.findings, ("P-I",)),
                "cover": _status_for_rules(
                    self.findings, ("P-R01", "P-E01", "P-V")
                ),
                "colophon": _status_for_rules(self.findings, ("P-C",)),
                "rights": _status_for_rules(self.findings, ("P-R",)),
                "exportable": dict(self.exportable),
            },
            "findings": [asdict(finding) for finding in self.findings],
        }


def _status_for_rules(findings: tuple[Finding, ...], prefixes: tuple[str, ...]) -> str:
    relevant = [finding for finding in findings if finding.rule.startswith(prefixes)]
    if any(finding.severity == "error" for finding in relevant):
        return "missing"
    if relevant:
        return "in_progress"
    return "ready"


def _normalise_target(book: BookPackage, target: str | None) -> Target:
    if target in {"paper", "ebook", "web"}:
        return cast(Target, target)
    if target is not None:
        raise ValueError(f"Unsupported publication target: {target}")
    if book.format.primary == "paperback":
        return "paper"
    if book.format.primary == "ebook":
        return "ebook"
    return "web"


def _add(
    findings: list[Finding],
    rule: str,
    severity: Literal["error", "warning", "info"],
    message: str,
    suggested_action: str,
) -> None:
    findings.append(Finding(rule, severity, message, suggested_action))


def _export_severity(gate: Gate) -> Literal["error", "info"]:
    return "error" if gate == "export" else "info"


def _read_declared_manuscript(
    package_root: Path, book: BookPackage, findings: list[Finding]
) -> dict[str, list[tuple[Path, str]]]:
    contents: dict[str, list[tuple[Path, str]]] = {}
    for section_name, entries in (
        ("frontmatter", book.manuscript.frontmatter),
        ("chapters", book.manuscript.chapters),
        ("backmatter", book.manuscript.backmatter),
    ):
        for entry in entries:
            paths: list[tuple[Path, str]] = []
            for index, raw_path in enumerate(entry.source_files(), start=1):
                label = f"manuscript.{section_name}.{entry.id}.{index}"
                path = resolve_package_path(package_root, raw_path)
                if not path.is_file():
                    _add(
                        findings,
                        "P-M01",
                        "error",
                        f"{label} が存在しません: {raw_path}",
                        "book.yaml の file/files を実在する原稿ファイルへ修正してください。",
                    )
                    continue
                paths.append((path, path.read_text(encoding="utf-8")))
            contents[entry.id] = paths
    return contents


def _collect_findings(
    package_root: Path,
    book: BookPackage,
    rights: RightsPackage,
    *,
    gate: Gate,
    target: Target,
) -> tuple[Finding, ...]:
    findings: list[Finding] = []
    manuscript = _read_declared_manuscript(package_root, book, findings)

    chapter_ids = {entry.id for entry in book.manuscript.chapters}
    anchors_by_id: dict[str, tuple[str, int]] = {}
    for chapter in book.manuscript.chapters:
        previous_sequence: int | None = None
        for _, text in manuscript.get(chapter.id, []):
            for anchor in extract_scene_anchors(text):
                if anchor.chapter_id not in chapter_ids:
                    _add(
                        findings,
                        "P-M02",
                        "error",
                        f"シーンアンカー {anchor.id} の章 ID が chapters にありません。",
                        "book.yaml の chapter ID か本文の scene アンカーを一致させてください。",
                    )
                if anchor.id in anchors_by_id:
                    _add(
                        findings,
                        "P-M03",
                        "error",
                        f"シーンアンカー ID が重複しています: {anchor.id}",
                        "同じ anchor ID を一度だけにし、必要なら新しい連番を付けてください。",
                    )
                else:
                    anchors_by_id[anchor.id] = (anchor.chapter_id, anchor.sequence)
                if previous_sequence is not None and anchor.sequence < previous_sequence:
                    _add(
                        findings,
                        "P-M04",
                        "warning",
                        f"{chapter.id} のシーンアンカーが昇順ではありません: {anchor.id}",
                        "本文内の scene アンカーを章内の出現順に並べてください。",
                    )
                previous_sequence = anchor.sequence

    illustration_ids = {illustration.id for illustration in book.illustrations}
    scene_refs = {
        illustration.scene_ref
        for illustration in book.illustrations
        if illustration.scene_ref is not None
    }
    for illustration in book.illustrations:
        if illustration.scene_ref is not None and illustration.scene_ref not in anchors_by_id:
            _add(
                findings,
                "P-I01",
                "error",
                f"挿絵 {illustration.id} の scene_ref が本文にありません: {illustration.scene_ref}",
                "scene_ref を実在する scene アンカーへ変更してください。",
            )
        if illustration.type == "insert" and illustration.scene_ref is None:
            _add(
                findings,
                "P-I04",
                "error",
                f"挿絵 {illustration.id} は type=insert ですが scene_ref がありません。",
                "insert 挿絵には本文の scene アンカーを scene_ref として指定してください。",
            )
        if illustration.type in {"cover", "character_intro"} and illustration.scene_ref is not None:
            _add(
                findings,
                "P-I04",
                "error",
                f"挿絵 {illustration.id} は {illustration.type} ですが scene_ref を持っています。",
                "cover / character_intro の scene_ref は null にしてください。",
            )
        if illustration.status in {"delivered", "approved"}:
            if illustration.asset is None:
                _add(
                    findings,
                    "P-I02",
                    "error",
                    f"挿絵 {illustration.id} は {illustration.status} ですが asset がありません。",
                    "採用した納品画像への相対パスを asset に指定してください。",
                )
            elif not resolve_package_path(package_root, illustration.asset).is_file():
                _add(
                    findings,
                    "P-I02",
                    "error",
                    f"挿絵 {illustration.id} の asset が存在しません: {illustration.asset}",
                    "asset を実在する採用画像の相対パスへ修正してください。",
                )

    for anchor_id in sorted(anchors_by_id):
        if anchor_id not in scene_refs:
            _add(
                findings,
                "P-I03",
                "info",
                f"シーン {anchor_id} は挿絵から参照されていません。",
                "挿絵候補として検討するか、この情報を無視してください。",
            )

    for files in manuscript.values():
        for _, text in files:
            for directive in extract_illustration_directives(text):
                if directive.illustration_id not in illustration_ids:
                    _add(
                        findings,
                        "P-I05",
                        "error",
                        f"挿絵ディレクティブが未登録の ID を参照しています: {directive.illustration_id}",
                        "book.yaml の illustrations[].id を登録するか、ディレクティブを修正してください。",
                    )

    missing_colophon = [
        name
        for name, value in (
            ("publish_date", book.colophon.publish_date),
            ("publisher", book.colophon.publisher),
            ("contact", book.colophon.contact),
        )
        if value is None
    ]
    if missing_colophon:
        _add(
            findings,
            "P-C01",
            _export_severity(gate),
            f"奥付の必須項目が不足しています: {', '.join(missing_colophon)}",
            "入稿前に colophon の publish_date、publisher、contact を指定してください。",
        )
    if book.colophon.copyright_notice is None and rights.copyright.notice is None:
        _add(
            findings,
            "P-C02",
            _export_severity(gate),
            "copyright_notice を book.yaml と rights.yaml のどちらからも生成できません。",
            "colophon.copyright_notice か rights.yaml の copyright.notice を指定してください。",
        )

    if target == "ebook":
        for cover in (item for item in book.illustrations if item.type == "cover"):
            permission = rights.assets.get(cover.id, None)
            ebook_permission = permission.usage.get("ebook") if permission else None
            if ebook_permission is None or ebook_permission.permission != "allowed":
                _add(
                    findings,
                    "P-R01",
                    _export_severity(gate),
                    f"表紙 {cover.id} の ebook 利用許諾が確認できません。",
                    "rights.yaml に ebook: allowed と根拠・確認日を記録してください。",
                )

    for asset_id, asset_rights in rights.assets.items():
        for scope, permission in asset_rights.usage.items():
            if (
                permission.permission == "unconfirmed"
                or not permission.basis
                or permission.confirmed_at is None
            ):
                _add(
                    findings,
                    "P-R02",
                    "warning",
                    f"素材 {asset_id} の {scope} 利用許諾は未確認です。",
                    "permission、basis、confirmed_at をすべて記録してください。",
                )

    registered_fonts = {font.name for font in rights.fonts}
    registered_materials = {material.name for material in rights.materials}
    for font_name in book.resources.fonts:
        if font_name not in registered_fonts:
            _add(
                findings,
                "P-R03",
                "warning",
                f"使用フォント {font_name} が rights.yaml に登録されていません。",
                "rights.yaml の fonts にライセンス、根拠、確認日を追加してください。",
            )
    for material_name in book.resources.materials:
        if material_name not in registered_materials:
            _add(
                findings,
                "P-R03",
                "warning",
                f"使用素材 {material_name} が rights.yaml に登録されていません。",
                "rights.yaml の materials にライセンス、根拠、確認日を追加してください。",
            )

    if target == "ebook":
        # Plan §3.3 option B: when cover.yaml exists, ebook cover is a composed
        # product — do not require export.ebook.cover_image as a static asset.
        if has_cover_layout(package_root):
            cover_layout = load_package_cover(package_root)
            if cover_layout is None:  # pragma: no cover - has_cover_layout invariant
                pass
            else:
                # Presence of resolvable base art is enough for P-E01 under option B.
                base_id = cover_layout.base_art.illustration_id
                base = next(
                    (item for item in book.illustrations if item.id == base_id),
                    None,
                )
                if (
                    base is None
                    or base.type != "cover"
                    or base.status != "approved"
                    or not base.asset
                    or not resolve_package_path(package_root, base.asset).is_file()
                ):
                    _add(
                        findings,
                        "P-E01",
                        _export_severity(gate),
                        "cover.yaml 由来の ebook 表紙を解決できません（approved cover asset）。",
                        "base_art.illustration_id を approved な type=cover の asset へ向けてください。",
                    )
        else:
            cover_image = book.export.ebook.cover_image
            if cover_image is None or not resolve_package_path(
                package_root, cover_image
            ).is_file():
                _add(
                    findings,
                    "P-E01",
                    _export_severity(gate),
                    "ebook 用の表紙画像が指定されていないか、存在しません。",
                    "export.ebook.cover_image に実在する ebook 表紙画像を指定するか、"
                    "cover.yaml でレイヤー合成表紙を定義してください。",
                )

    _collect_cover_layout_findings(
        package_root, book, rights, findings=findings, gate=gate
    )

    lock_path = package_root / "book.lock.yaml"
    if lock_path.is_file():
        # Import here to keep the lock writer's review dependency acyclic at module load.
        from .diff import LockDiffError, diff_against_lock

        try:
            lock_delta = diff_against_lock(package_root)
        except (LockDiffError, ValueError) as exc:
            _add(
                findings,
                "P-E02",
                "warning",
                f"book.lock.yaml と現在の入力一式を比較できません: {exc}",
                "book.lock.yaml を確認し、必要に応じて export review 後に再生成してください。",
            )
        else:
            changed = sum(len(paths) for paths in lock_delta.values())
            if changed:
                _add(
                    findings,
                    "P-E02",
                    "warning",
                    f"book.lock.yaml 作成後に入力一式が {changed} 件変わっています。",
                    "book_diff.py で差分を確認し、export review 後に book_lock.py を再実行してください。",
                )

    return tuple(findings)


def _collect_cover_layout_findings(
    package_root: Path,
    book: BookPackage,
    rights: RightsPackage,
    *,
    findings: list[Finding],
    gate: Gate,
) -> None:
    """Emit P-V01–P-V04 when cover.yaml is present. No-op without layout (compat)."""

    if not has_cover_layout(package_root):
        return
    try:
        layout = load_package_cover(package_root)
    except ValueError as exc:
        _add(
            findings,
            "P-V04",
            "error",
            f"cover.yaml を読み込めません: {exc}",
            "cover.yaml のスキーマとキー名を修正してください。",
        )
        return
    if layout is None:  # pragma: no cover
        return

    _check_cover_base_art(package_root, book, layout, findings)
    _check_cover_required_layers(book, layout, findings)
    _check_cover_font_and_asset_refs(package_root, layout, findings)
    _check_cover_rights(book, rights, layout, findings, gate=gate)


def _check_cover_base_art(
    package_root: Path,
    book: BookPackage,
    layout: CoverLayout,
    findings: list[Finding],
) -> None:
    illustration_id = layout.base_art.illustration_id
    matches = [item for item in book.illustrations if item.id == illustration_id]
    if not matches:
        _add(
            findings,
            "P-V01",
            "error",
            f"cover.yaml の base_art が book.yaml にありません: {illustration_id}",
            "illustration_id を type=cover の illustrations[].id へ合わせてください。",
        )
        return
    item = matches[0]
    if item.type != "cover" or item.status != "approved":
        _add(
            findings,
            "P-V01",
            "error",
            f"base_art は approved な type=cover である必要があります: "
            f"{illustration_id} (type={item.type}, status={item.status})",
            "表紙候補を approved にし、type を cover にしてください。",
        )
        return
    if not item.asset or not resolve_package_path(package_root, item.asset).is_file():
        _add(
            findings,
            "P-V01",
            "error",
            f"base_art の asset が存在しません: {item.asset}",
            "illustrations[].asset を実在する文字なし表紙画像へ向けてください。",
        )


def _check_cover_required_layers(
    book: BookPackage, layout: CoverLayout, findings: list[Finding]
) -> None:
    """Validate the semantic title/author layers and all required text sources.

    A title may be either editable text or a logo asset.  In both cases the
    layout must declare ``source`` (or an intentional ``value`` override), so
    the bibliography-to-cover relationship remains reviewable.
    """

    semantic_layers = {
        "title": ("title",),
        "author": ("author", "credit_author"),
    }
    expected_roles = ["title"]
    if book.cover.front.credit_author:
        expected_roles.append("author")

    checked_layer_ids: set[str] = set()
    for role in expected_roles:
        candidates = [
            layer
            for layer in layout.layers
            if layer.id in semantic_layers[role] and layer.required
        ]
        if not candidates:
            labels = " / ".join(semantic_layers[role])
            _add(
                findings,
                "P-V02",
                "error",
                f"表1に必要な {role} レイヤー（id: {labels}、required: true）がありません。",
                "cover.yaml に book.yaml を source とする必須 title / author レイヤーを定義してください。",
            )
            continue
        for layer in candidates:
            checked_layer_ids.add(layer.id)
            _check_required_layer_source(book, layer, findings)

    for layer in layout.layers:
        if layer.id in checked_layer_ids or layer.type != "text" or not layer.required:
            continue
        _check_required_layer_source(book, layer, findings)


def _check_required_layer_source(
    book: BookPackage, layer: CoverLayer, findings: list[Finding]
) -> None:
    """Add P-V02 instead of letting an invalid source abort the whole review."""

    try:
        text, skip_reason = resolve_layer_text(book, layer)
    except CoverComposeError as exc:
        _add(
            findings,
            "P-V02",
            "error",
            f"必須レイヤー {layer.id} の source を解決できません: {exc}",
            "cover.yaml の source を book.yaml で定義された参照先へ修正してください。",
        )
        return
    if text is not None:
        return
    # Display flags intentionally suppress a required credit layer only when
    # that credit is disabled in book.yaml.
    if skip_reason and skip_reason.startswith("cover.front."):
        return
    _add(
        findings,
        "P-V02",
        "error",
        f"必須レイヤー {layer.id} が解決できません"
        + (f": {skip_reason}" if skip_reason else ""),
        "book.yaml の title / author など source 参照先を確認してください。",
    )


def _check_cover_font_and_asset_refs(
    package_root: Path, layout: CoverLayout, findings: list[Finding]
) -> None:
    for font_ref, face in layout.fonts.items():
        try:
            resolve_font_path(
                file=face.file,
                family=face.family,
                package_root=package_root,
            )
        except FontError as exc:
            _add(
                findings,
                "P-V04",
                "error",
                f"font_ref {font_ref} を解決できません: {exc}",
                "fonts の family / file を実在する書体へ修正するか環境へ導入してください。",
            )
    for layer in layout.layers:
        if layer.type in {"logo_asset", "image", "barcode"} and layer.asset:
            path = resolve_package_path(package_root, layer.asset)
            if not path.is_file():
                severity: Literal["error", "warning"] = (
                    "error" if layer.required else "warning"
                )
                _add(
                    findings,
                    "P-V04",
                    severity,
                    f"レイヤー {layer.id} の asset が存在しません: {layer.asset}",
                    "cover/assets/ など実在パスへ修正してください。",
                )
    illustration_id = layout.base_art.illustration_id
    # illustration_id existence already covered by P-V01; still flag missing fonts map empty
    if layout.layers and any(layer.type == "text" for layer in layout.layers) and not layout.fonts:
        _add(
            findings,
            "P-V04",
            "error",
            "text レイヤーがありますが fonts が空です。",
            "cover.yaml の fonts に font_ref を定義してください。",
        )
    _ = illustration_id


def _check_cover_rights(
    book: BookPackage,
    rights: RightsPackage,
    layout: CoverLayout,
    findings: list[Finding],
    *,
    gate: Gate,
) -> None:
    """P-V03: fonts/materials used on the cover need rights.yaml records for export."""

    registered_fonts = {font.name for font in rights.fonts}
    registered_materials = {material.name for material in rights.materials}
    declared_resource_fonts = set(book.resources.fonts)
    severity = _export_severity(gate)

    for font_ref, face in layout.fonts.items():
        # Prefer the family label as the rights key; fall back to font_ref.
        candidates = {face.family, font_ref}
        if not candidates & registered_fonts and not candidates & declared_resource_fonts:
            _add(
                findings,
                "P-V03",
                severity,
                f"表紙書体 {face.family} (font_ref={font_ref}) のライセンス記録がありません。",
                "book.resources.fonts と rights.yaml: fonts に書体を登録してください。",
            )
        elif not candidates & registered_fonts:
            _add(
                findings,
                "P-V03",
                "warning" if gate == "writing" else severity,
                f"表紙書体 {face.family} が rights.yaml に未登録です。",
                "rights.yaml の fonts にライセンス・根拠・確認日を追加してください。",
            )

    for layer in layout.layers:
        if layer.type not in {"logo_asset", "image", "barcode"} or not layer.asset:
            continue
        material_name = layer.id
        if material_name not in registered_materials and layer.asset not in registered_materials:
            if layer.asset not in book.resources.materials and material_name not in book.resources.materials:
                _add(
                    findings,
                    "P-V03",
                    severity if layer.required else "warning",
                    f"表紙素材レイヤー {layer.id} のライセンス記録がありません。",
                    "rights.yaml の materials と book.resources.materials へ登録してください。",
                )


def review_package(
    package_root: str | Path,
    *,
    gate: Gate = "writing",
    target: str | None = None,
) -> ReviewResult:
    """Review one novel's publishing declarations without modifying any files."""

    root = Path(package_root).resolve()
    book = load_book_package(root / "book.yaml")
    rights = load_rights_package(root / "rights.yaml")
    resolved_target = _normalise_target(book, target)
    findings = _collect_findings(
        root, book, rights, gate=gate, target=resolved_target
    )
    exportable = {
        candidate: not any(
            finding.severity == "error"
            for finding in _collect_findings(
                root, book, rights, gate="export", target=candidate
            )
        )
        for candidate in ("paper", "ebook", "web")
    }
    return ReviewResult(
        package_root=root,
        gate=gate,
        target=resolved_target,
        findings=findings,
        exportable=exportable,
    )
