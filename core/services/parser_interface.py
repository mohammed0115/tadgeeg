"""
Parser Interface - Base class for all document parsers.

All parsers must implement this interface to work with the DocumentEngine.
This enables polymorphic document processing regardless of file type.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional, Dict, List, Any
import logging

logger = logging.getLogger(__name__)


@dataclass
class ParseResult:
    """Result of parsing a document with a parser."""
    
    raw_text: str = ""
    """Extracted raw text (OCR output or PDF text extraction)"""
    
    structured_data: Dict[str, Any] = None
    """Structured data if parser extracted it (JSON, CSV, Excel rows)"""
    
    pages: List[Dict[str, Any]] = None
    """For multi-page documents, per-page results"""
    
    metadata: Dict[str, Any] = None
    """Parser-specific metadata (encoding, confidence, page count, etc.)"""
    
    success: bool = True
    """Was the parsing successful"""
    
    error_message: str = ""
    """Error message if parsing failed"""

    def __post_init__(self):
        if self.structured_data is None:
            self.structured_data = {}
        if self.pages is None:
            self.pages = []
        if self.metadata is None:
            self.metadata = {}


class DocumentParsingError(Exception):
    """Raised when parser encounters an error during parsing."""
    pass


class DocumentValidationError(Exception):
    """Raised when file validation fails before parsing."""
    pass


class DocumentParser(ABC):
    """
    Abstract base class for all document parsers.
    
    Every parser must implement this interface:
    - parse() - extract raw data from document
    - validate() - validate if parser can handle file
    - get_parser_type() - identify parser type
    
    Example concrete implementation:
    
        class JSONParser(DocumentParser):
            def parse(self, file_path: str) -> ParseResult:
                with open(file_path) as f:
                    data = json.load(f)
                return ParseResult(structured_data=data, success=True)
            
            def validate(self, file_path: str, file_type: str) -> bool:
                return file_type in ['json', 'application/json']
            
            def get_parser_type(self) -> str:
                return 'json'
    """

    @abstractmethod
    def parse(self, file_path: str) -> ParseResult:
        """
        Parse document and extract raw data.
        
        Args:
            file_path: Path to file (local or S3 path)
        
        Returns:
            ParseResult: Structured result containing:
                - raw_text: Extracted text
                - structured_data: Parsed data if applicable
                - pages: Per-page data for multi-page docs
                - metadata: Parser-specific metadata
        
        Raises:
            DocumentParsingError: Any parsing failure
            DocumentValidationError: Invalid file format
        """
        pass

    @abstractmethod
    def validate(self, file_path: str, file_type: str) -> bool:
        """
        Check if this parser can handle the file.
        
        Args:
            file_path: Path to file
            file_type: MIME type or file extension
        
        Returns:
            bool: True if this parser can handle it
        """
        pass

    @abstractmethod
    def get_parser_type(self) -> str:
        """
        Return string identifier for this parser.
        
        Used for logging and tracking which parser was used.
        
        Returns:
            str: Parser type identifier (e.g., 'json', 'pdf', 'image')
        """
        pass

    def _log_parsing(self, message: str, level: str = "info"):
        """Helper to log parsing activities"""
        log_func = getattr(logger, level)
        log_func(f"[{self.get_parser_type()}] {message}")
