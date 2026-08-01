from __future__ import annotations

import importlib.util
import json
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RULES = ROOT / ".rulesync" / "rules"


def load_rulesync_runner():
    spec = importlib.util.spec_from_file_location("monocri_rulesync_runner", ROOT / "tools" / "rulesync.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def frontmatter(path: Path) -> str:
    text = path.read_text(encoding="utf-8")
    return text.split("---", 2)[1]


def test_rulesync_target_owner_and_toolchain_are_fixed() -> None:
    config = json.loads((ROOT / "rulesync.jsonc").read_text(encoding="utf-8"))
    toolchain = json.loads((ROOT / "config" / "rulesync_toolchain.json").read_text(encoding="utf-8"))
    assert config["targets"][-1] == "agentsmd"
    assert config["delete"] is False
    assert toolchain["version"] == "15.0.1"
    assert toolchain["url"].endswith("/v15.0.1/rulesync-windows-x64.exe")
    assert re.fullmatch(r"[0-9a-f]{64}", toolchain["sha256"])


def test_router_and_constant_rules_stay_small() -> None:
    overview = RULES / "overview.md"
    concepts = RULES / "concepts.md"
    roots = [path for path in RULES.glob("*.md") if "root: true" in frontmatter(path)]
    assert roots == [overview]
    assert len(overview.read_text(encoding="utf-8").splitlines()) <= 250
    assert len(overview.read_text(encoding="utf-8")) <= 10_000
    assert len(concepts.read_text(encoding="utf-8").splitlines()) <= 200
    assert len(concepts.read_text(encoding="utf-8")) <= 8_000
    assert 'globs: ["**/*"]' not in frontmatter(concepts)


def test_long_workflow_specification_is_not_sent_to_codexcli() -> None:
    specification = RULES / "workflow-specification.md"
    metadata = frontmatter(specification)
    assert "codexcli" not in metadata
    assert "novels/**" in metadata


def test_workflow_specification_keeps_relocated_mode_contracts() -> None:
    specification = (RULES / "workflow-specification.md").read_text(encoding="utf-8")
    required_headings = (
        "小説ファイル (novels/[novel_code]_[novel_title]/)",
        "Source Material Intake Mode",
        "Tag Mode",
        "Manga Tag Mode",
        "Illustration Tag Mode",
        "Cover Composition Mode",
        "Publication Package Mode",
        "Writing Mode",
        "Meta Management Mode",
        "First Reader Mode",
        "Editor Score Mode",
        "Consistency Audit Mode",
        "画像生成（txt2img）の事前確認",
    )
    missing = [heading for heading in required_headings if heading not in specification]
    assert not missing, f"workflow-specification.md に必要なモード仕様がありません: {missing}"


def test_legacy_floating_rulesync_command_is_not_used() -> None:
    for path in (ROOT / "readme.md", ROOT / "sync_rules.py"):
        assert "pnpm dlx rulesync" not in path.read_text(encoding="utf-8")


def test_runner_suppresses_only_known_agentsmd_compatibility_notices() -> None:
    runner = load_rulesync_runner()
    known = "Target 'agentsmd' does not support the feature 'mcp'. Skipping.\n"
    assert runner.is_expected_agentsmd_notice(known)
    assert not runner.is_expected_agentsmd_notice("Target 'agentsmd' failed to write AGENTS.md.\n")
    assert not runner.is_expected_agentsmd_notice("A future Rulesync warning.\n")


# Sections relocated from concepts.md into workflow-specification.md.
# Skills must not cite these as living under concepts.md.
RELOCATED_SECTIONS = (
    "Illustration Tag Mode 作品メタ",
    "Manga Tag Mode ワークフロー",
    "Manga `summary_en` の翻訳経路",
    "Tag Mode テンプレート一式",
    "Tag Mode バリアント階層",
    "Tag Mode 作品メタ",
    "Tag Mode 汎用テンプレートとカスタム要素",
    "Tag Mode 身体的正本",
    "タイトル命名ゲート",
    "プロジェクト・インテリジェンス",
    "公式スキルとユーザスキルの接続",
    "出版完成目安",
    "挿絵IR",
    "挿絵計画",
    "漫画IRと互換Markdown",
    "漫画互換Markdownの完了条件",
    "生成モード用語",
    "画像保存先",
    "画像生成: dry-run から本番まで",
    "画像生成失敗時の provider 切替",
    "表紙合成と題字",
    "計画書チェック更新ゲート",
    "評価ファイル命名と役割",
    "評価作業一時領域",
    "評価出力の保存先",
    "足切りと深掘り評価の住み分け",
    "選定レジストリ",
    "長文評価の閾値と前処理",
)

KEEP_CONCEPT_SECTIONS = ("完了扱い条件", "正本と副本", "ルールとドキュメント", "詳細仕様の参照先")


def _reference_sources() -> list[Path]:
    skills = list((ROOT / ".rulesync" / "skills").rglob("SKILL.md"))
    rules = [
        RULES / "workflow-specification.md",
        RULES / "rule-authoring.md",
    ]
    docs = list((ROOT / "docs").rglob("*.md"))
    return skills + rules + docs


def test_relocated_sections_are_not_cited_as_concepts() -> None:
    concepts = (RULES / "concepts.md").read_text(encoding="utf-8")
    workflow = (RULES / "workflow-specification.md").read_text(encoding="utf-8")
    for section in RELOCATED_SECTIONS:
        assert section not in concepts or section in KEEP_CONCEPT_SECTIONS
        assert section in workflow, f"relocated section missing from workflow-specification.md: {section}"

    attributed = re.compile(
        r"(?:\.rulesync/rules/)?concepts\.md[^。\n「『]{0,80}[「『]([^」』]+)[」』]|concepts[「『]([^」』]+)[」』]"
    )
    stale: list[str] = []
    for path in _reference_sources():
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in attributed.finditer(line):
                name = match.group(1) or match.group(2)
                if any(section in name or name in section for section in RELOCATED_SECTIONS):
                    stale.append(f"{path.relative_to(ROOT)}:{line_no}: {name}")
                elif name not in KEEP_CONCEPT_SECTIONS and name in workflow and name not in concepts:
                    stale.append(f"{path.relative_to(ROOT)}:{line_no}: {name}")
    assert not stale, "relocated sections still cited as concepts.md:\n" + "\n".join(stale)


def test_quoted_section_refs_resolve_to_existing_headings() -> None:
    concepts = (RULES / "concepts.md").read_text(encoding="utf-8")
    workflow = (RULES / "workflow-specification.md").read_text(encoding="utf-8")
    skip_names = {
        "執筆した",
        "本文を出した",
        "ファイルに保存した",
        "同一ターンで進める",
        "画像生成が完了した",
        "すべて出力した",
        "どの計画のどの項目を完了にしたか",
        "興味を持つか",
        "読み飛ばすか",
        "TPO → variant 対応表",
        "生成モードとプロバイダの対応",
        "`_how_to/tag.md` §3 に従う",
    }
    attributed = re.compile(
        r"(?:\.rulesync/rules/)?(concepts|workflow-specification)\.md[^。\n「『]{0,80}[「『]([^」』]+)[」』]"
    )
    missing: list[str] = []
    for path in _reference_sources():
        for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in attributed.finditer(line):
                label, name = match.group(1), match.group(2)
                if len(name) < 4 or name in skip_names:
                    continue
                target = concepts if label == "concepts" else workflow
                if name not in target:
                    missing.append(f"{path.relative_to(ROOT)}:{line_no}: {label}.md「{name}」")
    assert not missing, "quoted section refs do not resolve:\n" + "\n".join(missing)


def test_legacy_overview_mode_anchors_are_not_cited() -> None:
    stale: list[str] = []
    for path in _reference_sources():
        text = path.read_text(encoding="utf-8")
        if re.search(r"overview(?:\.md)?[^。\n]{0,80}§\s*\d+(?:\.\d+)*", text):
            stale.append(str(path.relative_to(ROOT)))
    assert not stale, f"dead overview mode anchors remain in: {stale}"


def test_workflow_specification_does_not_use_concepts_as_a_tag_source() -> None:
    specification = (RULES / "workflow-specification.md").read_text(encoding="utf-8")
    assert "concepts の一覧" not in specification
    assert "concepts にある" not in specification
