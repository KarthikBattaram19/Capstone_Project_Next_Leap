"""A guide chunk — one piece of one guide document, with its area, title and link."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel


class GuideChunk(BaseModel):
    id: str  # f"{locality_slug}-{doc_index}-{position}"
    locality: str  # the partition key (AD-9)
    title: str
    url: str
    text: str
    position: int
    fetched_on: date
