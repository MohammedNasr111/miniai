"""Web search tool. Not registered with the model yet."""

from security.gate import Tier, check_permission
from tools.web.search.tavily import TavilyProvider
from tools.web.untrusted import BEGIN_MARKER, END_MARKER, PREAMBLE, one_line, sanitize


def web_search(query: str, max_results: int = 5) -> str:
    """Search the public web and return a short untrusted result list."""
    check_permission(
        action="web_search",
        tier=Tier.AUTO_ALLOW,
        description=f"Web search: {query}",
    )
    if max_results < 1:
        max_results = 1
    elif max_results > 8:
        max_results = 8
    results = TavilyProvider().search(query, max_results)
    lines = [
        *PREAMBLE,
        BEGIN_MARKER,
        f"Search query: {one_line(sanitize(query))}",
    ]
    if not results:
        lines.append("No results.")
    else:
        for index, result in enumerate(results, start=1):
            title = one_line(sanitize(result.title))[:200]
            url = one_line(sanitize(result.url))
            snippet = one_line(sanitize(result.snippet))[:400]
            lines.append(f"[result {index}] Title: {title}")
            lines.append(f"URL: {url}")
            lines.append(f"Snippet: {snippet}")
    lines.append(END_MARKER)
    return "\n".join(lines)
