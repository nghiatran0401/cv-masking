"""Unit tests for optional-content dictionary and visibility-expression parsing."""

import pytest

from cv_masking.adapters.pdf.content import ContentError
from cv_masking.adapters.pdf.optional_content import (
    _property_entries,
    parse_pdf_array,
    parse_pdf_dict,
)


def test_parse_named_and_inline_property_entries() -> None:
    entries = parse_pdf_dict("<</MC0 8 0 R/MC1<</Type/OCMD/OCGs[7 0 R]/P/AllOn>>>>")
    assert entries["MC0"].strip() == "8 0 R"
    assert entries["MC1"].startswith("<<")
    assert "/AllOn" in entries["MC1"]


def test_parse_visibility_expression_with_nested_array() -> None:
    expr = parse_pdf_array("[/Or 5 0 R[/Not 5 0 R]]")
    assert expr[0] == "/Or"
    assert expr[1] == 5
    assert expr[2] == ["/Not", 5]


def test_unterminated_visibility_expression_fails_closed() -> None:
    with pytest.raises(ContentError):
        parse_pdf_array("[/And")


def test_unsupported_property_value_is_marked_hidden() -> None:
    found = _property_entries("<</MC0 /All>>")
    assert found[b"MC0"] == ("hidden", "")
