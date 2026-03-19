"""Text Normalization Service — normalize Arabic/English financial text."""

import re
import unicodedata


class TextNormalizationService:
    """Normalize Arabic/English financial text for consistent AI processing."""

    ARABIC_NUMERALS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")

    # Arabic Unicode ranges
    ARABIC_RANGE = re.compile(r"[\u0600-\u06FF\u0750-\u077F\uFB50-\uFDFF\uFE70-\uFEFF]")

    def normalize(self, text: str) -> str:
        """
        Full normalization pipeline:
        1. Normalize Arabic/Indic numerals to Western
        2. Unicode normalization (NFKC)
        3. Collapse whitespace
        4. Clean non-printable characters
        """
        if not text:
            return ""
        text = self._normalize_arabic_numerals(text)
        text = unicodedata.normalize("NFKC", text)
        text = self._remove_non_printable(text)
        text = self._collapse_whitespace(text)
        return text.strip()

    def detect_language(self, text: str) -> str:
        """
        Detect language of text.
        Returns: ar | en | ar-en | unknown
        """
        if not text or not text.strip():
            return "unknown"

        ratio = self._detect_arabic_ratio(text)

        if ratio >= 0.6:
            return "ar"
        elif ratio >= 0.2:
            return "ar-en"
        elif ratio < 0.05:
            # Check if there's enough ASCII letters for English
            ascii_letters = sum(1 for c in text if c.isalpha() and ord(c) < 128)
            total_letters = sum(1 for c in text if c.isalpha())
            if total_letters > 0 and ascii_letters / total_letters > 0.8:
                return "en"
        return "unknown"

    def _normalize_arabic_numerals(self, text: str) -> str:
        """Convert Arabic-Indic (Eastern Arabic) numerals to Western Arabic numerals."""
        return text.translate(self.ARABIC_NUMERALS)

    def _collapse_whitespace(self, text: str) -> str:
        """Collapse multiple spaces/tabs into a single space, preserve single newlines."""
        # Collapse horizontal whitespace
        text = re.sub(r"[ \t]+", " ", text)
        # Collapse 3+ newlines to 2
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text

    def _remove_non_printable(self, text: str) -> str:
        """Remove non-printable control characters except newlines and tabs."""
        result = []
        for ch in text:
            if ch in ("\n", "\t", "\r"):
                result.append(ch if ch != "\r" else "\n")
            elif unicodedata.category(ch) in ("Cc", "Cs"):
                # Control chars and surrogates
                continue
            else:
                result.append(ch)
        return "".join(result)

    def _detect_arabic_ratio(self, text: str) -> float:
        """Return ratio of Arabic characters to total alphabetic characters."""
        arabic_chars = len(self.ARABIC_RANGE.findall(text))
        total_alpha = sum(1 for c in text if c.isalpha())
        if total_alpha == 0:
            return 0.0
        return arabic_chars / total_alpha
