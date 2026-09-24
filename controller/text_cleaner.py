"""Text sanitization and cleaning module for ODIS Obliterator (TASK-003).

Removes target brand keywords (e.g. 'Lamborghini') from diagnostic blocks
(Message, Question, Comment) while strictly preserving system macros (e.g. @[std]...),
variables (e.g. %str_...%), and rich text markup.
"""

import re
from typing import Any, Dict, List, Optional, Pattern, Tuple
from pydantic import BaseModel, Field
from controller.config import Settings, get_settings


class TextCleanRequest(BaseModel):
    """Pydantic model for text sanitization request."""

    raw_text: str = Field(..., description="Original raw text from ODIS block.")
    block_type: Optional[str] = Field(
        default=None,
        description="Block type (MESSAGE, QUESTION, COMMENT, etc.).",
    )
    target_keyword: Optional[str] = Field(
        default=None,
        description="Target keyword override (defaults to configured target keyword).",
    )


class TextCleanResponse(BaseModel):
    """Pydantic model for text sanitization response."""

    cleaned_text: str = Field(..., description="Depurated and sanitized text.")
    modified: bool = Field(..., description="Whether any modifications were made.")
    occurrences_removed: int = Field(
        default=0,
        description="Number of target keyword occurrences removed.",
    )


class TextCleanResult:
    """Detailed result of a text cleaning operation."""

    def __init__(
        self,
        raw_text: str,
        cleaned_text: str,
        modified: bool,
        occurrences_removed: int,
        block_type: Optional[str] = None,
        protected_tokens: Optional[List[str]] = None,
    ):
        self.raw_text = raw_text
        self.cleaned_text = cleaned_text
        self.modified = modified
        self.occurrences_removed = occurrences_removed
        self.block_type = block_type
        self.protected_tokens = protected_tokens or []

    def to_response(self) -> TextCleanResponse:
        """Convert to TextCleanResponse Pydantic model."""
        return TextCleanResponse(
            cleaned_text=self.cleaned_text,
            modified=self.modified,
            occurrences_removed=self.occurrences_removed,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary representation."""
        return {
            "raw_text": self.raw_text,
            "cleaned_text": self.cleaned_text,
            "modified": self.modified,
            "occurrences_removed": self.occurrences_removed,
            "block_type": self.block_type,
            "protected_tokens_count": len(self.protected_tokens),
        }

    def __repr__(self) -> str:
        return (
            f"TextCleanResult(modified={self.modified}, "
            f"occurrences={self.occurrences_removed}, "
            f"cleaned_text={self.cleaned_text!r})"
        )


class TextCleaner:
    """Sanitizes text blocks by removing target brand keywords while protecting special tokens."""

    # Patterns for protected tokens that must never be altered or modified
    PROTECTED_PATTERNS: List[Pattern] = [
        re.compile(r"@\[[^\]\r\n]+\][A-Za-z0-9_]*"),  # ODIS macros: e.g. @[std]AU00003_Ende
        re.compile(r"%[A-Za-z0-9_]+%"),               # ODIS dynamic variables: e.g. %str_Bauteil%
        re.compile(r"<[/]?[A-Za-z][^>\r\n]*>"),        # XML/HTML Rich text tags: e.g. <b>, </font>
    ]

    # Delimiter using Unicode Private Use Area characters (\ue000, \ue001) which are \W (non-word)
    # and not whitespace, ensuring word boundaries \b trigger properly and tokens are not stripped.
    TOKEN_PLACEHOLDER_PREFIX = "\ue000ODIS_PROT_"
    TOKEN_PLACEHOLDER_SUFFIX = "\ue001"

    def __init__(
        self,
        target_keyword: Optional[str] = None,
        settings: Optional[Settings] = None,
    ):
        """Initialize TextCleaner.

        Args:
            target_keyword: Default keyword to remove (defaults to settings.target_keyword).
            settings: Settings instance.
        """
        self.settings = settings or get_settings()
        self.target_keyword = (
            target_keyword if target_keyword is not None else self.settings.target_keyword
        )

    def mask_protected_tokens(self, text: str) -> Tuple[str, List[str]]:
        """Identify and replace all protected tokens with non-word boundary placeholders.

        Args:
            text: Input string.

        Returns:
            Tuple of (masked_text, list_of_protected_tokens).
        """
        protected_tokens: List[str] = []

        # Find all match spans across all protected patterns
        matches: List[Tuple[int, int, str]] = []
        for pattern in self.PROTECTED_PATTERNS:
            for match in pattern.finditer(text):
                matches.append((match.start(), match.end(), match.group(0)))

        if not matches:
            return text, []

        # Sort matches by start index to replace from left to right
        matches.sort(key=lambda m: m[0])

        # Filter overlapping matches if any
        non_overlapping: List[Tuple[int, int, str]] = []
        last_end = -1
        for start, end, match_str in matches:
            if start >= last_end:
                non_overlapping.append((start, end, match_str))
                last_end = end

        # Build masked text
        output_parts: List[str] = []
        curr_idx = 0
        for i, (start, end, match_str) in enumerate(non_overlapping):
            output_parts.append(text[curr_idx:start])
            placeholder = f"{self.TOKEN_PLACEHOLDER_PREFIX}{i}{self.TOKEN_PLACEHOLDER_SUFFIX}"
            output_parts.append(placeholder)
            protected_tokens.append(match_str)
            curr_idx = end

        output_parts.append(text[curr_idx:])
        return "".join(output_parts), protected_tokens

    def unmask_protected_tokens(self, text: str, protected_tokens: List[str]) -> str:
        """Restore protected tokens from their placeholders.

        Args:
            text: Masked string.
            protected_tokens: List of original token strings.

        Returns:
            String with restored protected tokens.
        """
        for i, token in enumerate(protected_tokens):
            placeholder = f"{self.TOKEN_PLACEHOLDER_PREFIX}{i}{self.TOKEN_PLACEHOLDER_SUFFIX}"
            text = text.replace(placeholder, token)
        return text

    def _build_keyword_patterns(self, keyword: str) -> List[Tuple[Pattern, str]]:
        """Build regex replacement patterns for target keyword variations.

        Handles:
        - Hyphenated prefix/compounds (e.g. 'Lamborghini-Fahrzeuge' -> 'Fahrzeuge')
        - Hyphenated suffix (e.g. 'Test-Lamborghini' -> 'Test')
        - Possessive forms (e.g. "Lamborghini's ", "Lamborghini’s ", "Lamborghinis ")
        - Word standalone (case-insensitive) with following spaces
        """
        escaped = re.escape(keyword)

        return [
            # Compound with hyphen prefix: 'Lamborghini-Test' or 'Lamborghini - Test' -> 'Test'
            (re.compile(rf"\b{escaped}[ \t]*-[ \t]*(?=[A-Za-z0-9_])", re.IGNORECASE), ""),
            # Compound with hyphen suffix: 'Test-Lamborghini' or 'Test - Lamborghini' -> 'Test'
            (re.compile(rf"(?<=[A-Za-z0-9_])[ \t]*-[ \t]*{escaped}\b", re.IGNORECASE), ""),
            # Possessive with apostrophe: "Lamborghini's" or "Lamborghini’s"
            (re.compile(rf"\b{escaped}['’]s\b[ \t]*", re.IGNORECASE), ""),
            # Possessive or plural form 'Lamborghinis'
            (re.compile(rf"\b{escaped}s\b[ \t]*", re.IGNORECASE), ""),
            # Standalone word (with optional following horizontal whitespace)
            (re.compile(rf"\b{escaped}\b[ \t]*", re.IGNORECASE), ""),
        ]

    def _clean_single_line(self, line: str) -> str:
        """Process and clean artifacts on a single line of text."""
        if not line:
            return line

        # 1. Clean empty brackets/parentheses caused by keyword removal: e.g. "()", "( )", "[]"
        line = re.sub(r"\(\s*\)", "", line)
        line = re.sub(r"\[\s*\]", "", line)

        # 2. Fix duplicate punctuation: e.g. ",,", ", ,", "..", "::"
        line = re.sub(r",\s*,+", ",", line)
        line = re.sub(r"\.\s*\.+", ".", line)
        line = re.sub(r":\s*:+", ":", line)

        # 3. Check for list / bullet item prefix: e.g. "- ", "* ", "1. ", "1) "
        bullet_pattern = re.compile(r"^(\s*(?:[-*•]|\d+[.)]))(?:\s*[:,\-/])?(\s+)(.*)$")
        bullet_match = bullet_pattern.match(line)

        if bullet_match:
            bullet_marker = bullet_match.group(1)
            rest = bullet_match.group(3)

            # Remove dangling punctuation right at the start of bullet content
            rest = re.sub(r"^[:,\-/]\s*", "", rest)

            # Remove space before punctuation in content
            rest = re.sub(r"\s+([,.:;?!])", r"\1", rest)

            # Remove trailing commas before sentence punctuation or line end
            rest = re.sub(r",\s*(\.|\?|!|$)", r"\1", rest)

            # Normalize multiple spaces within content
            rest = re.sub(r"[ \t]{2,}", " ", rest).strip(" \t")

            # Capitalize first letter of bullet content if appropriate
            if rest and rest[0].islower():
                rest = rest[0].upper() + rest[1:]

            return f"{bullet_marker} {rest}" if rest else bullet_marker

        # Plain line (not a bullet/numbered list)
        indent_match = re.match(r"^(\s*)", line)
        indent = indent_match.group(1) if indent_match else ""
        if indent == " ":
            indent = ""
        content = line[len(indent):]

        # Remove dangling leading punctuation on content: e.g. ": Check", ", Check"
        content = re.sub(r"^[:,\-/]\s*", "", content)

        # Remove space before punctuation
        content = re.sub(r"\s+([,.:;?!])", r"\1", content)

        # Remove trailing commas before punctuation or line end
        content = re.sub(r",\s*(\.|\?|!|$)", r"\1", content)

        # Normalize multiple spaces within content
        content = re.sub(r"[ \t]{2,}", " ", content).strip(" \t")

        # Capitalize first letter if content starts with lowercase
        if content and content[0].islower():
            content = content[0].upper() + content[1:]

        return f"{indent}{content}" if content else ""

    def _clean_punctuation_and_whitespace(self, text: str) -> str:
        """Clean leftover punctuation artifacts, whitespace, and formatting inconsistencies."""
        has_crlf = "\r\n" in text
        lines = text.split("\r\n" if has_crlf else "\n")
        cleaned_lines = [self._clean_single_line(line) for line in lines]
        newline_char = "\r\n" if has_crlf else "\n"
        return newline_char.join(cleaned_lines)

    def clean(
        self,
        raw_text: str,
        block_type: Optional[str] = None,
        target_keyword: Optional[str] = None,
    ) -> TextCleanResult:
        """Depurate raw text by removing target keyword and preserving protected tokens.

        Args:
            raw_text: Original text string to sanitize.
            block_type: Optional block type identifier ('MESSAGE', 'QUESTION', 'COMMENT').
            target_keyword: Target keyword to remove (defaults to self.target_keyword).

        Returns:
            TextCleanResult instance containing cleaned text and modification statistics.
        """
        if not raw_text:
            return TextCleanResult(
                raw_text="",
                cleaned_text="",
                modified=False,
                occurrences_removed=0,
                block_type=block_type,
                protected_tokens=[],
            )

        keyword = target_keyword if target_keyword is not None else self.target_keyword
        if not keyword or not keyword.strip():
            return TextCleanResult(
                raw_text=raw_text,
                cleaned_text=raw_text,
                modified=False,
                occurrences_removed=0,
                block_type=block_type,
                protected_tokens=[],
            )

        # Step 1: Mask protected tokens (macros, variables, markup)
        masked_text, protected_tokens = self.mask_protected_tokens(raw_text)

        # Step 2: Count and remove target keyword matches from masked text
        patterns = self._build_keyword_patterns(keyword)

        # Count occurrences in masked text
        count_pattern = re.compile(rf"\b{re.escape(keyword)}(?:['’]s|s)?\b", re.IGNORECASE)
        occurrences = len(count_pattern.findall(masked_text))

        cleaned_masked = masked_text
        for pattern, replacement in patterns:
            cleaned_masked = pattern.sub(replacement, cleaned_masked)

        # Step 3: Clean punctuation and whitespace artifacts
        if occurrences > 0 or cleaned_masked != masked_text:
            cleaned_masked = self._clean_punctuation_and_whitespace(cleaned_masked)

        # Step 4: Unmask protected tokens
        final_cleaned_text = self.unmask_protected_tokens(cleaned_masked, protected_tokens)

        # Determine if text was actually modified
        modified = (final_cleaned_text != raw_text) and (occurrences > 0)

        return TextCleanResult(
            raw_text=raw_text,
            cleaned_text=final_cleaned_text,
            modified=modified,
            occurrences_removed=occurrences,
            block_type=block_type,
            protected_tokens=protected_tokens,
        )


def clean_text(
    raw_text: str,
    target_keyword: Optional[str] = None,
    block_type: Optional[str] = None,
) -> TextCleanResult:
    """Convenience helper function to sanitize text using default cleaner.

    Args:
        raw_text: Original text string to sanitize.
        target_keyword: Keyword to remove (defaults to settings.target_keyword).
        block_type: Optional block type ('MESSAGE', 'QUESTION', 'COMMENT').

    Returns:
        TextCleanResult instance.
    """
    cleaner = TextCleaner(target_keyword=target_keyword)
    return cleaner.clean(raw_text=raw_text, block_type=block_type)
