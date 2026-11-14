from pathlib import Path

import olefile
import pytest
from conftest import post

from app.core.config import Settings
from app.core.errors import DomainError
from app.modules.intake.analysis import parse_file

FIXTURE = Path(__file__).parent / "fixtures" / "legacy-word.doc"


def test_word_97_chinese_text_is_extracted_without_office():
    text = parse_file("resume.doc", "application/msword", FIXTURE.read_bytes(), Settings())
    assert "虚构候选人：测试甲" in text
    assert "工作年限：3" in text
    assert "Java、SQL" in text
    assert "English résumé" in text


def test_mixed_talent_import_accepts_doc_and_isolates_invalid_file(api):
    import json
    from uuid import uuid4

    files = [
        ("legacy.doc", FIXTURE.read_bytes(), "application/msword"),
        ("broken.doc", b"not a Word file", "application/msword"),
    ]
    response = api.post(
        "/api/v1/talent-imports",
        headers={"Idempotency-Key": uuid4().hex},
        data={
            "manifest": json.dumps(
                {
                    "execution_mode": "mock",
                    "items": [
                        {"client_item_id": str(i), "filename": f[0]} for i, f in enumerate(files)
                    ],
                }
            )
        },
        files=[("files", f) for f in files],
    )
    assert response.status_code == 202
    good, bad = response.json()["items"]
    assert good["disposition"] == "accepted"
    assert bad["disposition"] == "invalid"
    assert bad["error_code"] == "DOCUMENT_TEXT_UNAVAILABLE"
    replay = post(
        api,
        "/talent-imports",
        {
            "execution_mode": "mock",
            "items": [
                {"client_item_id": "text", "name": "separate.txt", "text": "职位：Java 工程师"}
            ],
        },
        expected=202,
    )
    assert replay["items"][0]["disposition"] == "accepted"


@pytest.mark.parametrize("kind", ["encrypted", "truncated", "bad_piece_offset"])
def test_invalid_legacy_word_fails_closed(tmp_path, kind):
    target = tmp_path / "damaged.doc"
    data = FIXTURE.read_bytes()
    target.write_bytes(data)
    if kind == "truncated":
        target.write_bytes(data[:600])
    else:
        with olefile.OleFileIO(target, write_mode=True) as document:
            word = bytearray(document.openstream("WordDocument").read())
            if kind == "encrypted":
                word[11] |= 1
            else:
                # fcClx in a Word 97 FIB: the table must never be read out of bounds.
                word[0x1A2:0x1A6] = b"\xff\xff\xff\xff"
            document.write_stream("WordDocument", bytes(word))
    with pytest.raises(DomainError) as error:
        parse_file("invalid.doc", "application/octet-stream", target.read_bytes(), Settings())
    assert error.value.code == "DOCUMENT_TEXT_UNAVAILABLE"
