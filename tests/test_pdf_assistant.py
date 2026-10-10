import asyncio
import io
import json
import pytest
import httpx
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
from app.pdf_documents import extract_pdf, process_pdf, PDFContext
from app.assistant_context import AssistantRequest


def pdf_bytes(texts, encrypted=False):
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        font = DictionaryObject({NameObject("/Type"): NameObject("/Font"), NameObject("/Subtype"): NameObject("/Type1"), NameObject("/BaseFont"): NameObject("/Helvetica")})
        page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 40 700 Td ({escaped}) Tj ET".encode())
        page[NameObject("/Contents")] = writer._add_object(stream)
    if encrypted: writer.encrypt("secret")
    output = io.BytesIO(); writer.write(output); return output.getvalue()


def test_extraction_reads_late_pages_in_large_document_and_preserves_page_numbers(tmp_path):
    path = tmp_path / "large.pdf"
    path.write_bytes(pdf_bytes([f"Introduction on page {i+1}." for i in range(299)] + ["Quantum widgets lose photons at 42 units per hour."]))
    result = extract_pdf(str(path))
    assert result["page_count"] == 300
    assert "42 units" in result["pages"][-1]["text"]
    assert result["pages"][-1]["page"] == 300


def test_isolated_extraction_and_unreadable_errors(tmp_path):
    path = tmp_path / "document.pdf"; output = tmp_path / "result.json"
    path.write_bytes(pdf_bytes(["A readable sentence."]))
    assert "readable sentence" in process_pdf(str(path), str(output))["pages"][0]["text"]
    path.write_bytes(pdf_bytes(["Encrypted text"], encrypted=True))
    with pytest.raises(ValueError, match="password-protected"): extract_pdf(str(path))
    path.write_bytes(pdf_bytes([""]))
    with pytest.raises(ValueError, match="No readable text"): extract_pdf(str(path))
    path.write_bytes(b"%PDF-1.7 broken")
    with pytest.raises(ValueError, match="cannot be processed"): extract_pdf(str(path))


def test_pdf_context_bounds_and_missing_evidence_skip_generation(monkeypatch):
    import server.api.research as research
    with pytest.raises(ValueError): PDFContext(document_id="d", name="test.pdf", page_count=1, chunks=[{"page":2,"text":"invalid"}])
    with pytest.raises(ValueError): PDFContext(document_id="d", name="test.pdf", page_count=1, chunks=[{"page":1,"text":"text"}] * 9)
    monkeypatch.setattr(research, "Settings", lambda: pytest.fail("No generation call is needed for missing PDF evidence"))
    request = AssistantRequest(message="What is the missing manufacturing cost?", pdf_context={"document_id":"d", "name":"test.pdf", "page_count":1,"chunks":[]})
    async def run():
        events = [event async for event in research._hybrid_events(research.ResearchJob(), request)]
        answer = events[-1][1]
        assert "could not find" in answer.answer
        assert not answer.citations
    asyncio.run(run())


def test_pdf_upload_endpoint_and_invalid_file(monkeypatch):
    monkeypatch.setattr('server.workspace.configured', lambda: False)
    from server.main import app
    async def run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as client:
            response = await client.post("/api/assistant/pdf?name=sample.pdf", content=pdf_bytes(["Evidence is grounded in the document."]), headers={"Content-Type":"application/pdf"})
            assert response.status_code == 200, response.text
            assert response.json()["name"] == "sample.pdf"
            assert "Evidence" in response.json()["pages"][0]["text"]
            invalid = await client.post("/api/assistant/pdf?name=fake.pdf", content=b"not pdf")
            assert invalid.status_code == 400
    asyncio.run(run())
