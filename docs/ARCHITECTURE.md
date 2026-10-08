# DocPulse — Architecture

> An asynchronous FastAPI microservice that accepts PDF / Markdown / TXT files (by upload or by URL),
> processes them concurrently in the background, extracts metadata, and splits the text into
> overlapping "chunks" ready to be embedded into a vector database.

This document explains **what** we are building and **why it is shaped this way**.
The step-by-step "type this code here" guide is in [`IMPLEMENTATION.md`](./IMPLEMENTATION.md).

---

## 1. The big picture (in plain words)

1. A client sends a document (uploads a file **or** gives us a URL).
2. The API checks the request (size, type, chunk settings), creates a **job** and immediately answers
   `202 Accepted` with a `document_id`. It does **not** make the client wait for processing.
3. In the background, the **pipeline** does the work:
   download (if URL) → parse text → extract metadata → chunk text → save to disk.
4. The client polls `GET /documents/{id}` to see the job state (`pending → processing → completed/failed`).
5. When completed, the client reads the chunks page by page with `GET /documents/{id}/chunks?page=1&size=20`.

```
                    +-----------------------------------+
   HTTP client ---> |  FastAPI app (app/main.py)        |
                    |  middleware: request logging      |
                    |  exception handlers -> JSON errors |
                    +----------------+------------------+
                                     |
          +--------------------------+---------------------------+
          |                          |                           |
 POST /documents/upload    POST /documents/ingest-url     GET /documents/{id}
          |                          |                    GET /documents/{id}/chunks
          v                          v                    GET /health
 +-------------------------------------------+                   |
 | Pydantic validation (models/)             |                   |
 | create job (state = pending) -> 202       |                   |
 +--------------------+----------------------+                   |
                      | BackgroundTasks                          |
                      v                                          |
 +-------------------------------------------+                   |
 | IngestionPipeline (services/pipeline.py)  |                   |
 |  [semaphore: max N jobs at once]          |                   |
 |  1. load bytes   (upload / httpx fetch)   |                   |
 |  2. parse        (to_thread: pypdf ...)   |                   |
 |  3. metadata     (word count, sha256 ...) |                   |
 |  4. chunk        (to_thread: sliding win) |                   |
 |  5. save         (aiofiles -> JSON)       |                   |
 +--------------------+----------------------+                   |
                      v                                          v
             +-------------------------------------------------------+
             | DocumentRepository (storage/repository.py)            |
             |   data/jobs/{id}.json        data/documents/{id}.json |
             +-------------------------------------------------------+
```

---

## 2. Layers and the one rule that keeps them clean

The code is split into layers. Each layer has **one job**, and dependencies only point **downwards**.

| Layer       | Folder          | Responsibility                                                   | Knows about FastAPI? |
|-------------|-----------------|------------------------------------------------------------------|----------------------|
| API         | `app/api/`      | HTTP: routes, query/form params, status codes, dependencies      | Yes                  |
| Services    | `app/services/` | Business logic: parse, extract metadata, chunk, fetch, orchestrate | **No**              |
| Storage     | `app/storage/`  | Save and load jobs and documents                                 | **No**               |
| Models      | `app/models/`   | Data contracts shared by every layer (Pydantic + dataclasses)    | No                   |
| Core        | `app/core/`     | Cross-cutting: settings, logging, custom exceptions              | No                   |

```
   api  ──►  services  ──►  storage
    │            │             │
    └────────────┴──────┬──────┘
                        ▼
                models  +  core      (everyone may import these)
```

**The rule:** `services/` and `storage/` must never `import fastapi`.
**Why:** your chunker and parser stay plain Python functions. You can test them without a server,
reuse them in a CLI script or a worker queue later, and swap FastAPI out without rewriting logic.

---

## 3. Production folder structure

