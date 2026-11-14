import json
from io import BytesIO
from uuid import uuid4

from conftest import drain, published_job
from pypdf import PdfWriter


def upload(api, job_id, files, key=None):
    manifest = {
        "execution_mode": "mock",
        "items": [
            {"client_item_id": str(index), "filename": file[0]} for index, file in enumerate(files)
        ],
    }
    return api.post(
        f"/api/v1/jobs/{job_id}/resume-batches",
        headers={"Idempotency-Key": key or uuid4().hex},
        data={"manifest": json.dumps(manifest)},
        files=[("files", file) for file in files],
    )


def test_mixed_files_isolation_and_single_item_replacement(api, runtime):
    job_id, _ = published_job(api, runtime)
    writer = PdfWriter()
    writer.add_blank_page(width=200, height=200)
    stream = BytesIO()
    writer.write(stream)
    response = upload(
        api,
        job_id,
        [
            ("valid.txt", b"years_experience: 5", "text/plain"),
            ("unsupported.png", b"image", "image/png"),
            ("scan.pdf", stream.getvalue(), "application/pdf"),
        ],
    )
    assert response.status_code == 202, response.text
    received = response.json()
    assert [item["disposition"] for item in received["items"]] == ["accepted", "invalid", "invalid"]
    assert received["items"][2]["error"]["code"] == "PDF_TEXT_UNAVAILABLE"
    drain(runtime)
    batch = api.get(f"/api/v1/batches/{received['batch_id']}").json()
    assert batch["status"] == "partial_failed"
    assert batch["counts"]["total"] == sum(v for k, v in batch["counts"].items() if k != "total")
    item_id = received["items"][1]["item_id"]
    replacement = api.post(
        f"/api/v1/batches/{received['batch_id']}/items/{item_id}/replace",
        headers={"Idempotency-Key": uuid4().hex},
        data={"expected_revision": "1"},
        files={"file": ("fixed.txt", b"years_experience: 4", "text/plain")},
    )
    assert replacement.status_code == 201, replacement.text
    assert replacement.json()["replaces_item_id"] == item_id
    drain(runtime)
    batch = api.get(f"/api/v1/batches/{received['batch_id']}").json()
    assert batch["counts"]["total"] == 3
    assert batch["counts"]["completed"] == 2 and batch["counts"]["failed"] == 1
    assert len(api.get(f"/api/v1/jobs/{job_id}/applications").json()["items"]) == 2


def test_renamed_file_duplicate_and_all_invalid_batch(api, runtime):
    job_id, _ = published_job(api, runtime)
    first = upload(api, job_id, [("one.txt", b"years_experience: 5", "text/plain")]).json()
    drain(runtime)
    second = upload(api, job_id, [("two.txt", b"years_experience: 5", "text/plain")]).json()
    assert second["items"][0]["disposition"] == "duplicate"
    assert second["items"][0]["application_id"] == first["items"][0]["application_id"]
    invalid = upload(api, job_id, [("fake.pdf", b"not a pdf", "application/pdf")]).json()
    batch = api.get(f"/api/v1/batches/{invalid['batch_id']}").json()
    assert batch["status"] == "failed" and batch["counts"]["failed"] == 1


def test_text_pdf_is_actually_extracted_and_screened(api, runtime):
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    job_id, _ = published_job(api, runtime)
    writer = PdfWriter()
    page = writer.add_blank_page(width=300, height=200)
    font = DictionaryObject(
        {
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        }
    )
    page[NameObject("/Resources")] = DictionaryObject(
        {NameObject("/Font"): DictionaryObject({NameObject("/F1"): font})}
    )
    contents = DecodedStreamObject()
    contents.set_data(b"BT /F1 12 Tf 30 100 Td (years_experience: 5) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(contents)
    stream = BytesIO()
    writer.write(stream)
    response = upload(api, job_id, [("text.pdf", stream.getvalue(), "application/pdf")])
    assert response.status_code == 202 and response.json()["items"][0]["disposition"] == "accepted"
    drain(runtime)
    app_id = response.json()["items"][0]["application_id"]
    assert api.get(f"/api/v1/applications/{app_id}").json()["screening_result"] == "passed"


def test_unexpected_pdf_parser_failure_does_not_rollback_other_items(api, runtime, monkeypatch):
    job_id, _ = published_job(api, runtime)

    def broken_pdf(_):
        raise OSError("fixture malformed document")

    monkeypatch.setattr("app.modules.intake.analysis.PdfReader", broken_pdf)
    response = upload(
        api,
        job_id,
        [
            ("good.txt", b"years_experience: 5", "text/plain"),
            ("broken.pdf", b"%PDF-fixture", "application/pdf"),
        ],
    )
    assert response.status_code == 202
    assert [item["disposition"] for item in response.json()["items"]] == ["accepted", "invalid"]
    assert response.json()["items"][1]["error"]["code"] == "PDF_TEXT_UNAVAILABLE"
    drain(runtime)
    assert (
        api.get(f"/api/v1/jobs/{job_id}/applications").json()["items"][0]["screening_result"]
        == "passed"
    )
