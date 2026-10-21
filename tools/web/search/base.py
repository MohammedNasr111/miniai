"""Provider-agnostic web search results."""

from abc import ABC, abstractmethod
from typing import Optional

from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str
    published_date: Optional[str] = None


class SearchProvider(ABC):
    """One search() method, same idea as the LLM provider."""

    @abstractmethod
    def search(self, query: str, max_results: int) -> list[SearchResult]:
        raise NotImplementedError
