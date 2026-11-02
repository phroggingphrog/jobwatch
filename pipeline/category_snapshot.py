"""Validated category data for one user's discovery configuration.

Category identifiers are opaque to consumers. An empty snapshot does not assign
categories or reject titles.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class Category(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9][a-zA-Z0-9_-]*$")
    label: str = Field(min_length=1, max_length=160)
    priority: int = Field(ge=0, strict=True)
    phrases: tuple[str, ...]
    action: Literal["admit", "side", "archive"]
    exclusion_confirmed: bool = Field(default=False, strict=True)
    promote: bool = Field(strict=True)
    hours: Literal["standard", "allow_hours_only"]

    @field_validator("id")
    @classmethod
    def not_unsure(cls, value: str) -> str:
        if value.casefold() == "unsure":
            raise ValueError("unsure is reserved for an unassigned model result")
        return value

    @field_validator("label")
    @classmethod
    def nonblank_label(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("label must not be blank")
        return value.strip()

    @field_validator("phrases")
    @classmethod
    def normalize_phrases(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        phrases = tuple(item.casefold().strip() for item in value)
        if any(not phrase for phrase in phrases):
            raise ValueError("phrases must not be blank")
        return tuple(dict.fromkeys(phrases))


class CategorySnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    categories: tuple[Category, ...] = ()

    @model_validator(mode="after")
    def unique_ids_and_priorities(self) -> CategorySnapshot:
        ids = [category.id for category in self.categories]
        priorities = [category.priority for category in self.categories]
        if len(set(ids)) != len(ids):
            raise ValueError("category IDs must be unique")
        if len(set(priorities)) != len(priorities):
            raise ValueError("category priorities must be unique")
        return self

    def ordered(self) -> tuple[Category, ...]:
        return tuple(sorted(self.categories, key=lambda category: category.priority))

    def get(self, category_id: str | None) -> Category | None:
        return next((category for category in self.categories if category.id == category_id), None)
