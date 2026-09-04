"""Text extraction for the RAG ingestion pipeline — PDF, DOCX, TXT, Markdown."""
from __future__ import annotations

from pathlib import Path

SUPPORTED_EXTENSIONS = {".pdf", ".docx", ".txt", ".md", ".markdown"}


def extract_text(file_path: str | Path, raw_bytes: bytes | None = None) -> str:
    path = Path(file_path)
    ext = path.suffix.lower()

    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type '{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}")

    if ext == ".pdf":
        return _extract_pdf(path, raw_bytes)
    if ext == ".docx":
        return _extract_docx(path, raw_bytes)
    # .txt / .md / .markdown
    if raw_bytes is not None:
        return raw_bytes.decode("utf-8", errors="replace")
    return path.read_text(encoding="utf-8", errors="replace")


def _extract_pdf(path: Path, raw_bytes: bytes | None) -> str:
    from pypdf import PdfReader
    import io

    reader = PdfReader(io.BytesIO(raw_bytes) if raw_bytes is not None else str(path))
    return "\n\n".join(page.extract_text() or "" for page in reader.pages)


def _extract_docx(path: Path, raw_bytes: bytes | None) -> str:
    import docx
    import io

    document = docx.Document(io.BytesIO(raw_bytes) if raw_bytes is not None else str(path))
    return "\n\n".join(p.text for p in document.paragraphs if p.text.strip())
