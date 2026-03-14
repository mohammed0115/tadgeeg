"""
Document Parsers Package

Each parser implements DocumentParser interface.
The document engine imports parsers from here.
"""

from .image_parser import ImageParser
from .pdf_parser import PDFParser
from .excel_parser import ExcelParser
from .csv_parser import CSVParser
from .json_parser import JSONParser
from .zip_parser import ZIPParser

__all__ = [
    "ImageParser",
    "PDFParser",
    "ExcelParser",
    "CSVParser",
    "JSONParser",
    "ZIPParser",
]
