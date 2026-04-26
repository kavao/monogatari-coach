from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


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


class CharacterPrompt(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"
    character_id: str
    name: str
    name_en: str | None = None
    role: str | None = None
    character_tags: list[str] = Field(default_factory=list)
    appearance: CharacterAppearance = Field(default_factory=CharacterAppearance)
    costume: CharacterCostume = Field(default_factory=CharacterCostume)
    personality: CharacterPersonality = Field(default_factory=CharacterPersonality)
    manga_rules: CharacterMangaRules = Field(default_factory=CharacterMangaRules)
    negative_tags: list[str] = Field(default_factory=list)

    def fixed_prompt_tags(self) -> list[str]:
        tags: list[str] = []
        tags.extend(self.character_tags)
        tags.extend(self.costume.outfit_tags)
        tags.extend(self.manga_rules.consistency_tags)
        tags.extend(self.appearance.species_features)
        tags.extend(self.appearance.distinctive_features)
        return list(dict.fromkeys(tag for tag in tags if tag))
