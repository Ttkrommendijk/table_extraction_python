import json

_LAST_OCRPARSE_JSON = None


def load_ocrparse_json(path: str) -> dict:

    global _LAST_OCRPARSE_JSON

    with open(path, "r", encoding="utf-8") as f:
        _LAST_OCRPARSE_JSON = json.load(f)

    return _LAST_OCRPARSE_JSON


def get_last_ocrparse_json() -> dict | None:
    """Return the most recently loaded OCRParse JSON, when available."""

    return _LAST_OCRPARSE_JSON


def _get_parsed_results(ocr_json) -> list:
    """Return the OCRParse ParsedResults list from all supported inputs.

    Supported shapes:
    - {"ParsedResults": [...]}
    - [{"ParsedResults": [...]}]
    - [{"Overlay"|"TextOverlay": ...}, ...]
    """

    if isinstance(ocr_json, dict):
        return ocr_json.get("ParsedResults", [])

    if isinstance(ocr_json, list):
        if len(ocr_json) == 1 and isinstance(ocr_json[0], dict) and "ParsedResults" in ocr_json[0]:
            return ocr_json[0].get("ParsedResults", [])

        return ocr_json

    return []


def extract_words(ocr_json: dict) -> list:

    pages = []
    parsed_results = _get_parsed_results(ocr_json)

    for page_index, page in enumerate(parsed_results):
        if not isinstance(page, dict):
            continue

        overlay = page.get("Overlay") or page.get("TextOverlay") or {}
        lines = overlay.get("Lines", [])

        words = []

        for line_index, line in enumerate(lines):
            line_text = line.get("LineText", "").strip()
            line_words = line.get("Words", [])
            line_id = f"{page_index}:{line_index}"

            for word_index, word in enumerate(line_words):
                left = word["Left"]
                top = word["Top"]
                width = word["Width"]
                height = word["Height"]

                words.append(
                    {
                        "text": word["WordText"].strip(),
                        "x1": left,
                        "y1": top,
                        "x2": left + width,
                        "y2": top + height,
                        "width": width,
                        "height": height,
                        "center_x": left + (width / 2),
                        "center_y": top + (height / 2),
                        "line_id": line_id,
                        "line_index": line_index,
                        "line_word_index": word_index,
                        "line_text": line_text,
                    }
                )

        pages.append(
            {
                "page_index": page_index,
                "words": words,
            }
        )

    return pages


def _line_text_from_overlay(page: dict) -> str:

    overlay = page.get("Overlay") or page.get("TextOverlay") or {}
    lines = overlay.get("Lines", [])

    line_texts = []

    for line in lines:
        text = line.get("LineText", "")

        if text is None:
            text = ""

        text = str(text).strip()

        if text:
            line_texts.append(text)

    return "\n".join(line_texts)


def extract_text_content(ocr_json: dict) -> list:
    """Return OCRParse ParsedText per page.

    OCRParse stores full page text in ParsedResults[n].ParsedText. The
    Klippa-compatible output should expose that as
    components.tables.text_content, split one list item per OCR page.

    We intentionally prefer ParsedText over Overlay.LineText because
    ParsedText is the OCR engine's own page-level text reconstruction.
    Overlay.LineText is only used as a defensive fallback when ParsedText is
    missing or empty.
    """

    text_content = []

    parsed_results = _get_parsed_results(ocr_json)

    for page in parsed_results:
        parsed_text = page.get("ParsedText")

        if parsed_text is None or str(parsed_text) == "":
            page_text = _line_text_from_overlay(page)
        else:
            # Keep the OCRParse page text content. Only remove trailing null-like
            # whitespace so we do not create unstable extra blank pages/lines.
            page_text = str(parsed_text).rstrip()

        text_content.append(page_text)

    return text_content
