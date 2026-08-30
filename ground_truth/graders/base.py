from __future__ import annotations

import re
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from ground_truth.golden.rubric import RubricRule
from ground_truth.golden.schema import ItemField

_WS = re.compile(r"\s+")


class Verdict(BaseModel):
    model_config = ConfigDict(strict=True, frozen=True)
    correct: bool
    reason: str
    grader_id: str
    grader_version: str


class Grader(Protocol):
    def __call__(self, field: ItemField, observed: str | None, rule: RubricRule) -> Verdict: ...


def collapse_whitespace(value: str) -> str:
    return _WS.sub(" ", value).strip()
