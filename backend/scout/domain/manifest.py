"""The build record — produced by the build, never written by hand (AD-2, spec §7.3)."""

from __future__ import annotations

from datetime import date

from pydantic import BaseModel, Field, model_validator


class GapReport(BaseModel):
    availability_marker: str | None
    fields_published: list[str]
    fields_missing: list[str]
    notes: str = ""


class DatasetManifest(BaseModel):
    bundle_version: str
    contract_version: str
    scraped_on: date
    localities: dict[str, int]
    total_listings: int
    availability_marker: str | None
    curation_rule: str
    fields_published: list[str]
    fields_missing: list[str]
    merged_records: dict[str, list[str]] = Field(default_factory=dict)
    osm_query_set: list[str] = Field(default_factory=list)
    osm_index_date: date | None = None
    embedding_model: str | None = None
    embedding_model_version: str | None = None
    chunk_count_per_locality: dict[str, int] = Field(default_factory=dict)
    guide_sources: dict[str, list[str]] = Field(default_factory=dict)
    chromadb_version: str | None = None
    onnxruntime_version: str | None = None

    @model_validator(mode="after")
    def _total_matches(self) -> "DatasetManifest":  # noqa: UP037 -- quoted in the addendum
        if self.total_listings != sum(self.localities.values()):
            raise ValueError("total_listings must equal the sum of per-locality counts")
        return self
