"""Unit tests for TextCleaner and text sanitization module (TASK-003).

Verifies removal of target keyword (e.g., 'Lamborghini') across Message, Question,
and Comment blocks while strictly guaranteeing the invariance of macros (@[std]...),
variables (%str_...%), and rich text markup.
"""

import pytest
from controller.text_cleaner import (
    TextCleanRequest,
    TextCleanResponse,
    TextCleanResult,
    TextCleaner,
    clean_text,
)


# ---------------------------------------------------------------------------
# Case 1: Standard Message Block with System Macro Tag (DESIGN.md Spec)
# ---------------------------------------------------------------------------
def test_case_01_message_block_with_macro_tag():
    """Verify standard message block cleaning with @[std]... macro preserved."""
    raw_text = "- Ignore the event memory Lamborghini entry\n\n@[std]AU00003_Ende"
    expected = "- Ignore the event memory entry\n\n@[std]AU00003_Ende"

    res = clean_text(raw_text, block_type="MESSAGE")
    assert res.modified is True
    assert res.occurrences_removed == 1
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 2: Question Block with Dynamic Variable
# ---------------------------------------------------------------------------
def test_case_02_question_block_with_dynamic_variable():
    """Verify question block with dynamic variable %str_Bauteil% preserved."""
    raw_text = "Is the Lamborghini %str_Bauteil% connected properly?"
    expected = "Is the %str_Bauteil% connected properly?"

    res = clean_text(raw_text, block_type="QUESTION")
    assert res.modified is True
    assert res.occurrences_removed == 1
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 3: Comment Block with Leading Brand Name
# ---------------------------------------------------------------------------
def test_case_03_comment_block_leading_keyword():
    """Verify comment block removal of leading brand keyword."""
    raw_text = "Lamborghini 1 = statisch"
    expected = "1 = statisch"

    res = clean_text(raw_text, block_type="COMMENT")
    assert res.modified is True
    assert res.occurrences_removed == 1
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 4: Protected Variable Containing Target Keyword Name
# ---------------------------------------------------------------------------
def test_case_04_protected_variable_with_keyword_inside():
    """Verify variable %str_Lamborghini_ECU% is NOT altered under any circumstances."""
    raw_text = "Reading DTC memory from %str_Lamborghini_ECU% now."
    expected = "Reading DTC memory from %str_Lamborghini_ECU% now."

    res = clean_text(raw_text)
    assert res.modified is False
    assert res.occurrences_removed == 0
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 5: Protected Macro Tag Containing Target Keyword
# ---------------------------------------------------------------------------
def test_case_05_protected_macro_with_keyword_inside():
    """Verify macro @[std]Lamborghini_Init is NOT altered under any circumstances."""
    raw_text = "Initialization sequence:\n@[std]Lamborghini_Init\n@[std]AU00003_Ende"
    expected = "Initialization sequence:\n@[std]Lamborghini_Init\n@[std]AU00003_Ende"

    res = clean_text(raw_text)
    assert res.modified is False
    assert res.occurrences_removed == 0
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 6: Hyphenated German Compound Word
# ---------------------------------------------------------------------------
def test_case_06_hyphenated_compound_german():
    """Verify German compound with hyphen 'Lamborghini-Fahrzeuge' -> 'Fahrzeuge'."""
    raw_text = "Lamborghini-Fahrzeuge mit %str_Steuergeraet% prüfen."
    expected = "Fahrzeuge mit %str_Steuergeraet% prüfen."

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.occurrences_removed >= 1
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 7: Hyphenated English Compound Word
# ---------------------------------------------------------------------------
def test_case_07_hyphenated_compound_english():
    """Verify English hyphenated compound 'Lamborghini-specific' -> 'specific'."""
    raw_text = "Perform Lamborghini-specific calibration step."
    expected = "Perform specific calibration step."

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 8: Possessive Form (Apostrophe-S and Suffix)
# ---------------------------------------------------------------------------
def test_case_08_possessive_forms():
    """Verify possessive forms 'Lamborghini's' and 'Lamborghinis'."""
    raw_text_1 = "Check the Lamborghini's battery voltage."
    expected_1 = "Check the battery voltage."
    res_1 = clean_text(raw_text_1)
    assert res_1.modified is True
    assert res_1.cleaned_text == expected_1

    raw_text_2 = "Inspect all Lamborghinis in the workshop."
    expected_2 = "Inspect all in the workshop."
    res_2 = clean_text(raw_text_2)
    assert res_2.modified is True
    assert res_2.cleaned_text == expected_2


