# DocPulse — Implementation Guide

Read [`ARCHITECTURE.md`](./ARCHITECTURE.md) first. This guide tells you **which file to create,
what code goes in it, why, and how to check that it works** before you move on.

## How to use this guide

* Work through the phases **in order**. Each phase only depends on earlier phases.
* **Type the code yourself.** Don't copy-paste it. Typing is how the patterns stick.
* Every file has a **✅ Checkpoint**. Don't move on until it passes.
* Comments in the code explain the *why*. Read them, but you don't have to type them all.
* When something breaks, read the **whole** error message from the bottom up. Python
  tracebacks show the real cause on the last line.

| Phase | What you build                      | Files                                                        |
|-------|-------------------------------------|--------------------------------------------------------------|
| 0     | Project setup                       | `pyproject.toml`, `.env`, `.gitignore`, folders              |
| 1     | Core (config, logging, errors)      | `app/core/*`                                                 |
| 2     | Data contracts                      | `app/models/*`                                               |
| 3     | Services (parse, metadata, chunk, fetch) | `app/services/parsers.py, metadata.py, chunker.py, fetcher.py` |
| 4     | Storage                             | `app/storage/repository.py`                                  |
| 5     | Pipeline                            | `app/services/pipeline.py`                                   |
| 6     | API + app                           | `app/api/*`, `app/main.py`                                   |
| 7     | Tests                               | `tests/*`                                                    |
| 8     | Quality gates                       | ruff + mypy                                                  |
| 9     | (Optional) Docker                   | `Dockerfile`                                                 |

---

## Python concepts you will meet (quick primer)

| Concept | Looks like | Meaning |
|---|---|---|
| Type hints | `def f(x: int) -> str:` | Documents types; mypy checks them; Pydantic/FastAPI **enforce** them at runtime |
| Union / optional | `str \| None` | "a string or None" (Python 3.10+ syntax) |
| Generics | `list[str]`, `dict[str, int]` | A list of strings, a dict from str to int |
| `Annotated` | `Annotated[int, Query(ge=1)]` | A type **plus** extra info for FastAPI ("this int comes from the query string and must be ≥ 1") |
| `async def` / `await` | `data = await client.get(url)` | A coroutine; `await` pauses *this* task and lets the event loop run others while waiting |
| Async context manager | `async with lock:` | Like `with`, but entering/exiting can `await` |
| Decorator | `@router.get("/health")` | A function that wraps/registers another function |
| `@dataclass` | `@dataclass class RawFile: ...` | Auto-generates `__init__`, `__repr__`, `__eq__` from the fields |
| `Enum` / `StrEnum` | `class JobState(StrEnum): ...` | A fixed set of named values; `StrEnum` members are also strings |
| `@lru_cache` | on `get_settings()` | Run once, then return the cached result every later call |
| Keyword-only args | `def f(a, *, b):` | Everything after `*` must be passed by name: `f(1, b=2)` |
| `raise X from exc` | | Raise a new error and keep the original as the "cause" in the traceback |

---

# Phase 0 — Project setup

### 0.1 Install `uv` and Python 3.12

Your system Python is 3.9, which is too old for the syntax used here (`str | None`, `StrEnum`, `match`).
`uv` installs and manages Python 3.12 for you without touching the system Python.

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh     # install uv (restart terminal afterwards)
uv --version
```

### 0.2 Create the project

```bash
cd ~/work-space/documents/Learning/Artificial-Intelligence/python
mv "doc_pulse(ingestion-pipeline))" docpulse        # simpler folder name (recommended)
cd docpulse

uv init --bare --python 3.12      # creates pyproject.toml only
uv python pin 3.12                # creates .python-version
git init
```

### 0.3 Add dependencies

```bash
# runtime dependencies
uv add fastapi "uvicorn[standard]" pydantic pydantic-settings python-dotenv \
       httpx python-multipart pypdf aiofiles

# development-only dependencies (tests, type checking, linting)
uv add --dev pytest pytest-asyncio mypy ruff types-aiofiles
```

**Why:** `uv add` installs the package into `.venv/`, records it in `pyproject.toml`, and pins exact
versions in `uv.lock`, so everyone (and Docker) gets identical versions.

Run any command inside the project's environment with `uv run <command>`, for example `uv run python`.

### 0.4 Tool configuration, appended to `pyproject.toml`

Open `pyproject.toml` and add these sections **at the end** (keep what uv generated):

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"      # lets you write `async def test_...` without extra decorators
testpaths = ["tests"]
pythonpath = ["."]         # so tests can `import app`

[tool.mypy]
python_version = "3.12"
strict = true              # every function must be fully annotated
plugins = ["pydantic.mypy"]

[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "UP", "B", "SIM"]   # errors, pyflakes, import-sort, upgrades, bugbear, simplify
```

### 0.5 `.gitignore`

```gitignore
.venv/
__pycache__/
*.pyc
.env
data/
.mypy_cache/
.pytest_cache/
.ruff_cache/
```

**Why:** `.env` can contain secrets, and `data/` is runtime output. Neither belongs in git.

### 0.6 `.env.example` (committed) and `.env` (your local copy)

```dotenv
APP_NAME=DocPulse
ENVIRONMENT=development
MAX_FILE_SIZE_MB=10
DEFAULT_CHUNK_SIZE=200
DEFAULT_CHUNK_OVERLAP=40
MAX_CONCURRENT_JOBS=4
HTTP_TIMEOUT_SECONDS=30
STORAGE_DIR=data
LOG_LEVEL=INFO
LOG_FORMAT=text
```

```bash
cp .env.example .env
```

Use `LOG_FORMAT=text` while developing because it is easier to read. Production uses `json`.

### 0.7 Create the folders and empty `__init__.py` files

```bash
mkdir -p app/core app/models app/services app/storage app/api/routes tests samples docs
touch app/__init__.py app/core/__init__.py app/models/__init__.py app/services/__init__.py \
      app/storage/__init__.py app/api/__init__.py app/api/routes/__init__.py tests/__init__.py
```

Put 2–3 small test files in `samples/`: a `notes.txt`, a `readme.md` with a `# Title` line, and any small PDF.

✅ **Checkpoint:** `uv run python --version` prints `Python 3.12.x`.

---

# Phase 1 — Core

## 1.1 `app/core/config.py`: settings

**Why:** settings must not be hard-coded. `BaseSettings` reads env vars and `.env`, converts the
strings to the right types (`"10"` → `10`), validates them, and fails at startup if something is wrong.

```python
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings, loaded from environment variables and the .env file.

    Field names are matched to env vars case-insensitively:
    MAX_FILE_SIZE_MB -> max_file_size_mb.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",  # ignore unknown variables in .env instead of crashing
    )

    app_name: str = "DocPulse"
    app_version: str = "0.1.0"
    environment: Literal["development", "production", "test"] = "development"

    max_file_size_mb: int = Field(default=10, gt=0, le=200)
    default_chunk_size: int = Field(default=200, gt=0, le=5000)
    default_chunk_overlap: int = Field(default=40, ge=0)
    max_concurrent_jobs: int = Field(default=4, gt=0, le=64)
    http_timeout_seconds: float = Field(default=30.0, gt=0)
    storage_dir: Path = Path("data")

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    log_format: Literal["json", "text"] = "json"

    @model_validator(mode="after")
    def _check_chunk_defaults(self) -> Self:
        # Runs after all fields are parsed: validation that involves TWO fields.
        if self.default_chunk_overlap >= self.default_chunk_size:
            raise ValueError("DEFAULT_CHUNK_OVERLAP must be smaller than DEFAULT_CHUNK_SIZE")
        return self

    @property
    def max_file_size_bytes(self) -> int:
        return self.max_file_size_mb * 1024 * 1024


@lru_cache
def get_settings() -> Settings:
    """Create Settings once and reuse it (reading .env on every request would be wasteful)."""
    return Settings()
```

