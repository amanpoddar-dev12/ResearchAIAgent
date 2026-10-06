"""Isolated, bounded PDF text extraction; uploaded files are never retained."""
import json
import subprocess
import sys
from pathlib import Path
from pydantic import BaseModel, Field, model_validator
MAX_UPLOAD_BYTES = 25 * 1024 * 1024
MAX_PAGES = 2000
MAX_TEXT = 8_000_000
class PDFChunk(BaseModel):
    page: int = Field(ge=1, le=MAX_PAGES)
    text: str = Field(min_length=1, max_length=2000)
class PDFContext(BaseModel):
    document_id: str = Field(min_length=1, max_length=80)
    name: str = Field(min_length=1, max_length=200)
    page_count: int = Field(ge=1, le=MAX_PAGES)
    chunks: list[PDFChunk] = Field(default_factory=list, max_length=8)
    @model_validator(mode="after")
    def pages_exist(self):
        if any(chunk.page > self.page_count for chunk in self.chunks):
            raise ValueError("A PDF citation refers to a page outside the document")
        return self

def extract_pdf(path: str) -> dict:
    from pypdf import PdfReader, Configuration
    # These limits are local to the disposable extraction process.
    for name in ["zlib_maximum_output_length", "lzw_maximum_output_length", "run_length_maximum_output_length", "jbig2_maximum_output_length", "array_based_stream_maximum_output_length", "maximum_declared_stream_length"]:
        setattr(Configuration, name, 20_000_000)
    try:
        reader = PdfReader(path, strict=False)
        if reader.is_encrypted:
            raise ValueError("This PDF is password-protected. Upload an unencrypted copy.")
        count = len(reader.pages)
        if not count or count > MAX_PAGES:
            raise ValueError(f"PDFs must contain between 1 and {MAX_PAGES} pages.")
        pages, empty, length = [], [], 0
        for number, page in enumerate(reader.pages, 1):
            contents = page.get_contents()
            if contents and len(contents.get_data()) > 20_000_000:
                raise ValueError(f"Page {number} is too complex to process safely. Try splitting the PDF.")
            text = (page.extract_text() or "").replace("\x00", "").strip()
            length += len(text)
            if length > MAX_TEXT:
                raise ValueError("The PDF contains too much extracted text. Split it into smaller documents.")
            if text: pages.append({"page": number, "text": text})
            else: empty.append(number)
        if not pages:
            raise ValueError("No readable text was found. This may be a scanned PDF; upload a searchable/OCR version.")
        warnings = [f"{len(empty)} pages have no extractable text and cannot be used as evidence (possibly scanned pages)."] if empty else []
        return {"page_count": count, "pages": pages, "warnings": warnings}
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError("This PDF cannot be processed. It may be damaged or use unsupported encoding. Try another searchable PDF.") from exc

def process_pdf(path: str, result_path: str) -> dict:
    try:
        subprocess.run([sys.executable, "-m", "app.pdf_documents", path, result_path], timeout=90, check=True, capture_output=True)
    except subprocess.TimeoutExpired as exc:
        raise ValueError("PDF processing timed out. Split the document and try again.") from exc
    except subprocess.CalledProcessError as exc:
        raise ValueError("The PDF could not be processed safely. Try a smaller searchable PDF.") from exc
    result = json.loads(Path(result_path).read_text(encoding="utf-8"))
    if result.get("error"): raise ValueError(result["error"])
    return result

if __name__ == "__main__":
    try: result = extract_pdf(sys.argv[1])
    except ValueError as exc: result = {"error": str(exc)}
    Path(sys.argv[2]).write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")
