"""漫画バッチの保存先: コマ=comic/、ページ=pages/、背景資料=backgrounds/。"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

import pytest

_TOOLS_ROOT = Path(__file__).resolve().parents[1]
if str(_TOOLS_ROOT) not in sys.path:
    sys.path.insert(0, str(_TOOLS_ROOT))

import image_provider_novel_manga_batch as manga_batch  # noqa: E402
import novel_image_layout as nil  # noqa: E402

_P4 = _TOOLS_ROOT / "manga_prompt_ir" / "examples" / "p4_compare"

_MARKDOWN_PAGE = """# 漫画

## Page 1

### Step1
コマ1: 少女が駅に立つ。
- **tag**：
`1girl, standing, station`

### Step2
コマ1: 少女が駅に立ち、切符を見る。
"""


def _yaml_novel(tmp_path: Path) -> Path:
    novel = tmp_path / "001_fixture"
    (novel / "manga").mkdir(parents=True)
    shutil.copytree(_P4 / "manga" / "pages", novel / "manga" / "pages")
    shutil.copytree(_P4 / "tag", novel / "tag")
    return novel


def _markdown_novel(tmp_path: Path) -> Path:
    novel = tmp_path / "002_fixture"
    manga = novel / "manga"
    manga.mkdir(parents=True)
    (manga / "manga_01.md").write_text(_MARKDOWN_PAGE, encoding="utf-8")
    return novel


def _assets(novel: Path) -> Path:
    return (novel / "manga" / "_assets" / "manga_01").resolve()


@pytest.mark.parametrize(
    ("source", "provider", "formatter", "subdir"),
    [
        ("step1-panels", "forge", "tag_csv", "comic"),
        ("step1-pages", "openrouter", "manga_page_instruction", "pages"),
        ("step2-pages", "openrouter", "manga_page_instruction", "pages"),
        ("background-concepts", "forge", "tag_csv", "backgrounds"),
    ],
)
def test_yaml_jobs_use_source_specific_output_dir(
    tmp_path: Path, source: str, provider: str, formatter: str, subdir: str
) -> None:
    novel = _yaml_novel(tmp_path)
    jobs = manga_batch.iter_yaml_manga_jobs(
        novel,
        "manga_01",
        source,
        provider,
        None,
        cli_negative_prompt="",
        prompt_formatter=formatter,
    )
    assert jobs
    expected = (_assets(novel) / subdir).as_posix()
    assert {Path(job["output_dir"]).as_posix() for job in jobs} == {expected}


@pytest.mark.parametrize(
    ("source", "subdir"),
    [
        ("step1-panels", "comic"),
        ("step1-pages", "pages"),
        ("step2-pages", "pages"),
    ],
)
def test_markdown_jobs_use_source_specific_output_dir(
    tmp_path: Path, source: str, subdir: str
) -> None:
    novel = _markdown_novel(tmp_path)
    jobs = manga_batch.iter_manga_jobs(
        novel,
        "manga_01",
        source,
        "forge",
        None,
        no_character_anchors=True,
    )
    assert jobs
    expected = (_assets(novel) / subdir).as_posix()
    assert {Path(job["output_dir"]).as_posix() for job in jobs} == {expected}


@pytest.mark.parametrize("source", ["step1-pages", "step2-pages"])
def test_subdir_by_page_is_rejected_for_page_sources(
    tmp_path: Path, source: str, capsys: pytest.CaptureFixture[str]
) -> None:
    novel = _yaml_novel(tmp_path)
    rc = manga_batch.main(
        [
            str(novel),
            "--manga-stem",
            "manga_01",
            "--source",
            source,
            "--provider",
            "openrouter",
            "--subdir-by-page",
            "--dry-run",
        ]
    )
    assert rc == 2
    assert "--subdir-by-page" in capsys.readouterr().err
    assert not (novel / "manga" / "_assets").exists()


def test_subdir_by_page_keeps_comic_page_folders_for_panels(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    novel = _yaml_novel(tmp_path)
    rc = manga_batch.main(
        [
            str(novel),
            "--manga-stem",
            "manga_01",
            "--source",
            "step1-panels",
            "--provider",
            "forge",
            "--subdir-by-page",
            "--dry-run",
        ]
    )
    assert rc == 0
    assert (_assets(novel) / "comic" / "p01").as_posix() in capsys.readouterr().out


def test_scaffold_creates_comic_pages_backgrounds(tmp_path: Path) -> None:
    novel = _markdown_novel(tmp_path)
    created = nil.scaffold_manga_dirs(novel, None)
    base = novel / "manga" / "_assets" / "manga_01"
    assert created == [base / "comic", base / "pages", base / "backgrounds", base / "names", base / "assembled"]
    assert all(path.is_dir() for path in created)


def test_panel_negative_omit_after_panel_additions(tmp_path: Path) -> None:
    import yaml
    from tag_prompt_mask import load_novel_negative_omit

    novel = _yaml_novel(tmp_path)
    (novel / "_meta.yaml").write_text("character_tag_batch:\n  omit_negative_tags: [child]\nmanga_tag_batch:\n  omit_negative_tags: [loli]\n", encoding="utf-8")
    page_path = next(p for p in (novel / "manga" / "pages").glob("manga_01_p*.yaml") if not p.name.endswith(".bubbles.yaml"))
    page = yaml.safe_load(page_path.read_text(encoding="utf-8"))
    page.setdefault("technical", {})["negative_tags"] = ["technical_bad", "loli"]
    page["panels"][0]["omit_negative_tags"] = ["panel_local"]
    page["panels"][0]["negative_tags"] = ["panel_local", "child", "cli_bad"]
    page_path.write_text(yaml.safe_dump(page, allow_unicode=True), encoding="utf-8")
    rules = (*load_novel_negative_omit(novel, primary_key="manga_tag_batch", fallback_key="character_tag_batch"), "cli_bad")
    jobs = manga_batch.iter_yaml_manga_jobs(novel, "manga_01", "step1-panels", "forge", None, cli_negative_prompt="panel_local, child, keep", prompt_formatter="tag_csv", negative_omit=rules)
    job = next(job for job in jobs if job["page"] == "1" and job["koma"] == "1")
    assert job["negative_prompt"] == "keep, technical_bad, panel_local"
    assert job["negative_omitted"] == ["child", "loli", "cli_bad"]
    unchanged = manga_batch.iter_yaml_manga_jobs(novel, "manga_01", "step1-panels", "forge", None, cli_negative_prompt="panel_local, child, keep", prompt_formatter="tag_csv")
    assert "child" in unchanged[0]["negative_prompt"]
    assert "panel_local" in unchanged[0]["negative_prompt"]


def test_manga_cli_negative_omit_and_unsupported_warning(tmp_path, monkeypatch, capsys) -> None:
    from types import SimpleNamespace
    novel = _yaml_novel(tmp_path)
    (novel / "_meta.yaml").write_text("character_tag_batch:\n  omit_negative_tags: [child]\nmanga_tag_batch:\n  omit_negative_tags: [loli]\n", encoding="utf-8")
    monkeypatch.setattr(manga_batch, "dotenv_or_env", lambda *a, **kw: None)
    monkeypatch.setattr(manga_batch, "resolve_novelai_reference", lambda *a, **kw: SimpleNamespace(paths=[], source="none", strength=0.5, information_extracted=0.5))
    monkeypatch.setattr(manga_batch, "preview_merged_params", lambda *a, **kw: {})
    code = manga_batch.main([str(novel), "--manga-stem", "manga_01", "--input", "yaml", "--source", "step1-panels", "--provider", "forge", "--dry-run", "--negative-prompt", "child, loli, cli_bad, keep", "--omit-negative-tags", "cli_bad"])
    assert code == 0
    out = capsys.readouterr().out
    assert "omit_negative_tags: child, loli, cli_bad" in out
    assert "negative omitted: child, loli, cli_bad" in out
    assert "negative: keep" in out
    code = manga_batch.main([str(novel), "--manga-stem", "manga_01", "--input", "yaml", "--source", "step1-pages", "--provider", "forge", "--dry-run", "--omit-negative-tags", "cli_bad"])
    assert code == 0
    assert "omit_negative_tags は YAML step1-panels のみ" in capsys.readouterr().err