**Key ideas**
* `Field(gt=0)`: "greater than 0". Pydantic checks it.
* `Literal["json", "text"]`: only these exact strings are allowed.
* `@property`: a computed attribute, used as `settings.max_file_size_bytes` (no parentheses).

✅ **Checkpoint**
```bash
uv run python -c "from app.core.config import get_settings; print(get_settings())"
DEFAULT_CHUNK_OVERLAP=500 uv run python -c "from app.core.config import get_settings; get_settings()"
# second command must fail with: DEFAULT_CHUNK_OVERLAP must be smaller than DEFAULT_CHUNK_SIZE
```

---

## 1.2 `app/core/logging.py`: structured logging

**Why:** in production you search logs by fields, for example "all jobs with `processing_time_ms > 2000`".
That needs one JSON object per line. We extend the standard `logging.Formatter`.

```python
import json
import logging
import sys
from datetime import UTC, datetime
from typing import Any

# Attributes every LogRecord already has. Anything else on a record came from `extra={...}`.
# ("color_message" is added by uvicorn; we don't want it in our JSON.)
_DUMMY_RECORD = logging.LogRecord("", 0, "", 0, "", None, None)
_STANDARD_ATTRS: set[str] = set(vars(_DUMMY_RECORD)) | {"message", "asctime", "color_message"}


class JsonFormatter(logging.Formatter):
    """Formats each log record as a single JSON line."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        # Copy custom fields passed via logger.info("...", extra={"chunk_count": 5})
        for key, value in vars(record).items():
            if key not in _STANDARD_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)  # default=str handles UUID, datetime, Path


def setup_logging(level: str, fmt: str) -> None:
    """Configure the root logger once, at application start-up."""
    handler = logging.StreamHandler(sys.stdout)
    if fmt == "json":
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s")
        )

    root = logging.getLogger()
    root.handlers.clear()  # avoid duplicate lines if called twice (e.g. in tests)
    root.addHandler(handler)
    root.setLevel(level)

    # Make uvicorn's own loggers go through our handler/format too.
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(name)
        uvicorn_logger.handlers.clear()
        uvicorn_logger.propagate = True
```

**How to use it everywhere else**
```python
import logging
logger = logging.getLogger(__name__)      # __name__ = "app.services.pipeline" etc.

logger.info("Ingestion completed", extra={"document_id": str(doc_id), "chunk_count": 12})
logger.exception("Ingestion failed")      # inside `except:` -> also logs the stack trace
```

⚠️ **Pitfall:** `extra` keys must not clash with built-in record attributes such as `filename`,
`name`, `module`, `message` or `args`. If they do, Python raises `KeyError: "Attempt to overwrite 'filename' in LogRecord"`.
That's why this project uses `file_name` in log extras.

✅ **Checkpoint**
```bash
uv run python -c "
import logging
from app.core.logging import setup_logging
setup_logging('INFO', 'json')
logging.getLogger('demo').info('hello', extra={'chunk_count': 3})"
# -> {"timestamp": "...", "level": "INFO", "logger": "demo", "message": "hello", "chunk_count": 3}
```

---

## 1.3 `app/core/exceptions.py`: custom errors

**Why:** services shouldn't know about HTTP, but the API needs to know which status code to return.
Each error class carries a `status_code` hint, and **one** handler in `main.py` converts all of them to JSON.

```python
class DocPulseError(Exception):
    """Base class for all expected application errors."""

    status_code: int = 500

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class DocumentNotFoundError(DocPulseError):
    status_code = 404


class DocumentNotReadyError(DocPulseError):
    status_code = 409


class FileTooLargeError(DocPulseError):
    status_code = 413


class UnsupportedFileTypeError(DocPulseError):
    status_code = 415


class InvalidChunkOptionsError(DocPulseError):
    status_code = 422


class DocumentParseError(DocPulseError):
    status_code = 422


class DocumentFetchError(DocPulseError):
    status_code = 502
```

**Key idea:** inheritance. `except DocPulseError` catches **all** of the subclasses.

---

# Phase 2 — Data contracts (models)

## 2.1 `app/models/enums.py`

**Why:** writing `"completed"` by hand in 5 places invites typos (`"complete"`). An enum gives one
source of truth, and Pydantic rejects any value not in it.

```python
from enum import StrEnum


class DocumentType(StrEnum):
    PDF = "pdf"
    MARKDOWN = "markdown"
    TEXT = "text"


class JobState(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class SourceType(StrEnum):
    UPLOAD = "upload"
    URL = "url"
```

## 2.2 `app/models/internal.py`: dataclasses

**Why dataclasses here, not Pydantic?** These objects never come from users. We build them
ourselves and pass them between our own functions, so validation would only cost time.
`frozen=True` makes them immutable (safer), and `slots=True` makes them smaller and faster.

```python
from dataclasses import dataclass

from app.models.enums import DocumentType


@dataclass(frozen=True, slots=True)
class RawFile:
    """Raw bytes of a document plus what we know about where it came from."""

    data: bytes
    filename: str
    content_type: str | None
    source_url: str | None = None  # None means it was uploaded


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    """Output of a parser: plain text plus format-specific info."""

    text: str
    document_type: DocumentType
    title: str | None = None
    page_count: int | None = None
```

## 2.3 `app/models/chunk.py`

```python
from typing import Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class ChunkOptions(BaseModel):
    """How to chunk one document. Built from request values or settings defaults."""

    chunk_size: int = Field(gt=0, le=5000)
    chunk_overlap: int = Field(ge=0)

    @model_validator(mode="after")
    def _overlap_smaller_than_size(self) -> Self:
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError("chunk_overlap must be smaller than chunk_size")
        return self


class DocumentChunk(BaseModel):
    """One piece of a document, ready to be embedded into a vector database."""

    model_config = ConfigDict(frozen=True)

    chunk_id: str = Field(description="'{document_id}:{index}', unique per chunk")
    document_id: UUID
    index: int = Field(ge=0, description="Position of the chunk in the document (0-based)")
    text: str = Field(min_length=1)
    token_count: int = Field(gt=0)
    start_char: int = Field(ge=0, description="Start offset in the full extracted text")
    end_char: int = Field(gt=0, description="End offset (exclusive) in the full extracted text")
    overlap_tokens: int = Field(ge=0, description="Tokens shared with the previous chunk")

    @model_validator(mode="after")
    def _check_range(self) -> Self:
        if self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self
```

## 2.4 `app/models/document.py`

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field

from app.models.chunk import DocumentChunk
from app.models.enums import DocumentType, SourceType


class DocumentMetadata(BaseModel):
    filename: str
    document_type: DocumentType
    source: SourceType
    source_url: str | None = None
    size_bytes: int = Field(ge=0)
    title: str | None = None
    page_count: int | None = Field(default=None, ge=0)
    word_count: int = Field(ge=0)
    char_count: int = Field(ge=0)
    line_count: int = Field(ge=0)
    content_sha256: str = Field(min_length=64, max_length=64)


