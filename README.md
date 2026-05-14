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

## PDF page extraction endpoint

```text
POST /pdf/extract-pages
```

Content type:

```text
multipart/form-data
```

Fields:

```text
inputFile = source.pdf
page_range = 2-3
```

The `page_range` value is 1-based. For example, `2-3` keeps original PDF pages 2 and 3. In the returned PDF, those pages become pages 1 and 2.

Supported examples:

```text
2-3
2
1,3,5-7
```

The endpoint returns a PDF file directly.


## Manual use remains unchanged

You can still run the parser manually exactly as before:

```bash
python main.py
```

The API service is separate and uses `api.py`.

## Local API run without container

For local development:

```bash
uvicorn api:app --reload
```

For local testing with production-like concurrency:

```bash
uvicorn api:app --host 0.0.0.0 --port 8000 --workers 4 --backlog 2048
```

Do not use `--reload` together with `--workers`.

## Podman deployment

Build:

```bash
podman build -t table-extraction-api -f Containerfile .
```

Run:

```bash
podman run --replace --name table-extraction-api -p 8000:8000 table-extraction-api
```

The container defaults to:

```text
APP_WORKERS=4
APP_BACKLOG=2048
APP_PORT=8000
```

That means the service can accept bursts of requests while only a controlled number of worker processes execute Python work at the same time.

To override the worker count:

```bash
podman run --replace --name table-extraction-api \
  -p 8000:8000 \
  -e APP_WORKERS=2 \
  -e APP_BACKLOG=2048 \
  table-extraction-api
```

Recommended starting values:

```text
2 CPU cores  -> APP_WORKERS=2
4 CPU cores  -> APP_WORKERS=4
8 CPU cores  -> APP_WORKERS=4 or 8
```

## Synchronous concurrency model

The service still works synchronously. A caller sends a request and waits for the result.

With Podman/Uvicorn configured like this:

```text
APP_WORKERS=4
APP_BACKLOG=2048
```

The behavior is:

```text
100 requests arrive
4 workers process requests immediately
remaining connections wait in the server/socket backlog
requests are not intentionally dropped by the app
```

Practical limits still apply:

```text
client timeout
reverse proxy timeout
server memory
request size
container restart
```

If you use Nginx, Traefik, Apache, or another reverse proxy in front of this service, configure its timeout high enough for the slowest expected extraction.

Example Nginx setting:

```nginx
proxy_read_timeout 300s;
proxy_connect_timeout 300s;
proxy_send_timeout 300s;
```

## Useful Podman commands

View logs:

```bash
podman logs -f table-extraction-api
```

Stop:

```bash
podman stop table-extraction-api
```

Remove:

```bash
podman rm table-extraction-api
```
