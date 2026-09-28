"""Stage 10: the hidden optional-content filter works on raw content-stream syntax."""

import pytest

from cv_masking.adapters.pdf.content import ContentError, decode_name, strip_hidden


def _strip(data: bytes, *, hidden: set[bytes] | None = None) -> tuple[bytes, int]:
    names = hidden if hidden is not None else {b"Off"}
    return strip_hidden(
        data, hidden_property=names.__contains__, hidden_xobject={b"HiddenIm"}.__contains__
    )


def test_visible_content_is_untouched() -> None:
    data = b"q BT /F1 11 Tf (Visible) Tj ET Q 0 0 1 1 re f"
    assert _strip(data) == (data, 0)


def test_visible_oc_markers_are_unwrapped() -> None:
    cleaned, removed = _strip(b"q BT /F1 11 Tf (Visible) Tj ET Q /OC /On BDC 0 0 1 1 re f EMC")
    assert removed == 2
    assert b"(Visible) Tj" in cleaned
    assert b"0 0 1 1 re f" in cleaned
    assert b"BDC" not in cleaned
    assert b"EMC" not in cleaned


def test_hidden_painting_is_removed_and_state_operators_kept() -> None:
    data = (
        b"/OC /Off BDC q 1 0 0 1 5 5 cm BT /F1 9 Tf (secret) Tj [(a) 5 (b)] TJ ET"
        b" 0 0 5 5 re f Q EMC"
    )
    cleaned, removed = _strip(data)
    assert removed == 5
    assert b"secret" not in cleaned
    assert b"(a)" not in cleaned
    for kept in (b"q", b"cm", b"BT", b"Tf", b"ET", b"re", b" n ", b"Q"):
        assert kept in cleaned
    assert b"BDC" not in cleaned
    assert b"EMC" not in cleaned


def test_quote_operators_keep_their_line_movement() -> None:
    cleaned, removed = _strip(b"/OC /Off BDC BT (one) ' 2 3 (two) \" ET EMC")
    assert removed == 4
    assert b"one" not in cleaned
    assert b"two" not in cleaned
    assert b" T* " in cleaned
    assert b" 2 Tw 3 Tc T* " in cleaned


def test_nested_blocks_inside_a_hidden_block_stay_hidden() -> None:
    data = b"/OC /Off BDC /Span <</ActualText (x)>> BDC (deep) Tj EMC EMC (shown) Tj"
    cleaned, removed = _strip(data)
    assert removed == 3
    assert b"deep" not in cleaned
    assert b"(shown) Tj" in cleaned
    assert b"/Span" in cleaned


def test_hidden_xobjects_and_inline_images_are_removed() -> None:
    data = b"/HiddenIm Do /VisibleIm Do /OC /Off BDC BI /W 1 /H 1 ID \x00EMC\xff EI EMC"
    cleaned, removed = _strip(data)
    assert removed == 4
    assert b"/HiddenIm" not in cleaned
    assert b"/VisibleIm Do" in cleaned
    assert b"EMC\xff" not in cleaned
    assert b"BDC" not in cleaned


def test_strings_with_parentheses_and_escapes_are_one_operand() -> None:
    data = b"/OC /Off BDC (a (nested) \\) EMC here) Tj EMC (after) Tj"
    cleaned, removed = _strip(data)
    assert removed == 3
    assert cleaned.endswith(b"(after) Tj")


def test_escaped_names_resolve() -> None:
    assert decode_name(b"Layer#20One") == b"Layer One"
    cleaned, removed = _strip(b"/OC /Layer#20One BDC (x) Tj EMC", hidden={b"Layer One"})
    assert removed == 3
    assert b"(x)" not in cleaned


@pytest.mark.parametrize(
    "data",
    [
        b"EMC",
        b"/OC /Off BDC (x) Tj",
        b"(unterminated",
        b"<abc",
        b"/OC BDC EMC",
        b"BI /W 1 ID \x00\x00",
        b"[ (a) Tj ]",
        b"} ",
        b"1 2",
    ],
    ids=[
        "lone-emc",
        "open-bdc",
        "string",
        "hex",
        "bdc-arity",
        "inline-image",
        "operator-in-array",
        "brace",
        "trailing",
    ],
)
def test_malformed_streams_fail_closed(data: bytes) -> None:
    with pytest.raises(ContentError):
        _strip(data)


def test_an_unknown_layer_name_fails_closed() -> None:
    def unknown(name: bytes) -> bool:
        raise ContentError("unknown optional-content name")

    with pytest.raises(ContentError):
        strip_hidden(
            b"/OC /Other BDC EMC", hidden_property=unknown, hidden_xobject=set().__contains__
        )


def test_inline_oc_dictionary_without_a_callback_fails_closed() -> None:
    with pytest.raises(ContentError, match="inline optional-content dictionary"):
        _strip(b"/OC << /Type /OCMD /P /AllOn >> BDC (secret) Tj EMC")


def test_inline_oc_dictionary_on_bdc_is_hidden() -> None:
    cleaned, removed = strip_hidden(
        b"/OC << /Type /OCMD /OCGs [10 0 R] /P /AllOn >> BDC (secret) Tj EMC (shown) Tj",
        hidden_property=set().__contains__,
        hidden_xobject=set().__contains__,
        hidden_inline=lambda _raw: True,
    )
    assert removed == 3
    assert b"secret" not in cleaned
    assert b"(shown) Tj" in cleaned
