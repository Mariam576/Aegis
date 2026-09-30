"""Download pages and pull out clean article text and metadata."""
import asyncio
import json
from urllib.parse import urlparse

import httpx
import trafilatura

import config

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/128.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
}
MIN_CHARS = 400  # shorter than this is usually a paywall, cookie wall or error page


async def _download(client: httpx.AsyncClient, url: str) -> str | None:
    try:
        r = await client.get(url)
    except httpx.HTTPError:
        return None
    if r.status_code >= 400 or "html" not in r.headers.get("content-type", ""):
        return None  # skip errors, PDFs, images...
    return r.text


def _parse(html: str, url: str) -> dict:
    out = trafilatura.extract(html, url=url, output_format="json", with_metadata=True,
                              include_comments=False, include_tables=True)
    return json.loads(out) if out else {}


async def load_source(client: httpx.AsyncClient, hit: dict) -> dict | None:
    text, meta = (hit.get("raw_content") or "").strip(), {}
    if len(text) < MIN_CHARS:  # search API gave no full text -> fetch the page ourselves
        html = await _download(client, hit["url"])
        if html:
            meta = await asyncio.to_thread(_parse, html, hit["url"])
            text = (meta.get("text") or "").strip()
    if len(text) < MIN_CHARS:
        return None
    domain = urlparse(hit["url"]).netloc.removeprefix("www.")
    return {
        "url": hit["url"],
        "title": meta.get("title") or hit.get("title") or hit["url"],
        "site": meta.get("sitename") or meta.get("source-hostname") or domain,
        "author": meta.get("author") or "",
        "date": meta.get("date") or hit.get("published_date") or "",
        "text": text[: config.MAX_CHARS_PER_SOURCE],
    }


async def fetch_all(hits: list[dict], max_sources: int) -> list[dict]:
    """Load pages in parallel; keep the first `max_sources` that worked, in rank order."""
    slots = asyncio.Semaphore(6)
    async with httpx.AsyncClient(headers=HEADERS, timeout=15, follow_redirects=True) as client:
        async def one(hit):
            async with slots:
                return await load_source(client, hit)
        loaded = await asyncio.gather(*(one(h) for h in hits))
    return [doc for doc in loaded if doc][:max_sources]