```
docpulse/                          <- project root (recommended name, see note below)
├── .env                           # your local settings (NOT committed to git)
├── .env.example                   # template of settings (committed)
├── .gitignore
├── .python-version                # created by uv, pins Python 3.12
├── pyproject.toml                 # dependencies + tool config (pytest, mypy, ruff)
├── uv.lock                        # exact dependency versions (created by uv)
├── Dockerfile                     # (optional, last phase) container image
├── README.md
│
├── docs/
│   ├── ARCHITECTURE.md            # this file
│   └── IMPLEMENTATION.md          # step-by-step build guide
│
├── app/
│   ├── __init__.py
│   ├── main.py                    # create_app(), lifespan (startup/shutdown), middleware, error handlers
│   │
│   ├── core/                      # cross-cutting concerns
│   │   ├── __init__.py
│   │   ├── config.py              # Settings(BaseSettings) loaded from .env
│   │   ├── logging.py             # JSON / text log formatter + setup_logging()
│   │   └── exceptions.py          # DocPulseError and subclasses (each has an HTTP status)
│   │
│   ├── models/                    # data contracts
│   │   ├── __init__.py
│   │   ├── enums.py               # DocumentType, JobState, SourceType
│   │   ├── internal.py            # @dataclass RawFile, ParsedDocument (internal only)
│   │   ├── chunk.py               # DocumentChunk, ChunkOptions
│   │   ├── document.py            # DocumentMetadata, IngestedDocument
│   │   ├── job.py                 # IngestionJobStatus
│   │   └── api.py                 # request/response bodies: IngestUrlRequest, ChunkPage, HealthResponse...
│   │
│   ├── services/                  # business logic (pure Python, no FastAPI)
│   │   ├── __init__.py
│   │   ├── parsers.py             # detect type + bytes -> ParsedDocument (pypdf / utf-8)
│   │   ├── metadata.py            # ParsedDocument -> DocumentMetadata
│   │   ├── chunker.py             # sliding-window chunking
│   │   ├── fetcher.py             # httpx async download with size limit
│   │   └── pipeline.py            # IngestionPipeline: orchestrates everything + job state + timing logs
│   │
│   ├── storage/
│   │   ├── __init__.py
│   │   └── repository.py          # DocumentRepository: async JSON-file storage (aiofiles)
│   │
│   └── api/
│       ├── __init__.py
│       ├── dependencies.py        # Depends() helpers: SettingsDep, RepositoryDep, PipelineDep
│       └── routes/
│           ├── __init__.py
│           ├── documents.py       # /documents/* endpoints
│           └── health.py          # /health endpoint
│
├── tests/
│   ├── __init__.py
│   ├── conftest.py                # shared fixtures (test client with temp storage)
│   ├── test_chunker.py
│   ├── test_parsers.py
│   ├── test_fetcher.py
│   └── test_api.py
│
├── samples/                       # a few small .txt / .md / .pdf files to try manually
└── data/                          # runtime storage, created automatically (NOT committed)
    ├── jobs/{document_id}.json
    └── documents/{document_id}.json
```

> **Folder name note:** your current folder is called `doc_pulse(ingestion-pipeline))`. Parentheses
> are special characters in bash and the name has an extra `)`. Rename it to something simple
> such as `docpulse` to avoid quoting headaches:
> `mv "doc_pulse(ingestion-pipeline))" docpulse`

**What is `__init__.py`?** An (empty) file that tells Python "this folder is a package", so you can
write `from app.core.config import get_settings`.

---

## 4. Tech stack — what and why

| Library              | Used for                                         | Why this one                                                                  |
|----------------------|--------------------------------------------------|-------------------------------------------------------------------------------|
| **FastAPI**          | HTTP API, routing, dependency injection, docs    | Async-first, validates requests with Pydantic, auto Swagger UI at `/docs`     |
| **uvicorn**          | ASGI server that runs FastAPI                    | Standard, fast server for async Python apps                                   |
| **Pydantic v2**      | Data models, validation, JSON (de)serialisation  | Turns type hints into runtime validation; FastAPI is built on it              |
| **pydantic-settings**| `Settings(BaseSettings)` from env vars / `.env`  | Typed + validated configuration in one class                                  |
| **python-dotenv**    | Reads the `.env` file                            | pydantic-settings uses it under the hood to load `env_file=".env"`            |
| **httpx**            | Async HTTP client to download remote documents   | `async`/`await` API (like `requests`, but non-blocking), streaming, timeouts  |
| **python-multipart** | Parsing `multipart/form-data` (file uploads)     | Required by FastAPI for `UploadFile` / `Form`                                 |
| **pypdf**            | Extracting text from PDFs                        | Pure Python, no system dependencies, typed                                    |
| **aiofiles**         | Async file reads/writes                          | Normal `open()` blocks the event loop; aiofiles does not                      |
| **pytest** (+ pytest-asyncio) | Tests                                   | Industry standard; pytest-asyncio lets you test `async def` functions         |
| **mypy** (strict)    | Static type checking                             | Enforces "strict type annotations across the codebase"                        |
| **ruff**             | Linting + import sorting + formatting            | One fast tool replaces flake8/isort/black                                     |
| **uv**               | Python version + virtualenv + dependency manager | One modern tool; installs Python 3.12 for you, creates a lock file            |
| `logging` (stdlib)   | Structured JSON logs                             | No extra dependency; we write a small JSON formatter ourselves (good learning)|

