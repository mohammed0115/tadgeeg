from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, List


@dataclass
class ParseResult:
    text: str = ""
    page_count: int = 1
    row_count: int = 0
    column_names: List[str] = field(default_factory=list)
    sheet_names: List[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    raw_data: Any = None
    error: str = ""
    success: bool = True


class BaseParser(ABC):
    """Abstract base class for all file parsers."""

    @abstractmethod
    def parse(self, file_path: str) -> ParseResult:
        """Parse the file at file_path and return a ParseResult."""
        raise NotImplementedError

    @property
    @abstractmethod
    def supported_extensions(self) -> List[str]:
        """Return list of file extensions this parser handles (e.g. ['.pdf'])."""
        raise NotImplementedError
