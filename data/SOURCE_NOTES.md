# Listing source — source notes (rewritten 2026-09-05)

**The source is `data/Bangalore_Properties_List.xlsx`, a spreadsheet supplied by the project owner.**
No site is scraped. bengaluru.rent is **out of scope** for this project; the
reconnaissance verdict that put it out of scope is kept at the bottom of this
file as the historical record.

**What changed on 2026-09-05.** The project owner added four columns to the
sheet: `Name`, `Phone Number`, `Voter ID` and `availability_status`. The first
three are **PII and are never imported**; the fourth is the availability marker
this dataset previously lacked, and it changes the Gate D finding. This file
supersedes the 2026-09-02 inventory.

## What the supplied dataset is

| | |
|---|---|
| File | `data/Bangalore_Properties_List.xlsx` (single sheet, `Bangalore_Properties_List`) |
| Columns | 21 (17 before 2026-09-05) |
| Rows | 9,180 |
| Localities | 566 |
| Rows with coordinates | 9,180 (all) |
| Listings per locality | min 1, median 5, max 411 |
| Localities holding **more than** 10 rows (i.e. that curation will cap) | 203 of 566 |
| Rent range | ₹10,000 – ₹1,50,000 |
| Deposit range | ₹50,000 – ₹5,00,000 |
| Availability marker | `availability_status` — `Yes` on 4,532 rows, `No` on 4,648, never blank |
| PII columns | 3 (`Name`, `Phone Number`, `Voter ID`) — present, discarded on import |

## Provenance of each column — read this before quoting any number

The sheet is **not a market observation**. It was assembled in four different
ways, and the difference matters for every claim the system makes:

| Column group | How it was produced | Safe to quote as fact? |
|---|---|---|
| `Latitude`, `Longitude` | Real coordinates drawn from sale listings in `data/raw/Buy-sell list.csv` (Makaan.com data via Hugging Face; the CSV's own `source` column reads `huggingface:InsiyaMaryam/Makaan-data`). **Verified 2026-09-05:** 9,157 of the 9,180 rows' pairs appear in that CSV, and **every one of them sits on a CSV row marked `is_synthetic=False`** — none was taken from the CSV's 4,058 synthetic rows. The remaining **23 rows (8 distinct pairs) appear nowhere in the CSV**; their origin is unrecorded. The copy is *not* row-for-row positional — only 28.1% of rows line up by position, so the sheet's row order carries no meaning | Yes as a map position for the 9,157; the 23 are unverified |
| `locality` | Derived from those coordinates by OpenStreetMap reverse geocoding (Nominatim), taking the `suburb`, else the block or village name. **Corroborated 2026-09-05:** the sheet's names are not the CSV's own `locality` values — they differ on 7,645 rows and are consistently coarser (`JP Nagar` where the CSV says `1st Phase JP Nagar`), which is what a reverse-geocoded suburb name looks like | Yes |
| `Rent`, `Deposit`, `parking_available`, `Society Type`, and the other descriptive columns | **Randomly generated** at the project owner's instruction, within stated bands, with 1BHK < 2BHK < 3BHK < 3BHK+ enforced for rent and deposit | **No.** These are plausible placeholders, not observed prices |
| `availability_status`, `Name`, `Phone Number`, `Voter ID` | **Randomly generated on 2026-09-05** at the project owner's instruction. `availability_status` is an independent coin flip per row; the three PII columns are invented identities, unique per row, matching no real person | **No.** `availability_status` is a marker whose *mechanism* is real and whose *values* are synthetic; the PII columns never reach the bundle at all |

**Consequence for the sign-off record (spec §7.3).** Any evaluation that treats
a rent or deposit in this dataset as a real market figure is measuring the
random generator, not Bengaluru. The same now applies to availability: a
listing shown as available is available because a coin came up heads, not
because anyone checked. The system's grounding discipline is unchanged and
still testable — a fact must still come from the dataset and carry its
provenance — but the *demo* must not be presented as real pricing or as real
availability.

## Field map (schema field → sheet column → published?)

**16 of the 24 schema fields are present** (14 before 2026-09-05;
`availability_status` and `society_type` are the additions — `society_type` was
added to the schema on 2026-09-05 because the sheet carries the column). The sheet states only that parking
exists, so it fills `parking_available` and leaves `parking` null; the
two-/four-wheeler kind is never guessed.

| schema field | sheet column | published |
|---|---|---|
| locality | `locality` | yes |
| bhk_type | `bhk_type` (`1BHK` 2,282 / `2BHK` 2,217 / `3BHK` 2,332 / `3BHK+` 2,349); `bedrooms` agrees with it — `3BHK+` is 4 bedrooms on 1,164 rows and 5 on 1,185 | yes |
| bedrooms | `bedrooms` | yes |
| bathrooms | `bathrooms` | yes |
| balconies | `balconies` | yes |
| rent | `Rent` (rupees per month) | yes |
| deposit | `Deposit` (rupees) | yes |
| maintenance_charges | (none) | no |
| maintenance_included | (none) | no |
| property_type | `property_type` — observed values only: `independent_house` (4,504), `villa` (2,386), `apartment` (2,290); `builder_floor` never occurs | yes |
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
| availability_status | `availability_status` (`Yes` / `No`) | **yes — new on 2026-09-05** |
| society_name | `society_name` (builder name) | yes |
| society_type | `Society Type` (`Gated Society` / `Non-gated Society`) | **yes — new on 2026-09-05** |
| coordinates | `Latitude`, `Longitude` | yes |

Three sheet columns have no schema home and are **not imported** — the PII
columns below. `Society Type` was one of them until 2026-09-05, when
`society_type` was added to the schema (spec §3.1) and the importer began
mapping its prose onto the enum.

## Shape facts the importer must handle

Measured on the 2026-09-05 sheet, not assumed:

| Fact | Figure | Why it matters |
|---|---|---|
| No blank cells anywhere | 0 blanks in all 21 columns × 9,180 rows | Nothing in this sheet is null because it was left empty; a null in the output is a field the sheet does not carry |
| `total_floors` holds two cell types | `int` on 2,290 rows, the string `Not Applicable` on 6,890 | An `int()` on the column raises; the string maps to null. It aligns exactly with `property_type`: every `apartment` row is numeric, every `villa` (2,386) and `independent_house` (4,504) row is `Not Applicable` |
| `Sl.` is unique but not contiguous | 9,180 values, min 1, max 9,185 — 5 numbers missing | Safe as the id and row reference; a row-count check against `max(Sl.)` would be wrong |
| `Phone Number` is stored as **text**, not a number | 9,180 strings of exactly 9 digits | A text-column guard can see it; a numeric guard would not |
| Coordinates repeat across rows | 2,750 distinct pairs for 9,180 rows; 992 pairs are shared by more than one row, covering 7,422 rows | A naive "within 50 m ⇒ same listing" dedupe would collapse most of the sheet. The tower guard is load-bearing: of those rows, only 762 (342 groups) also share a rent, and only 26 rows (13 groups) share coordinates, rent, society and BHK |
| No two rows are identical | 0 rows duplicate on all columns except `Sl.` and the three PII columns | There are no exact-duplicate listings to remove |
| `locality` needs no cleaning | 0 values with leading or trailing whitespace; 566 distinct | — |
| `society_name` is a builder name, reused widely | 44 distinct values over 9,180 rows; 5,467 society+locality groups, the largest holding 20 rows | Society name alone never identifies a building, so it cannot be a dedupe key on its own |

## Availability marker

**`availability_status`, values `Yes` / `No`, never blank.** 4,532 rows say
`Yes` and 4,648 say `No`. The importer reads `Yes` as `True` and `No` as
`False`; a blank would become `None` ("not stated"), but no blank occurs in the
present sheet.

Two consequences:

1. **Curation now drops rows, and drops whole localities.** Spec §3.1
   requires records marked unavailable to be dropped. That leaves **4,532
   rows across 464 localities**: **102 of the 566 localities have no
   available row at all** and disappear from the bundle, and only 119
   localities still hold more than 10 — the same "more than 10" measure as the
   203 above, so the two are comparable (on the "ten or more" measure the pair
   is 218 and 130). Task 0.6 owns the final counts; this is the figure Gate D
   has to weigh.
2. **The values are synthetic.** The marker's mechanism is exactly what the
   spec wants; the values behind it are a coin flip made on 2026-09-05. The
   stale-listing design (spec §3.14) is unchanged: availability remains an
   in-memory overlay an operator can flip, re-checked before the calendar
   writes. It now starts from a published value instead of "not stated".

## Square footage basis

Not stated. `area_basis` is `UNKNOWN` for every record.

## PII observed (to strip)

**Three columns, all discarded before anything is written to disk (spec §3.2).**

| sheet column | shape | disposal |
|---|---|---|
| `Name` | full name, e.g. `Zoya Narang`; 9,180 distinct values | never read into `ListingRecord`; no schema field exists for it |
| `Phone Number` | **exactly 9 digits**, e.g. `395862397`; 9,180 distinct values | never imported; the PII guard must also catch a bare 9-digit run, which the 2026-09-02 guard did not |
| `Voter ID` | 10 letters, mixed case, e.g. `MPSAnXINZQ`; 9,180 distinct values | never imported; treated as a government identifier |

**The 2026-09-02 PII guard would not have caught these numbers.** `strip_pii`
matched Indian mobiles — ten digits beginning 6–9, optionally prefixed
`+91`/`0`. All 9,180 phone numbers in this sheet are nine digits and **zero**
of them match that pattern. Task 0.5 extends the guard to a bare run of nine or
ten digits, and the importer's column allow-list is what actually keeps these
three columns out: the guard is the second line of defence, not the first.

The allow-list is safe for the numeric columns that remain: the widest of them
is `Deposit` at six digits, and the coordinate fractions run to eight, so no
legitimate value in this sheet is a nine-digit run.

`society_name` holds builder names, not people, and is imported; so is
`Society Type`, which is a property of the address, not of a person.

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