class IngestedDocument(BaseModel):
    """A fully processed document, as stored on disk."""

    id: UUID
    metadata: DocumentMetadata
    chunk_size: int
    chunk_overlap: int
    chunk_count: int = Field(ge=0)
    chunks: list[DocumentChunk]
    created_at: datetime
```

## 2.5 `app/models/job.py`

```python
from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from app.models.document import DocumentMetadata
from app.models.enums import JobState, SourceType


class IngestionJobStatus(BaseModel):
    """State of one ingestion job. Returned by GET /documents/{id}."""

    document_id: UUID
    state: JobState
    filename: str
    source: SourceType
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    processing_time_ms: float | None = None
    chunk_count: int | None = None
    error: str | None = None
    metadata: DocumentMetadata | None = None
```

## 2.6 `app/models/api.py`: request/response bodies

**Why separate from the domain models?** The API shape is a public promise to clients. Keeping
it separate lets you change internals without breaking clients.

```python
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, HttpUrl

from app.models.chunk import DocumentChunk
from app.models.enums import JobState


class IngestUrlRequest(BaseModel):
    url: HttpUrl  # Pydantic rejects anything that isn't a valid http(s) URL
    chunk_size: int | None = Field(default=None, gt=0, le=5000)
    chunk_overlap: int | None = Field(default=None, ge=0)


class IngestAcceptedResponse(BaseModel):
    document_id: UUID
    state: JobState
    status_url: str
    chunks_url: str


class ChunkPage(BaseModel):
    document_id: UUID
    page: int
    size: int
    total_chunks: int
    total_pages: int
    items: list[DocumentChunk]


class ConfigSummary(BaseModel):
    """Non-secret settings, safe to show in /health."""

    environment: str
    max_file_size_mb: int
    default_chunk_size: int
    default_chunk_overlap: int
    max_concurrent_jobs: int
    log_level: str


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app_name: str
    version: str
    uptime_seconds: float
    python_version: str
    platform: str
    cpu_count: int
    storage_writable: bool
    jobs: dict[str, int]
    config: ConfigSummary
```

✅ **Checkpoint: see validation working**
```bash
uv run python
>>> from app.models.chunk import ChunkOptions
>>> ChunkOptions(chunk_size=100, chunk_overlap=20)
ChunkOptions(chunk_size=100, chunk_overlap=20)
>>> ChunkOptions(chunk_size=100, chunk_overlap=100)
# ValidationError: chunk_overlap must be smaller than chunk_size
>>> ChunkOptions(chunk_size="50", chunk_overlap=0)    # "50" is converted to 50
```

---

# Phase 3 — Services

## 3.1 `app/services/parsers.py`: detect type and extract text

**Why:** each format needs different handling, but the rest of the pipeline only wants
"give me the text". This module hides the differences behind one function, `parse_document()`.

```python
import io
from collections.abc import Callable
from pathlib import Path

from pypdf import PdfReader
from pypdf.errors import PdfReadError

from app.core.exceptions import DocumentParseError, UnsupportedFileTypeError
from app.models.enums import DocumentType
from app.models.internal import ParsedDocument

_EXTENSIONS: dict[str, DocumentType] = {
    ".pdf": DocumentType.PDF,
    ".md": DocumentType.MARKDOWN,
    ".markdown": DocumentType.MARKDOWN,
    ".txt": DocumentType.TEXT,
}

_CONTENT_TYPES: dict[str, DocumentType] = {
    "application/pdf": DocumentType.PDF,
    "text/markdown": DocumentType.MARKDOWN,
    "text/x-markdown": DocumentType.MARKDOWN,
    "text/plain": DocumentType.TEXT,
}


def detect_document_type(filename: str, content_type: str | None) -> DocumentType:
    """Decide the format from the file extension first, then the Content-Type header."""
    suffix = Path(filename).suffix.lower()
    if suffix in _EXTENSIONS:
        return _EXTENSIONS[suffix]
    if content_type:
        base_type = content_type.split(";")[0].strip().lower()  # "text/plain; charset=utf-8"
        if base_type in _CONTENT_TYPES:
            return _CONTENT_TYPES[base_type]
    raise UnsupportedFileTypeError(
        f"Unsupported file '{filename}' ({content_type}). Allowed: pdf, md, txt"
    )


def parse_document(data: bytes, document_type: DocumentType) -> ParsedDocument:
    """Extract text from raw bytes. Blocking (CPU work): call it via asyncio.to_thread."""
    parser = _PARSERS[document_type]
    return parser(data)


def _decode(data: bytes) -> str:
    try:
        return data.decode("utf-8")
    except UnicodeDecodeError:
        return data.decode("latin-1")  # never fails: every byte maps to a character


def _parse_text(data: bytes) -> ParsedDocument:
    text = _decode(data)
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), None)
    title = first_line[:120] if first_line else None
    return ParsedDocument(text=text, document_type=DocumentType.TEXT, title=title)


def _parse_markdown(data: bytes) -> ParsedDocument:
    text = _decode(data)
    title = None
    for line in text.splitlines():
        if line.startswith("# "):  # first level-1 heading is the title
            title = line[2:].strip()
            break
    return ParsedDocument(text=text, document_type=DocumentType.MARKDOWN, title=title)


def _parse_pdf(data: bytes) -> ParsedDocument:
    try:
        reader = PdfReader(io.BytesIO(data))  # BytesIO: treat bytes in memory like a file
        pages = [page.extract_text() or "" for page in reader.pages]
    except PdfReadError as exc:
        raise DocumentParseError(f"Could not read PDF: {exc}") from exc
    title = reader.metadata.title if reader.metadata else None
    return ParsedDocument(
        text="\n\n".join(pages),
        document_type=DocumentType.PDF,
        title=title,
        page_count=len(pages),
    )


# A "dispatch table": maps each type to the function that handles it.
# Defined at the bottom because the functions must exist first.
_PARSERS: dict[DocumentType, Callable[[bytes], ParsedDocument]] = {
    DocumentType.PDF: _parse_pdf,
    DocumentType.MARKDOWN: _parse_markdown,
    DocumentType.TEXT: _parse_text,
}
```

**Key ideas**
* A leading underscore (`_parse_pdf`) means "private to this module". Other modules use the public functions.
* A dispatch dict instead of a long `if/elif`: adding `.docx` later means one new function and one dict entry.

✅ **Checkpoint**
```bash
uv run python -c "
from pathlib import Path
from app.services.parsers import detect_document_type, parse_document
p = Path('samples/readme.md')
t = detect_document_type(p.name, None)
print(t, parse_document(p.read_bytes(), t).title)"
```

## 3.2 `app/services/metadata.py`

```python
import hashlib

from app.models.document import DocumentMetadata
from app.models.enums import SourceType
from app.models.internal import ParsedDocument, RawFile


