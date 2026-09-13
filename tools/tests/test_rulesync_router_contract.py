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
        "執筆接続の起動判定",
        "Meta Management Mode",
        "First Reader Mode",
        "Editor Score Mode",
        "Consistency Audit Mode",
        "Reader Walk Mode",
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

KEEP_CONCEPT_SECTIONS = (
    "完了扱い条件",
    "正本と副本",
    "ルールとドキュメント",
    "詳細仕様の参照先",
    "執筆接続（writing_bridge）",
)


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


def test_writing_bridge_routing_is_single_path() -> None:
    concepts = (RULES / "concepts.md").read_text(encoding="utf-8")
    workflow = (RULES / "workflow-specification.md").read_text(encoding="utf-8")
    writing = (ROOT / ".rulesync" / "skills" / "novel-text-file-output" / "SKILL.md").read_text(encoding="utf-8")
    refinement = (ROOT / ".rulesync" / "skills" / "novel-refinement-output" / "SKILL.md").read_text(encoding="utf-8")
    reflection = (ROOT / ".rulesync" / "skills" / "novel-story-reflection" / "SKILL.md").read_text(encoding="utf-8")
    assert "執筆接続（writing_bridge）" in concepts
    assert "執筆接続の起動判定" in workflow
    assert "経路を一つ選ぶ" in writing
    assert "手編集で `_novel_text` を置換しない" in writing
    assert "同じ版へ `metron_cli.py analyze`" in writing
    assert "本スキルの正本更新を重ねない" in refinement
    assert "自動の再計測・イベント更新を起動しない" in refinement
    assert "CLIは `_meta.md` を書き換えない" in reflection
    assert "修復中" in reflection


def _cli_commands(block: str) -> list[str]:
    commands: list[str] = []
    buf = ""
    for raw in block.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            if buf:
                commands.append(" ".join(buf.split()))
                buf = ""
            continue
        if line.endswith("\\"):
            buf += line[:-1].rstrip() + " "
            continue
        buf += line
        commands.append(" ".join(buf.split()))
        buf = ""
    if buf:
        commands.append(" ".join(buf.split()))
    return commands


def _run_id(command: str) -> str | None:
    match = re.search(r"--run-id\s+(\S+)", command)
    return match.group(1) if match else None


def _assert_allow_publish_prepare_selector(command: str, *, path: Path | str = "") -> None:
    """未作成/空の new は selector なし。既存非空の refine は selector 必須。"""
    if "writing_bridge_cli.py prepare" not in command or "--allow-publish" not in command:
        return
    kind_match = re.search(r"--request-kind\s+(\S+)", command)
    kind = kind_match.group(1) if kind_match else "new"
    has_selector = "--selector-kind" in command
    loc = f" ({path})" if path else ""
    if kind == "new":
        assert not has_selector, f"レシピ1の new に selector がある{loc}: {command}"
        return
    if kind == "refine":
        assert has_selector, f"レシピ2の refine に selector が無い{loc}: {command}"
        return
    if kind == "append":
        return
    raise AssertionError(f"未定義の request-kind {kind}{loc}: {command}")


def test_docs_prepare_dry_run_is_not_followed_by_receive() -> None:
    text = (ROOT / "docs" / "tools" / "index.md").read_text(encoding="utf-8")
    start = text.index("### `writing_bridge_cli.py`")
    end = text.index("### `book_review.py`")
    for block in re.findall(r"```bash\n(.*?)```", text[start:end], re.S):
        pending_dry = False
        for command in _cli_commands(block):
            if "writing_bridge_cli.py prepare" in command and "--dry-run" in command:
                pending_dry = True
                continue
            if not pending_dry:
                continue
            if "writing_bridge_cli.py prepare" in command and "--dry-run" not in command:
                pending_dry = False
                continue
            if "writing_bridge_cli.py" in command:
                raise AssertionError(
                    "prepare --dry-run の次に本番 prepare 以外の writing_bridge コマンドがある: "
                    + command
                )


def test_instruction_driven_draft_prepare_omits_allow_publish() -> None:
    text = (ROOT / "docs" / "workflow" / "instruction-driven.md").read_text(encoding="utf-8")
    start = text.index("### B. 執筆する")
    end = text.index("### C. 清書")
    blocks = re.findall(r"```bash\n(.*?)```", text[start:end], re.S)
    assert len(blocks) >= 2
    draft = _cli_commands(blocks[0])
    save_blocks = [_cli_commands(block) for block in blocks[1:]]
    assert all("--allow-publish" not in command for command in draft)
    assert all("writing_bridge_cli.py publish" not in command for command in draft)
    assert save_blocks
    for save in save_blocks:
        assert any(
            "writing_bridge_cli.py prepare" in command and "--allow-publish" in command
            for command in save
        )
        assert any("writing_bridge_cli.py receive" in command for command in save)
        assert any("writing_bridge_cli.py inspect" in command for command in save)
        for command in save:
            _assert_allow_publish_prepare_selector(command)
        kinds = []
        for command in save:
            if "writing_bridge_cli.py receive" in command:
                kinds.append("receive")
            elif "writing_bridge_cli.py inspect" in command:
                kinds.append("inspect")
            elif "writing_bridge_cli.py publish" in command:
                kinds.append("publish")
        assert kinds.index("receive") < kinds.index("inspect") < kinds.index("publish")
        publish_ids = {_run_id(command) for command in save if "writing_bridge_cli.py publish" in command}
        receive_ids = {_run_id(command) for command in save if "writing_bridge_cli.py receive" in command}
        inspect_ids = {_run_id(command) for command in save if "writing_bridge_cli.py inspect" in command}
        assert publish_ids and publish_ids <= receive_ids
        assert inspect_ids == receive_ids
        assert "run-0001" not in publish_ids


