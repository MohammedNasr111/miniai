"""Provider-agnostic web search results."""

from abc import ABC, abstractmethod

from pydantic import BaseModel


class SearchResult(BaseModel):
    title: str
    url: str
    snippet: str


class SearchProvider(ABC):
    """One search() method, same idea as the LLM provider."""

    @abstractmethod
    def search(self, query: str, max_results: int) -> list[SearchResult]:
        raise NotImplementedError