def extract_metadata(parsed: ParsedDocument, raw_file: RawFile) -> DocumentMetadata:
    text = parsed.text
    return DocumentMetadata(
        filename=raw_file.filename,
        document_type=parsed.document_type,
        source=SourceType.URL if raw_file.source_url else SourceType.UPLOAD,
        source_url=raw_file.source_url,
        size_bytes=len(raw_file.data),
        title=parsed.title,
        page_count=parsed.page_count,
        word_count=len(text.split()),
        char_count=len(text),
        line_count=len(text.splitlines()),
        # The same file always gives the same hash, so it can detect duplicate uploads later.
        content_sha256=hashlib.sha256(raw_file.data).hexdigest(),
    )
```

## 3.3 `app/services/chunker.py`: sliding window (the heart of the project)

Re-read ARCHITECTURE.md §8 for the diagram before typing this.

```python
import re
from dataclasses import dataclass
from uuid import UUID

from app.models.chunk import DocumentChunk

_TOKEN_PATTERN = re.compile(r"\S+")  # a run of non-whitespace characters, roughly a word


@dataclass(frozen=True, slots=True)
class Token:
    text: str
    start: int  # character index where the token starts in the full text
    end: int  # character index right after the token ends


def tokenize(text: str) -> list[Token]:
    return [Token(m.group(), m.start(), m.end()) for m in _TOKEN_PATTERN.finditer(text)]