---

## 5. Data contracts (the models)

Two kinds of model are used on purpose:

* **Pydantic `BaseModel`**: data that crosses a boundary (HTTP request/response, JSON on disk).
  It **validates** input and converts to/from JSON.
* **`@dataclass`**: small internal containers passed between our own functions
  (`RawFile`, `ParsedDocument`, `Token`). We created the data ourselves, so it needs no validation.
  Dataclasses are lighter and faster.

### 5.1 Main models

```
IngestionJobStatus            (models/job.py)  -> returned by GET /documents/{id}
├── document_id: UUID
├── state: JobState           pending | processing | completed | failed
├── filename, source          upload | url
├── created_at, started_at, finished_at
├── processing_time_ms: float | None
├── chunk_count: int | None
├── error: str | None
└── metadata: DocumentMetadata | None     (filled when completed)

IngestedDocument              (models/document.py) -> saved as data/documents/{id}.json
├── id: UUID
├── metadata: DocumentMetadata
│   ├── filename, document_type (pdf|markdown|text), source, source_url
│   ├── size_bytes, title, page_count
│   ├── word_count, char_count, line_count
│   └── content_sha256        fingerprint, useful to detect duplicate uploads
├── chunk_size, chunk_overlap
├── chunk_count
├── chunks: list[DocumentChunk]
└── created_at

DocumentChunk                 (models/chunk.py) -> returned inside ChunkPage
├── chunk_id: "{document_id}:{index}"
├── document_id, index
├── text
├── token_count               number of tokens in this chunk
├── start_char, end_char      position of the chunk in the full text: text[start_char:end_char]
└── overlap_tokens            how many tokens are shared with the previous chunk
```

### 5.2 Job state machine

```
            create_job()            pipeline starts            success
  (none) ───────────────► PENDING ─────────────────► PROCESSING ─────────► COMPLETED
                                                         │
                                                         │ any exception
                                                         ▼
                                                       FAILED  (error message stored)

  On server restart: jobs still PENDING/PROCESSING are marked FAILED ("Interrupted by server restart").
```

---

## 6. Request lifecycles

### 6.1 `POST /documents/upload`

```
client                 route (documents.py)           pipeline                 repository
  │  multipart file        │                              │                         │
  ├───────────────────────►│ build ChunkOptions (422?)    │                         │
  │                        │ detect type        (415?)    │                         │
  │                        │ read bytes, check size (413?)│                         │
  │                        │ create_job ─────────────────►│ save_job(PENDING) ─────►│
  │◄── 202 {document_id} ──│ add_task(process_upload)     │                         │
  │                        │                              │                         │
  │              (after the response is sent)             │                         │
  │                        │                              │ wait for semaphore slot │
  │                        │                              │ save_job(PROCESSING) ──►│
  │                        │                              │ parse  (thread)         │
  │                        │                              │ metadata                │
  │                        │                              │ chunk  (thread)         │
  │                        │                              │ save_document ─────────►│
  │                        │                              │ save_job(COMPLETED) ───►│
  │                        │                              │ log: chunk_count, ms    │
```

### 6.2 `POST /documents/ingest-url`

Same as above, but the route only validates the JSON body (`{"url": "...", "chunk_size": 200}`).
**Downloading happens inside the background job**, so the client gets `202` instantly even if the
remote server is slow. Download errors (404, timeout, too big) put the job into `FAILED` with an error message.

### 6.3 Read endpoints

* `GET /documents/{id}`: reads the job from the in-memory cache. This is fast and needs no disk read.
* `GET /documents/{id}/chunks?page=1&size=20`: `409` if the job is not completed yet. Otherwise it loads the
  document JSON and returns a slice of the chunks with paging info.
* `GET /health`: uptime, Python version, CPU count, job counts per state, storage writable,
  and the active (non-secret) configuration.

