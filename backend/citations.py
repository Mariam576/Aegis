"""Citations: resolve [S3]-style markers into numbered [1] citations and format references."""
import re
from datetime import date

MARKER = re.compile(r"\[(S\d+(?:\s*[,;]\s*S\d+)*)\]")
YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def format_reference(src: dict) -> dict:
    """APA-style: Author (Year). Title. Site. URL (accessed YYYY-MM-DD)"""
    m = YEAR.search(src.get("date") or "")
    ref = {
        "id": src["id"],
        "author": src.get("author") or src["site"],
        "year": m.group(0) if m else "n.d.",
        "title": src["title"],
        "site": src["site"],
        "url": src["url"],
        "accessed": date.today().isoformat(),
    }
    ref["text"] = (f"{ref['author']} ({ref['year']}). {ref['title']}. {ref['site']}. "
                   f"{ref['url']} (accessed {ref['accessed']})")
    return ref


def resolve(markdown: str, sources: dict[str, dict]) -> tuple[str, list[dict], dict]:
    """Number sources in order of first citation; drop markers pointing to unknown sources."""
    order: dict[str, int] = {}
    stats = {"citations": 0, "invalid": 0}

    def replace(m: re.Match) -> str:
        nums = []
        for sid in re.split(r"\s*[,;]\s*", m.group(1)):
            if sid not in sources:
                stats["invalid"] += 1
                continue
            order.setdefault(sid, len(order) + 1)
            nums.append(order[sid])
            stats["citations"] += 1
        return "".join(f"[{n}]" for n in sorted(set(nums)))

    body = MARKER.sub(replace, markdown)
    body = re.sub(r"[ \t]+([.,;:])", r"\1", body)  # tidy spaces left by removed markers
    refs = [{"n": n, **format_reference(sources[sid])} for sid, n in order.items()]
    stats["sources_cited"] = len(refs)
    return body, refs, stats


def references_markdown(refs: list[dict]) -> str:
    return "\n\n".join(f"[{r['n']}] {r['text']}" for r in refs)