def chunk_text(
    text: str,
    document_id: UUID,
    chunk_size: int,
    chunk_overlap: int,
) -> list[DocumentChunk]:
    """Split text into overlapping windows of `chunk_size` tokens.

    Blocking CPU work: call it via asyncio.to_thread from async code.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if not 0 <= chunk_overlap < chunk_size:
        raise ValueError("chunk_overlap must be >= 0 and smaller than chunk_size")

    tokens = tokenize(text)
    if not tokens:
        return []

    step = chunk_size - chunk_overlap
    chunks: list[DocumentChunk] = []

    for index, start in enumerate(range(0, len(tokens), step)):
        window = tokens[start : start + chunk_size]
        first, last = window[0], window[-1]
        chunks.append(
            DocumentChunk(
                chunk_id=f"{document_id}:{index}",
                document_id=document_id,
                index=index,
                text=text[first.start : last.end],  # slice the ORIGINAL text, keep spacing
                token_count=len(window),
                start_char=first.start,
                end_char=last.end,
                overlap_tokens=0 if index == 0 else chunk_overlap,
            )
        )
        if start + chunk_size >= len(tokens):  # this window reached the end: stop
            break

    return chunks
```

**Why `break`?** Without it, `range(0, len, step)` would produce a few extra tiny windows at the
end that are entirely contained in the previous chunk.

✅ **Checkpoint**
```bash
uv run python -c "
from uuid import uuid4
from app.services.chunker import chunk_text
for c in chunk_text('0 1 2 3 4 5 6 7 8 9', uuid4(), 4, 1):
    print(c.index, repr(c.text), c.start_char, c.end_char, c.overlap_tokens)"
# 0 '0 1 2 3' 0 7 0
# 1 '3 4 5 6' 6 13 1
# 2 '6 7 8 9' 12 19 1
```

## 3.4 `app/services/fetcher.py`: async download with httpx

**Why stream?** `client.get(url)` would load the whole response into memory **before** we could
check its size. Someone could point us at a 5 GB file. With `client.stream`, we read piece by piece and stop
as soon as the limit is crossed.

```python
import logging
from pathlib import Path

import httpx

from app.core.exceptions import DocumentFetchError, FileTooLargeError
from app.models.internal import RawFile

logger = logging.getLogger(__name__)


async def fetch_document(client: httpx.AsyncClient, url: str, max_bytes: int) -> RawFile:
    """Download `url` without blocking the event loop, enforcing a size limit."""
    logger.info("Fetching remote document", extra={"url": url})
    try:
        async with client.stream("GET", url) as response:
            response.raise_for_status()  # turns 4xx/5xx into httpx.HTTPStatusError

            declared = response.headers.get("content-length")
            if declared is not None and int(declared) > max_bytes:
                raise FileTooLargeError(f"Remote file is {declared} bytes (limit {max_bytes})")

            buffer = bytearray()
            async for part in response.aiter_bytes():
                buffer.extend(part)
                if len(buffer) > max_bytes:
                    raise FileTooLargeError(f"Remote file exceeds limit of {max_bytes} bytes")

            content_type = response.headers.get("content-type")
    except httpx.HTTPStatusError as exc:
        raise DocumentFetchError(
            f"Remote server returned {exc.response.status_code} for {url}"
        ) from exc
    except httpx.RequestError as exc:  # DNS failure, timeout, connection refused...
        raise DocumentFetchError(f"Could not download {url}: {exc!r}") from exc

    filename = Path(httpx.URL(url).path).name or "download"
    return RawFile(data=bytes(buffer), filename=filename, content_type=content_type, source_url=url)
```

**Why does it receive `client` as a parameter instead of creating one?** A client keeps a pool of
open connections. Creating one per request is slow. We create **one** at startup (in `main.py`)
and pass it in. That is also what makes this function easy to test with a fake transport (Phase 7).

---

# Phase 4 — Storage

## 4.1 `app/storage/repository.py`

**Why a class?** It hides *how* data is stored. The pipeline calls `save_document(doc)`
and doesn't care whether that writes JSON, SQLite or S3.

```python
import asyncio
import logging
import os
from pathlib import Path
from uuid import UUID

import aiofiles

from app.core.exceptions import DocumentNotFoundError
from app.models.document import IngestedDocument
from app.models.enums import JobState
from app.models.job import IngestionJobStatus

logger = logging.getLogger(__name__)


class DocumentRepository:
    """Stores jobs (memory + JSON) and processed documents (JSON) on local disk."""

    def __init__(self, root: Path) -> None:
        self._root = root
        self._jobs_dir = root / "jobs"
        self._docs_dir = root / "documents"
        self._jobs: dict[UUID, IngestionJobStatus] = {}  # in-memory cache for fast reads

    async def init(self) -> None:
        """Create folders and reload jobs from a previous run."""
        for directory in (self._jobs_dir, self._docs_dir):
            await asyncio.to_thread(directory.mkdir, parents=True, exist_ok=True)

        for path in self._jobs_dir.glob("*.json"):
            job = IngestionJobStatus.model_validate_json(await _read_text(path))
            if job.state in (JobState.PENDING, JobState.PROCESSING):
                # The server stopped while this job was running: it will never finish.
                job = job.model_copy(
                    update={"state": JobState.FAILED, "error": "Interrupted by server restart"}
                )
                await _write_text(path, job.model_dump_json(indent=2))
            self._jobs[job.document_id] = job

        logger.info(
            "Repository ready",
            extra={"storage_dir": str(self._root), "jobs_loaded": len(self._jobs)},
        )

    # ---- jobs -------------------------------------------------------------

    async def save_job(self, job: IngestionJobStatus) -> None:
        self._jobs[job.document_id] = job
        await _write_text(self._jobs_dir / f"{job.document_id}.json", job.model_dump_json(indent=2))

    async def get_job(self, document_id: UUID) -> IngestionJobStatus:
        job = self._jobs.get(document_id)
        if job is None:
            raise DocumentNotFoundError(f"Document {document_id} not found")
        return job

    def job_counts(self) -> dict[str, int]:
        counts = {state.value: 0 for state in JobState}
        for job in self._jobs.values():
            counts[job.state.value] += 1
        return counts

    # ---- documents --------------------------------------------------------

    async def save_document(self, document: IngestedDocument) -> None:
        await _write_text(self._docs_dir / f"{document.id}.json", document.model_dump_json())

    async def get_document(self, document_id: UUID) -> IngestedDocument:
        path = self._docs_dir / f"{document_id}.json"
        if not await asyncio.to_thread(path.exists):
            raise DocumentNotFoundError(f"Document {document_id} has no stored content")
        return IngestedDocument.model_validate_json(await _read_text(path))

    # ---- health -----------------------------------------------------------

    def is_writable(self) -> bool:
        return os.access(self._root, os.W_OK)


async def _read_text(path: Path) -> str:
    async with aiofiles.open(path, encoding="utf-8") as file:
        return await file.read()


async def _write_text(path: Path, content: str) -> None:
    """Atomic write: write a temp file, then rename. Readers never see half a file."""
    tmp_path = path.with_suffix(".tmp")
    async with aiofiles.open(tmp_path, "w", encoding="utf-8") as file:
        await file.write(content)
    await asyncio.to_thread(tmp_path.replace, path)
```

**Key ideas**
* `model_dump_json()` / `model_validate_json()`: Pydantic converts a model to a JSON string and back
  (with validation).
* `model_copy(update={...})`: models are treated as immutable, so you create an updated copy.
* **No lock needed:** all access to `self._jobs` happens on the single event-loop thread, so two
  coroutines can never modify the dict at the exact same moment.

---

# Phase 5 — The pipeline

## 5.1 `app/services/pipeline.py`

**Why:** this is the conductor. It runs the steps in order, keeps the job state up to date, measures
time, logs results, and makes sure **no exception is ever lost**. A background task that raises
with nobody watching just disappears, and the job would stay `processing` forever.

```python
import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import UUID, uuid4

import httpx

from app.core.config import Settings
from app.core.exceptions import DocPulseError, DocumentParseError
from app.models.chunk import ChunkOptions
from app.models.document import IngestedDocument
from app.models.enums import JobState, SourceType
from app.models.internal import RawFile
from app.models.job import IngestionJobStatus
from app.services.chunker import chunk_text
from app.services.fetcher import fetch_document
from app.services.metadata import extract_metadata
from app.services.parsers import detect_document_type, parse_document
from app.storage.repository import DocumentRepository

logger = logging.getLogger(__name__)

# A type alias: "an async function with no arguments that returns a RawFile"
Loader = Callable[[], Awaitable[RawFile]]


class IngestionPipeline:
    def __init__(
        self,
        repository: DocumentRepository,
        http_client: httpx.AsyncClient,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._http = http_client
        self._settings = settings
        # At most N jobs run at the same time; the rest wait at `async with self._semaphore`.
        self._semaphore = asyncio.Semaphore(settings.max_concurrent_jobs)

    async def create_job(self, filename: str, source: SourceType) -> IngestionJobStatus:
        job = IngestionJobStatus(
            document_id=uuid4(),
            state=JobState.PENDING,
            filename=filename,
            source=source,
            created_at=datetime.now(UTC),
        )
        await self._repository.save_job(job)
        logger.info(
            "Job created",
            extra={"document_id": str(job.document_id), "source": source, "file_name": filename},
        )
        return job

    # ---- public entry points (called by BackgroundTasks) -------------------

    async def process_upload(
        self, document_id: UUID, raw_file: RawFile, options: ChunkOptions
    ) -> None:
        async def load() -> RawFile:
            return raw_file  # bytes were already read by the route

        await self._run(document_id, options, load)

    async def process_url(self, document_id: UUID, url: str, options: ChunkOptions) -> None:
        async def load() -> RawFile:
            return await fetch_document(self._http, url, self._settings.max_file_size_bytes)

        await self._run(document_id, options, load)

    # ---- internals --------------------------------------------------------

    async def _run(self, document_id: UUID, options: ChunkOptions, load: Loader) -> None:
        async with self._semaphore:
            log_ctx = {"document_id": str(document_id)}
            await self._update_job(
                document_id, state=JobState.PROCESSING, started_at=datetime.now(UTC)
            )
            started = time.perf_counter()

            try:
                raw_file = await load()
                document = await self._build_document(document_id, raw_file, options)
                await self._repository.save_document(document)
            except DocPulseError as exc:
                # Expected problem (bad PDF, 404 URL, too big): warning, no stack trace needed.
                logger.warning("Ingestion failed", extra={**log_ctx, "error": exc.message})
                await self._fail(document_id, started, exc.message)
                return
            except Exception as exc:
                # Unexpected: a bug. Log the full stack trace so we can fix it.
                logger.exception("Ingestion crashed", extra=log_ctx)
                await self._fail(document_id, started, f"Internal error: {exc!r}")
                return

            elapsed_ms = _elapsed_ms(started)
            logger.info(
                "Ingestion completed",
                extra={
                    **log_ctx,
                    "document_type": document.metadata.document_type,
                    "size_bytes": document.metadata.size_bytes,
                    "chunk_count": document.chunk_count,
                    "processing_time_ms": elapsed_ms,
                },
            )
            await self._update_job(
                document_id,
                state=JobState.COMPLETED,
                finished_at=datetime.now(UTC),
                processing_time_ms=elapsed_ms,
                chunk_count=document.chunk_count,
                metadata=document.metadata,
            )

    async def _build_document(
        self, document_id: UUID, raw_file: RawFile, options: ChunkOptions
    ) -> IngestedDocument:
        document_type = detect_document_type(raw_file.filename, raw_file.content_type)

        # CPU-heavy steps run in a worker thread so the event loop stays free.
        parsed = await asyncio.to_thread(parse_document, raw_file.data, document_type)
        if not parsed.text.strip():
            raise DocumentParseError("Document contains no extractable text (scanned PDF?)")

        metadata = extract_metadata(parsed, raw_file)
        chunks = await asyncio.to_thread(
            chunk_text, parsed.text, document_id, options.chunk_size, options.chunk_overlap
        )
        return IngestedDocument(
            id=document_id,
            metadata=metadata,
            chunk_size=options.chunk_size,
            chunk_overlap=options.chunk_overlap,
            chunk_count=len(chunks),
            chunks=chunks,
            created_at=datetime.now(UTC),
        )

    async def _fail(self, document_id: UUID, started: float, error: str) -> None:
        await self._update_job(
            document_id,
            state=JobState.FAILED,
            finished_at=datetime.now(UTC),
            processing_time_ms=_elapsed_ms(started),
            error=error,
        )

    async def _update_job(self, document_id: UUID, **changes: object) -> None:
        job = await self._repository.get_job(document_id)
        await self._repository.save_job(job.model_copy(update=changes))


def _elapsed_ms(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
```

**Key ideas**
* **`load` functions:** upload and URL differ in only **one step**, getting the bytes. Instead of
  duplicating `_run`, each entry point passes a small async function that knows how to get them.
  Functions are values in Python; you can pass them around like any other variable.
* **`asyncio.to_thread(func, arg1, arg2)`:** runs `func(arg1, arg2)` in a thread and lets you `await` the result.
* **`time.perf_counter()`:** a high-precision clock meant for measuring durations. Don't use `time.time()` for that.
* **`**changes`:** collects keyword arguments into a dict, e.g. `{"state": ..., "error": ...}`.

---

# Phase 6 — API layer and the app

## 6.1 `app/api/dependencies.py`

**Why:** FastAPI's **dependency injection**. A route *declares* what it needs
(`pipeline: PipelineDep`) and FastAPI provides it. Routes never create objects themselves,
and tests can swap the real objects for fakes.

```python
from typing import Annotated, cast

from fastapi import Depends, Request
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.exceptions import InvalidChunkOptionsError
from app.models.chunk import ChunkOptions
from app.services.pipeline import IngestionPipeline
from app.storage.repository import DocumentRepository


def get_repository(request: Request) -> DocumentRepository:
    # Objects created at startup (lifespan) are stored on app.state.
    return cast(DocumentRepository, request.app.state.repository)


def get_pipeline(request: Request) -> IngestionPipeline:
    return cast(IngestionPipeline, request.app.state.pipeline)


# Reusable shortcuts: `settings: SettingsDep` in a route signature = "inject the settings".
SettingsDep = Annotated[Settings, Depends(get_settings)]
RepositoryDep = Annotated[DocumentRepository, Depends(get_repository)]
PipelineDep = Annotated[IngestionPipeline, Depends(get_pipeline)]


def build_chunk_options(
    chunk_size: int | None, chunk_overlap: int | None, settings: Settings
) -> ChunkOptions:
    """Use the client's values if given, otherwise the defaults from settings."""
    try:
        return ChunkOptions(
            chunk_size=chunk_size if chunk_size is not None else settings.default_chunk_size,
            chunk_overlap=(
                chunk_overlap if chunk_overlap is not None else settings.default_chunk_overlap
            ),
        )
    except ValidationError as exc:
        raise InvalidChunkOptionsError(exc.errors()[0]["msg"]) from exc
