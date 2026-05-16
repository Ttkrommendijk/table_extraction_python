import base64
import binascii
import io
import json
import os
import re
from typing import Any

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from pypdf import PdfReader, PdfWriter

from main import build_klippa_result

DATA_URI_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.*)$", re.DOTALL)


class DocumentItem(BaseModel):
    # Optional JSON body mode, kept for compatibility.
    # The main test flow should use multipart/form-data with inputFile.
    data: Any


class ExtractRequest(BaseModel):
    organisation_document_id: int
    # Preferred JSON equivalent of multipart inputFile.
    # Accepts a JSON object, JSON string, or base64 encoded JSON string.
    inputFile: Any | None = None
    # Backwards-compatible n8n/webhook shape.
    document_array: list[DocumentItem] = Field(default_factory=list)


app = FastAPI(
    title="Table Extraction API",
    version="1.3.0",
)

load_dotenv()


def validate_api_key(x_api_key: str | None = Header(default=None)) -> None:
    api_key = os.getenv("API_KEY")

    if not api_key:
        raise HTTPException(
            status_code=500,
            detail="API_KEY environment variable is not configured",
        )

    if x_api_key != api_key:
        raise HTTPException(
            status_code=401,
            detail="Invalid API key",
        )


@app.get("/")
def healthcheck() -> dict[str, str]:
    return {"status": "running"}


@app.post("/pdf/extract-pages")
@app.post("/pdf/extract_pages")
async def extract_pdf_pages(
    inputFile: UploadFile = File(...),
    page_range: str = Form(...),
    _: None = Depends(validate_api_key),
) -> StreamingResponse:
    """Return a new PDF containing only the requested 1-based page range.

    Example:
      inputFile: source.pdf
      page_range: 2-3

    Result:
      a 2-page PDF containing original pages 2 and 3.
      In the returned PDF they are naturally pages 1 and 2.
    """

    filename = inputFile.filename or "input.pdf"
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=415,
            detail="inputFile must be a PDF file",
        )

    raw_pdf = await inputFile.read()
    if not raw_pdf:
        raise HTTPException(
            status_code=400,
            detail="inputFile cannot be empty",
        )

    try:
        reader = PdfReader(io.BytesIO(raw_pdf))
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"inputFile is not a valid PDF: {exc}",
        ) from exc

    total_pages = len(reader.pages)
    page_indexes = _parse_page_range(page_range, total_pages)

    writer = PdfWriter()
    for page_index in page_indexes:
        writer.add_page(reader.pages[page_index])

    output = io.BytesIO()
    writer.write(output)
    output.seek(0)

    output_filename = _build_extracted_pdf_filename(filename, page_range)

    return StreamingResponse(
        output,
        media_type="application/pdf",
        headers={
            "Content-Disposition": f'attachment; filename="{output_filename}"',
        },
    )


@app.post("/extract")
async def extract(
    inputFile: UploadFile = File(...),
    organisation_document_id: int = Form(...),
    _: None = Depends(validate_api_key),
) -> list[dict[str, Any]]:
    """Extract tables from an uploaded OCRParse JSON file.

    Multipart input:
      inputFile: OCRParse JSON file
      organisation_document_id: 121
    """

    raw_bytes = await inputFile.read()
    ocrparse_json = _load_ocrparse_json_from_bytes(
        raw_bytes, inputFile.filename or "inputFile"
    )
    return _build_api_response(organisation_document_id, [ocrparse_json])


@app.post("/extract/json")
def extract_json(
    payload: ExtractRequest,
    _: None = Depends(validate_api_key),
) -> list[dict[str, Any]]:
    """Extract tables from OCRParse JSON sent in a JSON body.

    Preferred JSON input mirrors /extract:
      {
        "organisation_document_id": 121,
        "inputFile": { ... OCRParse JSON ... }
      }

    Backwards-compatible input is also accepted:
      {
        "organisation_document_id": 121,
        "document_array": [{"data": { ... OCRParse JSON ... }}]
      }
    """

    documents: list[Any] = []

    if payload.inputFile is not None:
        documents.append(payload.inputFile)

    documents.extend(document.data for document in payload.document_array)

    if not documents:
        raise HTTPException(
            status_code=400,
            detail="Provide inputFile or document_array with at least one document",
        )

    ocrparse_documents = [_load_ocrparse_json(document) for document in documents]
    return _build_api_response(payload.organisation_document_id, ocrparse_documents)


@app.post("/extract/ocrparse")
def extract_ocrparse(
    payload: dict[str, Any],
    _: None = Depends(validate_api_key),
) -> dict[str, Any]:
    """Developer helper endpoint for direct OCRParse JSON testing."""

    return build_klippa_result(payload)


