"""Listing: 18 details from spec §3.1, each a wrapped fact, plus id and locality."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from scout.domain.provenance import Provenanced, Source, Timing


class BhkType(str, Enum):
    RK1 = "1RK"
    BHK1 = "1BHK"
    BHK2 = "2BHK"
    BHK3 = "3BHK"
    BHK3_PLUS = "3BHK+"


class PropertyType(str, Enum):
    APARTMENT = "apartment"
    INDEPENDENT_HOUSE = "independent_house"
    VILLA = "villa"
    BUILDER_FLOOR = "builder_floor"


class Furnishing(str, Enum):
    UNFURNISHED = "unfurnished"
    SEMI_FURNISHED = "semi_furnished"
    FULLY_FURNISHED = "fully_furnished"


class Parking(str, Enum):
    TWO_WHEELER = "two_wheeler"
    FOUR_WHEELER = "four_wheeler"
    BOTH = "both"
    NONE = "none"


class SocietyType(str, Enum):
    GATED = "gated"
    NON_GATED = "non_gated"


class AreaBasis(str, Enum):
    CARPET = "carpet"
    BUILT_UP = "built_up"
    UNKNOWN = "unknown"


class Coordinates(BaseModel, frozen=True):
    lat: float
    lng: float


# The searchable schema (spec §3.1). Every one is Optional: null is a real value.
SCHEMA_FIELDS: tuple[str, ...] = (
    "locality",
    "bhk_type",
    "bedrooms",
    "bathrooms",
    "balconies",
    "rent",
    "deposit",
    "maintenance_charges",
    "maintenance_included",
    "property_type",
    "furnishing",
    "square_footage",
    "area_basis",
    "floor",
    "total_floors",
    "lift",
    "parking",
    "parking_available",
    "amenities",
    "available_from",
    "availability_status",
    "society_name",
    "society_type",
    "coordinates",
)


class ListingRecord(BaseModel):
    """On-disk shape. Owner names/phones never enter this model (spec §3.2)."""

    # An unknown key is a mistake, not something to drop quietly: if a future sheet ever
    # feeds a `Name` or `Phone Number` column in here, the build fails instead of ignoring it.
    model_config = ConfigDict(extra="forbid")

    id: str
    source_url: str
    scraped_on: date
    merged_from: list[str] = Field(default_factory=list)
    locality: str
    bhk_type: BhkType | None = None
    bedrooms: int | None = None
    bathrooms: int | None = None
    balconies: int | None = None
    rent: int | None = None
    deposit: int | None = None
    maintenance_charges: int | None = None
    maintenance_included: bool | None = None
    property_type: PropertyType | None = None
    furnishing: Furnishing | None = None
    square_footage: int | None = None
    area_basis: AreaBasis = AreaBasis.UNKNOWN
    floor: int | None = None
    total_floors: int | None = None
    lift: bool | None = None
    parking: Parking | None = None
    # A source may say parking exists without saying which kind. Then `parking`
    # stays None and only this is set — never guess `BOTH` from a bare "yes".
    parking_available: bool | None = None
    amenities: list[str] | None = None
    available_from: date | None = None
    availability_status: bool | None = None
    society_name: str | None = None
    # The sheet's "Society Type" column: gated or non-gated. Its text ("Gated Society",
    # "Non-gated Society") is mapped to these values by the importer, not stored verbatim.
    society_type: SocietyType | None = None
    coordinates: Coordinates | None = None


@dataclass(frozen=True)
class Listing:
    id: str
    locality: str
    facts: dict[str, Provenanced[Any]]
    coordinates: Coordinates | None

    @classmethod
    def from_record(cls, rec: ListingRecord) -> "Listing":  # noqa: UP037 -- quoted in the addendum
        facts = {
            name: Provenanced(
                value=getattr(rec, name),
                source=Source.DATASET,
                timing=Timing.PRECOMPUTED,
                as_of=rec.scraped_on,
                citation_ref=f"dataset:{rec.id}",
            )
            for name in SCHEMA_FIELDS
        }
        return cls(id=rec.id, locality=rec.locality, facts=facts, coordinates=rec.coordinates)

    def field(self, name: str) -> Provenanced[Any]:
        # KeyError for anything outside the schema, on purpose
        return self.facts[name]
