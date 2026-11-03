"""Tiny deterministic Chinese PDFs; no network or document fixtures containing private data."""

import io
from pypdf import PdfWriter
from pypdf.generic import (
    DictionaryObject,
    NameObject,
    ArrayObject,
    NumberObject,
    DecodedStreamObject,
    TextStringObject,
)


def pdf(pages=None, encrypted=False, blank=False):
    writer = PdfWriter()
    for text in pages or [
        "青禾项目第一阶段预算为三百万元。主要工作包括城市绿化与社区公共空间改造。"
    ]:
        page = writer.add_blank_page(width=595, height=842)
        if blank:
            continue
        cid = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/CIDFontType0"),
                NameObject("/BaseFont"): NameObject("/STSong-Light"),
                NameObject("/CIDSystemInfo"): DictionaryObject(
                    {
                        NameObject("/Registry"): TextStringObject("Adobe"),
                        NameObject("/Ordering"): TextStringObject("GB1"),
                        NameObject("/Supplement"): NumberObject(4),
                    }
                ),
            }
        )
        font = DictionaryObject(
            {
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type0"),
                NameObject("/BaseFont"): NameObject("/STSong-Light"),
                NameObject("/Encoding"): NameObject("/UniGB-UCS2-H"),
                NameObject("/DescendantFonts"): ArrayObject([writer._add_object(cid)]),
            }
        )
        page[NameObject("/Resources")] = DictionaryObject(
            {
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}
                )
            }
        )
        lines = [text[i : i + 28] for i in range(0, len(text), 28)]
        stream = DecodedStreamObject()
        stream.set_data(
            (
                "BT /F1 14 Tf 50 780 Td 24 TL "
                + " T* ".join(
                    "<" + line.encode("utf-16-be").hex() + "> Tj" for line in lines
                )
                + " ET"
            ).encode()
        )
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted:
        writer.encrypt("test-password")
    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()