def _parse_page_range(page_range: str, total_pages: int) -> list[int]:
    """Parse a 1-based page range into 0-based page indexes.

    Supported examples:
      2-3
      2
      1,3,5-7
    """

    value = page_range.strip().replace(" ", "")
    if not value:
        raise HTTPException(
            status_code=400,
            detail="page_range cannot be empty",
        )

    indexes: list[int] = []

    for part in value.split(","):
        if not part:
            raise HTTPException(
                status_code=400,
                detail=f"Invalid page_range: {page_range}",
            )

        if "-" in part:
            start_text, end_text = part.split("-", 1)
            if not start_text.isdigit() or not end_text.isdigit():
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid page range segment: {part}",
                )

            start_page = int(start_text)
            end_page = int(end_text)

            if start_page > end_page:
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid page range segment: {part}. Start page must be before end page.",
                )

            indexes.extend(range(start_page - 1, end_page))
        else:
            if not part.isdigit():
                raise HTTPException(
                    status_code=400,
                    detail=f"Invalid page range segment: {part}",
                )

            indexes.append(int(part) - 1)

    if not indexes:
        raise HTTPException(
            status_code=400,
            detail="page_range did not select any pages",
        )

    invalid_pages = [
        index + 1 for index in indexes if index < 0 or index >= total_pages
    ]
    if invalid_pages:
        raise HTTPException(
            status_code=400,
            detail=f"Page range contains pages outside the PDF. PDF has {total_pages} pages. Invalid pages: {invalid_pages}",
        )

    deduplicated: list[int] = []
    seen: set[int] = set()
    for index in indexes:
        if index not in seen:
            deduplicated.append(index)
            seen.add(index)

    return deduplicated


def _build_extracted_pdf_filename(filename: str, page_range: str) -> str:
    safe_range = re.sub(r"[^0-9,\-]+", "_", page_range.strip()) or "pages"
    base_name = filename.rsplit(".", 1)[0]
    return f"{base_name}_pages_{safe_range}.pdf"


def _build_api_response(
    organisation_document_id: int,
    ocrparse_documents: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Run the same extraction path for manual, multipart, and JSON inputs."""

    results: list[dict[str, Any]] = []

    for ocrparse_json in ocrparse_documents:
        generated_result = build_klippa_result(ocrparse_json)
        ocr_result_klippa = _format_ocr_result_for_api(generated_result)

        results.append(
            {
                "json": {
                    "data": {
                        "organisation_document_id": organisation_document_id,
                        "ocr_result_klippa": ocr_result_klippa,
                    }
                }
            }
        )

    return results


def _format_ocr_result_for_api(generated_result: dict[str, Any]) -> dict[str, Any]:
    """Return exactly the same Klippa result produced by the manual runner."""

    return generated_result.get("ocr_result_klippa", {})


def _load_ocrparse_json_from_bytes(raw_bytes: bytes, filename: str) -> Any:
    if not raw_bytes:
        raise HTTPException(
            status_code=400,
            detail="inputFile cannot be empty",
        )

    lowered_filename = filename.lower()
    if lowered_filename.endswith(".pdf"):
        raise HTTPException(
            status_code=415,
            detail="PDF files are not supported in this version. Upload OCRParse JSON, for example AGTECH_ocrparse.json.",
        )

    try:
        json_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"inputFile is not valid UTF-8 JSON: {exc}",
        ) from exc

    return _parse_json_string(json_text)


def _load_ocrparse_json(data: Any) -> Any:
    """Load OCRParse JSON from the compatibility JSON endpoint."""

    if isinstance(data, dict):
        _validate_ocrparse_shape(data)
        return data

    if not isinstance(data, str):
        raise HTTPException(
            status_code=400,
            detail="document_array[].data must be OCRParse JSON as an object, JSON string, or base64 encoded JSON",
        )

    value = data.strip()

    if not value:
        raise HTTPException(
            status_code=400,
            detail="document_array[].data cannot be empty",
        )

    if value.startswith("{"):
        return _parse_json_string(value)

    mime_type, raw_bytes = _decode_data_uri_or_base64(value)

    if mime_type == "application/pdf":
        raise HTTPException(
            status_code=415,
            detail="PDF base64 is not supported in this version. Send OCRParse JSON to this endpoint.",
        )

    if mime_type not in {"", "application/json", "text/json", "text/plain"}:
        raise HTTPException(
            status_code=415,
            detail=f"Unsupported document mime type: {mime_type}. Send OCRParse JSON instead.",
        )

    try:
        json_text = raw_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Decoded document data is not valid UTF-8 JSON: {exc}",
        ) from exc

    return _parse_json_string(json_text)


def _parse_json_string(value: str) -> Any:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Document data is not valid OCRParse JSON: {exc}",
        ) from exc

    _validate_ocrparse_shape(parsed)
    return parsed


def _decode_data_uri_or_base64(value: str) -> tuple[str, bytes]:
    mime_type = ""
    base64_value = value

    match = DATA_URI_RE.match(value)
    if match:
        mime_type = match.group("mime").lower()
        base64_value = match.group("data")

    try:
        raw_bytes = base64.b64decode(base64_value, validate=True)
    except binascii.Error as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid base64 document data: {exc}",
        ) from exc

    return mime_type, raw_bytes


def _validate_ocrparse_shape(value: Any) -> None:
    if isinstance(value, dict) and "ParsedResults" in value:
        return

    if (
        isinstance(value, list)
        and len(value) == 1
        and isinstance(value[0], dict)
        and "ParsedResults" in value[0]
    ):
        return

    if isinstance(value, list) and all(
        isinstance(page, dict)
        and ("Overlay" in page or "TextOverlay" in page or "ParsedText" in page)
        for page in value
    ):
        return

    raise HTTPException(
        status_code=400,
        detail="Expected OCRParse JSON with a ParsedResults field",
    )
