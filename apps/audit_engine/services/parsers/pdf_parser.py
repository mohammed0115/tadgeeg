from apps.audit_engine.services.parsers.base import BaseParser, ParseResult


class PDFParser(BaseParser):
    """Parse PDF files using PyMuPDF (fitz)."""

    @property
    def supported_extensions(self):
        return [".pdf"]

    def parse(self, file_path: str) -> ParseResult:
        try:
            import fitz  # PyMuPDF

            doc = fitz.open(file_path)
            pages_text = []
            for page in doc:
                pages_text.append(page.get_text())
            doc_metadata = doc.metadata or {}
            full_text = "\n".join(pages_text)
            page_count = len(doc)
            doc.close()

            return ParseResult(
                text=full_text,
                page_count=page_count,
                metadata={
                    "title": doc_metadata.get("title", ""),
                    "author": doc_metadata.get("author", ""),
                    "subject": doc_metadata.get("subject", ""),
                    "creator": doc_metadata.get("creator", ""),
                    "producer": doc_metadata.get("producer", ""),
                },
                success=True,
            )
        except ImportError:
            return ParseResult(
                success=False,
                error="PyMuPDF (fitz) is not installed. Run: pip install pymupdf",
            )
        except Exception as exc:
            return ParseResult(success=False, error=str(exc))
