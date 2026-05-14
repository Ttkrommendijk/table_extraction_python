# Table Extraction API

`main.py` is still preserved for manual use.

Use `api.py` when you want to run the service.

## Install

```bash
pip install -r requirements.txt
```

## Run

```bash
uvicorn api:app --reload
```

Open:

```text
http://127.0.0.1:8000/docs
```

## Healthcheck

```text
GET /
```

Response:

```json
{
  "status": "running"
}
```

## Main endpoint

```text
POST /extract
```

Content type:

```text
multipart/form-data
```

Fields:

```text
inputFile = AGTECH_ocrparse.json
organisation_document_id = 121
```

This endpoint currently expects OCRParse JSON, not PDF.

## Response shape

```json
[
  {
    "json": {
      "data": {
        "organisation_document_id": 121,
        "ocr_result_klippa": {
          "version": "1",
          "components": {
            "tables": {
              "tables": []
            }
          },
          "text_content": []
        }
      }
    }
  }
]
```

## Compatibility JSON endpoint

```text
POST /extract/json
```

This accepts the previous JSON body structure:

```json
{
  "organisation_document_id": 121,
  "document_array": [
    {
      "data": {
        "ParsedResults": []
      }
    }
  ]
}
```
