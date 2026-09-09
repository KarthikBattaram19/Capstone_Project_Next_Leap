# Guide sources — how `sources.json` was chosen (Task 1.1, 2026-09-06)

`sources.json` maps every one of the manifest's 464 localities to 0–3 guide URLs. It is
the input to `python -m scout.pipeline.collect_guides`, which writes `data/bundle/chunks.json`.

## What was allowed

Plan §5 (Task 1.1): Wikipedia plus up to two open city guides per locality; no listing
portals, no advertising copy. **Only Wikipedia was used.** Wikivoyage was checked and
rejected: its Bengaluru coverage is one city article split by compass district, not one
page per locality, so any locality's chunks would carry text about its neighbours — the
cross-locality contamination Suite C exists to catch. No other open city guide with a
page per locality was found.

## How the list was built

1. For each locality name the Wikipedia API was asked for the exact title (redirects
   followed) and then for a search on `"<name>" Bengaluru`. A page was a candidate only
   if its title matched the name (after normalising punctuation and a
   `, Bengaluru` / `, Bangalore` suffix), it was not a disambiguation page, and its intro
   mentioned Bengaluru or Bangalore.
2. Every candidate was reviewed by hand against its intro sentence. Dropped: metro and
   railway station pages (Doddajala, HBR Layout, Heelalige, Hongasandra, Kudlu,
   Lakkasandra, Nagasandra), assembly-constituency pages (C V Raman Nagar, Jayamahal,
   Shanti Nagar), a cemetery (Agaram), an inscription (Byadarahalli), a same-name town
   elsewhere (Ullal, in Dakshina Kannada), a Mayasandra 50 km out whose identity with
   the sheet's is unknown, and Andapura, whose article body describes the adjacent
   village Chandapura.
3. A second hand-chosen pass added spelling variants and sub-areas that point at the
   same article (Bagaluru → Bagalur, Byappanahalli → Baiyyappanahalli, Frazer Town →
   Fraser Town, J.P Nagar / JP Nagar → Jayaprakash Nagar, HSR → HSR Layout, Koramangala
   5th Block / Kormangala East / Kormangala West → Koramangala, the three Electronics
   City phases → Electronic City, and so on) and titles the strict filter had missed
   (Chikkapete → Chickpet, Arakere → Arekere, KR Puram → Krishnarajapuram,
   Chamarajapete → Chamarajpet, Beguru → Begur). Rejected in that pass: Gunjur (a town in
   Gambia), Panathur (Kerala), Kudlu (Kasaragod), Kodati (a film), Bannerughatta
   (disambiguation), and every same-name village in another district.
4. **A third pass on 2026-09-09 went looking for more and found none.** It is written up
   under "Third pass" below so that nobody spends the session again.

## Result

| | Count |
|---|---|
| Localities with a Wikipedia article | 127 |
| Localities with no usable source (`[]`) | 337 |
| Distinct articles fetched | 107 |

The 337 empty entries are mostly apartment complexes (Prestige Finsbury Park, Sobha
Lifestyle Legacy, …), BBMP ward names, and small villages with no article. For them the
assistant must say it has no neighbourhood data; Suite C cases c-006 to c-010 cover that.
Several localities share one article (four spellings of Koramangala, two of Bagalur);
each still gets its own partition in Task 1.2, so nothing is answered from a neighbour's text.

## Things to know about the text

- Wikipedia's locality articles are short in prose. Koramangala's is under 250 words;
  the median article yields about three chunks. Lists (bus routes, landmarks) are not
  taken, only paragraphs of eight words or more.
- The collector sends a User-Agent with the repository URL. Wikimedia's robot policy
  answers HTTP 403 to a User-Agent without contact information.
- Raw HTML is kept under `data/raw/guides/<locality-slug>/<n>.html`, which is ignored by git.

## Third pass — 2026-09-09: the list could not be widened

Guide coverage reaches 127 of 464 localities, which is 741 of 2,370 listings (31%). A session
was spent trying to raise that. **It did not add a single source, and the reason is worth
recording: English Wikipedia is exhausted for this locality list.**

### What was tried

1. Every one of the 337 empty localities was expanded into name variants the earlier passes
   had not tried systematically — `, Bengaluru` / `, Bangalore` suffixes, the Nagar/Nagara and
   ur/uru transliteration drift that runs through this sheet, and `Layout` / `Ward` dropped.
   That gave 1,349 titles, asked in 27 batched API requests with redirects resolved.
2. The 289 localities still unresolved were each put through Wikipedia full-text search as
   `"<name>" Bengaluru`, and the intro of all 1,279 resulting hits was fetched.
3. Every candidate was then put through the same criteria as the earlier passes: title must
   match the locality after normalising punctuation and a `, Bengaluru` suffix; not a
   disambiguation page; intro must name Bengaluru or Bangalore; no station, constituency,
   cemetery, inscription or film pages.

### What came back

214 localities had *some* candidate page and 190 had one that was not obviously wrong. The
criteria cut those to six, and **all six were then rejected by hand**:

| Locality | Candidate | Why rejected |
|---|---|---|
| Andapura | Andapura | The article body describes the adjacent village Chandapura — the same rejection the 2026-09-06 pass made |
| Chikkanayakanahalli | Chikkanayakana Halli | A taluk headquarters in Tumakuru district, not the Bengaluru locality |
| Ullal | Ullal | The city in Dakshina Kannada — rejected in the earlier pass too |
| Avalahalli | Aavalahalli | Plausible spelling variant, but the article carries no coordinates and Bengaluru has more than one Avalahalli, so it cannot be verified |
| Jeevanahalli | Devara Jeevanahalli | Article sits 3.0 km from the median coordinate of this locality's listings — a different neighbourhood |
| Mulluru | Mullur | No coordinates on the article; unverifiable |

The last three were checked by comparing the article's own coordinates against the median
coordinate of that locality's listings in the bundle, with 3 km as the limit. A spelling
variant is only the same place if it is in the same place.

### The shape of what is left

The overwhelming majority of search hits for an empty locality are its **neighbours**, not
itself: AECS Layout → Brookefield, Devarabeesanahalli → Bellandur, Hosapalya → HSR Layout,
Doresanipalya → J P Nagar. Accepting any of them is precisely the cross-locality
contamination Suite C exists to catch, so the filter rejecting them is the filter working.

### The one lever that is left, and why it was not pulled

Most of the 337 are apartment complexes and BBMP ward names that sit *inside* a locality that
does have an article. Attributing the parent's article to the child would lift coverage a
long way. It is not a `sources.json` edit, though — it changes what a citation means. The
assistant would have to say "Prestige Finsbury Park is in Bagalur, and about **Bagalur**
Wikipedia says…", with the parent named in the citation and the distinction spoken. Nothing
in the retrieval or explanation layer can express that yet, so it belongs to Tasks 2.11–2.12
as a design decision, not to this file. Until then the honest answer for those 1,629 listings
is that there is no neighbourhood write-up, which is what Suite C cases c-006 to c-010 assert.

Kannada Wikipedia covers more of these localities but was not used: the chunks would be in a
language the assistant does not speak, and the pinned embedding model is English-only.