# ---------------------------------------------------------------------------
# Case 9: Uppercase / All-Caps Text
# ---------------------------------------------------------------------------
def test_case_09_all_caps_keyword():
    """Verify case-insensitive cleaning for ALL-CAPS target word."""
    raw_text = "ACHTUNG: LAMBORGHINI DIAGNOSE STARTEN"
    expected = "ACHTUNG: DIAGNOSE STARTEN"

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 10: Lowercase Keyword
# ---------------------------------------------------------------------------
def test_case_10_lowercase_keyword():
    """Verify case-insensitive cleaning for lowercase target word."""
    raw_text = "Connect lamborghini diagnostic interface to OBD socket."
    expected = "Connect diagnostic interface to OBD socket."

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 11: Multi-line Bulleted List with Initial Capitalization
# ---------------------------------------------------------------------------
def test_case_11_multiline_bullet_list_capitalization():
    """Verify bullet points preserve formatting and capitalize following word."""
    raw_text = (
        "- Lamborghini check ignition switch\n"
        "- Lamborghini verify CAN bus %str_BusName%\n"
        "- Standard measurement OK\n\n"
        "@[std]AU00003_Ende"
    )
    expected = (
        "- Check ignition switch\n"
        "- Verify CAN bus %str_BusName%\n"
        "- Standard measurement OK\n\n"
        "@[std]AU00003_Ende"
    )

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.occurrences_removed == 2
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 12: Parenthesized Keyword Cleanup
# ---------------------------------------------------------------------------
def test_case_12_parenthesized_keyword_removal():
    """Verify removal of keyword inside parentheses cleans empty parens."""
    raw_text = "Turn ignition switch to ON position (Lamborghini)."
    expected = "Turn ignition switch to ON position."

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 13: Text without Target Keyword (No Modification)
# ---------------------------------------------------------------------------
def test_case_13_no_keyword_unmodified():
    """Verify text without target keyword remains untouched."""
    raw_text = "Check battery voltage with multimeter.\n@[std]AU00001_Start"

    res = clean_text(raw_text)
    assert res.modified is False
    assert res.occurrences_removed == 0
    assert res.cleaned_text == raw_text


# ---------------------------------------------------------------------------
# Case 14: Empty, None, or Whitespace Inputs
# ---------------------------------------------------------------------------
def test_case_14_empty_and_whitespace_inputs():
    """Verify graceful handling of empty and whitespace inputs."""
    res_empty = clean_text("")
    assert res_empty.modified is False
    assert res_empty.cleaned_text == ""
    assert res_empty.occurrences_removed == 0


