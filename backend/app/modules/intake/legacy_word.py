"""Read the main text of Word 97--2003 files without executing Office or macros.

The FIB and PlcPcd layouts follow MS-DOC sections 2.5.1 and 2.8.35. Unsupported,
encrypted and damaged documents fail closed; bytes are never guessed as prose.
"""

import re
import struct
from io import BytesIO

import olefile

from app.core.errors import DomainError

MAX_STREAM_BYTES = 20_000_000


def _u16(data, offset):
    return struct.unpack_from("<H", data, offset)[0]


def _u32(data, offset):
    return struct.unpack_from("<I", data, offset)[0]


def _main_text(word, table):
    if _u16(word, 0) != 0xA5EC or _u16(word, 2) < 0x00C1:
        raise ValueError("Unsupported Word format")
    flags = _u16(word, 10)
    if flags & (0x0100 | 0x8000):
        raise ValueError("Encrypted Word file")
    offset = 32
    offset += 2 + _u16(word, offset) * 2
    long_count = _u16(word, offset)
    if long_count < 4:
        raise ValueError("Incomplete FIB")
    text_length = _u32(word, offset + 2 + 3 * 4)
    offset += 2 + long_count * 4
    pair_count = _u16(word, offset)
    if pair_count <= 33 or not 0 < text_length <= MAX_STREAM_BYTES:
        raise ValueError("Missing main text")
    clx_offset, clx_length = struct.unpack_from("<II", word, offset + 2 + 33 * 8)
    if clx_offset + clx_length > len(table):
        raise ValueError("Truncated CLX")
    clx = table[clx_offset : clx_offset + clx_length]
    offset = 0
    while offset < len(clx) and clx[offset] == 1:
        offset += 3 + _u16(clx, offset + 1)
    if offset >= len(clx) or clx[offset] != 2:
        raise ValueError("Missing piece table")
    size = _u32(clx, offset + 1)
    pieces = clx[offset + 5 : offset + 5 + size]
    if len(pieces) != size or size < 16 or (size - 4) % 12:
        raise ValueError("Invalid piece table")
    count = (size - 4) // 12
    if _u32(pieces, 0) != 0 or _u32(pieces, count * 4) < text_length:
        raise ValueError("Incomplete main text")
    result = []
    previous = 0
    for index in range(count):
        start, end = struct.unpack_from("<II", pieces, index * 4)
        if start != previous or end < start:
            raise ValueError("Invalid character ranges")
        previous = end
        if start >= text_length:
            break
        length = min(end, text_length) - start
        fc = _u32(pieces, (count + 1) * 4 + index * 8 + 2)
        compressed = bool(fc & 0x40000000)
        position = fc & 0x3FFFFFFF
        if compressed:
            position //= 2
        byte_length = length * (1 if compressed else 2)
        if position + byte_length > len(word):
            raise ValueError("Truncated text piece")
        result.append(
            word[position : position + byte_length].decode(
                "cp1252" if compressed else "utf-16-le", errors="strict"
            )
        )
    text = "".join(result)
    # Field instructions can contain private paths; retain the displayed result only.
    while "\x13" in text:
        cleaned = re.sub(r"\x13[^\x13\x14\x15]*(?:\x14([^\x13\x15]*))?\x15", r"\1", text)
        if cleaned == text:
            raise ValueError("Unbalanced Word field")
        text = cleaned
    text = text.replace("\r", "\n").replace("\x07", "\t").replace("\x0b", "\n")
    return re.sub(r"[\x00-\x08\x0c\x0e-\x1f]", "", text).strip()


def extract_legacy_word(data: bytes) -> str:
    try:
        with olefile.OleFileIO(BytesIO(data)) as document:
            if document.get_size("WordDocument") > MAX_STREAM_BYTES:
                raise ValueError("Word stream too large")
            flags = _u16(document.openstream("WordDocument").read(32), 10)
            table_name = "1Table" if flags & 0x0200 else "0Table"
            if any(
                document.get_size(name) > MAX_STREAM_BYTES for name in ("WordDocument", table_name)
            ):
                raise ValueError("Word stream too large")
            text = _main_text(
                document.openstream("WordDocument").read(), document.openstream(table_name).read()
            )
            if not text:
                raise ValueError("No readable main text")
            if document.exists("ObjectPool"):
                text += "\n[[UNREADABLE_EMBEDDED_CONTENT]]"
            return text
    except (OSError, ValueError, KeyError, struct.error, UnicodeError, IndexError) as exc:
        raise DomainError(
            "DOCUMENT_TEXT_UNAVAILABLE", "旧版 Word 无法可靠提取文本，请另存为 DOCX 或文本 PDF", 422
        ) from exc
