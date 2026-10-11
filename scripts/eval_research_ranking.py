"""Score web_research ranking variants against saved page snapshots.

Offline: reads tests/fixtures/web_snapshots/, embeds with Lemonade,
does not call Tavily or the network.
"""

import json
import sys
from pathlib import Path

from tools.filesystem.chunking import chunk_text
from tools.web.research_tools import (
    CHUNK_OVERLAP,
    CHUNK_SIZE,
    MAX_CHUNKS_PER_PAGE,
    _Page,
    _select,
    embed,
)

ROOT = Path(__file__).resolve().parents[1]
SNAP = ROOT / "tests" / "fixtures" / "web_snapshots"
VARIANTS = (
    ("A", False, False),
    ("B", True, False),
    ("C", False, True),
    ("D", True, True),
)


def _cache_embed() -> None:
    """Identical strings are embedded once. Ranking is unchanged."""
    import tools.web.research_tools as research

    real = embed
    cache: dict[tuple[str, ...], list[list[float]]] = {}

    def cached(text):
        key = (text,) if isinstance(text, str) else tuple(text)
        if key not in cache:
            cache[key] = real(text)
        return cache[key]

    research.embed = cached


def _pages(raw_pages: list[dict]) -> list[_Page]:
    pages = []
    for item in raw_pages:
        chunks = chunk_text(
            item["text"] or "",
            chunk_size=CHUNK_SIZE,
            overlap=CHUNK_OVERLAP,
        )[:MAX_CHUNKS_PER_PAGE]
        pages.append(
            _Page(
                rank=item["rank"],
                title=item.get("title"),
                final_url=item["url"],
                chunks=chunks,
            )
        )
    return pages


def _rendered(chosen) -> str:
    parts = []
    for score, page, index, text in chosen:
        parts.append(
            f"[source {page.rank}, chunk {index}, similarity {score:.3f}]\n{text}"
        )
    return "\n".join(parts)


def _best(chosen, expected: str):
    needle = expected.lower()
    hits = [
        (score, page, index, text)
        for score, page, index, text in chosen
        if needle in text.lower()
    ]
    if not hits:
        return None
    score, page, index, _text = max(hits, key=lambda row: row[0])
    return score, page.rank, index


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    _cache_embed()
    paths = sorted(SNAP.glob("*.json"))
    if len(paths) != 8:
        print(f"Expected 8 snapshots, found {len(paths)} in {SNAP}")
        sys.exit(1)
    rows = []
    q1_d = None
    for path in paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        question = data["question"]
        expected = data["expected"]
        holders = [
            page["url"]
            for page in data["pages"]
            if expected.lower() in (page.get("text") or "").lower()
        ]
        answerable = bool(holders)
        built = _pages(data["pages"])
        print(f"Q {path.stem}: answerable={answerable}")
        if holders:
            for url in holders:
                print(f"  contains {expected!r}: {url}")
        else:
            print(f"  {expected!r} not in any fetched page")
        variant_rows = []
        for name, prefixes, expand in VARIANTS:
            chosen = _select(
                question,
                built,
                use_prefixes=prefixes,
                expand_neighbors=expand,
            )
            rendered = _rendered(chosen)
            hit = expected.lower() in rendered.lower()
            best = _best(chosen, expected)
            variant_rows.append(
                {
                    "variant": name,
                    "hit": hit,
                    "chars": len(rendered),
                    "best": best,
                }
            )
            if path.stem == "01" and name == "D":
                q1_d = chosen
        rows.append(
            {
                "n": path.stem,
                "question": question,
                "expected": expected,
                "answerable": answerable,
                "variants": variant_rows,
            }
        )
    answerable_rows = [row for row in rows if row["answerable"]]
    print("\nTABLE")
    print(f"{'Q':<4}{'expected':<10}{'ok':<6}" + "".join(f"{name:>16}" for name, _, _ in VARIANTS))
    for row in rows:
        cells = []
        for item in row["variants"]:
            mark = "HIT" if item["hit"] else "miss"
            cells.append(f"{mark} {item['chars']}")
        flag = "yes" if row["answerable"] else "no"
        print(
            f"{row['n']:<4}{row['expected']:<10}{flag:<6}"
            + "".join(f"{cell:>16}" for cell in cells)
        )
        for item in row["variants"]:
            best = item["best"]
            if best is None:
                where = "none"
            else:
                score, rank, index = best
                where = f"source {rank} chunk {index} score {score:.3f}"
            print(f"    {item['variant']} best: {where}")
    print("\nTOTALS (answerable only)")
    n_ok = len(answerable_rows)
    for index, (name, _, _) in enumerate(VARIANTS):
        hits = sum(1 for row in answerable_rows if row["variants"][index]["hit"])
        chars = [row["variants"][index]["chars"] for row in answerable_rows]
        mean = sum(chars) / len(chars) if chars else 0
        print(f"{name}: {hits}/{n_ok} hits, mean output chars {mean:.0f}")
    print("\nQUESTION 1 VARIANT D CHUNKS")
    if not q1_d:
        print("(none selected)")
    else:
        for score, page, index, text in q1_d:
            print(f"--- source {page.rank} chunk {index} similarity {score:.3f} url {page.final_url}")
            print(text)
            print("--- end chunk ---")


if __name__ == "__main__":
    main()
