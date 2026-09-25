"""Tiny synthetic PDF and DOCX bytes generated at test time. No real documents."""

import io
import zipfile

SYNTHETIC_PDF = b"%PDF-1.7\n% synthetic test page\n"
CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="{main}"/>
</Types>
"""
DOCUMENT_XML = (
    b'<?xml version="1.0" encoding="UTF-8"?>'
    b'<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    b"<w:body><w:p><w:r><w:t>synthetic</w:t></w:r></w:p></w:body></w:document>"
)
DOCX_MAIN = "application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"
MACRO_MAIN = "application/vnd.ms-word.document.macroEnabled.main+xml"


def synthetic_docx(*, macro: bool = False) -> bytes:
    buffer = io.BytesIO()
    main = MACRO_MAIN if macro else DOCX_MAIN
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", CONTENT_TYPES.format(main=main))
        archive.writestr("word/document.xml", DOCUMENT_XML)
        if macro:
            archive.writestr("word/vbaProject.bin", b"synthetic-vba")
    return buffer.getvalue()
