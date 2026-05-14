import base64
import binascii
import json
import re
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from pydantic import BaseModel, Field

from main import build_klippa_result


DATA_URI_RE = re.compile(r"^data:(?P<mime>[^;]+);base64,(?P<data>.*)$", re.DOTALL)


class DocumentItem(BaseModel):
    # Optional JSON body mode, kept for compatibility.
    # The main test flow should use multipart/form-data with inputFile.
    data: Any


class ExtractRequest(BaseModel):
    organisation_document_id: int
    document_array: list[DocumentItem] = Field(default_factory=list)


app = FastAPI(
    title="Table Extraction API",
    version="1.3.0",
)


@app.get("/")
def healthcheck() -> dict[str, str]:
    return {"status": "running"}


@app.post("/extract")
async def extract(
    inputFile: UploadFile = File(...),
    organisation_document_id: int = Form(...),
) -> list[dict[str, Any]]:
    """Extract tables from an uploaded OCRParse JSON file.

    Expected request type:
      multipart/form-data

    Expected fields:
      inputFile: AGTECH_ocrparse.json
      organisation_document_id: 121
    """

    raw_bytes = await inputFile.read()
    ocrparse_json = _load_ocrparse_json_from_bytes(raw_bytes, inputFile.filename or "inputFile")

    generated_result = build_klippa_result(ocrparse_json)
    ocr_result_klippa = _format_ocr_result_for_api(generated_result)

    return [
        {
            "json": {
                "data": {
                    "organisation_document_id": organisation_document_id,
                    "ocr_result_klippa": ocr_result_klippa,
                }
            }
        }
    ]


@app.post("/extract/json")
def extract_json(payload: ExtractRequest) -> list[dict[str, Any]]:
    """Compatibility endpoint for the previous JSON body format."""

    if not payload.document_array:
        raise HTTPException(
            status_code=400,
            detail="document_array must contain at least one document",
        )

    results: list[dict[str, Any]] = []

    for document in payload.document_array:
        ocrparse_json = _load_ocrparse_json(document.data)
        generated_result = build_klippa_result(ocrparse_json)
        ocr_result_klippa = _format_ocr_result_for_api(generated_result)

        results.append(
            {
                "json": {
                    "data": {
                        "organisation_document_id": payload.organisation_document_id,
                        "ocr_result_klippa": ocr_result_klippa,
                    }
                }
            }
        )

    return results


@app.post("/extract/ocrparse")
def extract_ocrparse(payload: dict[str, Any]) -> dict[str, Any]:
    """Developer helper endpoint for direct OCRParse JSON testing."""

    return build_klippa_result(payload)


def _format_ocr_result_for_api(generated_result: dict[str, Any]) -> dict[str, Any]:
    """Return the Klippa compatible OCR result expected by the caller."""

    ocr_result = generated_result.get("ocr_result_klippa", {})
    tables_component = ocr_result.get("components", {}).get("tables", {})
    text_content = tables_component.get("text_content", [])

    return {
        **ocr_result,
        "text_content": text_content,
    }


def _load_ocrparse_json_from_bytes(raw_bytes: bytes, filename: str) -> dict[str, Any]:
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


def _load_ocrparse_json(data: Any) -> dict[str, Any]:
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


def _parse_json_string(value: str) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Document data is not valid OCRParse JSON: {exc}",
        ) from exc

    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=400,
            detail="OCRParse JSON must be a JSON object",
        )

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


def _validate_ocrparse_shape(value: dict[str, Any]) -> None:
    if "ParsedResults" not in value:
        raise HTTPException(
            status_code=400,
            detail="Expected OCRParse JSON with a ParsedResults field",
        )