# ---------------------------------------------------------------------------
# Case 15: Rich Text / HTML Formatting Tags Preservation
# ---------------------------------------------------------------------------
def test_case_15_rich_text_html_tags_preserved():
    """Verify rich text XML/HTML formatting tags are preserved bit-for-bit."""
    raw_text = "<b>Lamborghini</b> test: <font color=\"#ff0000\">WARNING</font>"
    expected = "<b></b> test: <font color=\"#ff0000\">WARNING</font>"

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.occurrences_removed == 1
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 16: Dangling Colons and Separators after Keyword Removal
# ---------------------------------------------------------------------------
def test_case_16_dangling_colons_and_punctuation():
    """Verify cleaning of dangling colons and commas left behind."""
    raw_text = "- Lamborghini: Check ECU status."
    expected = "- Check ECU status."

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 17: Multiple Variables and Macros in Single Complex Block
# ---------------------------------------------------------------------------
def test_case_17_complex_diagnostic_block():
    """Verify multi-variable diagnostic instruction with multiple occurrences."""
    raw_text = (
        "Lamborghini diagnostic routine for %str_Bauteil%:\n"
        "1. Lamborghini connect %str_Steuergeraet%.\n"
        "2. Query event memory in Lamborghini module.\n"
        "3. %i_Status% check.\n"
        "@[std]AU00003_Ende"
    )
    expected = (
        "Diagnostic routine for %str_Bauteil%:\n"
        "1. Connect %str_Steuergeraet%.\n"
        "2. Query event memory in module.\n"
        "3. %i_Status% check.\n"
        "@[std]AU00003_Ende"
    )

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.occurrences_removed == 3
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 18: Custom Target Keyword Parameter Override
# ---------------------------------------------------------------------------
def test_case_18_custom_target_keyword_override():
    """Verify cleaning with a custom target keyword parameter."""
    raw_text = "Check the Porsche 911 brake fluid level."
    expected = "Check the 911 brake fluid level."

    cleaner = TextCleaner(target_keyword="Porsche")
    res = cleaner.clean(raw_text)
    assert res.modified is True
    assert res.occurrences_removed == 1
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 19: Pydantic Request/Response Model Serialization
# ---------------------------------------------------------------------------
def test_case_19_pydantic_models_and_conversions():
    """Verify TextCleanRequest and TextCleanResponse integration."""
    req = TextCleanRequest(
        raw_text="- Test Lamborghini item\n@[std]End",
        block_type="MESSAGE",
    )
    assert req.raw_text == "- Test Lamborghini item\n@[std]End"
    assert req.block_type == "MESSAGE"

    res = clean_text(req.raw_text, block_type=req.block_type)
    response_model = res.to_response()

    assert isinstance(response_model, TextCleanResponse)
    assert response_model.modified is True
    assert response_model.occurrences_removed == 1
    assert response_model.cleaned_text == "- Test item\n@[std]End"


# ---------------------------------------------------------------------------
# Case 20: Windows CRLF Line Endings Preservation
# ---------------------------------------------------------------------------
def test_case_20_crlf_line_endings_preserved():
    """Verify CRLF line endings are preserved when cleaning multi-line texts."""
    raw_text = "Line 1: Lamborghini\r\nLine 2: Normal\r\n@[std]AU00003_Ende"
    expected = "Line 1:\r\nLine 2: Normal\r\n@[std]AU00003_Ende"

    res = clean_text(raw_text)
    assert res.modified is True
    assert "\r\n" in res.cleaned_text
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 21: German Umlauts and Compounds
# ---------------------------------------------------------------------------
def test_case_21_german_umlauts_and_compounds():
    """Verify German umlauts and compound word cleaning."""
    raw_text = "Prüfung der Lamborghini-Verkabelung für %str_Steuergeraet% durchführen."
    expected = "Prüfung der Verkabelung für %str_Steuergeraet% durchführen."

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 22: Unicode Curly Apostrophe Possessive Form
# ---------------------------------------------------------------------------
def test_case_22_unicode_curly_apostrophe_possessive():
    """Verify Unicode curly apostrophe (’) in possessive Lamborghini’s."""
    raw_text = "Check the Lamborghini’s high voltage relay."
    expected = "Check the high voltage relay."

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 23: Hyphenated Suffix Compound
# ---------------------------------------------------------------------------
def test_case_23_hyphenated_suffix_compound():
    """Verify suffix compound 'Fahrzeuge-Lamborghini' -> 'Fahrzeuge'."""
    raw_text = "Diagnose für Fahrzeuge-Lamborghini abschließen."
    expected = "Diagnose für Fahrzeuge abschließen."

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 24: TextCleanResult Dictionary and Repr Support
# ---------------------------------------------------------------------------
def test_case_24_result_dict_and_repr():
    """Verify to_dict and repr methods of TextCleanResult."""
    res = clean_text("Lamborghini test %var%", block_type="MESSAGE")
    res_dict = res.to_dict()
    assert res_dict["modified"] is True
    assert res_dict["block_type"] == "MESSAGE"
    assert res_dict["occurrences_removed"] == 1
    assert res_dict["protected_tokens_count"] == 1
    assert "TextCleanResult(" in repr(res)