def test_docs_publish_recipe_does_not_reuse_draft_run() -> None:
    pages = (
        (
            ROOT / "docs" / "tools" / "index.md",
            "### `writing_bridge_cli.py`",
            "### `book_review.py`",
            "bash",
        ),
        (
            ROOT / "docs" / "workflow" / "instruction-driven.md",
            "### B. 執筆する",
            "### C. 清書",
            "bash",
        ),
        (
            ROOT / "docs" / "architecture" / "writing-bridge.md",
            "## 本文正本への反映",
            "## 中断と再開",
            "powershell",
        ),
    )
    for path, start_mark, end_mark, fence in pages:
        text = path.read_text(encoding="utf-8")
        section = text[text.index(start_mark) : text.index(end_mark)]
        for block in re.findall(rf"```{fence}\n(.*?)```", section, re.S):
            commands = _cli_commands(block)
            publishes = [
                command
                for command in commands
                if "writing_bridge_cli.py publish" in command
            ]
            if not publishes:
                assert all("--allow-publish" not in command for command in commands), path
                continue
            assert any(
                "writing_bridge_cli.py prepare" in command
                and "--allow-publish" in command
                and "--dry-run" not in command
                for command in commands
            ), path
            assert not any(
                "writing_bridge_cli.py prepare" in command
                and "--allow-publish" not in command
                and "--dry-run" not in command
                for command in commands
            ), path
            assert any("writing_bridge_cli.py receive" in command for command in commands), path
            assert any("writing_bridge_cli.py inspect" in command for command in commands), path
            kinds = []
            for command in commands:
                if "writing_bridge_cli.py receive" in command:
                    kinds.append("receive")
                elif "writing_bridge_cli.py inspect" in command:
                    kinds.append("inspect")
                elif "writing_bridge_cli.py publish" in command:
                    kinds.append("publish")
            assert kinds.index("receive") < kinds.index("inspect") < kinds.index("publish"), path
            for command in commands:
                _assert_allow_publish_prepare_selector(command, path=path)
            publish_ids = {_run_id(command) for command in publishes}
            receive_ids = {
                _run_id(command)
                for command in commands
                if "writing_bridge_cli.py receive" in command
            }
            assert publish_ids and None not in publish_ids, path
            assert publish_ids <= receive_ids, path
            assert "run-0001" not in publish_ids, path


def test_sequential_chapter_contract_is_explicit() -> None:
    """複数章依頼の章境界と、次章へ進む根拠を正本・docs間で固定する。"""
    concepts = (RULES / "concepts.md").read_text(encoding="utf-8")
    workflow = (RULES / "workflow-specification.md").read_text(encoding="utf-8")
    writing = (ROOT / ".rulesync" / "skills" / "novel-text-file-output" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    refinement = (ROOT / ".rulesync" / "skills" / "novel-refinement-output" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    instruction = (ROOT / "docs" / "workflow" / "instruction-driven.md").read_text(encoding="utf-8")

    # F1: 範囲指定でも1章で止めることを概念正本とdocsに示す。
    assert "第X〜Y章と範囲" in concepts
    assert "1回の応答で完了報告してよい本文は1章" in concepts
    assert "最初の未完了章だけを扱い" in instruction
    assert "次章は完了報告のあと" in instruction

    # F2: 「次」の解決元をチャット記憶にしない。
    assert "_meta.md" in writing
    assert "完了している最新章" in writing
    assert "チャットの記憶だけで決めず" in writing

    # F4/F5: 未完了前章と全対象完了の条件を保持する。
    assert "前章が未完了のまま後続章を指定された場合" in writing
    assert "分割本文・複数sceneは一覧の全対象が完了するまで章完了にしない" in writing
    assert "本文と準備を始めず未完了理由" in instruction

    # F9: 章境界と経路の責任分界を別の正本へ向ける。
    assert "章境界は `concepts.md` の「完了扱い条件」" in workflow
    assert "経路の短い不変条件は `concepts.md` の「執筆接続（writing_bridge）」" in workflow
    assert "章境界の詳細は **`novel-text-file-output`**" in refinement


def test_sequential_chapter_bridge_grammar_contract_is_explicit() -> None:
    """F7: bridge候補を受領前に校正し、publish後の正本を直接fixしない。"""
    writing = (ROOT / ".rulesync" / "skills" / "novel-text-file-output" / "SKILL.md").read_text(
        encoding="utf-8"
    )
    workflow = (RULES / "workflow-specification.md").read_text(encoding="utf-8")
    assert "`receive` 前に候補へ `grammar --fix-dry-run`" in writing
    assert "publish後の正本へこの節の `--fix` を直接適用しない" in writing
    assert "writing_bridge の候補は `receive` 前に校正" in workflow
