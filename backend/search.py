"""Web search. Uses Tavily when TAVILY_API_KEY is set, otherwise DuckDuckGo (free, no key)."""
import asyncio
from urllib.parse import urlparse, urlunparse

import config

# Sites that rarely have readable article text
SKIP_DOMAINS = ("youtube.com", "facebook.com", "instagram.com", "tiktok.com",
                "twitter.com", "x.com", "pinterest.com", "linkedin.com")
MAX_PER_DOMAIN = 2                 # keep the mix of sources diverse
_ddg_slots = asyncio.Semaphore(2)  # DuckDuckGo blocks bursts of requests


async def search(query: str, max_results: int) -> list[dict]:
    if config.TAVILY_API_KEY:
        return await _tavily(query, max_results)
    return await _duckduckgo(query, max_results)


async def _tavily(query: str, max_results: int) -> list[dict]:
    from tavily import AsyncTavilyClient
    client = AsyncTavilyClient(api_key=config.TAVILY_API_KEY)
    resp = await client.search(query, max_results=max_results,
                               search_depth="basic", include_raw_content=True)
    return [{
        "url": r["url"],
        "title": r.get("title") or "",
        "snippet": r.get("content") or "",
        "raw_content": r.get("raw_content") or "",  # full page text -> no download needed
        "published_date": r.get("published_date") or "",
    } for r in resp.get("results", [])]


async def _duckduckgo(query: str, max_results: int) -> list[dict]:
    from ddgs import DDGS
    async with _ddg_slots:
        hits = await asyncio.to_thread(lambda: DDGS().text(query, max_results=max_results) or [])
    return [{"url": h["href"], "title": h.get("title") or "", "snippet": h.get("body") or "",
             "raw_content": "", "published_date": ""} for h in hits if h.get("href")]


def _domain(url: str) -> str:
    return urlparse(url).netloc.lower().removeprefix("www.")


def _dedupe_key(url: str) -> str:
    p = urlparse(url)
    return urlunparse(("", _domain(url), p.path.rstrip("/"), "", p.query, ""))


def _skipped(domain: str) -> bool:
    return any(domain == d or domain.endswith("." + d) for d in SKIP_DOMAINS)


async def search_all(queries: list[str], per_query: int) -> tuple[list[dict], list[str]]:
    """Run all queries in parallel, then merge round-robin so every query contributes."""
    results = await asyncio.gather(*(search(q, per_query) for q in queries),
                                   return_exceptions=True)
    errors = [f"'{q}': {r}" for q, r in zip(queries, results) if isinstance(r, Exception)]
    lists = [r for r in results if isinstance(r, list)]

    seen, per_domain, merged = set(), {}, []
    for rank in range(per_query):
        for hits in lists:
            if rank >= len(hits):
                continue
            hit = hits[rank]
            key, dom = _dedupe_key(hit["url"]), _domain(hit["url"])
            if key in seen or _skipped(dom) or per_domain.get(dom, 0) >= MAX_PER_DOMAIN:
                continue
            seen.add(key)
            per_domain[dom] = per_domain.get(dom, 0) + 1
            merged.append(hit)
    return merged, errors
