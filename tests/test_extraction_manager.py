from core.services.extraction_manager import ExtractionManager, ExtractionStrategy
from core.services.parsers.base_parser import ParseResult


class DummyStrategy(ExtractionStrategy):
    def __init__(self, name, supported=True, success=False, method=None, fatal_error="failed"):
        self.name = name
        self._supported = supported
        self._success = success
        self._method = method or name
        self._fatal_error = fatal_error
        self.calls = 0

    def supports(self, *, mime_type: str, file_path: str) -> bool:
        return self._supported

    def extract(self, *, file_path: str, mime_type: str, use_ai: bool = True) -> ParseResult:
        self.calls += 1
        if self._success:
            return ParseResult(
                success=True,
                raw_text=f"{self.name} text",
                extraction_method=self._method,
                metadata={"source": self.name},
            )
        return ParseResult(success=False, fatal_error=self._fatal_error, extraction_method=self._method)


def test_extraction_manager_uses_first_successful_strategy():
    first = DummyStrategy("structured", success=False)
    second = DummyStrategy("text_layer", success=True, method="pdf_text_layer")
    third = DummyStrategy("vision_ai", success=True, method="openai_vision")

    manager = ExtractionManager(strategies=[first, second, third])
    result = manager.extract(file_path="invoice.pdf", mime_type="application/pdf", use_ai=True)

    assert result.success is True
    assert result.extraction_method == "pdf_text_layer"
    assert first.calls == 1
    assert second.calls == 1
    assert third.calls == 0
    assert result.metadata["winning_strategy"] == "text_layer"
    assert result.metadata["attempted_strategies"] == ["structured", "text_layer"]


def test_extraction_manager_records_failures_when_all_strategies_fail():
    structured = DummyStrategy("structured", success=False, fatal_error="no structured data")
    text_layer = DummyStrategy("text_layer", success=False, fatal_error="no text layer")
    manager = ExtractionManager(strategies=[structured, text_layer])

    result = manager.extract(file_path="invoice.pdf", mime_type="application/pdf", use_ai=True)

    assert result.success is False
    assert result.fatal_error == "All configured extraction strategies failed."
    assert result.metadata["attempted_strategies"] == ["structured", "text_layer"]
    assert len(result.metadata["strategy_trace"]) == 2
