"""The one listing fact that can change after the build — an in-memory overlay (AD-11, spec §3.1)."""

from __future__ import annotations


class AvailabilityRegister:
    def __init__(self, store) -> None:
        self._store = store
        self._overlay: dict[str, bool] = {}

    def is_available(self, listing_id: str) -> bool:
        if listing_id in self._overlay:
            return self._overlay[listing_id]
        rec = self._store.listing_records.get(listing_id)
        return bool(rec and rec.availability_status)  # a missing record counts as unavailable

    def set(self, listing_id: str, available: bool) -> None:
        self._overlay[listing_id] = available

    def snapshot(self) -> dict[str, bool]:
        return dict(self._overlay)
