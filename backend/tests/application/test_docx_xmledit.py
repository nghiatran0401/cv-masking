"""Stage 10b: byte-level XML edits keep every byte that is not edited."""

import pytest

from cv_masking.adapters.docx.text import MalformedXmlError
from cv_masking.adapters.docx.xmledit import XmlEditError, XmlPart

W = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
_HEAD = b'<?xml version="1.0" encoding="UTF-8"?>\n'


def _part(body: bytes, prefix: bytes = b"w") -> XmlPart:
    return XmlPart(
        _HEAD
        + b"<"
        + prefix
        + b":document xmlns:"
        + prefix
        + b'="'
        + W.encode()
        + b'">'
        + body
        + b"</"
        + prefix
        + b":document>"
    )


def _find(part: XmlPart, local: str) -> list:  # type: ignore[type-arg]
    return [element for element in part.root.iter() if element.tag == f"{{{W}}}{local}"]


def test_an_unedited_part_is_returned_unchanged() -> None:
    data = (
        _HEAD
        + f'<w:document xmlns:w="{W}"><!-- note -->'.encode()
        + b"<w:t a='x>y'>a &amp; b</w:t></w:document>"
    )
    part = XmlPart(data)
    assert not part.changed
    assert part.serialize() is data


def test_delete_unwrap_and_text_edits_touch_only_their_bytes() -> None:
    part = _part(
        b'<w:p><w:ins w:id="1"><w:r><w:t>keep</w:t></w:r></w:ins><w:del><w:r/></w:del></w:p>'
    )
    part.unwrap(_find(part, "ins")[0])
    part.delete(_find(part, "del")[0])
    part.set_text(_find(part, "t")[0], "[NAME] & <x>")
    assert part.serialize() == (
        _HEAD
        + f'<w:document xmlns:w="{W}">'.encode()
        + b"<w:p><w:r><w:t>[NAME] &amp; &lt;x&gt;</w:t></w:r></w:p>"
        + b"</w:document>"
    )


def test_attributes_are_dropped_by_namespace_not_prefix() -> None:
    part = _part(b'<x:p x:rsidR="00AA" x:keep="1" rsidR="plain" title="t"/>', prefix=b"x")
    element = _find(part, "p")[0]
    part.drop_attributes(element, {f"{{{W}}}rsidR", "title"})
    assert b'<x:p x:keep="1" rsidR="plain"/>' in part.serialize()


def test_attribute_values_with_angle_brackets_and_quotes_are_kept() -> None:
    part = _part(b'<w:p w:a=\'1>2\' w:b="it\'s" w:rsidR="00"><w:t>x</w:t></w:p>')
    part.drop_attributes(_find(part, "p")[0], {f"{{{W}}}rsidR"})
    part.set_text(_find(part, "t")[0], "y")
    assert b"<w:p w:a='1>2' w:b=\"it's\"><w:t>y</w:t></w:p>" in part.serialize()


def test_a_self_closing_text_element_gets_content() -> None:
    part = _part(b"<w:r><w:t/></w:r>")
    part.set_text(_find(part, "t")[0], " [EMAIL] ")
    assert b'<w:r><w:t xml:space="preserve"> [EMAIL] </w:t></w:r>' in part.serialize()


def test_edits_inside_a_deleted_element_are_dropped() -> None:
    part = _part(b"<w:p><w:r><w:t>gone</w:t></w:r></w:p><w:p/>")
    part.set_text(_find(part, "t")[0], "x")
    part.delete(_find(part, "p")[0])
    assert part.serialize().endswith(f'<w:document xmlns:w="{W}"><w:p/></w:document>'.encode())


def test_unwrapping_a_self_closing_element_removes_it() -> None:
    part = _part(b"<w:p><w:ins/><w:r/></w:p>")
    part.unwrap(_find(part, "ins")[0])
    assert b"<w:p><w:r/></w:p>" in part.serialize()


def test_only_text_elements_can_get_new_text() -> None:
    part = _part(b"<w:r><w:rPr/><w:t>x</w:t></w:r>")
    with pytest.raises(XmlEditError):
        part.set_text(_find(part, "rPr")[0], "y")


def test_an_element_from_another_part_is_refused() -> None:
    first, second = _part(b"<w:p/>"), _part(b"<w:p/>")
    with pytest.raises(XmlEditError):
        first.delete(_find(second, "p")[0])


@pytest.mark.parametrize(
    "data",
    [
        b'<?xml version="1.0" encoding="UTF-16"?><a/>',
        b'<?xml version="1.0" encoding="ISO-8859-1"?><a/>',
        "<a/>".encode("utf-16"),
    ],
    ids=["declared-utf16", "declared-latin1", "utf16-bom"],
)
def test_non_utf8_parts_are_refused(data: bytes) -> None:
    with pytest.raises((XmlEditError, MalformedXmlError)):
        XmlPart(data)


def test_dtds_are_refused() -> None:
    data = b'<?xml version="1.0"?><!DOCTYPE a [<!ENTITY x "y">]><a>&x;</a>'
    with pytest.raises((XmlEditError, MalformedXmlError)):
        XmlPart(data)


def test_a_bom_does_not_shift_offsets() -> None:
    part = XmlPart(
        b"\xef\xbb\xbf" + _HEAD + f'<w:document xmlns:w="{W}"><w:t>a</w:t></w:document>'.encode()
    )
    part.set_text(_find(part, "t")[0], "b")
    assert part.serialize().endswith(b"<w:t>b</w:t></w:document>")
