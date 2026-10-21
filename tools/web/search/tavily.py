"""Tavily search over the documented REST endpoint. No SDK."""

import requests

from config import settings
from tools.web.search.base import SearchProvider, SearchResult

SEARCH_URL = "https://api.tavily.com/search"


class TavilyProvider(SearchProvider):
    def search(self, query: str, max_results: int) -> list[SearchResult]:
        key = settings.TAVILY_API_KEY
        if not key:
            raise ValueError("TAVILY_API_KEY is not set in .env")
        body = {
            "query": query,
            "search_depth": "basic",
            "max_results": max_results,
            "include_answer": False,
            "include_raw_content": False,
        }
        try:
            response = requests.post(
                SEARCH_URL,
                headers={
                    "Authorization": f"Bearer {key}",
                    "Content-Type": "application/json",
                },
                json=body,
                timeout=(10, 20),
            )
        except requests.RequestException:
            raise ValueError("Web search request failed") from None
        status = response.status_code
        if status == 429:
            raise ValueError(f"Web search failed with status {status} (rate limited)")
        if status < 200 or status >= 300:
            raise ValueError(f"Web search failed with status {status}")
        try:
            payload = response.json()
        except ValueError:
            raise ValueError(
                f"Web search failed with status {status}: response was not JSON"
            ) from None
        raw_results = payload.get("results", [])
        if not isinstance(raw_results, list):
            raise ValueError("Web search response results was not a list")
        results = []
        for item in raw_results:
            if not isinstance(item, dict):
                raise ValueError("Web search response result was not an object")
            published = item.get("published_date")
            if published is None:
                published = item.get("publishedDate")
            results.append(
                SearchResult(
                    title=_text(item.get("title")),
                    url=_text(item.get("url")),
                    snippet=_text(item.get("content")),
                    published_date=_text(published) or None,
                )
            )
        return results


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)
