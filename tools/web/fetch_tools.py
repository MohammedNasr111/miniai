"""Fetch one web page and return a short untrusted excerpt.

Each stage is its own function so tests can run it without the network
or without the permission prompt. fetch_url is not registered with the
model yet.
"""

import ipaddress
import socket
import time
from typing import Optional
from urllib.parse import urljoin, urlparse

import charset_normalizer
import requests
import trafilatura

from llm.lemonade.embeddings import embed
from security.gate import Tier, check_permission
from tools.filesystem.chunking import chunk_text
from tools.web.untrusted import (
    BEGIN_MARKER,
    END_MARKER,
    PREAMBLE,
    one_line,
    sanitize,
)
from tools.web.url_display import describe_url

MAX_REDIRECTS = 5
MAX_BYTES = 3_000_000
MAX_DOWNLOAD_SECONDS = 30
MAX_CHUNKS = 120
EMBED_BATCH = 32
USER_AGENT = "MiniAI/0.1 (personal local research agent)"
ALLOWED_TYPES = {"text/html", "application/xhtml+xml", "text/plain"}
REDIRECT_STATUSES = {301, 302, 303, 307, 308}


def _is_blocked(ip: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    """Block non-global addresses, including IPv4-mapped IPv6 forms."""
    addresses = [ip]
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        addresses.append(ip.ipv4_mapped)
    for address in addresses:
        if (
            address.is_loopback
            or address.is_private
            or address.is_link_local
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
            or not address.is_global
        ):
            return True
    return False


def validate_url(url: str) -> None:
    """Raise ValueError if url is not an http(s) URL to a public host."""
    parsed = urlparse(url)
    scheme = (parsed.scheme or "").lower()
    if scheme not in ("http", "https"):
        raise ValueError(
            f"URL scheme must be http or https, got {scheme!r} for {url!r}"
        )
    host = parsed.hostname
    if not host:
        raise ValueError(f"URL has no host: {url!r}")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise ValueError(f"Could not resolve host {host!r}: {exc}") from exc
    addresses = []
    for info in infos:
        ip_text = info[4][0]
        if "%" in ip_text:
            ip_text = ip_text.split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(ip_text)
        except ValueError as exc:
            raise ValueError(
                f"Host {host!r} resolved to an unreadable address {ip_text!r}"
            ) from exc
        addresses.append(ip)
    if not addresses:
        raise ValueError(f"Host {host!r} did not resolve to any address")
    blocked = [ip for ip in addresses if _is_blocked(ip)]
    if blocked:
        rendered = ", ".join(str(ip) for ip in blocked)
        raise ValueError(
            f"Host {host!r} resolves to a blocked address ({rendered}). "
            "Loopback, private, link-local, multicast, reserved, unspecified, "
            "and other non-public addresses are not fetched."
        )


def _media_type(header: Optional[str]) -> str:
    if not header:
        return ""
    return header.split(";", 1)[0].strip().lower()


def _declared_charset(header: Optional[str]) -> Optional[str]:
    if not header:
        return None
    for part in header.split(";")[1:]:
        piece = part.strip()
        if "=" not in piece:
            continue
        key, value = piece.split("=", 1)
        if key.strip().lower() == "charset":
            value = value.strip().strip('"').strip("'")
            return value or None
    return None


def _decode_body(body: bytes, content_type_header: Optional[str], response_encoding) -> str:
    """Decode a downloaded body.

    A declared charset keeps the previous path (the encoding requests
    derived from that parameter). With no charset, UTF-8 is tried
    strictly, then charset_normalizer, then UTF-8 with replacement.
    """
    if _declared_charset(content_type_header):
        encoding = response_encoding
        if not isinstance(encoding, str) or not encoding:
            encoding = "utf-8"
        return bytes(body).decode(encoding, errors="replace")
    try:
        return bytes(body).decode("utf-8")
    except UnicodeDecodeError:
        match = charset_normalizer.from_bytes(bytes(body)).best()
        if match is None:
            return bytes(body).decode("utf-8", errors="replace")
        return str(match)


def download(url: str) -> tuple[str, str, str]:
    """GET url, following at most 5 redirects, and return text.

    Every hop, including the first, is validated before it is requested.
    Returns (final_url, content_type, text).
    """
    validate_url(url)
    current = url
    headers = {"User-Agent": USER_AGENT}
    started = time.monotonic()
    for hop in range(MAX_REDIRECTS + 1):
        remaining = MAX_DOWNLOAD_SECONDS - (time.monotonic() - started)
        if remaining <= 0:
            raise ValueError("Download exceeded 30 s total")
        response = requests.get(
            current,
            allow_redirects=False,
            timeout=(min(10, remaining), min(20, remaining)),
            headers=headers,
            stream=True,
        )
        try:
            status = response.status_code
            if status in REDIRECT_STATUSES:
                if hop == MAX_REDIRECTS:
                    raise ValueError(
                        f"Too many redirects (max {MAX_REDIRECTS}) starting from {url}"
                    )
                location = response.headers.get("Location")
                if not location:
                    raise ValueError(
                        f"Redirect {status} from {current} had no Location header"
                    )
                target = urljoin(current, location)
                validate_url(target)
                current = target
                continue
            if status < 200 or status >= 300:
                raise ValueError(f"HTTP status {status} for {current}")
            raw_content_type = response.headers.get("Content-Type")
            content_type = _media_type(raw_content_type)
            if content_type not in ALLOWED_TYPES:
                named = content_type if content_type else "(missing)"
                raise ValueError(f"Unsupported content type: {named}")
            declared = response.headers.get("Content-Length")
            if declared is not None:
                try:
                    declared_n = int(declared)
                except ValueError:
                    declared_n = None
                if declared_n is not None and declared_n > MAX_BYTES:
                    raise ValueError(
                        f"Response body exceeds {MAX_BYTES} bytes "
                        f"(Content-Length {declared_n})"
                    )
            body = bytearray()
            for chunk in response.iter_content(chunk_size=65536):
                if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                    raise ValueError("Download exceeded 30 s total")
                if not chunk:
                    continue
                body.extend(chunk)
                if len(body) > MAX_BYTES:
                    raise ValueError(f"Response body exceeds {MAX_BYTES} bytes")
            if time.monotonic() - started > MAX_DOWNLOAD_SECONDS:
                raise ValueError("Download exceeded 30 s total")
            text = _decode_body(bytes(body), raw_content_type, response.encoding)
            return current, content_type, text
        finally:
            response.close()
    raise ValueError(f"Too many redirects (max {MAX_REDIRECTS}) starting from {url}")


def extract_text(html_or_text: str, content_type: str) -> tuple[Optional[str], str]:
    """Return (title, text). Plain text keeps a None title."""
    media = _media_type(content_type)
    if media == "text/plain":
        title = None
        text = html_or_text
    elif media in ("text/html", "application/xhtml+xml"):
        text = trafilatura.extract(
            html_or_text,
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        meta = trafilatura.extract_metadata(html_or_text)
        title = None if meta is None else meta.title
    else:
        named = media if media else "(missing)"
        raise ValueError(f"Unsupported content type: {named}")
    if text is None or not str(text).strip():
        raise ValueError("No readable text extracted")
    return title, text


def _dot(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


def rank_chunks(
    text: str, query: str, top_k: int
) -> list[tuple[int, float, str]]:
    """Embed up to 120 chunks and return the top_k in page order."""
    chunks = chunk_text(text, chunk_size=500, overlap=50)[:MAX_CHUNKS]
    if not chunks or top_k <= 0:
        return []
    vectors: list[list[float]] = []
    for start in range(0, len(chunks), EMBED_BATCH):
        vectors.extend(embed(chunks[start:start + EMBED_BATCH]))
    if len(vectors) != len(chunks):
        raise ValueError(
            f"Embedding service returned {len(vectors)} vectors for "
            f"{len(chunks)} chunks"
        )
    query_vector = embed(query)[0]
    scored = [
        (index, _dot(query_vector, vector), chunk)
        for index, (chunk, vector) in enumerate(zip(chunks, vectors))
    ]
    chosen = sorted(scored, key=lambda row: row[1], reverse=True)[:top_k]
    chosen.sort(key=lambda row: row[0])
    return chosen


def wrap_untrusted(
    final_url: str,
    title: Optional[str],
    ranked: list[tuple[int, float, str]],
) -> str:
    """Wrap ranked chunks so the model treats them as data, not instructions.

    Everything outside the markers is fixed text. The URL, title, and
    chunks are inside, with marker look-alikes collapsed.
    """
    safe_url = one_line(sanitize(final_url))
    safe_title = one_line(sanitize("" if title is None else title))[:200]
    blocks = []
    for index, similarity, chunk in ranked:
        cleaned = sanitize(chunk)
        blocks.append(f"[chunk {index}, similarity {similarity:.3f}]\n{cleaned}")
    lines = [
        *PREAMBLE,
        BEGIN_MARKER,
        f"Source URL: {safe_url}",
        f"Page title: {safe_title}",
    ]
    if blocks:
        lines.append("\n".join(blocks))
    lines.append(END_MARKER)
    return "\n".join(lines)


def fetch_url(url: str, query: str, top_k: int = 4) -> str:
    """Validate, ask permission, then download, extract, rank, and wrap."""
    validate_url(url)
    check_permission(
        action="fetch_url",
        tier=Tier.CONFIRM,
        description=f"Fetch URL:\n{describe_url(url)}\nQuery: {query}",
        url=url,
    )
    if top_k < 1:
        top_k = 1
    elif top_k > 6:
        top_k = 6
    final_url, content_type, text = download(url)
    title, extracted = extract_text(text, content_type)
    ranked = rank_chunks(extracted, query, top_k)
    return wrap_untrusted(final_url, title, ranked)
