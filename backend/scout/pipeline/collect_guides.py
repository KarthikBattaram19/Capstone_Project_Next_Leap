"""Fetch each guide once, strip boilerplate, chunk semantically, write data/bundle/chunks.json."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from scout.domain.guides import GuideChunk
from scout.pipeline.chunking import chunk_document
from scout.pipeline.embedding import get_embedding_function
from scout.pipeline.pii import assert_no_pii, strip_pii

SOURCES = Path("data/guides/sources.json")
RAW = Path("data/raw/guides")
OUT = Path("data/bundle/chunks.json")

# Wikimedia's robot policy rejects a User-Agent without a contact URL (HTTP 403,
# "Please respect our robot policy"), so the bare "scout-capstone/0.1" is not enough.
USER_AGENT = (
    "scout-capstone/0.1 (https://github.com/KarthikBattaram19/Capstone_Project_Next_Leap)"
    " python-httpx"
)


# Wikipedia furniture that sits inside the content div but is not prose: inline map
# coordinates, the "Media related to …" side box, hatnotes, navboxes, reference lists.
_FURNITURE = "#coordinates, span[class*='geo'], .side-box, .hatnote, .navbox, .reflist, .noprint"


def _tidy(para: str) -> str:
    """One line, no space before punctuation (link text joins leave 'Bengaluru , India')."""
    para = re.sub(r"\s+", " ", para.replace("\ufeff", ""))
    para = re.sub(r"\s+([,.;:!?)\]])", r"\1", para)
    return re.sub(r"([(\[])\s+", r"\1", para).strip()


def extract_text(html: str) -> tuple[str, str]:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "nav", "footer", "aside", "table", "sup"]):
        tag.decompose()
    for tag in soup.select(_FURNITURE):
        tag.decompose()
    title = soup.title.get_text(strip=True) if soup.title else ""
    title = title.split(" - ")[0]
    body = soup.select_one("#mw-content-text") or soup.select_one("main") or soup.body
    paras = [_tidy(p.get_text(" ", strip=True)) for p in body.find_all("p")] if body else []
    # A paragraph ending in ":" only introduces a list we do not take.
    paras = [p for p in paras if len(p.split()) >= 8 and not p.endswith(":")]
    text = re.sub(r"\[\d+\]", "", "\n\n".join(paras))
    return title, strip_pii(text)


def main() -> None:
    sources: dict[str, list[str]] = json.loads(SOURCES.read_text(encoding="utf-8"))
    ef = get_embedding_function()

    def embed(texts: list[str]) -> list[list[float]]:
        return [[float(x) for x in v] for v in ef(texts)]

    today = datetime.now(ZoneInfo("Asia/Kolkata")).date()
    chunks: list[GuideChunk] = []
    fetched: dict[str, str] = {}  # the same page serves several locality spellings
    with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=30, follow_redirects=True) as c:
        for locality, urls in sources.items():
            slug = re.sub(r"[^a-z0-9]+", "-", locality.lower()).strip("-")
            for d, url in enumerate(urls):
                if url not in fetched:
                    r = c.get(url)
                    r.raise_for_status()
                    fetched[url] = r.text
                    time.sleep(1.0)  # one request a second, never faster
                html = fetched[url]
                raw = RAW / slug / f"{d}.html"
                raw.parent.mkdir(parents=True, exist_ok=True)
                raw.write_text(html, encoding="utf-8")
                title, text = extract_text(html)
                for pos, piece in enumerate(chunk_document(text, embed=embed)):
                    chunks.append(
                        GuideChunk(
                            id=f"{slug}-{d}-{pos}",
                            locality=locality,
                            title=title,
                            url=url,
                            text=piece,
                            position=pos,
                            fetched_on=today,
                        )
                    )
    payload = json.dumps(
        [ch.model_dump(mode="json") for ch in chunks], indent=2, ensure_ascii=False
    )
    # Committed output gets the same last check as listings.json and the manifest.
    assert_no_pii(payload, where=str(OUT))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(payload, encoding="utf-8")
    per_loc: dict[str, int] = {}
    for ch in chunks:
        per_loc[ch.locality] = per_loc.get(ch.locality, 0) + 1
    print(json.dumps(per_loc, indent=2))
    print("total:", len(chunks))


if __name__ == "__main__":
    main()
