# Listing source — source notes (rewritten 2026-09-02)

**The source is `data/Bangalore_Properties_List.xlsx`, a spreadsheet supplied by the project owner.**
No site is scraped. bengaluru.rent is **out of scope** for this project; the
reconnaissance verdict that put it out of scope is kept at the bottom of this
file as the historical record.

## What the supplied dataset is

| | |
|---|---|
| File | `data/Bangalore_Properties_List.xlsx` (single sheet, `Bangalore_Properties_List`) |
| Rows | 9,180 |
| Localities | 566 |
| Rows with coordinates | 9,180 (all) |
| Listings per locality | min 1, median 5, max 411 |
| Localities above the 10-per-locality ceiling | 203 of 566 |
| Rent range | ₹10,000 – ₹1,50,000 |
| Deposit range | ₹50,000 – ₹5,00,000 |

There is **no availability marker** and **no PII**. The sheet carries no owner
names, no phone numbers and no email addresses, so the PII-stripping step that
the scrape design required (`scout.pipeline.pii`) has nothing to remove from
this source. The `society_name` column holds builder names, not people.

## Provenance of each column — read this before quoting any number

The sheet is **not a market observation**. It was assembled in three different
ways, and the difference matters for every claim the system makes:

| Column group | How it was produced | Safe to quote as fact? |
|---|---|---|
| `Latitude`, `Longitude` | Real coordinates, copied positionally from sale listings in `data/Buy-sell list.csv` (originally Makaan.com data via Hugging Face) | Yes, as a map position |
| `locality` | Derived from those coordinates by OpenStreetMap reverse geocoding (Nominatim), taking the `suburb`, else the block or village name | Yes |
| `Rent`, `Deposit`, `parking_available`, `Society Type`, and the other descriptive columns | **Randomly generated** at the project owner's instruction, within stated bands, with 1BHK < 2BHK < 3BHK < 3BHK+ enforced for rent and deposit | **No.** These are plausible placeholders, not observed prices |

**Consequence for the sign-off record (spec §7.3).** Any evaluation that treats
a rent or deposit in this dataset as a real market figure is measuring the
random generator, not Bengaluru. The system's grounding discipline is unchanged
and still testable — a fact must still come from the dataset and carry its
provenance — but the *demo* must not be presented as real pricing.

## Field map (schema field → sheet column → published?)

14 of the 23 schema fields are present. The sheet states only that parking
exists, so it fills `parking_available` and leaves `parking` null; the
two-/four-wheeler kind is never guessed.

| schema field | sheet column | published |
|---|---|---|
| locality | `locality` | yes |
| bhk_type | `bhk_type` (`1BHK` / `2BHK` / `3BHK` / `3BHK+`) | yes |
| bedrooms | `bedrooms` | yes |
| bathrooms | `bathrooms` | yes |
| balconies | `balconies` | yes |
| rent | `Rent` (rupees per month) | yes |
| deposit | `Deposit` (rupees) | yes |
| maintenance_charges | (none) | no |
| maintenance_included | (none) | no |
| property_type | `property_type` (`apartment` / `independent_house` / `villa` / `builder_floor`) | yes |
| furnishing | `furnishing` (`unfurnished` / `semi_furnished` / `fully_furnished`) | yes |
| square_footage | `square_feet` | yes |
| area_basis | (none) | no — every record is `AreaBasis.UNKNOWN` |
| floor | (none) | no |
| total_floors | `total_floors` | yes — a number on the 2,290 `apartment` rows; the literal text `Not Applicable` on all 6,890 `independent_house` and `villa` rows, which the importer must read as null |
| lift | (none) | no |
| parking | (none) | no — the kind is not stated, so this stays null |
| parking_available | `parking_available` (`Yes` / `No`) | yes |
| amenities | (none) | no |
| available_from | (none) | no |
| availability_status | (none) | no — see below |
| society_name | `society_name` (builder name) | yes |
| coordinates | `Latitude`, `Longitude` | yes |

One sheet column has no schema home and is **not imported**: `Society Type`
(`Gated Society` / `Non-gated Society`).

## Availability marker

**NONE.** The sheet has no availability column, so `availability_status` is
`null` for every record and the gap report must say so. The stale-listing
design (spec §3.14) is unaffected in mechanism: availability remains an
in-memory overlay flag that an operator can flip and that is re-checked before
the calendar writes. It simply starts from "not stated" rather than from a
value the source published.

## Square footage basis

Not stated. `area_basis` is `UNKNOWN` for every record.

## PII observed (to strip)

None. The sheet contains no owner names, phone numbers or email addresses.
The PII guard is kept in the importer as a defence-in-depth assertion, not
because this source needs it.

---

## Historical record — why bengaluru.rent is out of scope

Superseded on 2026-09-02 by the decision to use the supplied spreadsheet.
Retained because it documents why no scrape exists.

**Verdict: disallowed.** `robots.txt` allowed every crawler, but the site's
Terms of Use (last updated 4 June 2026) forbade scraping, harvesting or bulk
extraction "without written permission" and forbade automated tools (bots,
crawlers) outright. The terms govern; robots.txt is a technical convention, not
a licence. Under the plan's Task 0.4 gate this was a **stop**, and Task 0.4
halted at Step 1: the reconnaissance fetcher was never written and the
four-page fetch was never run. Nothing from the site was saved into this
repository, and no listing data in this project comes from it.

`/terms`, section **Acceptable use**, verbatim:

> You agree NOT to:
> - Scrape, harvest, or bulk-extract data from bengaluru.rent without written permission
> - Resell or commercially repurpose the data without written permission
> - Attempt to bypass rate limits, IP bans, or other technical protections
> - Use automated tools (bots, crawlers) to interact with the site