---

## 7. Concurrency model (the most important concept in this project)

FastAPI runs on **one event loop** (one thread) that juggles many requests. The loop can only
switch to another task when the current one hits an `await`.

| Kind of work                         | Example in DocPulse                     | How we run it                     | Why                                        |
|--------------------------------------|-----------------------------------------|-----------------------------------|--------------------------------------------|
| **I/O-bound, async library exists**  | downloading with httpx, writing files   | `await client.get(...)`, `aiofiles` | While waiting on network/disk, the loop serves other requests |
| **CPU-bound / blocking library**     | pypdf parsing, chunking big text        | `await asyncio.to_thread(func, ...)` | Runs in a worker thread so the loop is **not blocked** |
| **"Fire and forget after response"** | the whole pipeline                      | FastAPI `BackgroundTasks`         | Client gets `202` immediately               |
| **Limit parallel work**              | max N documents processed at once       | `asyncio.Semaphore(MAX_CONCURRENT_JOBS)` | Protects RAM/CPU when 100 uploads arrive at once |

**The classic beginner bug:** calling a slow, normal (blocking) function directly inside `async def`,
for example `PdfReader(...)` on a 50 MB PDF. That freezes **every** request, `/health` included,
until it finishes. In this project every blocking call goes through `asyncio.to_thread`.

> Note: because of Python's GIL, threads don't make pure-Python CPU work *faster*; they keep the
> server *responsive*. For true CPU parallelism you would later use a process pool or a separate
> worker service (see §11).

---

## 8. Sliding-window chunking algorithm

**Goal:** split long text into pieces small enough for an embedding model. Neighbouring pieces
**overlap**, so a sentence cut at a boundary still appears whole in one of the chunks.

* **Token**: for this project, a token is any run of non-whitespace characters (`\S+`), roughly a word.
  We remember each token's `start`/`end` character position in the original text.
* **Window**: `chunk_size` tokens.
* **Step**: `chunk_size - chunk_overlap` tokens.

```
tokens:   0  1  2  3  4  5  6  7  8  9          chunk_size = 4, overlap = 1, step = 3
chunk 0: [0  1  2  3]
chunk 1:          [3  4  5  6]                   token 3 is shared (overlap 1)
chunk 2:                   [6  7  8  9]          stop: this window reached the end
```

Each chunk's `text` is `original_text[first_token.start : last_token.end]`. This keeps the
original spacing and newlines, and `start_char`/`end_char` let you highlight the chunk inside the source.

Rules enforced by `ChunkOptions`: `chunk_size > 0`, `0 <= chunk_overlap < chunk_size`.

---

## 9. Storage design

* **Jobs:** kept in an in-memory `dict` for fast reads and also written to `data/jobs/{id}.json`, so
  they survive restarts. On startup the repository reloads them.
* **Documents (with chunks):** `data/documents/{id}.json`, written with `aiofiles`.
* **Atomic writes:** write to `{id}.tmp`, then rename it to `{id}.json`. A crash in the middle never leaves a
  half-written JSON file.

Everything goes through the `DocumentRepository` class. To move to SQLite/Postgres later, you
write a new class with the **same method names** (`save_job`, `get_job`, `save_document`,
`get_document`, ...) and change one line in `main.py`. Nothing else changes. That is the reason
the repository pattern exists.

---

## 10. Configuration, logging, errors

### 10.1 Configuration (`core/config.py`)

All settings come from environment variables or `.env`. Env vars win over `.env`. Values are validated at startup,
so a bad config such as `DEFAULT_CHUNK_OVERLAP >= DEFAULT_CHUNK_SIZE` **crashes immediately with a clear message**
instead of failing later.

| Variable                | Default       | Meaning                                    |
|-------------------------|---------------|--------------------------------------------|
| `APP_NAME`              | `DocPulse`    | Shown in docs and `/health`                |
| `ENVIRONMENT`           | `development` | `development` / `production`               |
| `MAX_FILE_SIZE_MB`      | `10`          | Upload/download size limit                 |
| `DEFAULT_CHUNK_SIZE`    | `200`         | Tokens per chunk if the client sends none  |
| `DEFAULT_CHUNK_OVERLAP` | `40`          | Overlap tokens if the client sends none    |
| `MAX_CONCURRENT_JOBS`   | `4`           | Semaphore size                             |
| `HTTP_TIMEOUT_SECONDS`  | `30`          | httpx timeout for URL ingestion            |
| `STORAGE_DIR`           | `data`        | Where JSON files are stored                |
| `LOG_LEVEL`             | `INFO`        | `DEBUG` / `INFO` / `WARNING` / `ERROR`     |
| `LOG_FORMAT`            | `json`        | `json` (production) or `text` (readable locally) |