# ---------------------------------------------------------------------------
# Case 25: Question Block with Selection Numbers
# ---------------------------------------------------------------------------
def test_case_25_question_block_with_selection_syntax():
    """Verify Question block with answer selections (1 = YES / 2 = NO)."""
    raw_text = (
        "Is the Lamborghini CAN line %str_BusName% active?\n"
        "1 = YES\n"
        "2 = NO"
    )
    expected = (
        "Is the CAN line %str_BusName% active?\n"
        "1 = YES\n"
        "2 = NO"
    )

    res = clean_text(raw_text, block_type="QUESTION")
    assert res.modified is True
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 26: Empty / Whitespace Target Keyword Guard
# ---------------------------------------------------------------------------
def test_case_26_empty_or_whitespace_target_keyword():
    """Verify that passing empty or whitespace-only keyword returns raw text unmodified."""
    raw_text = "Standard diagnostic routine for Lamborghini."
    cleaner = TextCleaner(target_keyword="")
    res = cleaner.clean(raw_text, target_keyword="")
    assert res.modified is False
    assert res.cleaned_text == raw_text
    assert res.occurrences_removed == 0

    cleaner_ws = TextCleaner(target_keyword="   ")
    res_ws = cleaner_ws.clean(raw_text, target_keyword="   ")
    assert res_ws.modified is False
    assert res_ws.cleaned_text == raw_text
    assert res_ws.occurrences_removed == 0


# ---------------------------------------------------------------------------
# Case 27: Adjacent Protected Tokens
# ---------------------------------------------------------------------------
def test_case_27_adjacent_protected_tokens():
    """Verify multiple adjacent macros and variables are preserved intact."""
    raw_text = "Check Lamborghini %str_A%%str_B% @[std]Start@[std]End"
    expected = "Check %str_A%%str_B% @[std]Start@[std]End"

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.occurrences_removed == 1
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 28: Mixed Case Variations
# ---------------------------------------------------------------------------
def test_case_28_mixed_case_variations():
    """Verify mixed case matching like 'LaMbOrGhInI' is cleaned."""
    raw_text = "Testing LaMbOrGhInI control module."
    expected = "Testing control module."

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.occurrences_removed == 1
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 29: Hyphenated Compound with Spaces
# ---------------------------------------------------------------------------
def test_case_29_hyphenated_compound_with_spaces():
    """Verify compound with spaces around hyphen 'Lamborghini - Tester'."""
    raw_text = "Verbindung mit Lamborghini - Tester herstellen."
    expected = "Verbindung mit Tester herstellen."

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 30: Nested HTML/XML Formatting Tags
# ---------------------------------------------------------------------------
def test_case_30_nested_html_xml_tags():
    """Verify complex nested HTML formatting with font, bold, color, and break tags."""
    raw_text = "<font color=\"#0000ff\"><b>Lamborghini</b></font><br/>Check %str_ECU%."
    expected = "<font color=\"#0000ff\"><b></b></font><br/>Check %str_ECU%."

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.occurrences_removed == 1
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 31: Various Bullet Styles and Numbering
# ---------------------------------------------------------------------------
def test_case_31_various_bullet_styles():
    """Verify various bullet points (•, *, 1., 2)) capitalize the subsequent word."""
    raw_text = (
        "• Lamborghini check fuse\n"
        "* Lamborghini measure voltage\n"
        "1. Lamborghini start motor\n"
        "2) Lamborghini record values"
    )
    expected = (
        "• Check fuse\n"
        "* Measure voltage\n"
        "1. Start motor\n"
        "2) Record values"
    )

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.occurrences_removed == 4
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 32: Trailing Commas and Punctuation Duplication
# ---------------------------------------------------------------------------
def test_case_32_trailing_commas_and_duplicate_punctuation():
    """Verify duplicate commas and trailing punctuation are properly cleaned."""
    raw_text = "Check Lamborghini, , for errors."
    expected = "Check, for errors."

    res = clean_text(raw_text)
    assert res.modified is True
    assert res.cleaned_text == expected


# ---------------------------------------------------------------------------
# Case 33: Whitespace Only Input
# ---------------------------------------------------------------------------
def test_case_33_whitespace_only_input():
    """Verify whitespace-only string returns unchanged."""
    raw_text = "    \t   "
    res = clean_text(raw_text)
    assert res.modified is False
    assert res.cleaned_text == raw_text
    assert res.occurrences_removed == 0


