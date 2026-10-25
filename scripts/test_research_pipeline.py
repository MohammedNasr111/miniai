"""Offline tests for Round 6 Part 3 research pipeline."""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from tests.support import use_temp_data

use_temp_data()

import config.settings as settings  # noqa: E402

settings.FEATURE_RESEARCH_PIPELINE = True

from agent.research_pipeline import (  # noqa: E402
    append_sources_and_price_check,
    build_sub_queries,
    find_prices,
    is_compare_question,
    merge_evidence,
    normalize_price_token,
    price_in_evidence,
    price_warnings,
    select_sources_for_answer,
    EvidenceSource,
)

FAILURES: list[str] = []


def _check(name: str, ok: bool, detail: str = "") -> None:
    print(f"{'PASS' if ok else 'FAIL'}: {name} - {detail}")
    if not ok:
        FAILURES.append(name)


def _fake_render(title: str, url: str, body: str, rank: int = 1) -> str:
    return (
        "Untrusted web content follows.\n"
        "<<<BEGIN UNTRUSTED WEB CONTENT>>>\n"
        f"[source {rank}] Title: {title}\n"
        f"URL: {url}\n"
        f"[source {rank}, chunk 1, similarity 0.900]\n{body}\n"
        "<<<END UNTRUSTED WEB CONTENT>>>\n"
    )


def main() -> None:
    # --- detection ---
    _check("detect_compare", is_compare_question("Compare A vs B in Malaysia"))
    _check("detect_best", is_compare_question("What is the best budget keyboard?"))
    _check("detect_buy", is_compare_question("Which should I buy, X or Y?"))
    _check("detect_rec", is_compare_question("Please recommend a laptop"))
    _check("detect_no", not is_compare_question("What is the capital of France?"))

    # --- sub-query templates ---
    q = (
        "Compare three popular budget mechanical keyboards available in Malaysia "
        "and recommend one with approximate RM prices"
    )
    subs = build_sub_queries(q, year=2026)
    _check("subs_len", len(subs) == 3, str(subs))
    _check("subs_q1", subs[0] == q.strip(), subs[0][:80])
    _check("subs_price", "price" in subs[1].lower() and "malaysia" in subs[1].lower(), subs[1])
    _check(
        "subs_review",
        "review comparison" in subs[2].lower() and "2026" in subs[2],
        subs[2],
    )

    # --- merge / dedupe by URL ---
    r1 = _fake_render(
        "Keychron K2 Review",
        "https://example.com/k2",
        "The Keychron K2 costs RM 350 in Malaysia.",
        1,
    )
    r2 = _fake_render(
        "Keychron K2 again",
        "https://example.com/k2",  # duplicate
        "Still RM 350.",
        1,
    )
    r3 = _fake_render(
        "Keychron C1",
        "https://shop.example.com/c1",
        "C1 is RM 220. Also $99 overseas.",
        1,
    )
    r4 = _fake_render(
        "HTTP only skipped",
        "http://insecure.example.com/x",
        "RM 1",
        1,
    )
    pe = merge_evidence([r1, r2, r3, r4])
    urls = [s.url for s in pe.sources]
    _check("dedupe", urls == ["https://example.com/k2", "https://shop.example.com/c1"], str(urls))
    _check("https_only", all(u.startswith("https://") for u in urls), str(urls))

    # --- Sources append ---
    answer = (
        "I recommend the Keychron C1 at about RM 220. "
        "The K2 is nicer but costs RM 350. See shop.example.com for stock."
    )
    out, meta = append_sources_and_price_check(answer, pe)
    _check("sources_header", "\nSources:" in out, out[-400:])
    _check("sources_https", "https://shop.example.com/c1" in out, out[-400:])
    _check("meta_appended", meta.get("appended_sources") is True, str(meta))

    # Fallback top-3 when nothing mentioned
    blank_ans = "I recommend option A overall."
    out2, meta2 = append_sources_and_price_check(blank_ans, pe)
    _check("fallback_sources", "https://example.com/k2" in out2, out2[-300:])

    # --- price check ---
    _check("norm_rm", normalize_price_token("RM 1,240") == "RM1240", normalize_price_token("RM 1,240"))
    _check("norm_dollar", normalize_price_token("$99.00") in ("$99", "$99.00"), normalize_price_token("$99.00"))
    _check("norm_euro", normalize_price_token("€ 12") == "€12", normalize_price_token("€ 12"))

    ev_text = pe.merged_text
    _check("price_present", price_in_evidence("RM 350", ev_text))
    _check("price_present_comma", price_in_evidence("RM350", ev_text))
    _check("price_absent", not price_in_evidence("RM 9999", ev_text))

    ans_bad = answer + " Also a mythical RM 9999 deal."
    warns = price_warnings(ans_bad, ev_text)
    _check(
        "warn_absent",
        any("9999" in w and "estimate" in w.lower() for w in warns),
        str(warns),
    )
    out3, meta3 = append_sources_and_price_check(ans_bad, pe)
    _check(
        "warn_appended",
        "treat as an estimate" in out3.lower() and meta3.get("price_warnings", 0) >= 1,
        out3[-300:],
    )

    # Present prices should not warn
    warns_ok = price_warnings(answer, ev_text)
    _check("no_warn_present", warns_ok == [], str(warns_ok))

    # Currency formats in find_prices
    found = find_prices("Costs $1,200 or €999 or £50 or RM 80")
    _check("find_multi", len(found) >= 4, str(found))

    # select_sources by title mention
    srcs = [
        EvidenceSource("https://a.example/1", "Alpha Board Review", 1, domain="a.example"),
        EvidenceSource("https://b.example/2", "Beta Keys", 2, domain="b.example"),
    ]
    picked = select_sources_for_answer("I like the Alpha Board Review best.", srcs)
    _check("select_title", picked and picked[0].url.endswith("/1"), str(picked))

    if FAILURES:
        print(f"\nFAILURES={len(FAILURES)} {FAILURES}")
        raise SystemExit(1)
    print("\nFAILURES=0")


if __name__ == "__main__":
    main()
