from apps.audit_engine.exceptions import AuditParsingError
from apps.audit_engine.services.parsers.base import BaseParser, ParseResult
from apps.audit_engine.services.parsers.csv_parser import CSVParser
from apps.audit_engine.services.parsers.excel_parser import ExcelParser
from apps.audit_engine.services.parsers.image_parser import ImageParser
from apps.audit_engine.services.parsers.json_parser import JSONParser
from apps.audit_engine.services.parsers.pdf_parser import PDFParser


class ParserDispatcher:
    """
    Routes a file to the appropriate parser based on file extension.
    All parsers are registered at instantiation time.
    """

    def __init__(self):
        self._parsers: dict[str, BaseParser] = {}
        self._register_defaults()

    def _register_defaults(self):
        for parser_class in [PDFParser, ExcelParser, CSVParser, JSONParser, ImageParser]:
            parser_instance = parser_class()
            for ext in parser_instance.supported_extensions:
                self._parsers[ext.lower()] = parser_instance

    def register(self, parser: BaseParser):
        """Register a custom parser, overriding any existing one for its extensions."""
        for ext in parser.supported_extensions:
            self._parsers[ext.lower()] = parser

    def get_parser(self, file_extension: str) -> BaseParser:
        ext = file_extension.lower()
        if not ext.startswith("."):
            ext = f".{ext}"
        if ext not in self._parsers:
            raise AuditParsingError(
                f"No parser registered for extension '{ext}'. "
                f"Supported: {sorted(self._parsers.keys())}"
            )
        return self._parsers[ext]

    def parse(self, file_path: str, file_extension: str) -> ParseResult:
        """Dispatch file_path to the correct parser and return ParseResult."""
        parser = self.get_parser(file_extension)
        return parser.parse(file_path)

    @property
    def supported_extensions(self) -> list:
        return sorted(self._parsers.keys())