```

**Why `cast`?** `app.state` can hold anything, so its type is `Any`. `cast` tells mypy what's in
there. It does nothing at runtime.

## 6.2 `app/api/routes/health.py`

```python
import os
import platform
import time
from typing import cast

from fastapi import APIRouter, Request

from app.api.dependencies import RepositoryDep, SettingsDep
from app.models.api import ConfigSummary, HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health")
async def health(
    request: Request, settings: SettingsDep, repository: RepositoryDep
) -> HealthResponse:
    started_at = cast(float, request.app.state.started_at)
    writable = repository.is_writable()
    return HealthResponse(
        status="ok" if writable else "degraded",
        app_name=settings.app_name,
        version=settings.app_version,
        uptime_seconds=round(time.monotonic() - started_at, 2),
        python_version=platform.python_version(),
        platform=platform.platform(),
        cpu_count=os.cpu_count() or 1,
        storage_writable=writable,
        jobs=repository.job_counts(),
        config=ConfigSummary(
            environment=settings.environment,
            max_file_size_mb=settings.max_file_size_mb,
            default_chunk_size=settings.default_chunk_size,
            default_chunk_overlap=settings.default_chunk_overlap,
            max_concurrent_jobs=settings.max_concurrent_jobs,
            log_level=settings.log_level,
        ),
    )
```

**Note:** the return type `-> HealthResponse` is also used by FastAPI as the **response model**.
It validates the output and documents it in Swagger. You don't need `response_model=`.

## 6.3 `app/api/routes/documents.py`

```python
import math
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, File, Form, Query, UploadFile, status

from app.api.dependencies import PipelineDep, RepositoryDep, SettingsDep, build_chunk_options
from app.core.exceptions import DocumentNotReadyError, DocumentParseError, FileTooLargeError
from app.models.api import ChunkPage, IngestAcceptedResponse, IngestUrlRequest
from app.models.enums import JobState, SourceType
from app.models.internal import RawFile
from app.models.job import IngestionJobStatus
from app.services.parsers import detect_document_type

router = APIRouter(prefix="/documents", tags=["documents"])


@router.post("/upload", status_code=status.HTTP_202_ACCEPTED)
async def upload_document(
    background_tasks: BackgroundTasks,
    pipeline: PipelineDep,
    settings: SettingsDep,
    file: Annotated[UploadFile, File(description="A .pdf, .md or .txt file")],
    chunk_size: Annotated[int | None, Form()] = None,
    chunk_overlap: Annotated[int | None, Form()] = None,
) -> IngestAcceptedResponse:
    # 1. Validate cheap things first and fail fast, before reading the whole file.
    options = build_chunk_options(chunk_size, chunk_overlap, settings)
    filename = file.filename or "upload"
    detect_document_type(filename, file.content_type)  # raises 415 if unsupported

    # 2. Read at most limit+1 bytes: if we got more than the limit, the file is too big.
    max_bytes = settings.max_file_size_bytes
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise FileTooLargeError(f"File exceeds {settings.max_file_size_mb} MB")
    if not data:
        raise DocumentParseError("Uploaded file is empty")

    # 3. Create the job and schedule the work to run AFTER the response is sent.
    job = await pipeline.create_job(filename, SourceType.UPLOAD)
    raw_file = RawFile(data=data, filename=filename, content_type=file.content_type)
    background_tasks.add_task(pipeline.process_upload, job.document_id, raw_file, options)
    return _accepted(job)


@router.post("/ingest-url", status_code=status.HTTP_202_ACCEPTED)
async def ingest_url(
    body: IngestUrlRequest,  # a Pydantic model param = JSON request body
    background_tasks: BackgroundTasks,
    pipeline: PipelineDep,
    settings: SettingsDep,
) -> IngestAcceptedResponse:
    options = build_chunk_options(body.chunk_size, body.chunk_overlap, settings)
    url = str(body.url)
    job = await pipeline.create_job(url, SourceType.URL)
    background_tasks.add_task(pipeline.process_url, job.document_id, url, options)
    return _accepted(job)


@router.get("/{document_id}")
async def get_document_status(document_id: UUID, repository: RepositoryDep) -> IngestionJobStatus:
    return await repository.get_job(document_id)


@router.get("/{document_id}/chunks")
async def get_document_chunks(
    document_id: UUID,
    repository: RepositoryDep,
    page: Annotated[int, Query(ge=1, description="1-based page number")] = 1,
    size: Annotated[int, Query(ge=1, le=100, description="Chunks per page")] = 20,
) -> ChunkPage:
    job = await repository.get_job(document_id)
    if job.state != JobState.COMPLETED:
        raise DocumentNotReadyError(f"Document {document_id} is '{job.state}', not completed")

    document = await repository.get_document(document_id)
    total = len(document.chunks)
    start = (page - 1) * size
    return ChunkPage(
        document_id=document_id,
        page=page,
        size=size,
        total_chunks=total,
        total_pages=math.ceil(total / size),
        items=document.chunks[start : start + size],
    )


def _accepted(job: IngestionJobStatus) -> IngestAcceptedResponse:
    return IngestAcceptedResponse(
        document_id=job.document_id,
        state=job.state,
        status_url=f"/documents/{job.document_id}",
        chunks_url=f"/documents/{job.document_id}/chunks",
    )
