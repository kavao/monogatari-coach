"""フキダシの設計位置の下書き（bubble_draft.py / novel_manga_bubbles_draft.py）と描き分け。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest
import yaml

_TOOLS_ROOT = Path(__file__).resolve().parents[2]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

from manga_prompt_ir.bubble_draft import DraftText, draft_panel  # noqa: E402
from manga_prompt_ir.bubble_geometry import load_bubble_design  # noqa: E402
from manga_prompt_ir.panel_assembly import BALLOON_STYLES, PanelAssemblyError, balloon_image  # noqa: E402

_EXAMPLES = _TOOLS_ROOT / "manga_prompt_ir" / "examples"


def _inside(inner, outer) -> bool:
    return inner[0] >= outer[0] and inner[1] >= outer[1] and inner[2] <= outer[2] and inner[3] <= outer[3]


def _overlap(a, b) -> bool:
    return not (a[2] <= b[0] or b[2] <= a[0] or a[3] <= b[1] or b[3] <= a[1])


def test_draft_places_right_to_left_inside_panel_without_overlap() -> None:
    frame = (100, 100, 1300, 700)
    items = [DraftText(f"t{i}", "speech", 8, 42) for i in range(3)]
    result = draft_panel(frame, items)
    assert result.fitted and result.scale == 1.0
    boxes = [b.frame for b in result.bubbles]
    assert all(_inside(box, frame) for box in boxes)
    assert not any(_overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1 :])
    # 右から左（1つ目が一番右）
    assert boxes[0][0] > boxes[1][0] > boxes[2][0]
    # 文字の範囲はフキダシの内側、台詞にはしっぽ
    for bubble in result.bubbles:
        assert _inside(bubble.text, bubble.frame)
        assert bubble.tail and len(bubble.tail) == 3


def test_draft_shrinks_when_panel_is_small() -> None:
    frame = (0, 0, 400, 300)
    items = [DraftText(f"t{i}", "speech", 20, 42) for i in range(3)]
    result = draft_panel(frame, items)
    assert result.scale < 1.0 or not result.fitted
    if result.fitted:
        boxes = [b.frame for b in result.bubbles]
        assert not any(_overlap(a, b) for i, a in enumerate(boxes) for b in boxes[i + 1 :])
    else:
        assert all(b.allow_overlap for b in result.bubbles)


def test_draft_types_narration_and_sfx_have_no_tail() -> None:
    result = draft_panel((0, 0, 1000, 800), [DraftText("n", "narration", 10, 42), DraftText("s", "sfx", 3, 42)])
    assert all(b.tail is None for b in result.bubbles)


@pytest.mark.parametrize("style", list(BALLOON_STYLES))
def test_balloon_styles_draw(style: str) -> None:
    image = balloon_image((300, 300), style, (50, 50, 250, 180), [(140, 170), (120, 280), (160, 170)], 3)
    if style == "sfx":
        assert image is None
    else:
        assert image is not None and image.getchannel("A").getbbox() is not None


def test_unknown_balloon_style_is_rejected() -> None:
    with pytest.raises(PanelAssemblyError, match="描き方"):
        balloon_image((100, 100), "cloud9", (10, 10, 90, 90), None, 2)


def test_shout_hint_selects_shout_style() -> None:
    from novel_manga_assemble_psd import balloon_style

    assert balloon_style("speech", "shout bubble") == "shout"
    assert balloon_style("speech", "叫びのフキダシ") == "shout"
    assert balloon_style("speech", "small speech bubble") == "speech"
    assert balloon_style("thought", "shout") == "thought"


# ── CLI ───────────────────────────────────────────────


def _novel(tmp_path: Path) -> Path:
    novel = tmp_path / "novel"
    pages = novel / "manga" / "pages"
    pages.mkdir(parents=True)
    shutil.copy2(_EXAMPLES / "manga_page_5panel.yaml", pages / "manga_01_p01.yaml")
    return novel


def _cli(argv: list[str]) -> int:
    from novel_manga_bubbles_draft import main

    return main(argv)


def test_cli_dry_run_writes_nothing(tmp_path: Path) -> None:
    novel = _novel(tmp_path)
    assert _cli([str(novel)]) == 0
    assert not (novel / "manga" / "pages" / "manga_01_p01.bubbles.yaml").exists()


def test_cli_apply_writes_valid_design_covering_all_texts(tmp_path: Path) -> None:
    from manga_prompt_ir.bubble_geometry import local_frame_targets

    novel = _novel(tmp_path)
    assert _cli([str(novel), "--apply"]) == 0
    sidecar = novel / "manga" / "pages" / "manga_01_p01.bubbles.yaml"
    text = sidecar.read_text(encoding="utf-8")
    assert text.startswith("# 自動の下書き")
    document = load_bubble_design(yaml.safe_load(text))
    page = yaml.safe_load((novel / "manga" / "pages" / "manga_01_p01.yaml").read_text(encoding="utf-8"))
    targets = {(t["text_id"], t["panel_id"]) for t in local_frame_targets(page)}
    assert {(b.text_id, b.panel_id) for b in document.bubbles} == targets
    kinds = {t["text_id"]: t["type"] for t in local_frame_targets(page)}
    mapping = {"dialogue": "speech", "monologue": "thought", "narration": "narration", "sfx": "sfx"}
    assert all(b.bubble_type == mapping[kinds[b.text_id]] for b in document.bubbles)


def test_cli_keeps_existing_and_backs_up_on_overwrite(tmp_path: Path) -> None:
    novel = _novel(tmp_path)
    pages = novel / "manga" / "pages"
    assert _cli([str(novel), "--apply"]) == 0
    sidecar = pages / "manga_01_p01.bubbles.yaml"
    sidecar.write_text(sidecar.read_text(encoding="utf-8") + "# 手で直した\n", encoding="utf-8")
    edited = sidecar.read_text(encoding="utf-8")
    assert _cli([str(novel), "--apply"]) == 0
    assert sidecar.read_text(encoding="utf-8") == edited
    assert _cli([str(novel), "--apply", "--overwrite"]) == 0
    backups = list((pages / "_old").glob("*/manga_01_p01.bubbles.yaml"))
    assert len(backups) == 1 and backups[0].read_text(encoding="utf-8") == edited


def test_cli_skips_text_mode_none(tmp_path: Path, capsys) -> None:
    novel = _novel(tmp_path)
    page = novel / "manga" / "pages" / "manga_01_p01.yaml"
    data = yaml.safe_load(page.read_text(encoding="utf-8"))
    data["render_instruction"]["text_mode"] = "none"
    data["render_instruction"]["text_policy"] = "No text in the image."
    data["manga"]["text_policy"] = "No text in the image."
    page.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    assert _cli([str(novel), "--apply"]) == 0
    assert "text_mode が none" in capsys.readouterr().out
