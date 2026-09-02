# bengaluru.rent — source notes (recon on 2026-09-02)

**Verdict: disallowed.** `robots.txt` allows every crawler, but the site's Terms of Use (last updated 4 June 2026) forbid scraping, harvesting or bulk extraction "without written permission" and forbid automated tools (bots, crawlers) outright. The terms govern; robots.txt is a technical convention, not a licence. Per the plan (§5, Task 0.4) this is a **stop**: no scrape (Task 0.5) may run until either written permission from the operator (hi@bengaluru.rent) is in hand or the spec names a different source. Task 0.4 halted at Step 1; the reconnaissance fetcher (`recon.py`) was not written and the four-page fetch was not run.

What *was* fetched, once each, with a self-identifying User-Agent, in the course of reading the terms: `/robots.txt`, `/sitemap.xml`, `/terms`, `/koramangala`, `/`, and `/?pin=<uuid>`. Nothing was saved into the repository. The field observations below come from reading the landing page's own client-side code, not from extracting data.

## robots.txt / terms

`robots.txt` (HTTP 200), verbatim relevant lines:

```
# bengaluru.rent — explicitly allow AI crawlers + standard search engines
User-agent: *
Allow: /
User-agent: ClaudeBot
Allow: /
Sitemap: https://bengaluru.rent/sitemap.xml
```

`/terms` ("Terms of Use", last updated 4 June 2026), section **Acceptable use**, verbatim:

> You agree NOT to:
> - Scrape, harvest, or bulk-extract data from bengaluru.rent without written permission
> - Resell or commercially repurpose the data without written permission
> - Attempt to bypass rate limits, IP bans, or other technical protections
> - Use automated tools (bots, crawlers) to interact with the site

Section **Moderation**, verbatim: "We reserve the right to remove pins, listings, comments, or accounts that: … Appear to be spam, fraud, or scraping attempts". Section **Intellectual property**, verbatim: "The aggregated rent data, statistical aggregates, and area medians are derived from user contributions; you may not redistribute these in bulk without permission."

Section **No warranty**, verbatim (bears on the availability marker): "We do not guarantee: … That listed flats are actually available for rent".

Verdict: **disallowed** (robots.txt: allowed; terms: disallowed without written permission).

## Locality discovery

- Locality list URL: `https://bengaluru.rent/sitemap.xml` — 21 locality pages: indiranagar, koramangala, hsr-layout, domlur, frazer-town, cv-raman-nagar, whitefield, marathahalli, bellandur, btm-layout, jayanagar, jp-nagar, hebbal, electronic-city, sarjapur-road, banashankari, malleshwaram, kr-puram, kammanahalli, basavanagudi, vijayanagar.
- Locality index URL pattern: `https://bengaluru.rent/<locality-slug>` — a static SEO summary page (about 11 KB) carrying only median-rent statistics per BHK and FAQ JSON-LD. It contains **no listing HTML** and links to at most one pin (`/?pin=<uuid>`).
- Listing URL pattern: `https://bengaluru.rent/?pin=<uuid>` — the same 650 KB single-page map application as `/`; the pin is looked up client-side from a Supabase table (`pins_public`, selected by `id`). There is no server-rendered listing page.
- Pagination: none. The map application loads all pins client-side from Supabase REST (`pins_public`, ordered by `created_at` descending).

## Availability marker

- Marker: NONE FOUND in HTML. In the application's data model each pin has `pin_kind` (`'tolet_spot'` = a flat offered to let; anything else = a rent-transparency pin) and `listing_type` (`'whole_flat'` | `'room'`). Whether a to-let pin is still available is not published; the terms explicitly disclaim it ("We do not guarantee … That listed flats are actually available for rent").
- "Not for rent" / transparency-only pins look like: the map popup text "Not for rent" (six occurrences in the client code) on pins whose `pin_kind` is not `'tolet_spot'` — these are renters reporting what they pay, not flats on offer. The Koramangala page's own FAQ states the scale: 311 rent pins across 1/2/3 BHK versus "1 flats in Koramangala are listed directly by owners".

## Field map (schema field → selector → example value → published?)

Not examined against listing pages — the fetch was stopped at Step 1 by the terms verdict. The `selector` column therefore records the client-side data field the map application renders, read from the landing page's JavaScript, not a CSS selector on a listing page. "published?" is provisional.

| field | selector | example | published |
|---|---|---|---|
| locality | (none — pins carry `lat`/`lng` only; locality is implied by map position) | — | no |
| bhk_type | `bhk` | — | yes |
| bedrooms | (none) | — | no |
| bathrooms | (none) | — | no |
| rent | `rent_amount` (also `rent_per_room` for rooms) | — | yes |
| deposit | `deposit_months` (months of rent, not rupees) | — | partial |
| maintenance_charges | (none) | — | no |
| maintenance_included | `maintenance_included` | — | yes |
| property_type | (none; `listing_type` is whole_flat / room, not apartment / house) | — | no |
| furnishing | `furnished` | — | yes |
| square_footage | `sqft` | — | yes |
| area_basis | (none) | — | no |
| floor | (none) | — | no |
| total_floors | (none) | — | no |
| lift | (none) | — | no |
| parking | `parking_count` (a count, not two-/four-wheeler) | — | partial |
| amenities | `gated`, `pet_friendly` only | — | partial |
| available_from | (none) | — | no |
| availability_status | (none; see Availability marker) | — | no |
| society_name | `society` | — | yes |
| coordinates | `lat`, `lng` | — | yes |

## Square footage basis

not stated

## PII observed (to strip)

- owner name: selector — not examined (stopped at Step 1). Owner contact is held server-side and released only through match emails (`set_pin_owner_contact`, `set_pin_owner_email`, `contact_creator` RPCs); it does not appear in `pins_public`.
- phone: selector — not examined (stopped at Step 1) (also appears inside description text? unknown — pins have no free-text description field in the client model)