```

**Key ideas: where does FastAPI take each parameter from?**

| Parameter declaration                     | Comes from                         |
|-------------------------------------------|------------------------------------|
| `document_id: UUID` (name is in the path) | URL path `/documents/{document_id}`; invalid UUID gives 422 automatically |
| `Annotated[int, Query(...)]`              | query string `?page=2&size=10`      |
| `Annotated[UploadFile, File()]`           | multipart file field                |
| `Annotated[int \| None, Form()]`          | multipart text field                |
| `body: IngestUrlRequest` (Pydantic model) | JSON body                           |
| `BackgroundTasks`, `Request`              | injected by FastAPI                 |
| `X: SomethingDep`                         | your `Depends(...)` function        |

**Why must the upload bytes be read inside the route?** The `UploadFile` is closed once the
response is sent, so the background task can't read it later. We pass plain `bytes` instead.

## 6.4 `app/main.py`: wiring everything together

**Why `lifespan`?** Some objects must be created **once** when the server starts and cleaned up when it
stops: the httpx client (an open connection pool), the repository (folders, reloaded jobs) and the pipeline (semaphore).

```python
import logging
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.api.routes import documents, health
from app.core.config import get_settings
from app.core.exceptions import DocPulseError
from app.core.logging import setup_logging
from app.services.pipeline import IngestionPipeline
from app.storage.repository import DocumentRepository

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # ---- startup: runs once before the first request ----
    settings = get_settings()
    repository = DocumentRepository(settings.storage_dir)
    await repository.init()

    async with httpx.AsyncClient(
        timeout=settings.http_timeout_seconds, follow_redirects=True
    ) as http_client:
        app.state.repository = repository
        app.state.pipeline = IngestionPipeline(repository, http_client, settings)
        app.state.started_at = time.monotonic()
        logger.info(
            "DocPulse started",
            extra={"environment": settings.environment, "config": settings.model_dump(mode="json")},
        )
        yield  # ---- the app serves requests while we are paused here ----

    # ---- shutdown: the `async with` above already closed the http client ----
    logger.info("DocPulse stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    setup_logging(settings.log_level, settings.log_format)

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Asynchronous document ingestion and chunking service",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def log_requests(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        started = time.perf_counter()
        response = await call_next(request)  # run the actual route
        logger.info(
            "HTTP request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status_code": response.status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
            },
        )
        return response

    @app.exception_handler(DocPulseError)
    async def handle_docpulse_error(request: Request, exc: DocPulseError) -> JSONResponse:
        logger.warning(
            "Request failed",
            extra={"path": request.url.path, "error": type(exc).__name__, "detail": exc.message},
        )
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": type(exc).__name__, "detail": exc.message},
        )

    @app.exception_handler(Exception)
    async def handle_unexpected_error(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled error", extra={"path": request.url.path})
        # Never leak internal details (stack traces) to clients.
        return JSONResponse(
            status_code=500,
            content={"error": "InternalServerError", "detail": "Unexpected error"},
        )

    app.include_router(health.router)
    app.include_router(documents.router)
    return app


app = create_app()  # uvicorn looks for this: `uvicorn app.main:app`
```

**Why a `create_app()` factory?** Tests can build a **fresh** app with different settings
(e.g. a temporary storage folder). This is the "application factory" pattern.

✅ **Checkpoint: run it!**
```bash
uv run uvicorn app.main:app --reload --no-access-log
```
* `--reload`: restarts the server when you save a file (development only).
* `--no-access-log`: our middleware already logs every request.

Open **http://127.0.0.1:8000/docs**. This is the interactive Swagger UI, where you can call every endpoint from the browser.

**Try it with curl (in a second terminal):**
```bash
# health
curl -s localhost:8000/health | python3 -m json.tool

# upload a file
curl -s -F "file=@samples/readme.md" -F chunk_size=50 -F chunk_overlap=10 \
     localhost:8000/documents/upload
# -> {"document_id":"<ID>","state":"pending","status_url":"/documents/<ID>", ...}

# check status (replace <ID>)
curl -s localhost:8000/documents/<ID> | python3 -m json.tool

# read chunks, page 1, 5 per page
curl -s "localhost:8000/documents/<ID>/chunks?page=1&size=5" | python3 -m json.tool

# ingest from a URL
curl -s -X POST localhost:8000/documents/ingest-url \
     -H "Content-Type: application/json" \
     -d '{"url": "https://raw.githubusercontent.com/fastapi/fastapi/master/README.md"}'

# error cases: see the status codes
curl -s -F "file=@/bin/ls;filename=ls.exe" localhost:8000/documents/upload        # 415
curl -s -F "file=@samples/notes.txt" -F chunk_size=10 -F chunk_overlap=10 \
     localhost:8000/documents/upload                                              # 422
curl -s localhost:8000/documents/00000000-0000-0000-0000-000000000000             # 404
```

**See concurrency with your own eyes:** set `MAX_CONCURRENT_JOBS=1` in `.env`, then upload
several files at once and watch the logs. The jobs finish one after another, while `/health`
keeps answering instantly.
```bash
for i in 1 2 3 4 5; do curl -s -F "file=@samples/notes.txt" localhost:8000/documents/upload & done; wait
```

Look in `data/jobs/` and `data/documents/` to see the stored JSON.

---

# Phase 7 — Tests

**Why:** tests prove your code works **and keep proving it** every time you change something.

## 7.1 `tests/conftest.py`: shared fixtures

```python
from collections.abc import Iterator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import create_app


@pytest.fixture
def client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Iterator[TestClient]:
    """A test client backed by a fresh app that stores data in a temporary folder."""
    monkeypatch.setenv("STORAGE_DIR", str(tmp_path))  # env vars beat .env values
    monkeypatch.setenv("LOG_FORMAT", "text")
    monkeypatch.setenv("ENVIRONMENT", "test")
    get_settings.cache_clear()  # forget cached settings so the new env vars are used

    with TestClient(create_app()) as test_client:  # `with` runs the lifespan (startup/shutdown)
        yield test_client

    get_settings.cache_clear()
```

**Fixtures** are pytest's dependency injection: a test that has a `client` parameter receives
what this function yields. `tmp_path` and `monkeypatch` are built-in fixtures.

## 7.2 `tests/test_chunker.py`

```python
from uuid import uuid4

import pytest

from app.services.chunker import chunk_text

TEXT = " ".join(str(i) for i in range(10))  # "0 1 2 3 4 5 6 7 8 9"


def test_empty_text_gives_no_chunks() -> None:
    assert chunk_text("   ", uuid4(), chunk_size=4, chunk_overlap=1) == []


def test_sliding_window_with_overlap() -> None:
    chunks = chunk_text(TEXT, uuid4(), chunk_size=4, chunk_overlap=1)
    assert [c.text for c in chunks] == ["0 1 2 3", "3 4 5 6", "6 7 8 9"]
    assert [c.overlap_tokens for c in chunks] == [0, 1, 1]


def test_offsets_point_into_original_text() -> None:
    text = "Hello   world,\n\nthis is   DocPulse speaking."
    for chunk in chunk_text(text, uuid4(), chunk_size=3, chunk_overlap=1):
        assert text[chunk.start_char : chunk.end_char] == chunk.text


def test_short_text_is_single_chunk() -> None:
    chunks = chunk_text("just three words", uuid4(), chunk_size=100, chunk_overlap=10)
    assert len(chunks) == 1
    assert chunks[0].token_count == 3


@pytest.mark.parametrize(("size", "overlap"), [(0, 0), (5, 5), (5, -1)])
def test_invalid_options_raise(size: int, overlap: int) -> None:
    with pytest.raises(ValueError):
        chunk_text(TEXT, uuid4(), chunk_size=size, chunk_overlap=overlap)
```

## 7.3 `tests/test_parsers.py`

```python
import pytest

from app.core.exceptions import UnsupportedFileTypeError
from app.models.enums import DocumentType
from app.services.parsers import detect_document_type, parse_document


@pytest.mark.parametrize(
    ("filename", "content_type", "expected"),
    [
        ("a.pdf", None, DocumentType.PDF),
        ("a.MD", None, DocumentType.MARKDOWN),
        ("notes.txt", None, DocumentType.TEXT),
        ("download", "text/plain; charset=utf-8", DocumentType.TEXT),
    ],
)
def test_detect_document_type(
    filename: str, content_type: str | None, expected: DocumentType
) -> None:
    assert detect_document_type(filename, content_type) == expected


def test_detect_unsupported_type() -> None:
    with pytest.raises(UnsupportedFileTypeError):
        detect_document_type("virus.exe", "application/octet-stream")


def test_markdown_title_is_first_heading() -> None:
    parsed = parse_document(b"intro\n# My Title\n## Sub\nbody", DocumentType.MARKDOWN)
    assert parsed.title == "My Title"
```

## 7.4 `tests/test_fetcher.py`: testing httpx without the internet

`httpx.MockTransport` lets you plug in a fake server: a function that receives the request and
returns a response. No network is used, so tests are fast and reliable.

```python
import httpx
import pytest

from app.core.exceptions import DocumentFetchError, FileTooLargeError
from app.services.fetcher import fetch_document


def _client(status: int, body: bytes, content_type: str = "text/plain") -> httpx.AsyncClient:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, content=body, headers={"content-type": content_type})

    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


