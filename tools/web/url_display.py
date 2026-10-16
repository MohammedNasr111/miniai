"""Human-readable URL lines for permission prompts.

Shows the full URL, then decoded path / query / fragment when the URL
carries data that percent-encoding would otherwise hide.
"""

from urllib.parse import parse_qsl, unquote, urlparse

from tools.web.untrusted import one_line, sanitize

_MAX_PARAM_CHARS = 300


def describe_url(url: str) -> str:
    """Full URL on one line, plus decoded path/query/fragment when present."""
    raw = one_line(sanitize(url or ""))
    parsed = urlparse(url or "")
    path_raw = parsed.path or ""
    path_decoded = unquote(path_raw)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    fragment_raw = parsed.fragment or ""
    fragment_decoded = unquote(fragment_raw) if fragment_raw else ""

    carries_data = (
        (bool(path_raw) and path_decoded != path_raw)
        or bool(pairs)
        or bool(fragment_raw)
    )
    if not carries_data:
        return raw

    lines = [raw, "Data carried in this URL:"]
    if path_raw and path_decoded != path_raw:
        lines.append(f"  path: {one_line(sanitize(path_decoded))}")
    for name, value in pairs:
        shown = unquote(value)[:_MAX_PARAM_CHARS]
        lines.append(
            f"  {one_line(sanitize(name))} = {one_line(sanitize(shown))}"
        )
    if fragment_raw:
        lines.append(f"  fragment: {one_line(sanitize(fragment_decoded))}")
    return "\n".join(lines)
