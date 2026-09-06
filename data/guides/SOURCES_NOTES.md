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
