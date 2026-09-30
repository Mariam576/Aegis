"""The research pipeline:  plan -> search -> read -> extract -> compare -> write -> cite

ResearchAgent.run() is an async generator that yields (event, data) pairs.
main.py streams them to the browser as they happen.
"""
import asyncio
import json
import re
from datetime import date

import config
import llm
import prompts
from citations import references_markdown, resolve
from extract import fetch_all
from search import search_all


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _grounded(quote: str, norm_text: str) -> bool:
    """True if the quote really appears in the source (ignores case/punctuation, allows '...')."""
    parts = [_norm(p) for p in re.split(r"\.\.\.|…", quote or "")]
    parts = [p for p in parts if len(p) >= 8]
    return bool(parts) and all(p in norm_text for p in parts)


class ResearchAgent:
    def __init__(self, topic: str, depth: str = "standard"):
        self.topic = topic.strip()
        self.cfg = config.DEPTHS.get(depth, config.DEPTHS["standard"])
        self.today = date.today()

    # ------------------------------------------------------------------ pipeline
    async def run(self):
        # 1. PLAN
        yield "stage", {"stage": "plan", "status": "active"}
        plan = await self.plan()
        yield "plan", plan
        yield "stage", {"stage": "plan", "status": "done"}

        # 2. SEARCH
        yield "stage", {"stage": "search", "status": "active"}
        hits, errors = await search_all(plan["queries"], self.cfg["per_query"])
        for err in errors:
            yield "log", {"message": f"Search failed for {err}"}
        if not hits:
            raise RuntimeError("Search returned no results. Check TAVILY_API_KEY or try another topic.")
        yield "log", {"message": f"Found {len(hits)} candidate pages"}
        yield "stage", {"stage": "search", "status": "done"}

        # 3. READ pages
        yield "stage", {"stage": "read", "status": "active"}
        docs = await fetch_all(hits[: self.cfg["max_sources"] * 2], self.cfg["max_sources"])
        if not docs:
            raise RuntimeError("None of the pages could be read (paywalls or blocked sites).")
        sources = {}
        for i, doc in enumerate(docs, 1):
            doc["id"] = f"S{i}"
            sources[doc["id"]] = doc
        yield "sources", {"sources": [self.public(s) for s in sources.values()]}
        yield "log", {"message": f"Read {len(sources)} sources"}
        yield "stage", {"stage": "read", "status": "done"}

        # 4. EXTRACT claims from every source (llm.py paces the requests)
        yield "stage", {"stage": "extract", "status": "active"}
        tasks = [asyncio.create_task(self.extract(s, plan)) for s in sources.values()]
        try:
            for next_done in asyncio.as_completed(tasks):
                yield "source_analyzed", self.public(await next_done)
        finally:
            for t in tasks:
                t.cancel()  # no-op if finished; stops work if the user disconnects
        useful = {sid: s for sid, s in sources.items() if s["relevant"] and s["claims"]}
        if not useful:
            raise RuntimeError("The sources found had no relevant, verifiable information.")
        n_claims = sum(len(s["claims"]) for s in useful.values())
        yield "log", {"message": f"{n_claims} verified claims from {len(useful)} relevant sources"}
        yield "stage", {"stage": "extract", "status": "done"}

        # 5. COMPARE sources
        yield "stage", {"stage": "compare", "status": "active"}
        comparison = await self.compare(useful, plan)
        yield "comparison", comparison
        yield "stage", {"stage": "compare", "status": "done"}

        # 6. WRITE the report (cites sources as [S1], [S2] ...)
        yield "stage", {"stage": "write", "status": "active"}
        draft = await self.write(useful, plan, comparison)
        yield "stage", {"stage": "write", "status": "done"}

        # 7. CITE: turn [S#] markers into numbered citations + a reference list
        yield "stage", {"stage": "cite", "status": "active"}
        body, refs, stats = resolve(draft, useful)
        if stats["invalid"]:
            yield "log", {"message": f"Removed {stats['invalid']} citation(s) to unknown sources"}
        yield "log", {"message": f"{stats['citations']} citations to {stats['sources_cited']} sources"}
        full = f"{body.rstrip()}\n\n## References\n\n{references_markdown(refs)}\n"
        yield "report", {"markdown": body, "references": refs, "full_markdown": full}
        yield "stage", {"stage": "cite", "status": "done"}

    # ------------------------------------------------------------------ stages
    async def plan(self) -> dict:
        data = await llm.ask_json(
            prompts.PLAN.substitute(topic=self.topic, n=self.cfg["queries"],
                                    today=self.today.isoformat(), year=self.today.year),
            system=prompts.PLANNER_SYSTEM, max_tokens=4000)
        subs = [q.strip() for q in data.get("sub_questions") or [] if isinstance(q, str) and q.strip()]
        queries = [q.strip() for q in data.get("queries") or [] if isinstance(q, str) and q.strip()]
        return {"sub_questions": subs[:5] or [self.topic],
                "queries": queries[: self.cfg["queries"]] or [self.topic]}

    async def extract(self, src: dict, plan: dict) -> dict:
        prompt = prompts.EXTRACT.substitute(
            topic=self.topic, sub_questions=self._numbered(plan["sub_questions"]),
            sid=src["id"], title=src["title"], site=src["site"], url=src["url"], text=src["text"])
        try:
            data = await llm.ask_json(prompt, system=prompts.EXTRACT_SYSTEM,
                                      model=config.MODEL_FAST, max_tokens=6000)
        except Exception as e:  # one bad source shouldn't stop the whole run
            src.update(relevant=False, claims=[], claims_total=0, summary=f"Could not analyse: {e}")
            return src

        norm_text = _norm(src["text"])
        claims = [c for c in data.get("claims") or [] if isinstance(c, dict) and c.get("claim")][:8]
        verified = [c for c in claims if _grounded(c.get("quote", ""), norm_text)]
        try:
            credibility = min(5, max(1, int(data.get("credibility", 3))))
        except (TypeError, ValueError):
            credibility = 3

        src.update(
            relevant=bool(data.get("relevant", True)),
            summary=data.get("summary", ""),
            source_type=data.get("source_type", "other"),
            credibility=credibility,
            credibility_reason=data.get("credibility_reason", ""),
            author=src["author"] or data.get("author", ""),
            date=src["date"] or data.get("published", ""),
            claims=verified,
            claims_total=len(claims),
        )
        return src

    async def compare(self, sources: dict, plan: dict) -> dict:
        data = await llm.ask_json(
            prompts.COMPARE.substitute(topic=self.topic, count=len(sources),
                                       sub_questions=self._numbered(plan["sub_questions"]),
                                       claims=self._claim_lines(sources)),
            system=prompts.COMPARE_SYSTEM, max_tokens=8000)

        known = set(sources)

        def ids(xs):  # drop source ids the model made up
            return [i for i in (xs or []) if i in known]

        def items(key):
            return [x for x in data.get(key) or [] if isinstance(x, dict)]

        return {
            "consensus": [{**x, "sources": ids(x.get("sources"))} for x in items("consensus")],
            "disagreements": [
                {**d, "positions": [{**p, "sources": ids(p.get("sources"))}
                                    for p in d.get("positions") or [] if isinstance(p, dict)]}
                for d in items("disagreements")],
            "single_source": [{**x, "sources": ids(x.get("sources"))} for x in items("single_source")],
            "gaps": [g for g in data.get("gaps") or [] if isinstance(g, str)],
        }

    async def write(self, sources: dict, plan: dict, comparison: dict) -> str:
        source_lines = "\n".join(
            f"{s['id']} - {s['title']} ({s['site']}, {s['date'] or 'n.d.'}, "
            f"{s['source_type']}, {s['credibility']}/5)" for s in sources.values())
        prompt = prompts.REPORT.substitute(
            today=self.today.isoformat(), topic=self.topic,
            sub_questions=self._numbered(plan["sub_questions"]), sources=source_lines,
            claims=self._claim_lines(sources), comparison=json.dumps(comparison, indent=1))
        return await llm.ask(prompt, system=prompts.REPORT_SYSTEM, max_tokens=16000)

    # ------------------------------------------------------------------ helpers
    @staticmethod
    def _numbered(items: list[str]) -> str:
        return "\n".join(f"{i}. {q}" for i, q in enumerate(items))

    @staticmethod
    def _claim_lines(sources: dict) -> str:
        return "\n".join(f"- ({s['id']}, {s['credibility']}/5) {c['claim']}"
                         for s in sources.values() for c in s["claims"])

    @staticmethod
    def public(src: dict) -> dict:
        """What the browser gets to see (never the full page text)."""
        keys = ("id", "title", "url", "site", "author", "date", "summary", "source_type",
                "credibility", "credibility_reason", "relevant", "claims_total")
        out = {k: src.get(k) for k in keys}
        out["analyzed"] = "claims" in src
        out["claims"] = [{"claim": c["claim"], "quote": c.get("quote", "")}
                         for c in src.get("claims", [])]
        return out
