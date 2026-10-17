"""Human-readable URL lines for permission prompts.

Shows the full URL, then decoded path / query / fragment when the URL
carries data that percent-encoding would otherwise hide.
"""

from urllib.parse import parse_qsl, unquote, urlparse

from tools.web.untrusted import one_line, sanitize

_MAX_PARAM_CHARS = 300


def _url_data_parts(url: str) -> tuple[str, str, list[tuple[str, str]], str, str]:
    """Parse path/query/fragment the same way for describe_url and carries_data."""
    parsed = urlparse(url or "")
    path_raw = parsed.path or ""
    path_decoded = unquote(path_raw)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    fragment_raw = parsed.fragment or ""
    fragment_decoded = unquote(fragment_raw) if fragment_raw else ""
    return path_raw, path_decoded, pairs, fragment_raw, fragment_decoded


def carries_data(url: str) -> bool:
    """True if the URL has a query, a fragment, or a path changed by decoding."""
    path_raw, path_decoded, pairs, fragment_raw, _fragment_decoded = _url_data_parts(
        url
    )
    return (
        (bool(path_raw) and path_decoded != path_raw)
        or bool(pairs)
        or bool(fragment_raw)
    )


def describe_url(url: str) -> str:
    """Full URL on one line, plus decoded path/query/fragment when present."""
    raw = one_line(sanitize(url or ""))
    path_raw, path_decoded, pairs, fragment_raw, fragment_decoded = _url_data_parts(
        url
    )
    if not carries_data(url):
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
