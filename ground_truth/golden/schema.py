from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, StrictStr


class FieldType(StrEnum):
    MONEY = "money"
    PERCENT = "percent"
    DATE = "date"
    IDENTIFIER = "identifier"
    PARTY_NAME = "party_name"
    ENUM_CATEGORY = "enum_category"
    COUNT = "count"
    LINE_ITEM_DESCRIPTION = "line_item_description"


class Split(StrEnum):
    PUBLIC = "public"
    PRIVATE = "private"


class Source(StrEnum):
    SYNTHETIC = "synthetic"
    PARTNER = "partner"


class ItemField(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    field_name: StrictStr
    field_type: FieldType
    expected_value: StrictStr
    expected_normalised: StrictStr | None = None
    tolerance: Decimal | None = None


class Item(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    item_id: StrictStr
    split: Split
    rubric_version: StrictStr
    source: Source
    content_hash: StrictStr
    fields: list[ItemField]
    # Row descriptions and distractor figures, so render_document can lay out a realistic
    # sheet without re-drawing from the rng (audit M1). Generation metadata, never a label:
    # write_manifest must not emit it, and the Task 9 leak test proves it does not.
    layout: dict[str, object] = Field(default_factory=dict)
    injected_error: StrictStr | None = None