### 10.2 Logging (`core/logging.py`)

Every module does `logger = logging.getLogger(__name__)`. A single handler on the root logger
formats every record as one JSON line, including any `extra={...}` fields:

```json
{"timestamp": "2026-10-07T10:15:02.120+00:00", "level": "INFO", "logger": "app.services.pipeline",
 "message": "Ingestion completed", "document_id": "6f1c...", "document_type": "pdf",
 "chunk_count": 42, "processing_time_ms": 183.4}
```

What gets logged:
* every HTTP request: method, path, status code, duration (middleware in `main.py`)
* job created / completed (with `chunk_count`, `processing_time_ms`) / failed (with **stack trace** via `logger.exception`)
* startup and shutdown with the effective configuration

JSON logs can be searched by tools like Loki, ELK or Datadog: "show all failed jobs over 2 s".

### 10.3 Errors (`core/exceptions.py`)

Services raise **our own** exceptions. They have no HTTP knowledge, only a `status_code` hint. One handler in
`main.py` turns any `DocPulseError` into a JSON response:

| Exception                  | HTTP | When                                          |
|----------------------------|------|-----------------------------------------------|
| `DocumentNotFoundError`    | 404  | unknown `document_id`                         |
| `DocumentNotReadyError`    | 409  | chunks requested before job is completed      |
| `FileTooLargeError`        | 413  | over `MAX_FILE_SIZE_MB`                       |
| `UnsupportedFileTypeError` | 415  | not pdf/md/txt                                |
| `InvalidChunkOptionsError` | 422  | overlap >= size, etc.                         |
| `DocumentParseError`       | 422  | empty / unreadable / no extractable text      |
| `DocumentFetchError`       | 502  | remote URL failed (only visible in job.error) |
| anything else              | 500  | bug: logged with full stack trace             |

Response shape: `{"error": "FileTooLargeError", "detail": "File exceeds 10 MB"}`

---

## 11. API reference

| Method | Path                         | Body / Params                                              | Success |
|--------|------------------------------|------------------------------------------------------------|---------|
| POST   | `/documents/upload`          | multipart: `file`, optional `chunk_size`, `chunk_overlap`  | 202 `IngestAcceptedResponse` |
| POST   | `/documents/ingest-url`      | JSON: `{"url", "chunk_size"?, "chunk_overlap"?}`           | 202 `IngestAcceptedResponse` |
| GET    | `/documents/{id}`            | –                                                          | 200 `IngestionJobStatus` |
| GET    | `/documents/{id}/chunks`     | query: `page` (≥1, default 1), `size` (1–100, default 20)  | 200 `ChunkPage` |
| GET    | `/health`                    | –                                                          | 200 `HealthResponse` |
| GET    | `/docs`                      | interactive Swagger UI (auto-generated by FastAPI)          | – |

---

## 12. Known limitations and next steps (after v1 works)

| Limitation in v1                                       | Production upgrade                                              |
|--------------------------------------------------------|-----------------------------------------------------------------|
| Background tasks live inside the API process; a crash loses running jobs | Queue + workers: **arq** / **Celery** / **Dramatiq** with Redis |
| JSON files on local disk                               | Postgres/SQLite (SQLAlchemy async) + object storage (S3) for raw files |
| "Token" = whitespace word                              | Real tokenizer (`tiktoken`) matching your embedding model     |
| Scanned PDFs have no text                              | OCR (e.g. Tesseract)                                            |
| Any URL can be fetched                                 | **SSRF protection**: block private IPs (`127.0.0.1`, `10.x`, `169.254.x`), allow-list domains |
| No authentication                                      | API keys or OAuth2 (FastAPI has `Security` helpers)             |
| No metrics                                             | Prometheus metrics (`prometheus-fastapi-instrumentator`)       |
| Chunks are not embedded                                | Next project: send chunks to an embedding model + vector DB (Qdrant, pgvector) |
