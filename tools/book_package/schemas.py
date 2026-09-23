"""Pydantic contracts for the Phase 1 publishing package."""

from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re
from typing import Any, Literal, TypeVar

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


_IDENTIFIER_PATTERN = r"^[a-z][a-z0-9_]*$"
_CHAPTER_IDENTIFIER_PATTERN = re.compile(r"^ch\d{2,}$")
ModelT = TypeVar("ModelT", bound=BaseModel)


class StrictModel(BaseModel):
    """Reject misspelled declaration keys instead of silently ignoring them."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class PersonCredit(StrictModel):
    name: str = Field(min_length=1)
    kana: str | None = None


class BookInfo(StrictModel):
    title: str = Field(min_length=1)
    subtitle: str | None = None
    volume: int | None = Field(default=1, ge=1)
    author: PersonCredit
    illustrator: PersonCredit | None = None
    genre: list[str] = Field(default_factory=list)
    synopsis: str | None = None


class BookFormat(StrictModel):
    primary: Literal["paperback", "ebook", "web"]
    writing_direction: Literal["vertical", "horizontal"]
    binding: Literal["right", "left"]
    trim_size: str = Field(min_length=1)
    target_pages: int | None = Field(default=None, ge=1)


class ManuscriptEntry(StrictModel):
    """One logical publication section, backed by one or more source files."""

    id: str = Field(pattern=_IDENTIFIER_PATTERN)
    title: str = Field(min_length=1)
    file: str | None = None
    files: list[str] = Field(default_factory=list)
    start_page_policy: Literal["odd_page", "any"] = "any"

    @model_validator(mode="after")
    def require_exactly_one_file_form(self) -> "ManuscriptEntry":
        if bool(self.file) == bool(self.files):
            raise ValueError("Specify exactly one of file or files.")
        return self

    def source_files(self) -> list[str]:
        return [self.file] if self.file is not None else list(self.files)


class Manuscript(StrictModel):
    source: Literal["novel_text", "novel_text_re"] | None = None
    frontmatter: list[ManuscriptEntry] = Field(default_factory=list)
    chapters: list[ManuscriptEntry] = Field(min_length=1)
    backmatter: list[ManuscriptEntry] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_entry_ids(self) -> "Manuscript":
        chapter_ids = [entry.id for entry in self.chapters]
        if any(_CHAPTER_IDENTIFIER_PATTERN.fullmatch(entry_id) is None for entry_id in chapter_ids):
            raise ValueError("manuscript.chapters[].id must use the chNN form.")

        all_ids = [
            *(entry.id for entry in self.frontmatter),
            *chapter_ids,
            *(entry.id for entry in self.backmatter),
        ]
        if len(all_ids) != len(set(all_ids)):
            raise ValueError("manuscript entry ids must be unique across all sections.")
        return self


class Illustration(StrictModel):
    id: str = Field(pattern=_IDENTIFIER_PATTERN)
    type: Literal["cover", "frontispiece", "insert", "chapter_title", "character_intro"]
    color: bool
    scene_ref: str | None = None
    brief: str = Field(min_length=1)
    status: Literal["planned", "ordered", "delivered", "approved"]
    asset: str | None = None


class CoverFront(StrictModel):
    title_display: str | None = None
    credit_author: bool = True
    credit_illustrator: bool = True


class CoverSpine(StrictModel):
    enabled: bool = True


class CoverBack(StrictModel):
    isbn: str | None = None
    barcode: bool = False
    blurb: str | None = None


class Cover(StrictModel):
    front: CoverFront = Field(default_factory=CoverFront)
    spine: CoverSpine = Field(default_factory=CoverSpine)
    back: CoverBack = Field(default_factory=CoverBack)


class Colophon(StrictModel):
    # Historical works sometimes preserve the original creation timestamp as
    # their publication record. Keep date-only declarations valid as well.
    publish_date: date | datetime | None = None
    edition: str | None = None
    publisher: str | None = None
    contact: str | None = None
    printer: str | None = None
    copyright_notice: str | None = None


class PaperExport(StrictModel):
    bleed_mm: float = Field(default=3, ge=0)
    format: str = Field(default="pdf_x1a", min_length=1)


class EbookExport(StrictModel):
    format: str = Field(default="epub3", min_length=1)
    cover_image: str | None = None


class WebExport(StrictModel):
    platform: Literal["kakuyomu", "narou", "pixiv"] = "kakuyomu"
    chapter_split: Literal["per_chapter", "per_scene"] = "per_chapter"


class ExportSettings(StrictModel):
    paper: PaperExport = Field(default_factory=PaperExport)
    ebook: EbookExport = Field(default_factory=EbookExport)
    web: WebExport = Field(default_factory=WebExport)


class Price(StrictModel):
    paper_jpy: int | None = Field(default=None, ge=0)
    ebook_jpy: int | None = Field(default=None, ge=0)


class Sales(StrictModel):
    catch_copy: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    price: Price = Field(default_factory=Price)


class ProductionResources(StrictModel):
    """Names of fonts and third-party materials used by the publication."""

    fonts: list[str] = Field(default_factory=list)
    materials: list[str] = Field(default_factory=list)


class BookPackage(StrictModel):
    schema_version: Literal[2]
    book: BookInfo
    format: BookFormat
    manuscript: Manuscript
    illustrations: list[Illustration] = Field(default_factory=list)
    cover: Cover = Field(default_factory=Cover)
    colophon: Colophon = Field(default_factory=Colophon)
    export: ExportSettings = Field(default_factory=ExportSettings)
    sales: Sales = Field(default_factory=Sales)
    resources: ProductionResources = Field(default_factory=ProductionResources)

    @model_validator(mode="after")
    def validate_illustration_ids(self) -> "BookPackage":
        ids = [illustration.id for illustration in self.illustrations]
        if len(ids) != len(set(ids)):
            raise ValueError("illustrations[].id must be unique.")
        return self


class UsagePermission(StrictModel):
    permission: Literal["allowed", "not_allowed", "unconfirmed"]
    basis: str | None = None
    confirmed_at: date | None = None


class AssetRights(StrictModel):
    holder: str = Field(min_length=1)
    usage: dict[str, UsagePermission] = Field(default_factory=dict)


class FontRights(StrictModel):
    name: str = Field(min_length=1)
    usage_scope: list[Literal["paper_book", "ebook", "web", "promotion"]] = Field(
        default_factory=list
    )
    license: str | None = None
    basis: str | None = None
    confirmed_at: date | None = None


class MaterialRights(StrictModel):
    name: str = Field(min_length=1)
    usage_scope: list[Literal["paper_book", "ebook", "web", "promotion"]] = Field(
        default_factory=list
    )
    license: str | None = None
    basis: str | None = None
    confirmed_at: date | None = None


class Copyright(StrictModel):
    notice: str | None = None
    note: str | None = None


class RightsPackage(StrictModel):
    schema_version: Literal[2]
    assets: dict[str, AssetRights] = Field(default_factory=dict)
    fonts: list[FontRights] = Field(default_factory=list)
    materials: list[MaterialRights] = Field(default_factory=list)
    copyright: Copyright = Field(default_factory=Copyright)


# --- cover.yaml (Phase C1: layout only; bibliography stays in book.yaml) ---


class CoverBox(StrictModel):
    """Normalized finish-area box. Origin top-left, values in 0.0–1.0."""

    x: float = Field(ge=0.0, le=1.0)
    y: float = Field(ge=0.0, le=1.0)
    w: float = Field(gt=0.0, le=1.0)
    h: float = Field(gt=0.0, le=1.0)

    @model_validator(mode="after")
    def within_finish(self) -> "CoverBox":
        if self.x + self.w > 1.0 + 1e-9 or self.y + self.h > 1.0 + 1e-9:
            raise ValueError("cover layer box must stay within the finish area (0–1).")
        return self


class CoverTypography(StrictModel):
    font_ref: str = Field(min_length=1)
    direction: Literal["vertical", "horizontal"] = "vertical"
    size_pt: float = Field(default=14.0, gt=0)
    tracking: float = Field(default=0.0)
    color: str = Field(default="#ffffff", min_length=1)


class CoverLayer(StrictModel):
    id: str = Field(pattern=_IDENTIFIER_PATTERN)
    type: Literal["text", "logo_asset", "shape", "image", "barcode"]
    source: str | None = None
    value: str | None = None
    required: bool = False
    box: CoverBox
    typography: CoverTypography | None = None
    # shape / logo / image / barcode extras (kept minimal for C1)
    fill: str | None = None
    asset: str | None = None
    opacity: float | None = Field(default=None, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_layer_payload(self) -> "CoverLayer":
        if self.type == "text":
            if self.typography is None:
                raise ValueError("text layers require typography.")
            if self.source is None and self.value is None:
                raise ValueError("text layers require source or value.")
        if self.type in {"logo_asset", "image", "barcode"} and self.asset is None:
            raise ValueError(f"{self.type} layers require asset.")
        if self.type == "shape" and self.fill is None:
            raise ValueError("shape layers require fill.")
        return self


class CoverBaseArt(StrictModel):
    illustration_id: str = Field(pattern=_IDENTIFIER_PATTERN)
    fit: Literal["contain", "cover"] = "contain"
    background: str = Field(default="#ffffff", min_length=1)


class CoverFontFace(StrictModel):
    family: str = Field(min_length=1)
    file: str | None = None
    subfont_index: int = Field(default=0, ge=0)


class CoverProfileRef(StrictModel):
    canvas: str = Field(min_length=1)


class CoverLayout(StrictModel):
    """cover.yaml — where/how to place layers. Does not duplicate bibliography."""

    schema_version: Literal[1]
    base_art: CoverBaseArt
    layers: list[CoverLayer] = Field(default_factory=list)
    safe_areas: dict[str, CoverBox] = Field(default_factory=dict)
    fonts: dict[str, CoverFontFace] = Field(default_factory=dict)
    profiles: dict[str, CoverProfileRef] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_font_refs_and_layer_ids(self) -> "CoverLayout":
        layer_ids = [layer.id for layer in self.layers]
        if len(layer_ids) != len(set(layer_ids)):
            raise ValueError("cover layers[].id must be unique.")
        for layer in self.layers:
            if layer.type != "text" or layer.typography is None:
                continue
            if layer.typography.font_ref not in self.fonts:
                raise ValueError(
                    f"layers[{layer.id}].typography.font_ref "
                    f"{layer.typography.font_ref!r} is not declared under fonts."
                )
        return self


def _load_mapping(path: Path) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise ValueError(f"Unable to read YAML: {path}") from exc
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML: {path}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"YAML root must be a mapping: {path}")
    return data


def _load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    return model_type.model_validate(_load_mapping(path))


def load_book_package(path: str | Path) -> BookPackage:
    book = _load_model(Path(path), BookPackage)
    from .paths import validate_book_file_references

    validate_book_file_references(book)
    return book


def load_rights_package(path: str | Path) -> RightsPackage:
    return _load_model(Path(path), RightsPackage)


def load_cover_layout(path: str | Path) -> CoverLayout:
    """Load and validate cover.yaml (layout only; no book.yaml path checks)."""

    return _load_model(Path(path), CoverLayout)