async def test_fetch_success() -> None:
    async with _client(200, b"hello world") as client:
        raw = await fetch_document(client, "https://example.com/files/notes.txt", max_bytes=1024)
    assert raw.data == b"hello world"
    assert raw.filename == "notes.txt"
    assert raw.source_url == "https://example.com/files/notes.txt"


async def test_fetch_too_large() -> None:
    async with _client(200, b"x" * 2048) as client:
        with pytest.raises(FileTooLargeError):
            await fetch_document(client, "https://example.com/big.txt", max_bytes=1024)


async def test_fetch_http_error() -> None:
    async with _client(404, b"not found") as client:
        with pytest.raises(DocumentFetchError):
            await fetch_document(client, "https://example.com/missing.txt", max_bytes=1024)
```

## 7.5 `tests/test_api.py`: end-to-end through HTTP

`TestClient` waits for background tasks to finish before `post()` returns, so the job is already
complete when we check it.

```python
from uuid import uuid4

from fastapi.testclient import TestClient


def test_health(client: TestClient) -> None:
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_upload_then_read_chunks(client: TestClient) -> None:
    content = " ".join(f"word{i}" for i in range(500)).encode()
    response = client.post(
        "/documents/upload",
        files={"file": ("sample.txt", content, "text/plain")},
        data={"chunk_size": "100", "chunk_overlap": "20"},
    )
    assert response.status_code == 202
    document_id = response.json()["document_id"]

    job = client.get(f"/documents/{document_id}").json()
    assert job["state"] == "completed"
    assert job["chunk_count"] == 6  # 500 tokens, step 80: windows start at 0,80,160,240,320,400
    assert job["metadata"]["word_count"] == 500

    page = client.get(f"/documents/{document_id}/chunks", params={"page": 2, "size": 4}).json()
    assert page["total_pages"] == 2
    assert len(page["items"]) == 2
    assert page["items"][0]["index"] == 4


def test_unsupported_file_type(client: TestClient) -> None:
    response = client.post(
        "/documents/upload", files={"file": ("tool.exe", b"MZ...", "application/octet-stream")}
    )
    assert response.status_code == 415
    assert response.json()["error"] == "UnsupportedFileTypeError"


def test_invalid_chunk_options(client: TestClient) -> None:
    response = client.post(
        "/documents/upload",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"chunk_size": "10", "chunk_overlap": "10"},
    )
    assert response.status_code == 422


def test_unknown_document(client: TestClient) -> None:
    assert client.get(f"/documents/{uuid4()}").status_code == 404


def test_page_size_validation(client: TestClient) -> None:
    response = client.get(f"/documents/{uuid4()}/chunks", params={"size": 1000})
    assert response.status_code == 422  # size must be <= 100
```

✅ **Checkpoint**
```bash
uv run pytest -v
```

---

# Phase 8 — Quality gates

```bash
uv run ruff format .        # auto-format the code
uv run ruff check . --fix   # lint and auto-fix simple issues
uv run mypy app tests       # strict type checking
uv run pytest               # tests
```

Run all four before every commit. When all four pass, you have met the
"strict type annotations across the entire codebase" requirement.

Common mypy messages for beginners:
* `Function is missing a return type annotation`: add `-> None` (or the real type).
* `Returning Any from function declared to return "X"`: use `cast(X, value)` (see `dependencies.py`).
* `Item "None" of "X | None" has no attribute ...`: check `if value is not None:` first.

---

# Phase 9 — (Optional) Docker

`Dockerfile` in the project root:

```dockerfile
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /srv

# Install dependencies first (cached layer, rebuilt only when the lock file changes)
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

COPY app ./app
ENV PATH="/srv/.venv/bin:$PATH" \
    LOG_FORMAT=json \
    ENVIRONMENT=production

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
```

```bash
docker build -t docpulse .
docker run -p 8000:8000 -v "$PWD/data:/srv/data" docpulse
```

---

# Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ModuleNotFoundError: No module named 'app'` | Run commands from the project root, and check that every folder has an `__init__.py` |
| `Form data requires "python-multipart"` | `uv add python-multipart` |
| `KeyError: "Attempt to overwrite 'filename' in LogRecord"` | Rename that `extra` key (use `file_name`) |
| Job stays `pending` forever | An exception escaped in the background task; check the logs, and make sure `_run` has both `except` blocks |
| `/health` is slow while a big PDF processes | A blocking call is running on the event loop; wrap it in `asyncio.to_thread` |
| Settings changes ignored in tests | Call `get_settings.cache_clear()` (it's `lru_cache`d) |
| PDF ingests but `"no extractable text"` | It's a scanned image PDF; it needs OCR (out of scope) |
| pytest prints `StarletteDeprecationWarning: Using httpx with starlette.testclient is deprecated` | Harmless warning from a newer Starlette; tests still pass. Ignore it for now |
| `SyntaxError` on `str \| None` | You're on Python < 3.10; use `uv run ...` so the 3.12 environment is used |

---

# Stretch goals (after everything is green)

1. **Duplicate detection:** if the `content_sha256` of an upload was already ingested, return the existing `document_id`.
2. **Real tokens:** use `tiktoken` so `token_count` matches what an embedding model sees.
3. **Sentence-aware chunking:** try to end chunks at `.`, `!` or `?` when one is near the window edge.
4. **`GET /documents`:** list all jobs with filtering by `state` and pagination.
5. **SQLite storage:** write `SqliteRepository` (with `aiosqlite`) that has the same methods, and switch to it in `main.py`.
6. **Request IDs:** generate a UUID per request in the middleware, return it in an `X-Request-ID` header, and include it in every log line (`contextvars`).
7. **SSRF protection:** reject URLs that resolve to private IP addresses before fetching.
8. **Real worker queue:** move processing out of the API process with `arq` + Redis.
