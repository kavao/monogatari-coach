"""Machine-readable inspection for a generated paper proof PDF."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfReader

from .build import POINTS_PER_MM


class PreflightError(ValueError):
    """The requested PDF or manifest cannot be inspected."""


def _resolve(value: Any) -> Any:
    return value.get_object() if hasattr(value, "get_object") else value


def _embedded_font(font: Any) -> bool:
    candidate = _resolve(font)
    descriptor = _resolve(candidate.get("/FontDescriptor")) if candidate else None
    if descriptor and any(key in descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")):
        return True
    descendants = candidate.get("/DescendantFonts") if candidate else None
    if descendants:
        for descendant in descendants:
            nested = _resolve(descendant)
            nested_descriptor = _resolve(nested.get("/FontDescriptor"))
            if nested_descriptor and any(
                key in nested_descriptor for key in ("/FontFile", "/FontFile2", "/FontFile3")
            ):
                return True
    return False


def _page_resources(page: Any) -> tuple[list[dict[str, Any]], int]:
    resources = _resolve(page.get("/Resources")) or {}
    fonts = _resolve(resources.get("/Font")) or {}
    font_data = [
        {
            "resource": str(name),
            "base_font": str(_resolve(font).get("/BaseFont", "")),
            "embedded": _embedded_font(font),
        }
        for name, font in fonts.items()
    ]
    xobjects = _resolve(resources.get("/XObject")) or {}
    image_count = 0
    for xobject in xobjects.values():
        obj = _resolve(xobject)
        if obj.get("/Subtype") == "/Image":
            image_count += 1
    return font_data, image_count


def _finding(
    findings: list[dict[str, str]],
    rule: str,
    severity: str,
    message: str,
    suggested_action: str,
) -> None:
    findings.append(
        {
            "rule": rule,
            "severity": severity,
            "message": message,
            "suggested_action": suggested_action,
        }
    )


def preflight_paper_pdf(pdf_path: str | Path, manifest: dict[str, Any]) -> dict[str, Any]:
    """Check page geometry, embedded fonts, image placement and odd-page starts."""

    pdf = Path(pdf_path)
    if not pdf.is_file():
        raise PreflightError(f"PDF がありません: {pdf}")
    if manifest.get("target") != "paper":
        raise PreflightError("paper build manifest が必要です。")

    try:
        reader = PdfReader(str(pdf), strict=True)
    except Exception as exc:  # pypdf uses several exception types
        raise PreflightError(f"PDF を読み込めません: {exc}") from exc

    findings: list[dict[str, str]] = []
    profile = manifest["profile"]
    expected_width = float(profile["width_mm"]) * POINTS_PER_MM
    expected_height = float(profile["height_mm"]) * POINTS_PER_MM
    page_reports: list[dict[str, Any]] = []
    all_fonts: list[dict[str, Any]] = []

    for number, page in enumerate(reader.pages, start=1):
        box = page.mediabox
        width = float(box.width)
        height = float(box.height)
        fonts, images = _page_resources(page)
        all_fonts.extend(fonts)
        page_reports.append(
            {
                "number": number,
                "width_pt": round(width, 3),
                "height_pt": round(height, 3),
                "image_count": images,
                "fonts": fonts,
            }
        )
        if abs(width - expected_width) > 0.5 or abs(height - expected_height) > 0.5:
            _finding(
                findings,
                "PF-P01",
                "error",
                f"{number}ページ目の寸法が JIS B5 と一致しません: {width:.2f} × {height:.2f} pt",
                "組版プロファイルの仕上がり寸法を 182 × 257 mm に修正してください。",
            )

    if not reader.pages:
        _finding(
            findings,
            "PF-P02",
            "error",
            "PDF にページがありません。",
            "本文ブロックと組版処理を確認してください。",
        )

    unique_fonts = {
        (font["resource"], font["base_font"], bool(font["embedded"]))
        for font in all_fonts
    }
    if not unique_fonts:
        _finding(
            findings,
            "PF-F01",
            "error",
            "PDF にフォントリソースがありません。",
            "日本語 TrueType フォントを登録して本文を描画してください。",
        )
    elif any(not font[2] for font in unique_fonts):
        _finding(
            findings,
            "PF-F01",
            "error",
            "PDF に埋め込まれていないフォントがあります。",
            "埋め込み可能な TrueType フォントを使って再生成してください。",
        )

    for entry in manifest["entries"]:
        if entry["start_page_policy"] != "odd_page":
            continue
        start_page = entry.get("start_page")
        if not isinstance(start_page, int) or start_page % 2 == 0:
            _finding(
                findings,
                "PF-L01",
                "error",
                f"{entry['id']} は odd_page 指定ですが奇数ページで始まりません。",
                "開始前に空白ページを挿入する組版規則を確認してください。",
            )

    minimum_dpi = float(profile["minimum_image_dpi"])
    for placement in manifest.get("placements", []):
        page_number = int(placement["page"])
        if page_number < 1 or page_number > len(page_reports):
            _finding(
                findings,
                "PF-I01",
                "error",
                f"挿絵 {placement['illustration_id']} の配置ページが PDF 範囲外です。",
                "挿絵配置とページ送りの処理を確認してください。",
            )
            continue
        if page_reports[page_number - 1]["image_count"] < 1:
            _finding(
                findings,
                "PF-I01",
                "error",
                f"挿絵 {placement['illustration_id']} が {page_number} ページ目に見つかりません。",
                "illustration directive と採用 asset の解決を確認してください。",
            )
        draw_width_in = float(placement["draw_width_pt"]) / 72.0
        draw_height_in = float(placement["draw_height_pt"]) / 72.0
        dpi = min(
            float(placement["source_width_px"]) / draw_width_in,
            float(placement["source_height_px"]) / draw_height_in,
        )
        placement["effective_dpi"] = round(dpi, 1)
        if dpi < minimum_dpi:
            _finding(
                findings,
                "PF-I02",
                "error",
                f"挿絵 {placement['illustration_id']} の実効解像度が不足しています: {dpi:.1f} dpi",
                f"{minimum_dpi:.0f} dpi 以上になるよう画像か配置寸法を調整してください。",
            )

    _finding(
        findings,
        "PF-X01",
        "warning",
        "この成果物はローカル proof PDF であり、PDF/X-1a と印刷所固有のカラープロファイルは未検証です。",
        "印刷所テンプレート、綴じ、用紙、カラープロファイルを確定後に入稿用カバーと PDF/X を作成してください。",
    )

    errors = sum(finding["severity"] == "error" for finding in findings)
    warnings = sum(finding["severity"] == "warning" for finding in findings)
    return {
        "preflight_version": 1,
        "target": "paper",
        "pdf": pdf.name,
        "conformance": "proof" if errors == 0 else "failed",
        "page_count": len(reader.pages),
        "expected_page_size_pt": {
            "width": round(expected_width, 3),
            "height": round(expected_height, 3),
        },
        "pages": page_reports,
        "findings": findings,
        "summary": {"errors": errors, "warnings": warnings},
    }


def preflight_reader_proof(
    pdf_path: str | Path, manifest: dict[str, Any], *, interior_page_count: int
) -> dict[str, Any]:
    """Check that the reader-facing proof starts with a B5 cover page."""

    pdf = Path(pdf_path)
    if not pdf.is_file():
        raise PreflightError(f"PDF がありません: {pdf}")
    if manifest.get("target") != "paper":
        raise PreflightError("paper build manifest が必要です。")

    try:
        reader = PdfReader(str(pdf), strict=True)
    except Exception as exc:  # pypdf uses several exception types
        raise PreflightError(f"PDF を読み込めません: {exc}") from exc

    findings: list[dict[str, str]] = []
    profile = manifest["profile"]
    expected_width = float(profile["width_mm"]) * POINTS_PER_MM
    expected_height = float(profile["height_mm"]) * POINTS_PER_MM
    page_reports: list[dict[str, Any]] = []
    all_fonts: list[dict[str, Any]] = []

    for number, page in enumerate(reader.pages, start=1):
        box = page.mediabox
        width = float(box.width)
        height = float(box.height)
        fonts, images = _page_resources(page)
        all_fonts.extend(fonts)
        page_reports.append(
            {
                "number": number,
                "width_pt": round(width, 3),
                "height_pt": round(height, 3),
                "image_count": images,
                "fonts": fonts,
            }
        )
        if abs(width - expected_width) > 0.5 or abs(height - expected_height) > 0.5:
            _finding(
                findings,
                "PF-R01",
                "error",
                f"閲覧用 proof の {number} ページ目が JIS B5 と一致しません: {width:.2f} × {height:.2f} pt",
                "表紙と本文を同じ組版プロファイルで再生成してください。",
            )

    expected_page_count = interior_page_count + 1
    if len(reader.pages) != expected_page_count:
        _finding(
            findings,
            "PF-R02",
            "error",
            f"閲覧用 proof のページ数が本文 proof + 表紙1ページになっていません: {len(reader.pages)} ページ",
            "reader-proof.pdf の先頭に表紙1ページだけを結合してください。",
        )
    if not page_reports or page_reports[0]["image_count"] < 1:
        _finding(
            findings,
            "PF-R03",
            "error",
            "閲覧用 proof の1ページ目に表紙画像が見つかりません。",
            "book.yaml の approved な cover asset を指定して再生成してください。",
        )

    unique_fonts = {
        (font["resource"], font["base_font"], bool(font["embedded"]))
        for font in all_fonts
    }
    if not unique_fonts:
        _finding(
            findings,
            "PF-F01",
            "error",
            "PDF にフォントリソースがありません。",
            "本文 proof を埋め込み可能な TrueType フォントで再生成してください。",
        )
    elif any(not font[2] for font in unique_fonts):
        _finding(
            findings,
            "PF-F01",
            "error",
            "PDF に埋め込まれていないフォントがあります。",
            "埋め込み可能な TrueType フォントを使って再生成してください。",
        )

    errors = sum(finding["severity"] == "error" for finding in findings)
    warnings = sum(finding["severity"] == "warning" for finding in findings)
    return {
        "preflight_version": 1,
        "target": "reader",
        "pdf": pdf.name,
        "conformance": "reader_proof" if errors == 0 else "failed",
        "page_count": len(reader.pages),
        "expected_page_count": expected_page_count,
        "expected_page_size_pt": {
            "width": round(expected_width, 3),
            "height": round(expected_height, 3),
        },
        "pages": page_reports,
        "findings": findings,
        "summary": {"errors": errors, "warnings": warnings},
    }


def preflight_paper_build(
    interior_pdf: str | Path, reader_proof_pdf: str | Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    """Run all Phase 2A proof checks for one paper build directory."""

    interior = preflight_paper_pdf(interior_pdf, manifest)
    reader = preflight_reader_proof(
        reader_proof_pdf, manifest, interior_page_count=interior["page_count"]
    )
    artifacts = {"interior": interior, "reader_proof": reader}
    errors = sum(item["summary"]["errors"] for item in artifacts.values())
    warnings = sum(item["summary"]["warnings"] for item in artifacts.values())
    return {
        "preflight_version": 2,
        "target": "paper",
        "conformance": "proof" if errors == 0 else "failed",
        "artifacts": artifacts,
        "summary": {"errors": errors, "warnings": warnings},
    }
