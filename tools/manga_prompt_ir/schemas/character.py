from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from manga_prompt_ir.character_clothing_tokens import find_forbidden_costume_tags


class CharacterAppearance(BaseModel):
    model_config = ConfigDict(extra="forbid")

    age_range: str | None = None
    gender_presentation: str | None = None
    body_type: str | None = None
    height: str | None = None
    face_shape: str | None = None
    eye_shape: str | None = None
    eye_color: str | None = None
    hair_style: str | None = None
    hair_color: str | None = None
    skin_tone: str | None = None
    species_features: list[str] = Field(default_factory=list)
    distinctive_features: list[str] = Field(default_factory=list)


class CharacterCostume(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outfit_tags: list[str] = Field(default_factory=list)
    main_outfit: str | None = None
    accessories: list[str] = Field(default_factory=list)
    color_palette: list[str] = Field(default_factory=list)


class CharacterPersonality(BaseModel):
    model_config = ConfigDict(extra="forbid")

    archetype_tags: list[str] = Field(default_factory=list)
    personality_tags: list[str] = Field(default_factory=list)
    default_expression: str | None = None
    speech_style: str | None = None


class CharacterMangaRules(BaseModel):
    model_config = ConfigDict(extra="forbid")

    consistency_tags: list[str] = Field(default_factory=list)
    do_not_change: list[str] = Field(default_factory=list)
    simplified_chibi_rules: str | None = None
    closeup_rules: str | None = None


class CharacterTagBatchLayers(BaseModel):
    """image_provider_novel_tag_batch.py 向けのプロンプト前後タグ（任意）。"""

    model_config = ConfigDict(extra="forbid")

    prepend_tags: list[str] = Field(default_factory=list)
    append_tags: list[str] = Field(default_factory=list)
    prepend_negative_tags: list[str] = Field(default_factory=list)
    append_negative_tags: list[str] = Field(default_factory=list)


class VisualLayer(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: str
    color: str

    @field_validator("type", "color")
    @classmethod
    def required_nonempty(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("visual_spec の必須項目が空です")
        return text


class VisualOuter(VisualLayer):
    hood: bool
    collar: str
    closure: str

    @field_validator("collar", "closure")
    @classmethod
    def required_nonempty_outer(cls, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise ValueError("visual_spec の必須項目が空です")
        return text


class VisualSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    outer: VisualOuter
    inner: VisualLayer
    bottom: VisualLayer
    shoes: VisualLayer | None = None
    accessories: list[str] = Field(default_factory=list)

    @field_validator("accessories")
    @classmethod
    def accessories_nonempty(cls, values: list[str]) -> list[str]:
        cleaned: list[str] = []
        for item in values:
            text = str(item).strip()
            if not text:
                raise ValueError("visual_spec.accessories に空文字があります")
            cleaned.append(text)
        return cleaned


class CharacterPromptVariant(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variant_id: str
    title: str
    description: str
    danbooru_tags: list[str] = Field(default_factory=list)
    combines_with: str | None = None
    caption: str | None = None
    translation: str | None = None
    variant_kind: Literal["base", "costume", "state", "derived"] | None = None
    visual_spec: VisualSpec | None = None
    inherits_costume: str | None = None
    state_tags: list[str] = Field(default_factory=list)


class CharacterPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0", "1.1"] = "1.0"
    character_id: str
    name: str
    name_en: str | None = None
    role: str | None = None
    appearance: CharacterAppearance = Field(default_factory=CharacterAppearance)
    costume: CharacterCostume = Field(default_factory=CharacterCostume)
    personality: CharacterPersonality = Field(default_factory=CharacterPersonality)
    manga_rules: CharacterMangaRules = Field(default_factory=CharacterMangaRules)
    prompt_variants: list[CharacterPromptVariant] = Field(default_factory=list)
    negative_tags: list[str] = Field(default_factory=list)
    tag_batch: CharacterTagBatchLayers | None = None

    def fixed_prompt_tags(self) -> list[str]:
        for variant in self.prompt_variants:
            if variant.variant_id == "000_base":
                return list(dict.fromkeys(tag for tag in variant.danbooru_tags if tag))
        return []

    def variant_danbooru_tags(self, variant_id: str | None = None) -> list[str]:
        if self.schema_version == "1.1":
            from manga_prompt_ir.character_visual_resolver import resolve_character_visual

            return resolve_character_visual(self, variant_id).danbooru_tags
        from manga_prompt_ir.character_fixed_tags import resolve_variant_danbooru_tags

        return resolve_variant_danbooru_tags(self.model_dump(), variant_id)

    @model_validator(mode="after")
    def validate_schema_contract(self) -> CharacterPrompt:
        if self.schema_version == "1.0":
            self._validate_schema_1_0()
            return self
        self._validate_schema_1_1()
        return self

    def _validate_schema_1_0(self) -> None:
        for variant in self.prompt_variants:
            extras = []
            if variant.variant_kind is not None:
                extras.append("variant_kind")
            if variant.visual_spec is not None:
                extras.append("visual_spec")
            if variant.inherits_costume:
                extras.append("inherits_costume")
            if variant.state_tags:
                extras.append("state_tags")
            if extras:
                raise ValueError(
                    f"CharacterPrompt 1.0 では {', '.join(extras)} を使えません: "
                    f"{variant.variant_id}"
                )

    def _validate_schema_1_1(self) -> None:
        costume = self.costume
        leftover = []
        if costume.outfit_tags:
            leftover.append("costume.outfit_tags")
        if costume.main_outfit:
            leftover.append("costume.main_outfit")
        if costume.accessories:
            leftover.append("costume.accessories")
        if costume.color_palette:
            leftover.append("costume.color_palette")
        if leftover:
            raise ValueError(
                "CharacterPrompt 1.1 では旧 costume.* に衣装情報を置けません: "
                + ", ".join(leftover)
            )

        seen: dict[str, int] = {}
        for variant in self.prompt_variants:
            vid = variant.variant_id.strip()
            seen[vid] = seen.get(vid, 0) + 1
        dupes = [vid for vid, count in seen.items() if count > 1]
        if dupes:
            raise ValueError(f"variant_id が重複しています: {', '.join(dupes)}")

        by_id = {variant.variant_id: variant for variant in self.prompt_variants}
        for variant in self.prompt_variants:
            _validate_variant_kind_rules(variant, by_id)

        for field_name, tags in (
            ("000_base", self.fixed_prompt_tags()),
            ("manga_rules.consistency_tags", list(self.manga_rules.consistency_tags)),
        ):
            hits = find_forbidden_costume_tags([str(tag) for tag in tags])
            if hits:
                raise ValueError(f"{field_name} に衣装語があります: {', '.join(hits)}")

        from manga_prompt_ir.character_visual_resolver import (
            VisualResolverError,
            resolve_character_visual,
        )

        for variant in self.prompt_variants:
            if variant.variant_kind == "base":
                continue
            try:
                resolved = resolve_character_visual(self.model_dump(mode="json"), variant.variant_id)
            except VisualResolverError as exc:
                raise ValueError(str(exc)) from exc
            cached = [str(tag) for tag in variant.danbooru_tags if tag]
            if cached and cached != resolved.danbooru_tags:
                raise ValueError(
                    f"{variant.variant_id} の danbooru_tags が visual resolver 出力と不一致です"
                )


def _validate_variant_kind_rules(
    variant: CharacterPromptVariant,
    by_id: dict[str, CharacterPromptVariant],
) -> None:
    vid = variant.variant_id
    kind = variant.variant_kind
    if kind is None:
        raise ValueError(f"CharacterPrompt 1.1 では variant_kind が必須です: {vid}")
    if vid == "000_base" and kind != "base":
        raise ValueError("000_base の variant_kind は base でなければなりません")
    if kind == "base" and vid != "000_base":
        raise ValueError(f"variant_kind=base は 000_base 専用です: {vid}")
    if kind == "base":
        if variant.visual_spec is not None:
            raise ValueError("base variant に visual_spec を置けません")
        if variant.inherits_costume:
            raise ValueError("base variant に inherits_costume を置けません")
        if variant.state_tags:
            raise ValueError("base variant に state_tags を置けません")
        if (variant.combines_with or "").strip():
            raise ValueError("base variant に combines_with を置けません")
        return
    if kind == "costume":
        if variant.visual_spec is None:
            raise ValueError(f"costume variant に visual_spec が必要です: {vid}")
        if variant.inherits_costume:
            raise ValueError(f"costume variant に inherits_costume を置けません: {vid}")
        if (variant.combines_with or "").strip():
            raise ValueError("costume variant に combines_with を置けません")
        return
    if kind in {"state", "derived"}:
        if variant.visual_spec is not None:
            raise ValueError(f"{kind} variant に visual_spec を置けません: {vid}")
        inherits = (variant.inherits_costume or "").strip()
        if not inherits:
            raise ValueError(f"{kind} variant に inherits_costume が必要です: {vid}")
        if inherits == vid:
            raise ValueError(f"inherits_costume が自己参照です: {vid}")
        target = by_id.get(inherits)
        if target is None:
            raise ValueError(f"inherits_costume の参照先がありません: {inherits}")
        if target.variant_kind != "costume":
            raise ValueError(f"inherits_costume の参照先が costume ではありません: {inherits}")
        combines = (variant.combines_with or "").strip()
        if combines:
            if combines == inherits:
                raise ValueError("inherits_costume と combines_with が同じ id です")
            _assert_combines_acyclic(by_id, combines, {vid})
        return
    raise ValueError(f"未知の variant_kind です: {kind}")


def _assert_combines_acyclic(
    by_id: dict[str, CharacterPromptVariant],
    variant_id: str,
    visited: set[str],
) -> None:
    vid = variant_id.strip()
    if vid in visited:
        raise ValueError(f"combines_with が循環しています: {vid}")
    target = by_id.get(vid)
    if target is None:
        raise ValueError(f"combines_with の参照先がありません: {vid}")
    if target.variant_kind == "costume":
        raise ValueError(f"combines_with が costume variant を指しています: {vid}")
    nxt = (target.combines_with or "").strip()
    if nxt:
        _assert_combines_acyclic(by_id, nxt, {*visited, vid})
