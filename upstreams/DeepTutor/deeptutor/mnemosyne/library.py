"""UNIT-01: adapter to real ReadingStore/PyMuPDF; no replacement database."""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import asyncio
import hashlib
import inspect
import json
import math
import os
from pathlib import Path
import re
import secrets
import sqlite3
import time
from typing import Any, Callable, Iterator, Sequence
import unicodedata
from urllib.parse import urlsplit
import uuid

from deeptutor.reading.service import search_material
from deeptutor.reading.store import ReadingStore


def locator_for_page(page_index: int) -> int:
    if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0:
        raise ValueError("Invalid physical page index")
    return page_index + 1


def viewport_point(point: list[float], geometry: dict[str, Any], *, inverse=False) -> list[float]:
    """Physical points at scale 1, origin at rotated CropBox top left."""
    x0, y0, x1, y1 = geometry["crop_box"]
    w, h = x1 - x0, y1 - y0
    unit, rotation = geometry["user_unit"], geometry["rotation_degrees"]
    if (
        not all(math.isfinite(v) for v in [*point, x0, y0, x1, y1, unit])
        or unit <= 0
        or w <= 0
        or h <= 0
    ):
        raise ValueError("Invalid PDF geometry")
    if inverse:
        X, Y = (v / unit for v in point)
        u, v = {0: (X, h - Y), 90: (Y, X), 180: (w - X, Y), 270: (w - Y, h - X)}[rotation]
        return [u + x0, v + y0]
    u, v = point[0] - x0, point[1] - y0
    X, Y = {0: (u, h - v), 90: (v, u), 180: (w - u, v), 270: (h - v, w - u)}[rotation]
    return [X * unit, Y * unit]


def normalized_rect_to_pdf(rect: list[float], geometry: dict[str, Any]) -> list[float]:
    """DeepTutor Rect is normalized rotated render bounds, x0/y0/x1/y1."""
    x0, y0, x1, y1 = rect
    if not (0 <= x0 < x1 <= 1 and 0 <= y0 < y1 <= 1):
        raise ValueError("Invalid normalized rectangle")
    llx, lly, urx, ury = geometry["crop_box"]
    w, h = urx - llx, ury - lly
    if geometry["rotation_degrees"] in (90, 270):
        w, h = h, w
    w *= geometry["user_unit"]
    h *= geometry["user_unit"]
    points = [
        viewport_point([x * w, y * h], geometry, inverse=True)
        for x, y in [(x0, y0), (x0, y1), (x1, y0), (x1, y1)]
    ]
    xs, ys = zip(*points)
    return [min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys)]


def extract_pdf_pages(
    path: Path,
    document_id: str,
    version_id: str,
    *,
    segment_mode: str = "blocks",
) -> list[dict[str, Any]]:
    """Exact text + geometry adapter. Paths come from trusted repository lookup.

    This small boundary currently addresses complete extracted text blocks.
    UNIT-01 must add char/quad spans for partial selections, OCR and RAG blocks.
    """
    import pymupdf

    from deeptutor.reading.extract import extract_material

    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if version_id != "sha256:" + digest:
        raise ValueError("Original version mismatch")
    extraction = extract_material(path)
    pages = []
    with pymupdf.open(path) as pdf:
        for index, page in enumerate(pdf):
            # PyMuPDF cropbox is top-left MediaBox-relative; contract box is raw PDF.
            media = list(page.mediabox)
            crop = list(page.cropbox)
            raw_crop = [crop[0], media[3] - crop[3], crop[2], media[3] - crop[1]]
            _, raw_unit = pdf.xref_get_key(page.xref, "UserUnit")
            unit = 1.0 if raw_unit == "null" else float(raw_unit)
            text = unicodedata.normalize(
                "NFC", extraction.units[index].replace("\r\n", "\n").replace("\r", "\n")
            )
            segments, offset = [], 0
            if segment_mode not in {"blocks", "words"}:
                raise ValueError("segment_mode must be 'blocks' or 'words'")
            source_segments = (
                page.get_text("blocks")
                if segment_mode == "blocks"
                else page.get_text("words")
            )
            for source_segment in source_segments:
                if segment_mode == "blocks":
                    if source_segment[6] != 0:
                        continue
                    segment_text = unicodedata.normalize("NFC", source_segment[4]).rstrip("\n")
                    bx0, by0, bx1, by1 = source_segment[:4]
                else:
                    segment_text = unicodedata.normalize("NFC", source_segment[4])
                    bx0, by0, bx1, by1 = source_segment[:4]
                start = text.find(segment_text, offset)
                if start < 0:
                    if segment_mode == "blocks":
                        raise ValueError("Parser block/text mismatch")
                    # Some PDF extractors emit a ligature or a combining mark
                    # differently in the word list. Keep page text available,
                    # but never invent offsets for that word.
                    continue
                # PyMuPDF boxes are unrotated, crop-relative top-left points.
                rect = [
                    raw_crop[0] + bx0 / unit,
                    raw_crop[3] - by1 / unit,
                    (bx1 - bx0) / unit,
                    (by1 - by0) / unit,
                ]
                end = start + len(segment_text)
                if end > start:
                    segments.append(
                        {
                            "start_scalar": start,
                            "end_scalar": end,
                            "rect": [round(v, 6) for v in rect],
                        }
                    )
                offset = end
            pages.append(
                {
                    "document_id": document_id,
                    "version_id": version_id,
                    "page_index": index,
                    "display_page_number": index + 1,
                    "display_label": page.get_label() or str(index + 1),
                    "parse_revision": "pymupdf-" + pymupdf.VersionBind + "-nfc-1",
                    "text_basis": "parser:nfc-lf-v1",
                    "text": text,
                    "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
                    "geometry": {
                        "media_box": media,
                        "crop_box": raw_crop,
                        "rotation_degrees": page.rotation,
                        "user_unit": unit,
                    },
                    "segments": segments,
                }
            )
    return pages


CONTRACT_VERSION = "0.1.0"
MAX_PDF_BYTES = 100 * 1024 * 1024
_SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
_LANGUAGE_RE = re.compile(r"^(und|[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*)$")
_ANNOTATION_KINDS = frozenset({"highlight", "note", "bookmark", "ink"})
_UNSET = object()


class LibraryError(ValueError):
    """A user-correctable document, sync or citation error."""


class CursorExpired(LibraryError):
    """A sync cursor is unknown, expired, or belongs to another document."""


class DocumentDeleted(LibraryError):
    """The requested document has a retained deletion tombstone."""


class RevisionConflict(LibraryError):
    """A document metadata write did not match its If-Match revision."""

    def __init__(self, message: str, current_revision: int) -> None:
        super().__init__(message)
        self.current_revision = current_revision


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _uuid(value: Any, label: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise LibraryError(f"invalid {label} UUID") from exc


def _version(value: Any) -> str:
    candidate = str(value or "")
    if not candidate.startswith("sha256:") or not _SHA256_RE.fullmatch(candidate[7:]):
        raise LibraryError("invalid document version")
    return candidate


def _safe_filename(value: str) -> str:
    candidate = str(value or "").replace("\\", "/").split("/")[-1].strip()
    candidate = "".join(ch for ch in candidate if ch >= " " and ch not in "\x7f")
    if not candidate or candidate in {".", ".."} or not candidate.lower().endswith(".pdf"):
        raise LibraryError("only PDF files are accepted")
    if len(candidate) > 240:
        candidate = candidate[-240:]
    return candidate


def _canonical_json(value: Any) -> bytes:
    """Canonicalize JSON objects and compare finite numbers mathematically."""
    def number_text(number: int | float) -> str:
        try:
            decimal = Decimal(str(number))
        except InvalidOperation as exc:
            raise LibraryError("invalid JSON number") from exc
        if not decimal.is_finite():
            raise LibraryError("non-finite values are not JSON")
        if decimal == 0:
            return "0"
        sign, digits, exponent = decimal.as_tuple()
        digits = list(digits)
        while digits and digits[-1] == 0:
            digits.pop()
            exponent += 1
        value_text = "".join(str(digit) for digit in digits)
        if exponent >= 0:
            value_text += "0" * exponent
        else:
            split = len(value_text) + exponent
            if split > 0:
                value_text = value_text[:split] + "." + value_text[split:]
            else:
                value_text = "0." + "0" * (-split) + value_text
        return ("-" if sign else "") + value_text

    def normalize(item: Any) -> Any:
        if item is None or isinstance(item, (str, bool)):
            return item
        if isinstance(item, (int, float)):
            if isinstance(item, float) and not math.isfinite(item):
                raise LibraryError("non-finite values are not JSON")
            return {"$number": number_text(item)}
        if isinstance(item, list):
            return [normalize(child) for child in item]
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise LibraryError("JSON object keys must be strings")
            return {key: normalize(item[key]) for key in sorted(item)}
        raise LibraryError("value is not JSON")

    return json.dumps(normalize(value), ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def _find_casefold_span(text: str, needle: str, near: int = 0) -> tuple[int, int] | None:
    """Find a case-insensitive match while preserving source scalar offsets."""
    wanted = unicodedata.normalize("NFC", needle).casefold()
    if not wanted:
        return None
    folded_parts: list[str] = []
    source_starts: list[int] = []
    source_ends: list[int] = []
    for index, character in enumerate(text):
        folded = character.casefold()
        folded_parts.append(folded)
        source_starts.extend([index] * len(folded))
        source_ends.extend([index + 1] * len(folded))
    folded_text = "".join(folded_parts)
    matches: list[tuple[int, int]] = []
    position = folded_text.find(wanted)
    while position >= 0:
        end = position + len(wanted)
        matches.append((source_starts[position], source_ends[end - 1]))
        position = folded_text.find(wanted, position + 1)
    if not matches:
        return None
    return min(matches, key=lambda span: (abs(span[0] - near), span[0]))


class _LibraryDatabase:
    """Versioned SQLite persistence for Mnemosyne's stable IDs and sync log."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "_mnemosyne.sqlite3"
        self.originals = self.root / "mnemosyne-originals"
        self.originals.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.exports = self.root / "mnemosyne-exports"
        self.exports.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.originals, 0o700)
        os.chmod(self.exports, 0o700)
        descriptor = os.open(self.db_path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(descriptor)
        os.chmod(self.db_path, 0o600)
        self._migrate()

    @contextmanager
    def connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()
            self._secure_db_permissions()

    def _secure_db_permissions(self) -> None:
        for path in (self.db_path, Path(f"{self.db_path}-wal"), Path(f"{self.db_path}-shm")):
            if path.exists():
                os.chmod(path, 0o600)

    def _migrate(self) -> None:
        with sqlite3.connect(self.db_path, timeout=30) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA synchronous=FULL")
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS mnemosyne_schema (
                    version INTEGER NOT NULL
                );
                INSERT INTO mnemosyne_schema(version)
                    SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM mnemosyne_schema);
                UPDATE mnemosyne_schema SET version=3 WHERE version<3;

                CREATE TABLE IF NOT EXISTS mnemosyne_subjects (
                    subject_id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    server_revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE TABLE IF NOT EXISTS mnemosyne_documents (
                    document_id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    subject_id TEXT REFERENCES mnemosyne_subjects(subject_id) ON DELETE SET NULL,
                    content_language TEXT NOT NULL DEFAULT 'und',
                    server_revision INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );
                CREATE INDEX IF NOT EXISTS idx_mnemo_documents_subject
                    ON mnemosyne_documents(subject_id, updated_at DESC);
                CREATE TABLE IF NOT EXISTS mnemosyne_versions (
                    document_id TEXT NOT NULL REFERENCES mnemosyne_documents(document_id),
                    version_id TEXT NOT NULL,
                    source_sha256 TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    material_id TEXT,
                    page_count INTEGER NOT NULL DEFAULT 0,
                    parse_revision TEXT,
                    parse_state TEXT NOT NULL,
                    parse_error_code TEXT NOT NULL DEFAULT '',
                    parse_error_detail TEXT NOT NULL DEFAULT '',
                    index_state TEXT NOT NULL,
                    index_error_code TEXT NOT NULL DEFAULT '',
                    index_error_detail TEXT NOT NULL DEFAULT '',
                    index_kb TEXT,
                    index_started_at REAL,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY(document_id, version_id)
                );
                CREATE INDEX IF NOT EXISTS idx_mnemo_versions_sha
                    ON mnemosyne_versions(source_sha256);
                CREATE TABLE IF NOT EXISTS mnemosyne_pages (
                    document_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    page_index INTEGER NOT NULL,
                    parse_revision TEXT NOT NULL,
                    page_json TEXT NOT NULL,
                    PRIMARY KEY(document_id, version_id, page_index, parse_revision),
                    FOREIGN KEY(document_id, version_id)
                        REFERENCES mnemosyne_versions(document_id, version_id)
                );
                CREATE TABLE IF NOT EXISTS mnemosyne_assets (
                    document_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    page_index INTEGER NOT NULL,
                    mime TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    data BLOB NOT NULL,
                    PRIMARY KEY(document_id, version_id, asset_id),
                    FOREIGN KEY(document_id, version_id)
                        REFERENCES mnemosyne_versions(document_id, version_id)
                );
                CREATE TABLE IF NOT EXISTS mnemosyne_annotation_clock (
                    document_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    revision INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(document_id, version_id),
                    FOREIGN KEY(document_id, version_id)
                        REFERENCES mnemosyne_versions(document_id, version_id)
                );
                CREATE TABLE IF NOT EXISTS mnemosyne_annotations (
                    document_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    annotation_id TEXT NOT NULL,
                    server_revision INTEGER NOT NULL,
                    record_json TEXT NOT NULL,
                    PRIMARY KEY(document_id, version_id, annotation_id),
                    FOREIGN KEY(document_id, version_id)
                        REFERENCES mnemosyne_versions(document_id, version_id)
                );
                CREATE TABLE IF NOT EXISTS mnemosyne_annotation_log (
                    document_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    annotation_id TEXT NOT NULL,
                    record_json TEXT NOT NULL,
                    PRIMARY KEY(document_id, version_id, revision),
                    FOREIGN KEY(document_id, version_id)
                        REFERENCES mnemosyne_versions(document_id, version_id)
                );
                CREATE TABLE IF NOT EXISTS mnemosyne_mutations (
                    client_mutation_id TEXT PRIMARY KEY,
                    payload_sha256 TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    response_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mnemosyne_cursors (
                    token TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    expires_at REAL NOT NULL,
                    created_at REAL NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_mnemo_cursors_expiry
                    ON mnemosyne_cursors(expires_at);
                CREATE TABLE IF NOT EXISTS mnemosyne_verifications (
                    verification_id TEXT PRIMARY KEY,
                    citation_id TEXT NOT NULL,
                    document_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    anchor_json TEXT NOT NULL,
                    expires_at REAL NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mnemosyne_exports (
                    export_id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    version_id TEXT NOT NULL,
                    original_sha256 TEXT NOT NULL,
                    export_sha256 TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS mnemosyne_public_settings (
                    settings_id TEXT PRIMARY KEY CHECK(settings_id='global'),
                    public_json TEXT NOT NULL,
                    server_revision INTEGER NOT NULL,
                    credential_configured INTEGER NOT NULL CHECK(credential_configured IN (0, 1)),
                    updated_at TEXT NOT NULL
                );
                """
            )
            version_columns = {
                str(row[1]) for row in conn.execute("PRAGMA table_info(mnemosyne_versions)")
            }
            if "index_started_at" not in version_columns:
                conn.execute("ALTER TABLE mnemosyne_versions ADD COLUMN index_started_at REAL")
            conn.execute("UPDATE mnemosyne_schema SET version=3 WHERE version<3")
            version = int(conn.execute("SELECT version FROM mnemosyne_schema LIMIT 1").fetchone()[0])
            if version > 3:
                raise RuntimeError(f"Mnemosyne database schema {version} is newer than this server")
        self._secure_db_permissions()

    def original_path(self, digest: str) -> Path:
        if not _SHA256_RE.fullmatch(str(digest)):
            raise LibraryError("invalid source hash")
        return self.originals / digest[:2] / f"{digest}.pdf"

    def store_original(self, data: bytes, digest: str) -> Path:
        if hashlib.sha256(data).hexdigest() != digest:
            raise LibraryError("source hash mismatch")
        final = self.original_path(digest)
        final.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        if final.exists():
            if not final.is_file() or hashlib.sha256(final.read_bytes()).hexdigest() != digest:
                raise LibraryError("content-addressed original is corrupt")
            return final
        temporary = final.parent / f".{uuid.uuid4().hex}.tmp"
        try:
            descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(temporary, 0o400)
            try:
                os.link(temporary, final)
            except FileExistsError:
                if hashlib.sha256(final.read_bytes()).hexdigest() != digest:
                    raise LibraryError("content-addressed original is corrupt")
        finally:
            temporary.unlink(missing_ok=True)
        return final


class DocumentRepositoryAdapter:
    """Async port facade for UNIT-02; all work stays in-process and SQLite-backed."""

    def __init__(self, library: "LibraryAdapter") -> None:
        self.library = library

    async def get_document(self, document_id: str, version_id: str | None = None) -> dict[str, Any]:
        return await asyncio.to_thread(self.library.get_document, document_id, version_id)

    async def get_page(
        self, document_id: str, version_id: str, page_index: int, parse_revision: str
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self.library.get_page, document_id, version_id, page_index, parse_revision
        )

    async def get_page_assets(
        self, document_id: str, version_id: str, page_index: int
    ) -> list[dict[str, Any]]:
        return await asyncio.to_thread(
            self.library.get_page_assets, document_id, version_id, page_index
        )

    async def get_asset(self, document_id: str, version_id: str, asset_id: str) -> bytes:
        return await asyncio.to_thread(self.library.get_asset, document_id, version_id, asset_id)


class LibraryAdapter:
    """UNIT-01 internal service facade over DeepTutor's ReadingStore and RAG."""

    def __init__(
        self,
        store: ReadingStore,
        annotation_sync: Any = None,
        *,
        max_upload_bytes: int = MAX_PDF_BYTES,
        rag_indexer: Callable[..., Any] | None = None,
        rag_search: Callable[..., Any] | None = None,
        settings_defaults_provider: Callable[[], dict[str, Any]] | None = None,
        settings_secret_writer: Callable[[str], Any] | None = None,
        settings_credential_reader: Callable[[], bool] | None = None,
        settings_base_url_validator: Callable[[str], bool] | None = None,
    ) -> None:
        self.store = store
        self.db = _LibraryDatabase(store.root)
        self.annotation_sync = annotation_sync or self
        self.max_upload_bytes = max(1, int(max_upload_bytes))
        self.rag_indexer = rag_indexer
        self.rag_search = rag_search
        self.settings_defaults_provider = settings_defaults_provider
        self.settings_secret_writer = settings_secret_writer
        self.settings_credential_reader = settings_credential_reader
        self.settings_base_url_validator = settings_base_url_validator
        from deeptutor.reading.catalog_store import ReadingCatalogStore

        self.catalog = ReadingCatalogStore(store.root)
        self.documents = DocumentRepositoryAdapter(self)

    # -- subjects and folders ------------------------------------------

    def list_subjects(self) -> list[dict[str, Any]]:
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT subject_id, name, server_revision FROM mnemosyne_subjects "
                "WHERE deleted_at IS NULL ORDER BY name COLLATE NOCASE, subject_id"
            ).fetchall()
        return [dict(row) for row in rows]

    def create_subject(self, name: str) -> dict[str, Any]:
        value = str(name or "").strip()
        if not value or len(value) > 120:
            raise LibraryError("subject name must be 1–120 characters")
        subject_id, now = str(uuid.uuid4()), _now()
        try:
            with self.db.connect(write=True) as conn:
                conn.execute(
                    "INSERT INTO mnemosyne_subjects VALUES (?, ?, 1, ?, ?, NULL)",
                    (subject_id, value, now, now),
                )
        except sqlite3.IntegrityError as exc:
            raise LibraryError("subject name already exists") from exc
        return {"subject_id": subject_id, "name": value, "server_revision": 1}

    def rename_subject(
        self, subject_id: str, name: str, *, expected_revision: int | None = None
    ) -> dict[str, Any]:
        subject_id, value = _uuid(subject_id, "subject"), str(name or "").strip()
        if not value or len(value) > 120:
            raise LibraryError("subject name must be 1–120 characters")
        try:
            with self.db.connect(write=True) as conn:
                row = conn.execute(
                    "SELECT name, server_revision FROM mnemosyne_subjects "
                    "WHERE subject_id=? AND deleted_at IS NULL", (subject_id,)
                ).fetchone()
                if row is None:
                    raise LibraryError("subject not found")
                current_revision = int(row["server_revision"])
                if expected_revision is not None and current_revision != expected_revision:
                    raise RevisionConflict("subject changed on another client", current_revision)
                revision = current_revision + int(value != row["name"])
                conn.execute(
                    "UPDATE mnemosyne_subjects SET name=?, server_revision=?, updated_at=? "
                    "WHERE subject_id=?",
                    (value, revision, _now(), subject_id),
                )
        except sqlite3.IntegrityError as exc:
            raise LibraryError("subject name already exists") from exc
        return {"subject_id": subject_id, "name": value, "server_revision": revision}

    def delete_subject(self, subject_id: str, *, expected_revision: int | None = None) -> bool:
        subject_id = _uuid(subject_id, "subject")
        now = _now()
        with self.db.connect(write=True) as conn:
            row = conn.execute(
                "SELECT server_revision FROM mnemosyne_subjects "
                "WHERE subject_id=? AND deleted_at IS NULL", (subject_id,)
            ).fetchone()
            if row is None:
                return False
            current_revision = int(row["server_revision"])
            if expected_revision is not None and current_revision != expected_revision:
                raise RevisionConflict("subject changed on another client", current_revision)
            conn.execute(
                "UPDATE mnemosyne_subjects SET deleted_at=?, updated_at=?, server_revision=? "
                "WHERE subject_id=?",
                (now, now, current_revision + 1, subject_id),
            )
            conn.execute(
                "UPDATE mnemosyne_documents SET subject_id=NULL, server_revision=server_revision+1, "
                "updated_at=? WHERE subject_id=? AND deleted_at IS NULL",
                (now, subject_id),
            )
        return True

    def create_folder(self, name: str, description: str = "") -> dict[str, Any]:
        """Reuse DeepTutor's durable reading workspaces as Library folders."""
        record = self.catalog.create_workspace(str(name or "").strip(), description=description)
        return record.to_dict()

    def list_folders(self) -> list[dict[str, Any]]:
        return [row.to_dict() for row in self.catalog.list_workspaces(limit=500)]

    def assign_folder(self, document_id: str, folder_id: str) -> dict[str, Any]:
        document = self._active_document(_uuid(document_id, "document"))
        version_row = self._version_row(document["document_id"], document["version_id"])
        material_id = version_row["material_id"]
        if not material_id:
            raise LibraryError("document parsing is not ready")
        return self.catalog.add_material(str(folder_id), str(material_id)).to_dict()

    def remove_from_folder(self, document_id: str, folder_id: str) -> dict[str, Any]:
        document = self._active_document(_uuid(document_id, "document"))
        version_row = self._version_row(document["document_id"], document["version_id"])
        if not version_row["material_id"]:
            raise LibraryError("document parsing is not ready")
        return self.catalog.remove_material(str(folder_id), str(version_row["material_id"])).to_dict()

    # -- public provider settings; secret material stays with UNIT-02 ------

    def _validate_public_provider(
        self, provider: Any, *, allow_api_key: bool
    ) -> tuple[dict[str, str], str | None]:
        if not isinstance(provider, dict):
            raise LibraryError("provider settings must be an object")
        allowed = {"adapter", "base_url", "model"} | ({"api_key"} if allow_api_key else set())
        if set(provider) - allowed or not {"adapter", "base_url", "model"} <= set(provider):
            raise LibraryError("provider settings fields do not match contract")
        if provider.get("adapter") != "openai-compatible":
            raise LibraryError("unsupported provider adapter")
        base_url = provider.get("base_url")
        if not isinstance(base_url, str) or len(base_url) > 2048:
            raise LibraryError("provider base_url is invalid")
        try:
            parsed = urlsplit(base_url)
            valid_url = (
                parsed.scheme in {"http", "https"}
                and bool(parsed.hostname)
                and parsed.username is None
                and parsed.password is None
                and not parsed.fragment
            )
        except ValueError:
            valid_url = False
        if not valid_url:
            raise LibraryError("provider base_url must be an HTTP(S) URI without embedded credentials")
        if self.settings_base_url_validator is None:
            raise LibraryError("provider base URL policy is not connected")
        try:
            allowed = self.settings_base_url_validator(base_url)
        except Exception as exc:
            raise LibraryError("provider base URL policy rejected the configured URI") from exc
        if inspect.isawaitable(allowed):
            close = getattr(allowed, "close", None)
            if callable(close):
                close()
            raise LibraryError("provider base URL validator must be synchronous")
        if allowed is not True:
            raise LibraryError("provider base URL policy rejected the configured URI")
        model = provider.get("model")
        if not isinstance(model, str) or not model.strip() or len(model.strip()) > 200:
            raise LibraryError("provider model is required")
        api_key = provider.get("api_key")
        if api_key is not None and (not isinstance(api_key, str) or not api_key.strip()):
            raise LibraryError("api_key must be a non-empty string when supplied")
        return {"adapter": "openai-compatible", "base_url": base_url, "model": model.strip()}, api_key

    def _credential_is_configured(self, fallback: bool = False) -> bool:
        if self.settings_credential_reader is None:
            return bool(fallback)
        try:
            return bool(self.settings_credential_reader())
        except Exception as exc:
            raise LibraryError("secure credential status is unavailable") from exc

    def get_public_settings(self) -> dict[str, Any]:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT public_json, server_revision, credential_configured "
                "FROM mnemosyne_public_settings WHERE settings_id='global'"
            ).fetchone()
        if row is None:
            if self.settings_defaults_provider is None:
                raise LibraryError("public settings are not configured")
            try:
                defaults = self.settings_defaults_provider()
            except Exception as exc:
                raise LibraryError("public settings defaults are unavailable") from exc
            if not isinstance(defaults, dict):
                raise LibraryError("public settings defaults are invalid")
            provider, _ = self._validate_public_provider(defaults.get("provider"), allow_api_key=False)
            language = defaults.get("response_language", "ko")
            revision = 1
            fallback_credential = False
        else:
            defaults = json.loads(row["public_json"])
            provider, _ = self._validate_public_provider(defaults.get("provider"), allow_api_key=False)
            language = defaults.get("response_language")
            revision = int(row["server_revision"])
            fallback_credential = bool(row["credential_configured"])
        if not isinstance(language, str) or not _LANGUAGE_RE.fullmatch(language):
            raise LibraryError("response_language setting is invalid")
        provider["credential_configured"] = self._credential_is_configured(fallback_credential)
        return {
            "server_revision": revision,
            "provider": provider,
            "response_language": language,
        }

    def save_public_settings(
        self,
        settings: Any,
        *,
        expected_revision: int,
        confirm_action: str,
    ) -> dict[str, Any]:
        if confirm_action != "settings.update":
            raise LibraryError("explicit settings confirmation is required")
        if isinstance(expected_revision, bool) or not isinstance(expected_revision, int) or expected_revision < 1:
            raise LibraryError("settings revision is invalid")
        if not isinstance(settings, dict) or set(settings) != {"provider", "response_language"}:
            raise LibraryError("settings fields do not match contract")
        provider, api_key = self._validate_public_provider(settings["provider"], allow_api_key=True)
        language = settings["response_language"]
        if not isinstance(language, str) or not _LANGUAGE_RE.fullmatch(language):
            raise LibraryError("response_language setting is invalid")
        if api_key is not None:
            if self.settings_secret_writer is None:
                raise LibraryError("secure credential writer is not connected")

        public_json = json.dumps(
            {"provider": provider, "response_language": language},
            ensure_ascii=False,
            separators=(",", ":"),
        )
        with self.db.connect(write=True) as conn:
            row = conn.execute(
                "SELECT server_revision, credential_configured FROM mnemosyne_public_settings "
                "WHERE settings_id='global'"
            ).fetchone()
            current_revision = int(row["server_revision"]) if row is not None else 1
            if current_revision != expected_revision:
                raise RevisionConflict("public settings changed on another client", current_revision)
            old_credential = bool(row["credential_configured"]) if row is not None else False
            if api_key is not None:
                try:
                    result = self.settings_secret_writer(api_key)
                except Exception as exc:
                    raise LibraryError("secure credential storage failed") from exc
                if inspect.isawaitable(result):
                    close = getattr(result, "close", None)
                    if callable(close):
                        close()
                    raise LibraryError("secure credential writer must be synchronous")
                if result is False:
                    raise LibraryError("secure credential storage failed")
            configured = (
                True if api_key is not None
                else self._credential_is_configured(old_credential)
            )
            revision = current_revision + 1
            conn.execute(
                "INSERT INTO mnemosyne_public_settings VALUES ('global', ?, ?, ?, ?) "
                "ON CONFLICT(settings_id) DO UPDATE SET public_json=excluded.public_json, "
                "server_revision=excluded.server_revision, credential_configured=excluded.credential_configured, "
                "updated_at=excluded.updated_at",
                (public_json, revision, int(configured), _now()),
            )
        provider["credential_configured"] = configured
        return {
            "server_revision": revision,
            "provider": provider,
            "response_language": language,
        }

    # -- document upload, metadata, source, pages and search ------------

    def upload_pdf(
        self,
        data: bytes,
        filename: str,
        *,
        title: str | None = None,
        subject_id: str | None = None,
        content_language: str = "und",
    ) -> dict[str, Any]:
        if not isinstance(data, bytes) or not data:
            raise LibraryError("empty PDF upload")
        if len(data) > self.max_upload_bytes:
            raise LibraryError("PDF upload exceeds the configured size limit")
        if not data.startswith(b"%PDF-"):
            raise LibraryError("uploaded file is not a PDF")
        filename = _safe_filename(filename)
        resolved_title = str(title or Path(filename).stem).strip()
        if not resolved_title:
            raise LibraryError("document title is required")
        language = str(content_language or "und").strip()
        if not _LANGUAGE_RE.fullmatch(language):
            raise LibraryError("invalid content language")
        resolved_subject = _uuid(subject_id, "subject") if subject_id is not None else None
        if resolved_subject is not None and not any(
            row["subject_id"] == resolved_subject for row in self.list_subjects()
        ):
            raise LibraryError("subject not found")

        source_sha = hashlib.sha256(data).hexdigest()
        version_id = "sha256:" + source_sha
        document_id = str(uuid.uuid4())
        now = _now()
        original_path = self.db.store_original(data, source_sha)
        self._insert_document(
            document_id=document_id,
            version_id=version_id,
            source_sha256=source_sha,
            filename=filename,
            title=resolved_title,
            subject_id=resolved_subject,
            content_language=language,
            created_at=now,
        )
        try:
            manifest = self.store.ingest(original_path, filename=filename)
            material_path = self.store.raw_path(manifest.material_id)
            if (
                material_path is None
                or not material_path.is_file()
                or hashlib.sha256(material_path.read_bytes()).hexdigest() != source_sha
            ):
                raise LibraryError("DeepTutor material identity does not match the full source hash")
            self.catalog.upsert_material(
                content_id=manifest.material_id,
                material_id=manifest.material_id,
                filename=filename,
                title=resolved_title,
                source_kind="file",
                mime="application/pdf",
                render_mode="pdf",
                status="ready",
            )
            pages = extract_pdf_pages(
                original_path, document_id, version_id, segment_mode="words"
            )
            if not pages:
                raise LibraryError("PDF has no physical pages")
            with self.db.connect(write=True) as conn:
                conn.execute(
                    "UPDATE mnemosyne_versions SET material_id=?, page_count=?, parse_revision=?, "
                    "parse_state='ready', parse_error_code='', parse_error_detail='' "
                    "WHERE document_id=? AND version_id=?",
                    (manifest.material_id, len(pages), pages[0]["parse_revision"], document_id, version_id),
                )
                for page in pages:
                    conn.execute(
                        "INSERT INTO mnemosyne_pages VALUES (?, ?, ?, ?, ?)",
                        (document_id, version_id, page["page_index"], page["parse_revision"],
                         json.dumps(page, ensure_ascii=False, separators=(",", ":"))),
                    )
            self._copy_reading_assets(document_id, version_id, manifest.material_id)
        except Exception as exc:
            page_count = self._best_effort_page_count(original_path)
            code = "parser_unavailable" if "PyMuPDF" in str(exc) or isinstance(exc, ImportError) else "parse_failed"
            detail = f"{type(exc).__name__}: {exc}".replace(str(self.store.root), "[data]")[:1000]
            material_id = hashlib.sha256(data).hexdigest()[:16]
            with self.db.connect(write=True) as conn:
                conn.execute(
                    "DELETE FROM mnemosyne_pages WHERE document_id=? AND version_id=?",
                    (document_id, version_id),
                )
                conn.execute(
                    "DELETE FROM mnemosyne_assets WHERE document_id=? AND version_id=?",
                    (document_id, version_id),
                )
                conn.execute(
                    "UPDATE mnemosyne_versions SET material_id=?, page_count=?, parse_state='failed', "
                    "parse_error_code=?, parse_error_detail=?, index_state='failed', "
                    "index_error_code=?, index_error_detail=? WHERE document_id=? AND version_id=?",
                    (material_id, page_count, code, detail, "parser_not_ready", detail,
                     document_id, version_id),
                )
            try:
                self.catalog.upsert_material(
                    content_id=material_id, material_id=material_id, filename=filename,
                    title=resolved_title, source_kind="file", mime="application/pdf",
                    render_mode="pdf", status="failed", error_code=code, error_detail=detail,
                )
            except Exception:
                # The immutable original and failed document record are the
                # authoritative state even if a legacy catalog upgrade fails.
                pass
        return self.get_document(document_id)

    async def upload_pdf_async(
        self,
        data: bytes,
        filename: str,
        *,
        title: str | None = None,
        subject_id: str | None = None,
        content_language: str = "und",
    ) -> dict[str, Any]:
        """Parse first, then attempt the configured DeepTutor index pipeline."""
        document = await asyncio.to_thread(
            self.upload_pdf,
            data,
            filename,
            title=title,
            subject_id=subject_id,
            content_language=content_language,
        )
        if document["parse_state"] != "ready":
            return document
        return await self.prepare_index(document["document_id"], document["version_id"])

    def list_documents(
        self, *, subject_id: str | None = None, search: str = "", limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        clauses = ["d.deleted_at IS NULL"]
        params: list[Any] = []
        if subject_id is not None:
            clauses.append("d.subject_id=?")
            params.append(_uuid(subject_id, "subject"))
        if search.strip():
            clauses.append("(d.title LIKE ? ESCAPE '\\' OR v.filename LIKE ? ESCAPE '\\')")
            query = self._escape_like(search.strip())
            params.extend((f"%{query}%", f"%{query}%"))
        params.extend((max(1, min(int(limit), 500)), max(0, int(offset))))
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT d.document_id FROM mnemosyne_documents d "
                "JOIN mnemosyne_versions v ON v.document_id=d.document_id "
                "WHERE " + " AND ".join(clauses) +
                " ORDER BY d.updated_at DESC, d.document_id LIMIT ? OFFSET ?",
                params,
            ).fetchall()
        return [self.get_document(str(row["document_id"])) for row in rows]

    def get_document(self, document_id: str, version_id: str | None = None) -> dict[str, Any]:
        document_id = _uuid(document_id, "document")
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT d.*, v.version_id, v.source_sha256, v.filename, v.page_count, "
                "v.parse_state, v.parse_error_code, v.parse_error_detail, v.index_state, "
                "v.index_error_code, v.index_error_detail, v.material_id "
                "FROM mnemosyne_documents d JOIN mnemosyne_versions v USING(document_id) "
                "WHERE d.document_id=? AND (? IS NULL OR v.version_id=?) "
                "ORDER BY v.created_at DESC LIMIT 1",
                (document_id, version_id, version_id),
            ).fetchone()
        if row is None:
            raise LibraryError("document not found")
        if row["deleted_at"]:
            raise DocumentDeleted("document was deleted")
        source_path = self.db.original_path(str(row["source_sha256"]))
        available = source_path.is_file()
        return {
            "document_id": row["document_id"],
            "version_id": row["version_id"],
            "source_sha256": row["source_sha256"],
            "title": row["title"],
            "subject_id": row["subject_id"],
            "content_language": row["content_language"],
            "page_count": int(row["page_count"]),
            "server_revision": int(row["server_revision"]),
            "original_available": available,
            "parse_state": row["parse_state"],
            "index_state": row["index_state"],
            "created_at": row["created_at"],
            "filename": row["filename"],
            "parse_error_code": row["parse_error_code"],
            "parse_error_detail": row["parse_error_detail"],
            "index_error_code": row["index_error_code"],
            "index_error_detail": row["index_error_detail"],
        }

    def update_document(
        self, document_id: str, *, title: str | None = None, subject_id: Any = _UNSET,
        expected_revision: int | None = None,
    ) -> dict[str, Any]:
        document_id = _uuid(document_id, "document")
        if title is None and subject_id is _UNSET:
            raise LibraryError("document update is empty")
        new_subject = _uuid(subject_id, "subject") if isinstance(subject_id, str) else None
        if isinstance(subject_id, str) and new_subject not in {row["subject_id"] for row in self.list_subjects()}:
            raise LibraryError("subject not found")
        if subject_id is not _UNSET and subject_id is not None and not isinstance(subject_id, str):
            raise LibraryError("subject_id must be a UUID or null")
        value = None if title is None else str(title).strip()
        if value is not None and not value:
            raise LibraryError("document title is required")
        if value is not None and len(value) > 500:
            raise LibraryError("document title is too long")
        now = _now()
        with self.db.connect(write=True) as conn:
            row = conn.execute(
                "SELECT title, subject_id, server_revision FROM mnemosyne_documents "
                "WHERE document_id=? AND deleted_at IS NULL", (document_id,)
            ).fetchone()
            if row is None:
                raise LibraryError("document not found")
            current_revision = int(row["server_revision"])
            if expected_revision is not None and current_revision != expected_revision:
                raise RevisionConflict("document metadata changed on another client", current_revision)
            final_title = row["title"] if value is None else value
            final_subject = row["subject_id"] if subject_id is _UNSET else new_subject
            changed = final_title != row["title"] or final_subject != row["subject_id"]
            revision = current_revision + int(changed)
            conn.execute(
                "UPDATE mnemosyne_documents SET title=?, subject_id=?, server_revision=?, updated_at=? "
                "WHERE document_id=?",
                (final_title, final_subject, revision, now, document_id),
            )
        return self.get_document(document_id)

    def download_original(self, document_id: str, version_id: str | None = None) -> bytes:
        document = self.get_document(document_id, version_id)
        path = self.db.original_path(document["source_sha256"])
        self._require_managed_path(path, self.db.originals)
        try:
            data = path.read_bytes()
        except OSError as exc:
            raise LibraryError("original PDF is unavailable") from exc
        if hashlib.sha256(data).hexdigest() != document["source_sha256"]:
            raise LibraryError("original PDF hash verification failed")
        return data

    def delete_document(
        self, document_id: str, *, confirm: bool = False,
        confirm_action: str | None = None, expected_revision: int | None = None,
    ) -> bool:
        document_id = _uuid(document_id, "document")
        confirmation_ok = confirm is True or confirm_action == f"document.delete:{document_id}"
        if not confirmation_ok:
            raise LibraryError("explicit delete confirmation is required")
        now = _now()
        with self.db.connect(write=True) as conn:
            row = conn.execute(
                "SELECT d.deleted_at, v.version_id, v.source_sha256, v.material_id "
                "FROM mnemosyne_documents d JOIN mnemosyne_versions v USING(document_id) "
                "WHERE d.document_id=? ORDER BY v.created_at DESC LIMIT 1", (document_id,)
            ).fetchone()
            if row is None:
                raise LibraryError("document not found")
            if row["deleted_at"]:
                return False
            current_revision = conn.execute(
                "SELECT server_revision FROM mnemosyne_documents WHERE document_id=?", (document_id,)
            ).fetchone()
            current_revision = int(current_revision["server_revision"])
            if expected_revision is not None and current_revision != expected_revision:
                raise RevisionConflict("document metadata changed on another client", current_revision)
            conn.execute(
                "UPDATE mnemosyne_documents SET deleted_at=?, updated_at=?, server_revision=server_revision+1 "
                "WHERE document_id=?", (now, now, document_id)
            )
            other = conn.execute(
                "SELECT 1 FROM mnemosyne_documents d JOIN mnemosyne_versions v USING(document_id) "
                "WHERE d.deleted_at IS NULL AND v.source_sha256=? LIMIT 1", (row["source_sha256"],)
            ).fetchone()
        if other is None:
            self.db.original_path(str(row["source_sha256"])).unlink(missing_ok=True)
        material_id = row["material_id"]
        if material_id:
            with self.db.connect() as conn:
                shared = conn.execute(
                    "SELECT 1 FROM mnemosyne_documents d JOIN mnemosyne_versions v USING(document_id) "
                    "WHERE d.deleted_at IS NULL AND v.material_id=? LIMIT 1", (material_id,)
                ).fetchone()
            if shared is None:
                self.catalog.delete_material(material_id)
                self.store.delete(material_id)
        return True

    def get_page(
        self, document_id: str, version_id: str, page_index: int, parse_revision: str | None = None
    ) -> dict[str, Any]:
        document_id, version_id = _uuid(document_id, "document"), _version(version_id)
        if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0:
            raise LibraryError("page_index must be a non-negative integer")
        document = self._active_document(document_id, version_id)
        if document["parse_state"] != "ready":
            raise LibraryError("document parsing is not ready")
        with self.db.connect() as conn:
            if parse_revision is None:
                row = conn.execute(
                    "SELECT page_json FROM mnemosyne_pages WHERE document_id=? AND version_id=? "
                    "AND page_index=? ORDER BY parse_revision DESC LIMIT 1",
                    (document_id, version_id, page_index),
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT page_json FROM mnemosyne_pages WHERE document_id=? AND version_id=? "
                    "AND page_index=? AND parse_revision=?",
                    (document_id, version_id, str(parse_revision)),
                ).fetchone()
        if row is None:
            raise LibraryError("parsed page not found")
        return json.loads(row["page_json"])

    def get_asset(self, document_id: str, version_id: str, asset_id: str) -> bytes:
        document_id, version_id = _uuid(document_id, "document"), _version(version_id)
        self._active_document(document_id, version_id)
        asset_id = _uuid(asset_id, "asset")
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT data, sha256 FROM mnemosyne_assets WHERE document_id=? AND version_id=? AND asset_id=?",
                (document_id, version_id, asset_id),
            ).fetchone()
        if row is None:
            raise LibraryError("document image not found")
        data = bytes(row["data"])
        if hashlib.sha256(data).hexdigest() != row["sha256"]:
            raise LibraryError("stored image hash verification failed")
        return data

    def get_page_assets(
        self, document_id: str, version_id: str, page_index: int
    ) -> list[dict[str, Any]]:
        document_id, version_id = _uuid(document_id, "document"), _version(version_id)
        if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0:
            raise LibraryError("page_index must be a non-negative integer")
        self.get_page(document_id, version_id, page_index)
        with self.db.connect() as conn:
            rows = conn.execute(
                "SELECT asset_id, page_index, mime, sha256 FROM mnemosyne_assets "
                "WHERE document_id=? AND version_id=? AND page_index=? ORDER BY asset_id",
                (document_id, version_id, page_index),
            ).fetchall()
        return [dict(row) for row in rows]

    def search(self, material_id: str, query: str, limit: int = 12):
        """Preserve the actual DeepTutor lexical search API used by its readers."""
        return search_material(self.store, material_id, query, limit=limit)

    def search_document(self, document_id: str, query: str, limit: int = 12):
        document_id = _uuid(document_id, "document")
        document = self.get_document(document_id)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT material_id FROM mnemosyne_versions WHERE document_id=? AND version_id=?",
                (document_id, document["version_id"]),
            ).fetchone()
        if row is None or not row["material_id"] or document["parse_state"] != "ready":
            raise LibraryError("document search is not ready")
        lexical = search_material(self.store, str(row["material_id"]), query, limit=limit)
        return lexical

    def search_anchors(
        self, document_id: str, version_id: str, query: str, limit: int = 12
    ) -> list[dict[str, Any]]:
        if not isinstance(query, str) or not query.strip():
            raise LibraryError("search query is required")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
            raise LibraryError("search limit must be between 1 and 100")
        document_id, version_id = _uuid(document_id, "document"), _version(version_id)
        document = self.get_document(document_id, version_id)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT material_id FROM mnemosyne_versions WHERE document_id=? AND version_id=?",
                (document_id, version_id),
            ).fetchone()
        if row is None or not row["material_id"] or document["parse_state"] != "ready":
            raise LibraryError("document search is not ready")
        result = search_material(self.store, str(row["material_id"]), query, limit=limit)
        anchors = []
        for hit in result.hits:
            try:
                page = self.get_page(document_id, version_id, hit.locator - 1)
            except LibraryError:
                continue
            reported_start = max(0, int(hit.offset))
            source_text = page["text"]
            match = _find_casefold_span(source_text, query.strip(), reported_start)
            if match is None:
                match = _find_casefold_span(source_text, str(hit.match), reported_start)
            if match is None:
                # DeepTutor's normalized/terms fallbacks can report a nearby
                # term offset. Return a literal source term at its real offset.
                terms = re.findall(r"[\w\u3400-\u9fff]+", query, flags=re.UNICODE)
                matches = [
                    candidate for term in terms
                    if (candidate := _find_casefold_span(source_text, term, reported_start)) is not None
                ]
                match = min(matches, key=lambda span: (abs(span[0] - reported_start), span[0])) if matches else None
            if match is None:
                continue
            start, end = match
            quote = source_text[start:end]
            selected = [
                segment for segment in page["segments"]
                if int(segment["start_scalar"]) < end and int(segment["end_scalar"]) > start
            ]
            if not selected:
                continue
            anchor = {
                "document_id": document_id,
                "version_id": version_id,
                "page_index": page["page_index"],
                "parse_revision": page["parse_revision"],
                "text_sha256": page["text_sha256"],
                "start_scalar": start,
                "end_scalar": end,
                "quote": quote,
                "rects": [segment["rect"] for segment in selected],
            }
            try:
                self.verify_anchor(anchor, page)
            except LibraryError:
                continue
            anchors.append(anchor)
        return anchors

    async def search_document_async(self, document_id: str, query: str, limit: int = 12) -> dict[str, Any]:
        """Use DeepTutor's configured RAG pipeline when indexed; retain lexical search."""
        document_id = _uuid(document_id, "document")
        document = self.get_document(document_id)
        lexical = self.search_document(document_id, query, limit)
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT index_kb FROM mnemosyne_versions WHERE document_id=? AND version_id=?",
                (document_id, document["version_id"]),
            ).fetchone()
        kb_name = str(row["index_kb"] or "") if row else ""
        if document["index_state"] != "ready" or not kb_name:
            return {"lexical": lexical, "rag": None, "index_state": document["index_state"]}
        if self.rag_search is not None:
            value = self.rag_search(document=document, query=query, limit=limit)
            result = await value if inspect.isawaitable(value) else value
        else:
            from deeptutor.services.path_service import get_path_service
            from deeptutor.services.rag.service import RAGService

            root = get_path_service().get_knowledge_bases_root()
            service = RAGService(kb_base_dir=str(root))
            result = await service.search(query=query, kb_name=kb_name, similarity_top_k=limit)
        return {"lexical": lexical, "rag": result, "index_state": "ready"}

    async def prepare_index(self, document_id: str, version_id: str | None = None) -> dict[str, Any]:
        """Run the pinned DeepTutor knowledge/indexing pipeline for one immutable PDF."""
        document_id = _uuid(document_id, "document")
        document = self.get_document(document_id, version_id)
        resolved_version = document["version_id"]
        if document["parse_state"] != "ready":
            self._set_index_state(
                document_id, resolved_version, "failed", "parser_not_ready",
                "PDF parsing must complete before RAG indexing.",
            )
            return self.get_document(document_id, resolved_version)
        source_path = self.db.original_path(document["source_sha256"])
        self._require_managed_path(source_path, self.db.originals)
        now = time.time()
        with self.db.connect(write=True) as conn:
            current = conn.execute(
                "SELECT index_state, index_started_at FROM mnemosyne_versions "
                "WHERE document_id=? AND version_id=?",
                (document_id, resolved_version),
            ).fetchone()
            if current is None:
                raise LibraryError("document version not found")
            state = str(current["index_state"])
            started_at = current["index_started_at"]
            if state == "ready" or (
                state == "running" and started_at is not None and now - float(started_at) < 1800
            ):
                claimed = 0
            else:
                if state == "running":
                    conn.execute(
                        "UPDATE mnemosyne_versions SET index_state='failed', index_started_at=NULL, "
                        "index_error_code='index_interrupted', "
                        "index_error_detail='Previous indexing run did not finish.' "
                        "WHERE document_id=? AND version_id=?",
                        (document_id, resolved_version),
                    )
                claimed = conn.execute(
                    "UPDATE mnemosyne_versions SET index_state='running', index_started_at=?, index_error_code='', "
                    "index_error_detail='' WHERE document_id=? AND version_id=? "
                    "AND index_state IN ('pending', 'failed')",
                    (now, document_id, resolved_version),
                ).rowcount
        if not claimed:
            return self.get_document(document_id, resolved_version)
        kb_name = "mnemo_" + document_id.replace("-", "")[:20] + "_" + document["source_sha256"][:8]
        try:
            if self.rag_indexer is not None:
                indexed = self.rag_indexer(
                    document=document, original_path=source_path, kb_name=kb_name
                )
                result = await indexed if inspect.isawaitable(indexed) else indexed
                if result is False or (isinstance(result, dict) and result.get("ready") is False):
                    raise RuntimeError("configured RAG indexer did not publish a ready index")
                if isinstance(result, dict):
                    kb_name = str(result.get("kb_name") or kb_name)
            else:
                # Reuse DeepTutor's KB initializer, RAGService provider binding,
                # parser, image pipeline, and durable index readiness check.
                from deeptutor.knowledge.initializer import initialize_knowledge_base
                from deeptutor.services.path_service import get_path_service

                root = get_path_service().get_knowledge_bases_root()
                succeeded = await initialize_knowledge_base(
                    kb_name=kb_name,
                    source_files=[str(source_path)],
                    base_dir=str(root),
                )
                if not succeeded:
                    raise RuntimeError("DeepTutor RAG initializer returned no ready index")
            self._set_index_state(document_id, resolved_version, "ready", index_kb=kb_name)
        except asyncio.CancelledError:
            self._set_index_state(
                document_id, resolved_version, "failed", "index_cancelled",
                "Indexing was cancelled before the run completed.",
            )
            raise
        except Exception as exc:
            message = f"{type(exc).__name__}: {exc}".replace(str(self.store.root), "[data]")[:1000]
            lowered = message.lower()
            code = "embedding_provider_unavailable" if any(
                token in lowered for token in ("embedding", "api key", "provider", "credential", "not configured")
            ) else "index_failed"
            self._set_index_state(document_id, resolved_version, "failed", code, message)
        return self.get_document(document_id, resolved_version)

    def _copy_reading_assets(self, document_id: str, version_id: str, material_id: str) -> None:
        rows = self.store.media_items(material_id)
        for row in rows:
            path = self.store.media_path(material_id, str(row.get("name") or ""))
            if path is None or not path.is_file():
                raise LibraryError("DeepTutor extracted media is missing")
            data = path.read_bytes()
            asset_id = str(uuid.uuid5(uuid.UUID(document_id), f"{version_id}:{row['name']}"))
            digest = hashlib.sha256(data).hexdigest()
            with self.db.connect(write=True) as conn:
                conn.execute(
                    "INSERT OR REPLACE INTO mnemosyne_assets VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (document_id, version_id, asset_id, max(0, int(row.get("locator", 1)) - 1),
                     str(row.get("mime") or "application/octet-stream"), digest, data),
                )

    def _insert_document(
        self, *, document_id: str, version_id: str, source_sha256: str, filename: str,
        title: str, subject_id: str | None, content_language: str, created_at: str,
    ) -> None:
        with self.db.connect(write=True) as conn:
            conn.execute(
                "INSERT INTO mnemosyne_documents VALUES (?, ?, ?, ?, 1, ?, ?, NULL)",
                (document_id, title, subject_id, content_language, created_at, created_at),
            )
            conn.execute(
                "INSERT INTO mnemosyne_versions(document_id, version_id, source_sha256, filename, "
                "page_count, parse_state, index_state, created_at) VALUES (?, ?, ?, ?, 0, 'pending', 'pending', ?)",
                (document_id, version_id, source_sha256, filename, created_at),
            )
            conn.execute(
                "INSERT INTO mnemosyne_annotation_clock(document_id, version_id, revision) VALUES (?, ?, 0)",
                (document_id, version_id),
            )

    def _best_effort_page_count(self, path: Path) -> int:
        try:
            import pymupdf

            with pymupdf.open(path) as pdf:
                return int(pdf.page_count)
        except Exception:
            return 0

    def _set_index_state(
        self, document_id: str, version_id: str, state: str, code: str = "", detail: str = "",
        *, index_kb: str | None = None,
    ) -> None:
        if state not in {"pending", "running", "ready", "failed"}:
            raise ValueError("invalid index state")
        with self.db.connect(write=True) as conn:
            conn.execute(
                "UPDATE mnemosyne_versions SET index_state=?, index_started_at=?, index_error_code=?, "
                "index_error_detail=?, index_kb=COALESCE(?, index_kb) "
                "WHERE document_id=? AND version_id=?",
                (state, time.time() if state == "running" else None, code[:128], detail[:1000],
                 index_kb, document_id, version_id),
            )

    def _version_row(self, document_id: str, version_id: str) -> sqlite3.Row:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM mnemosyne_versions WHERE document_id=? AND version_id=?",
                (document_id, version_id),
            ).fetchone()
        if row is None:
            raise LibraryError("document version not found")
        return row

    def _active_document(self, document_id: str, version_id: str | None = None) -> sqlite3.Row:
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT d.*, v.version_id, v.source_sha256, v.filename, v.page_count, v.parse_state, "
                "v.index_state, v.material_id FROM mnemosyne_documents d "
                "JOIN mnemosyne_versions v USING(document_id) WHERE d.document_id=? "
                "AND (? IS NULL OR v.version_id=?) ORDER BY v.created_at DESC LIMIT 1",
                (document_id, version_id, version_id),
            ).fetchone()
        if row is None:
            raise LibraryError("document or version not found")
        if row["deleted_at"]:
            raise DocumentDeleted("document was deleted")
        return row

    @staticmethod
    def _require_managed_path(path: Path, root: Path) -> None:
        try:
            resolved, base = path.resolve(strict=True), root.resolve(strict=True)
            if os.path.commonpath((str(resolved), str(base))) != str(base) or not resolved.is_file():
                raise LibraryError("managed file path is invalid")
        except (OSError, ValueError) as exc:
            raise LibraryError("managed file path is invalid") from exc

    @staticmethod
    def _escape_like(value: str) -> str:
        return value.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")

    def _page_for_anchor(self, anchor: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(anchor, dict):
            raise LibraryError("citation anchor must be an object")
        document_id = _uuid(anchor.get("document_id"), "document")
        version_id = _version(anchor.get("version_id"))
        page_index = anchor.get("page_index")
        if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0:
            raise LibraryError("citation page index is invalid")
        return self.get_page(document_id, version_id, page_index, str(anchor.get("parse_revision") or ""))

    def verify_anchor(self, anchor: dict[str, Any], page: dict[str, Any]) -> None:
        if not isinstance(anchor, dict) or not isinstance(page, dict):
            raise LibraryError("citation anchor and page must be objects")
        for field in ("document_id", "version_id", "page_index", "parse_revision", "text_sha256"):
            if anchor.get(field) != page.get(field):
                raise LibraryError("citation provenance mismatch")
        text = page.get("text")
        if not isinstance(text, str) or hashlib.sha256(text.encode("utf-8")).hexdigest() != page.get("text_sha256"):
            raise LibraryError("parsed page text hash mismatch")
        start, end, quote = anchor.get("start_scalar"), anchor.get("end_scalar"), anchor.get("quote")
        if (
            isinstance(start, bool) or not isinstance(start, int)
            or isinstance(end, bool) or not isinstance(end, int)
            or not (0 <= start < end <= len(text))
            or not isinstance(quote, str) or text[start:end] != quote
        ):
            raise LibraryError("citation text or scalar offsets mismatch")
        segments = page.get("segments")
        if not isinstance(segments, list):
            raise LibraryError("parsed page has no geometry map")
        selected = [
            segment for segment in segments
            if int(segment["start_scalar"]) < end and int(segment["end_scalar"]) > start
        ]
        if not selected:
            raise LibraryError("citation has no parser geometry")
        # Every selected non-space scalar must be represented by the parser's
        # segments; missing OCR/text geometry is rejected rather than guessed.
        covered = [False] * (end - start)
        for segment in selected:
            left, right = max(start, int(segment["start_scalar"])), min(end, int(segment["end_scalar"]))
            for position in range(left, right):
                if not text[position].isspace():
                    covered[position - start] = True
        if any(not covered[i] for i in range(len(covered)) if not text[start + i].isspace()):
            raise LibraryError("citation crosses text without source geometry")
        expected = [segment["rect"] for segment in selected]
        rects = anchor.get("rects")
        if not isinstance(rects, list) or len(rects) != len(expected):
            raise LibraryError("citation geometry mismatch")
        for actual, wanted in zip(rects, expected):
            if (
                not isinstance(actual, list) or len(actual) != 4
                or not all(isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) for value in actual)
                or not all(math.isclose(float(a), float(b), abs_tol=1e-6) for a, b in zip(actual, wanted))
            ):
                raise LibraryError("citation geometry mismatch")
        geometry = page.get("geometry") or {}
        crop = geometry.get("crop_box")
        if not isinstance(crop, list) or len(crop) != 4:
            raise LibraryError("page geometry is invalid")
        llx, lly, urx, ury = (float(value) for value in crop)
        if not llx < urx or not lly < ury:
            raise LibraryError("page crop box is invalid")
        for x, y, width, height in rects:
            if width <= 0 or height <= 0 or x < llx - 1e-5 or y < lly - 1e-5 or x + width > urx + 1e-5 or y + height > ury + 1e-5:
                raise LibraryError("citation rectangle is outside the page crop")

    def verify_citation(self, anchor: dict[str, Any], *, citation_id: str | None = None) -> dict[str, Any]:
        citation_id = _uuid(citation_id or uuid.uuid4(), "citation")
        page = self._page_for_anchor(anchor)
        self.verify_anchor(anchor, page)
        verified = {
            "document_id": page["document_id"],
            "version_id": page["version_id"],
            "page_index": page["page_index"],
            "parse_revision": page["parse_revision"],
            "text_sha256": page["text_sha256"],
            "start_scalar": int(anchor["start_scalar"]),
            "end_scalar": int(anchor["end_scalar"]),
            "quote": str(anchor["quote"]),
            "rects": anchor["rects"],
        }
        verification_id, expires = str(uuid.uuid4()), time.time() + 600
        with self.db.connect(write=True) as conn:
            conn.execute(
                "INSERT INTO mnemosyne_verifications VALUES (?, ?, ?, ?, ?, ?)",
                (verification_id, citation_id, page["document_id"], page["version_id"],
                 json.dumps(verified, ensure_ascii=False, separators=(",", ":")), expires),
            )
        return {"citation_id": citation_id, "verification_id": verification_id, "verified": True, "anchor": verified}

    def require_verified_citation(self, citation: dict[str, Any]) -> dict[str, Any]:
        try:
            verification_id = _uuid(citation.get("verification_id"), "verification")
        except (AttributeError, LibraryError) as exc:
            raise LibraryError("citation verification is required") from exc
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT * FROM mnemosyne_verifications WHERE verification_id=?", (verification_id,)
            ).fetchone()
        if row is None or float(row["expires_at"]) < time.time():
            raise LibraryError("citation verification expired")
        anchor = json.loads(row["anchor_json"])
        if citation.get("citation_id") != row["citation_id"] or citation.get("anchor") != anchor:
            raise LibraryError("citation verification does not match this request")
        self.verify_anchor(anchor, self.get_page(anchor["document_id"], anchor["version_id"], anchor["page_index"], anchor["parse_revision"]))
        return anchor

    # -- annotated PDF export -------------------------------------------

    def export_annotated_pdf(
        self,
        document_id: str,
        version_id: str,
        annotation_revision: int,
        *,
        include_ink: bool = True,
    ) -> dict[str, Any]:
        document_id, version_id = _uuid(document_id, "document"), _version(version_id)
        if isinstance(annotation_revision, bool) or not isinstance(annotation_revision, int) or annotation_revision < 0:
            raise LibraryError("annotation revision is invalid")
        if not isinstance(include_ink, bool):
            raise LibraryError("include_ink must be a boolean")
        document = self.get_document(document_id, version_id)
        original = self.download_original(document_id, version_id)
        actual_source_hash = hashlib.sha256(original).hexdigest()
        records = self._annotations_at_revision(document_id, version_id, annotation_revision)
        visible = [record for record in records if not record["deleted"] and (include_ink or record["kind"] != "ink")]
        if visible:
            try:
                import pymupdf
            except ImportError as exc:
                raise LibraryError("annotated PDF export requires PyMuPDF") from exc
            try:
                with pymupdf.open(stream=original, filetype="pdf") as pdf:
                    bookmarks = pdf.get_toc(simple=True)
                    bookmark_rows = []
                    for record in visible:
                        page_index = int(record["page_index"])
                        if not 0 <= page_index < pdf.page_count:
                            raise LibraryError("annotation page is outside the source PDF")
                        page_data = self.get_page(document_id, version_id, page_index)
                        page = pdf[page_index]
                        payload = record["payload"]
                        if record["kind"] == "highlight":
                            anchor = payload["anchor"]
                            self.verify_anchor(anchor, page_data)
                            rects = [self._raw_rect_to_mupdf(pymupdf, rect, page_data["geometry"]) for rect in anchor["rects"]]
                            annot = page.add_highlight_annot(rects)
                            rgb, alpha = self._pdf_color(payload["color"])
                            annot.set_colors(stroke=rgb)
                            annot.set_opacity(alpha)
                            annot.set_info(content=anchor["quote"])
                            annot.update()
                        elif record["kind"] == "note":
                            point = self._raw_point_to_mupdf(pymupdf, payload["position"], page_data["geometry"])
                            annot = page.add_text_annot(point, payload["body"])
                            annot.update()
                        elif record["kind"] == "bookmark":
                            label = payload["label"].strip() or document["title"]
                            bookmark_rows.append([1, label, page_index + 1])
                        elif record["kind"] == "ink":
                            self._draw_contract_ink(pymupdf, page, payload, page_data["geometry"])
                        else:
                            raise LibraryError(f"PDF export does not support annotation kind {record['kind']!r}")
                    if bookmark_rows:
                        pdf.set_toc([*bookmarks, *bookmark_rows])
                    output = pdf.tobytes(deflate=True, garbage=3)
            except LibraryError:
                raise
            except Exception as exc:
                raise LibraryError(f"failed to export annotations ({type(exc).__name__})") from exc
        else:
            output = original
        if hashlib.sha256(original).hexdigest() != actual_source_hash:
            raise LibraryError("source PDF changed during export")
        export_id = str(uuid.uuid4())
        export_path = self.db.exports / f"{export_id}.pdf"
        self._write_export(export_path, output)
        export_hash = hashlib.sha256(output).hexdigest()
        with self.db.connect(write=True) as conn:
            conn.execute(
                "INSERT INTO mnemosyne_exports VALUES (?, ?, ?, ?, ?, ?)",
                (export_id, document_id, version_id, actual_source_hash, export_hash, _now()),
            )
        return {
            "export_id": export_id,
            "download_path": f"/v1/exports/{export_id}/file",
            "original_sha256": actual_source_hash,
            "export_sha256": export_hash,
        }

    def download_export(self, export_id: str) -> bytes:
        export_id = _uuid(export_id, "export")
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT export_sha256 FROM mnemosyne_exports WHERE export_id=?", (export_id,)
            ).fetchone()
        if row is None:
            raise LibraryError("export not found")
        path = self.db.exports / f"{export_id}.pdf"
        self._require_managed_path(path, self.db.exports)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != row["export_sha256"]:
            raise LibraryError("export hash verification failed")
        return data

    def _annotations_at_revision(
        self, document_id: str, version_id: str, revision: int
    ) -> list[dict[str, Any]]:
        self._active_document(document_id, version_id)
        with self.db.connect() as conn:
            watermark = self._watermark(conn, document_id, version_id)
            if revision > watermark:
                raise LibraryError("requested annotation revision is not available")
            latest = conn.execute(
                "SELECT annotation_id, MAX(revision) AS revision FROM mnemosyne_annotation_log "
                "WHERE document_id=? AND version_id=? AND revision<=? GROUP BY annotation_id "
                "ORDER BY annotation_id",
                (document_id, version_id, revision),
            ).fetchall()
            records = []
            for row in latest:
                record = conn.execute(
                    "SELECT record_json FROM mnemosyne_annotation_log WHERE document_id=? AND version_id=? "
                    "AND annotation_id=? AND revision=?",
                    (document_id, version_id, row["annotation_id"], row["revision"]),
                ).fetchone()
                if record is not None:
                    records.append(json.loads(record["record_json"]))
        return records

    @staticmethod
    def _raw_rect_to_mupdf(pymupdf, rect: Sequence[float], geometry: dict[str, Any]):
        x, y, width, height = (float(value) for value in rect)
        llx, lly, urx, ury = (float(value) for value in geometry["crop_box"])
        unit = float(geometry["user_unit"])
        return pymupdf.Rect(
            (x - llx) * unit,
            (ury - y - height) * unit,
            (x + width - llx) * unit,
            (ury - y) * unit,
        )

    @staticmethod
    def _raw_point_to_mupdf(pymupdf, point: Sequence[float], geometry: dict[str, Any]):
        x, y = float(point[0]), float(point[1])
        llx, lly, urx, ury = (float(value) for value in geometry["crop_box"])
        unit = float(geometry["user_unit"])
        return pymupdf.Point((x - llx) * unit, (ury - y) * unit)

    @staticmethod
    def _pdf_color(value: str) -> tuple[tuple[float, float, float], float]:
        red, green, blue, alpha = (int(value[index:index + 2], 16) for index in (1, 3, 5, 7))
        return (red / 255, green / 255, blue / 255), alpha / 255

    @classmethod
    def _draw_contract_ink(cls, pymupdf, page, payload: dict[str, Any], geometry: dict[str, Any]) -> None:
        for stroke in payload["strokes"]:
            rgb, alpha = cls._pdf_color(stroke["color"])
            width = float(stroke["width_pt"])
            points = [cls._raw_point_to_mupdf(pymupdf, [item["x"], item["y"]], geometry) for item in stroke["points"]]
            radii = [width * float(item["pressure"]) / 2 for item in stroke["points"]]
            if len(points) == 1:
                if radii[0] > 0:
                    page.draw_circle(points[0], radii[0], color=None, fill=rgb, fill_opacity=alpha, overlay=True)
                continue
            for index, (start, end) in enumerate(zip(points, points[1:])):
                pressure = (float(stroke["points"][index]["pressure"]) + float(stroke["points"][index + 1]["pressure"])) / 2
                segment_width = width * pressure
                if segment_width > 0:
                    page.draw_line(start, end, color=rgb, width=segment_width, lineCap=1, overlay=True, stroke_opacity=alpha)
            for point, radius in zip(points, radii):
                if radius > 0:
                    page.draw_circle(point, radius, color=None, fill=rgb, fill_opacity=alpha, overlay=True)

    @staticmethod
    def _write_export(path: Path, data: bytes) -> None:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.chmod(path, 0o400)
        except BaseException:
            path.unlink(missing_ok=True)
            raise

    # -- annotation schema validation and transactional sync -------------

    def _validate_draft(self, draft: Any, document_id: str, version_id: str) -> dict[str, Any]:
        if not isinstance(draft, dict):
            raise LibraryError("annotation must be an object")
        required = {"annotation_id", "document_id", "version_id", "page_index", "kind", "payload"}
        if set(draft) != required:
            raise LibraryError("annotation fields do not match contract 0.1.0")
        annotation_id = _uuid(draft["annotation_id"], "annotation")
        if _uuid(draft["document_id"], "document") != document_id or _version(draft["version_id"]) != version_id:
            raise LibraryError("annotation document provenance mismatch")
        page_index = draft["page_index"]
        if isinstance(page_index, bool) or not isinstance(page_index, int) or not 0 <= page_index <= 9007199254740991:
            raise LibraryError("annotation page index is invalid")
        kind, payload = draft["kind"], draft["payload"]
        if not isinstance(kind, str) or kind not in _ANNOTATION_KINDS or not isinstance(payload, dict):
            raise LibraryError("unsupported annotation kind or payload")
        page = self.get_page(document_id, version_id, page_index)
        geometry = page["geometry"]
        crop = geometry["crop_box"]
        llx, lly, urx, ury = (float(value) for value in crop)

        if kind == "highlight":
            if set(payload) != {"anchor", "color"}:
                raise LibraryError("highlight payload fields do not match contract")
            anchor = payload["anchor"]
            if not isinstance(anchor, dict):
                raise LibraryError("highlight anchor must be an object")
            if anchor.get("document_id") != document_id or anchor.get("version_id") != version_id or anchor.get("page_index") != page_index:
                raise LibraryError("highlight anchor provenance mismatch")
            self.verify_anchor(anchor, page)
            self._validate_color(payload["color"])
        elif kind == "note":
            if set(payload) != {"position", "body", "anchor"}:
                raise LibraryError("note payload fields do not match contract")
            position, body, anchor = payload["position"], payload["body"], payload["anchor"]
            if (
                not isinstance(position, list) or len(position) != 2
                or not all(self._finite_number(point) for point in position)
                or not llx <= float(position[0]) <= urx or not lly <= float(position[1]) <= ury
                or not isinstance(body, str) or not 1 <= len(body) <= 20000
            ):
                raise LibraryError("note position or body is invalid")
            if anchor is not None:
                if not isinstance(anchor, dict):
                    raise LibraryError("note anchor must be an object or null")
                if anchor.get("document_id") != document_id or anchor.get("version_id") != version_id or anchor.get("page_index") != page_index:
                    raise LibraryError("note anchor provenance mismatch")
                self.verify_anchor(anchor, page)
        elif kind == "bookmark":
            if set(payload) != {"label"} or not isinstance(payload["label"], str) or len(payload["label"]) > 240:
                raise LibraryError("bookmark payload is invalid")
        else:
            if set(payload) != {"strokes"} or not isinstance(payload["strokes"], list) or not payload["strokes"]:
                raise LibraryError("ink payload is invalid")
            if len(payload["strokes"]) > 10000:
                raise LibraryError("ink payload exceeds the stroke limit")
            seen_strokes: set[str] = set()
            for stroke in payload["strokes"]:
                if not isinstance(stroke, dict) or set(stroke) != {"stroke_id", "tool", "color", "width_pt", "points"}:
                    raise LibraryError("ink stroke fields do not match contract")
                stroke_id = _uuid(stroke["stroke_id"], "stroke")
                if stroke_id in seen_strokes:
                    raise LibraryError("duplicate stroke id")
                seen_strokes.add(stroke_id)
                if not isinstance(stroke["tool"], str) or stroke["tool"] not in {"pen", "highlighter"}:
                    raise LibraryError("unsupported ink tool")
                self._validate_color(stroke["color"])
                if not self._finite_number(stroke["width_pt"]) or not 0 < float(stroke["width_pt"]) <= 100:
                    raise LibraryError("ink width is invalid")
                points = stroke["points"]
                if not isinstance(points, list) or not 1 <= len(points) <= 100000:
                    raise LibraryError("ink points are invalid")
                for point in points:
                    if not isinstance(point, dict) or set(point) != {"x", "y", "pressure", "t_ms"}:
                        raise LibraryError("ink point fields do not match contract")
                    x, y, pressure, t_ms = point["x"], point["y"], point["pressure"], point["t_ms"]
                    if (
                        not self._finite_number(x) or not self._finite_number(y)
                        or not llx <= float(x) <= urx or not lly <= float(y) <= ury
                        or not self._finite_number(pressure) or not 0 <= float(pressure) <= 1
                        or isinstance(t_ms, bool) or not isinstance(t_ms, int)
                        or not 0 <= t_ms <= 9007199254740991
                    ):
                        raise LibraryError("ink point is outside its page or invalid")
        return {
            "annotation_id": annotation_id,
            "document_id": document_id,
            "version_id": version_id,
            "page_index": page_index,
            "kind": kind,
            "payload": payload,
        }

    @staticmethod
    def _finite_number(value: Any) -> bool:
        if not isinstance(value, (int, float)) or isinstance(value, bool):
            return False
        try:
            return math.isfinite(float(value))
        except (OverflowError, ValueError):
            return False

    @staticmethod
    def _validate_color(value: Any) -> None:
        if not isinstance(value, str) or not re.fullmatch(r"#[A-Fa-f0-9]{8}", value):
            raise LibraryError("annotation color must be #RRGGBBAA")

    @staticmethod
    def _current_record(conn: sqlite3.Connection, document_id: str, version_id: str, annotation_id: str):
        row = conn.execute(
            "SELECT record_json FROM mnemosyne_annotations WHERE document_id=? AND version_id=? AND annotation_id=?",
            (document_id, version_id, annotation_id),
        ).fetchone()
        return json.loads(row["record_json"]) if row else None

    @staticmethod
    def _watermark(conn: sqlite3.Connection, document_id: str, version_id: str) -> int:
        row = conn.execute(
            "SELECT revision FROM mnemosyne_annotation_clock WHERE document_id=? AND version_id=?",
            (document_id, version_id),
        ).fetchone()
        return int(row["revision"]) if row else 0

    async def apply_mutations(self, batch: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(batch, dict) or set(batch) != {"contract_version", "document_id", "version_id", "mutations"}:
            raise LibraryError("mutation batch fields do not match contract")
        if batch["contract_version"] != CONTRACT_VERSION:
            raise LibraryError("contract version mismatch")
        document_id, version_id = _uuid(batch["document_id"], "document"), _version(batch["version_id"])
        mutations = batch["mutations"]
        if not isinstance(mutations, list) or not 1 <= len(mutations) <= 100:
            raise LibraryError("mutation batch must contain 1–100 operations")
        results = []
        for mutation in mutations:
            results.append(self._apply_mutation(mutation, document_id, version_id))
        return {
            "contract_version": CONTRACT_VERSION,
            "document_id": document_id,
            "version_id": version_id,
            "results": results,
        }

    def _apply_mutation(self, mutation: Any, batch_document: str, batch_version: str) -> dict[str, Any]:
        if not isinstance(mutation, dict) or "client_mutation_id" not in mutation:
            raise LibraryError("mutation requires client_mutation_id")
        mutation_id = _uuid(mutation["client_mutation_id"], "mutation")
        try:
            payload_hash = hashlib.sha256(_canonical_json(mutation)).hexdigest()
        except (LibraryError, RecursionError):
            with self.db.connect() as conn:
                return self._mutation_result(
                    mutation_id, "rejected", "invalid_request",
                    self._watermark(conn, batch_document, batch_version),
                    None,
                )
        try:
            document_id = _uuid(mutation.get("document_id"), "document")
            version_id = _version(mutation.get("version_id"))
            annotation_id = _uuid(mutation.get("annotation_id"), "annotation")
        except LibraryError:
            document_id, version_id, annotation_id = batch_document, batch_version, str(uuid.uuid4())
        if document_id != batch_document or version_id != batch_version:
            raise LibraryError("mutation does not match its batch document version")

        with self.db.connect(write=True) as conn:
            prior = conn.execute(
                "SELECT payload_sha256, response_json FROM mnemosyne_mutations WHERE client_mutation_id=?",
                (mutation_id,),
            ).fetchone()
            if prior is not None:
                if prior["payload_sha256"] == payload_hash:
                    return json.loads(prior["response_json"])
                return self._mutation_result(
                    mutation_id, "rejected", "idempotency_mismatch",
                    self._watermark(conn, batch_document, batch_version),
                    self._current_record(conn, batch_document, batch_version, annotation_id),
                )

            status, code, current = "rejected", "invalid_request", None
            watermark = self._watermark(conn, batch_document, batch_version)
            try:
                self._active_document(batch_document, batch_version)
                self._validate_mutation_envelope(mutation, batch_document, batch_version, annotation_id)
                existing = self._current_record(conn, batch_document, batch_version, annotation_id)
                current = existing
                base_revision = mutation["base_revision"]
                operation = mutation["operation"]
                if operation == "upsert":
                    draft = self._validate_draft(mutation["annotation"], batch_document, batch_version)
                    if draft["annotation_id"] != annotation_id:
                        raise LibraryError("mutation and draft annotation ids differ")
                    if existing is None:
                        if base_revision != 0:
                            status, code = "conflict", "conflict"
                        else:
                            status, code = "applied", "ok"
                    elif int(base_revision) != int(existing["server_revision"]) or existing["deleted"]:
                        status, code = "conflict", "conflict"
                    else:
                        status, code = "applied", "ok"
                    if status == "applied":
                        watermark += 1
                        now = _now()
                        current = {
                            **draft,
                            "server_revision": watermark,
                            "updated_at": now,
                            "deleted": False,
                            "deleted_at": None,
                        }
                        self._write_annotation(conn, current)
                else:
                    if existing is None:
                        raise LibraryError("cannot delete an unknown annotation")
                    if int(base_revision) != int(existing["server_revision"]) or existing["deleted"]:
                        status, code = "conflict", "conflict"
                    else:
                        watermark += 1
                        now = _now()
                        current = {
                            "annotation_id": annotation_id,
                            "document_id": batch_document,
                            "version_id": batch_version,
                            "page_index": existing["page_index"],
                            "kind": existing["kind"],
                            "server_revision": watermark,
                            "updated_at": now,
                            "deleted": True,
                            "deleted_at": now,
                            "payload": None,
                        }
                        status, code = "applied", "ok"
                        self._write_annotation(conn, current)
            except DocumentDeleted:
                status, code = "rejected", "document_deleted"
            except (LibraryError, TypeError, ValueError, OverflowError, KeyError, AttributeError, RecursionError):
                status, code = "rejected", "invalid_request"

            result = self._mutation_result(mutation_id, status, code, watermark, current)
            conn.execute(
                "INSERT INTO mnemosyne_mutations VALUES (?, ?, ?, ?, ?, ?)",
                (mutation_id, payload_hash, batch_document, batch_version,
                 json.dumps(result, ensure_ascii=False, separators=(",", ":")), _now()),
            )
            return result

    @staticmethod
    def _validate_mutation_envelope(
        mutation: dict[str, Any], document_id: str, version_id: str, annotation_id: str
    ) -> None:
        operation = mutation.get("operation")
        expected = {
            "client_mutation_id", "client_id", "document_id", "version_id", "annotation_id",
            "base_revision", "created_at", "operation",
        }
        if isinstance(operation, str) and operation == "upsert":
            expected.add("annotation")
        if (
            not isinstance(operation, str)
            or operation not in {"upsert", "delete"}
            or set(mutation) != expected
        ):
            raise LibraryError("mutation fields do not match contract")
        _uuid(mutation["client_id"], "client")
        if _uuid(mutation["document_id"], "document") != document_id:
            raise LibraryError("mutation document mismatch")
        if _version(mutation["version_id"]) != version_id:
            raise LibraryError("mutation version mismatch")
        if _uuid(mutation["annotation_id"], "annotation") != annotation_id:
            raise LibraryError("mutation annotation id mismatch")
        base = mutation["base_revision"]
        if isinstance(base, bool) or not isinstance(base, int) or not 0 <= base <= 9007199254740991:
            raise LibraryError("base revision is invalid")
        created_at = mutation["created_at"]
        if not isinstance(created_at, str):
            raise LibraryError("mutation created_at is invalid")
        try:
            datetime.fromisoformat(created_at.replace("Z", "+00:00"))
        except ValueError as exc:
            raise LibraryError("mutation created_at is invalid") from exc

    @staticmethod
    def _write_annotation(conn: sqlite3.Connection, record: dict[str, Any]) -> None:
        document_id, version_id = record["document_id"], record["version_id"]
        revision = int(record["server_revision"])
        encoded = json.dumps(record, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        conn.execute(
            "UPDATE mnemosyne_annotation_clock SET revision=? WHERE document_id=? AND version_id=?",
            (revision, document_id, version_id),
        )
        conn.execute(
            "INSERT INTO mnemosyne_annotations VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(document_id, version_id, annotation_id) DO UPDATE SET "
            "server_revision=excluded.server_revision, record_json=excluded.record_json",
            (document_id, version_id, record["annotation_id"], revision, encoded),
        )
        conn.execute(
            "INSERT INTO mnemosyne_annotation_log VALUES (?, ?, ?, ?, ?)",
            (document_id, version_id, revision, record["annotation_id"], encoded),
        )

    @staticmethod
    def _mutation_result(mutation_id: str, status: str, code: str, watermark: int, current: Any) -> dict[str, Any]:
        return {
            "client_mutation_id": mutation_id,
            "status": status,
            "code": code,
            "server_revision": watermark,
            "current": current,
        }

    async def snapshot(self, document_id: str, version_id: str) -> dict[str, Any]:
        document_id, version_id = _uuid(document_id, "document"), _version(version_id)
        self._active_document(document_id, version_id)
        with self.db.connect(write=True) as conn:
            watermark = self._watermark(conn, document_id, version_id)
            rows = conn.execute(
                "SELECT record_json FROM mnemosyne_annotations WHERE document_id=? AND version_id=? "
                "ORDER BY json_extract(record_json, '$.page_index'), server_revision, annotation_id",
                (document_id, version_id),
            ).fetchall()
            cursor = self._new_cursor(conn, document_id, version_id, watermark)
            return {
                "contract_version": CONTRACT_VERSION,
                "document_id": document_id,
                "version_id": version_id,
                "snapshot_revision": watermark,
                "annotations": [json.loads(row["record_json"]) for row in rows],
                "next_cursor": cursor,
            }

    async def changes(self, cursor: str, limit: int = 100) -> dict[str, Any]:
        if not isinstance(cursor, str) or not cursor or len(cursor) > 256:
            raise CursorExpired("invalid sync cursor")
        limit = max(1, min(int(limit), 500))
        with self.db.connect(write=True) as conn:
            row = conn.execute(
                "SELECT * FROM mnemosyne_cursors WHERE token=?", (cursor,)
            ).fetchone()
            if row is None or float(row["expires_at"]) <= time.time():
                raise CursorExpired("sync cursor expired; request a fresh snapshot")
            document_id, version_id, revision = row["document_id"], row["version_id"], int(row["revision"])
            try:
                self._active_document(document_id, version_id)
            except DocumentDeleted:
                raise
            rows = conn.execute(
                "SELECT revision, record_json FROM mnemosyne_annotation_log WHERE document_id=? AND version_id=? "
                "AND revision>? ORDER BY revision LIMIT ?",
                (document_id, version_id, revision, limit + 1),
            ).fetchall()
            has_more = len(rows) > limit
            selected = rows[:limit]
            next_revision = int(selected[-1]["revision"]) if selected else revision
            next_cursor = self._new_cursor(conn, document_id, version_id, next_revision)
            return {
                "contract_version": CONTRACT_VERSION,
                "document_id": document_id,
                "version_id": version_id,
                "changes": [json.loads(item["record_json"]) for item in selected],
                "next_cursor": next_cursor,
                "has_more": has_more,
            }

    @staticmethod
    def _new_cursor(conn: sqlite3.Connection, document_id: str, version_id: str, revision: int) -> str:
        token = secrets.token_urlsafe(32)
        now, ttl = time.time(), 30 * 24 * 60 * 60
        conn.execute("DELETE FROM mnemosyne_cursors WHERE expires_at<=?", (now,))
        conn.execute(
            "INSERT INTO mnemosyne_cursors VALUES (?, ?, ?, ?, ?, ?)",
            (token, document_id, version_id, revision, now + ttl, now),
        )
        return token

def register_library(
    store: ReadingStore,
    *,
    annotation_sync=None,
    max_upload_bytes: int = MAX_PDF_BYTES,
    rag_indexer: Callable[..., Any] | None = None,
    rag_search: Callable[..., Any] | None = None,
    settings_defaults_provider: Callable[[], dict[str, Any]] | None = None,
    settings_secret_writer: Callable[[str], Any] | None = None,
    settings_credential_reader: Callable[[], bool] | None = None,
    settings_base_url_validator: Callable[[str], bool] | None = None,
) -> LibraryAdapter:
    """Build UNIT-01 services; no router, HTTP loopback, or fake success state."""
    return LibraryAdapter(
        store,
        annotation_sync,
        max_upload_bytes=max_upload_bytes,
        rag_indexer=rag_indexer,
        rag_search=rag_search,
        settings_defaults_provider=settings_defaults_provider,
        settings_secret_writer=settings_secret_writer,
        settings_credential_reader=settings_credential_reader,
        settings_base_url_validator=settings_base_url_validator,
    )


def build_library_router(library: LibraryAdapter):
    """Create the external HTTP adapter; the integrator mounts it after auth/Origin guards.

    The service methods above are also callable directly by Tutor. This router
    does not make internal loopback requests and deliberately does not install
    authentication middleware; the shared API assembly owns that boundary.
    """
    from fastapi import APIRouter, Header, Request
    from fastapi.responses import JSONResponse, Response

    # With postponed annotations FastAPI resolves Request against module globals,
    # while keeping the framework import lazy for direct service consumers.
    globals()["Request"] = Request
    router = APIRouter(prefix="/v1")

    def request_id(request: Request) -> str:
        supplied = request.headers.get("X-Request-ID", "")
        try:
            return str(uuid.UUID(supplied)) if supplied else str(uuid.uuid4())
        except ValueError:
            return str(uuid.uuid4())

    def error_response(request: Request, exc: Exception | None = None, *, code: str | None = None, status: int | None = None):
        details: dict[str, Any] = {}
        retryable = False
        if isinstance(exc, RevisionConflict):
            code, status = "conflict", 409
            details["current_revision"] = exc.current_revision
        elif isinstance(exc, CursorExpired):
            code, status = "cursor_expired", 410
        elif isinstance(exc, DocumentDeleted):
            code, status = "document_deleted", 410
        elif isinstance(exc, LibraryError):
            message = str(exc).lower()
            if "not found" in message:
                code, status = "not_found", 404
            elif any(token in message for token in (
                "not ready", "requires pymupdf", "not configured", "not connected",
                "unavailable", "secure credential writer",
            )):
                code, status = "not_ready", 503
                retryable = True
            elif "exceeds" in message or "size limit" in message:
                code, status = "too_large", 413
            elif "not a pdf" in message or "only pdf" in message or "empty pdf" in message:
                code, status = "invalid_pdf", 400
            elif "confirmation" in message:
                code, status = "forbidden", 403
            else:
                code, status = "invalid_request", 400
        elif isinstance(exc, (ValueError, TypeError)):
            code, status = "invalid_request", 400
        elif isinstance(exc, sqlite3.Error):
            code, status, retryable = "provider_error", 503, True
        elif exc is not None:
            code, status = "internal_error", 500
        code = code or "internal_error"
        status = status or 500
        messages = {
            "invalid_request": "요청 형식이나 값이 올바르지 않습니다.",
            "invalid_pdf": "PDF 파일을 읽을 수 없습니다.",
            "too_large": "업로드 파일이 허용된 크기를 초과했습니다.",
            "not_found": "요청한 문서나 항목을 찾을 수 없습니다.",
            "not_ready": "요청한 기능이 아직 준비되지 않았습니다.",
            "conflict": "다른 기기에서 먼저 변경했습니다. 최신 상태를 동기화해 주세요.",
            "idempotency_mismatch": "같은 mutation ID가 다른 내용으로 재사용되었습니다.",
            "cursor_expired": "동기화 cursor가 만료되었습니다. 새 snapshot을 받아 주세요.",
            "document_deleted": "문서가 삭제되어 더 이상 변경할 수 없습니다.",
            "contract_mismatch": "계약 버전이 일치하지 않습니다.",
            "rate_limited": "요청이 많습니다. 잠시 후 다시 시도해 주세요.",
            "provider_error": "저장소 또는 인덱싱 제공자를 사용할 수 없습니다.",
            "unauthorized": "인증이 필요합니다.",
            "forbidden": "이 작업은 허용되지 않습니다.",
            "internal_error": "서버에서 요청을 처리하지 못했습니다.",
        }
        body = {
            "contract_version": CONTRACT_VERSION,
            "code": code,
            "message_ko": messages.get(code, messages["internal_error"]),
            "request_id": request_id(request),
            "retryable": retryable,
            "details": details,
        }
        return JSONResponse(body, status_code=status)

    def contract_response(request: Request, value: str | None):
        if value != CONTRACT_VERSION:
            return error_response(request, code="contract_mismatch", status=409)
        return None

    async def execute(request: Request, operation: Callable[[], Any], *, status: int = 200, headers=None):
        try:
            value = operation()
            if inspect.isawaitable(value):
                value = await value
            if isinstance(value, Response):
                return value
            return JSONResponse(value, status_code=status, headers=headers)
        except Exception as exc:
            return error_response(request, exc)

    def contract_document(document: dict[str, Any]) -> dict[str, Any]:
        keys = (
            "document_id", "version_id", "source_sha256", "title", "subject_id",
            "content_language", "page_count", "server_revision", "original_available",
            "parse_state", "index_state", "created_at",
        )
        return {key: document[key] for key in keys}

    def expected_revision(value: str | None) -> int:
        match = re.fullmatch(r'"([1-9][0-9]*)"', value or "")
        if match is None:
            raise LibraryError("If-Match must contain a quoted server revision")
        return int(match.group(1))

    @router.get("/settings")
    async def get_public_settings(
        request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            value = await asyncio.to_thread(library.get_public_settings)
            return JSONResponse(value, headers={"ETag": f'"{value["server_revision"]}"'})
        return await execute(request, operation)

    @router.put("/settings")
    async def update_public_settings(
        request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
        if_match: str | None = Header(None, alias="If-Match"),
        confirm_action: str | None = Header(None, alias="X-Confirm-Action"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            body = await request.json()
            revision = expected_revision(if_match)
            value = await asyncio.to_thread(
                library.save_public_settings,
                body,
                expected_revision=revision,
                confirm_action=str(confirm_action or ""),
            )
            return JSONResponse(value, headers={"ETag": f'"{value["server_revision"]}"'})
        return await execute(request, operation)

    @router.get("/subjects")
    async def list_subjects(request: Request, contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version")):
        mismatch = contract_response(request, contract)
        return mismatch or await execute(request, library.list_subjects)

    @router.post("/subjects", status_code=201)
    async def create_subject(request: Request, contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version")):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"name"}:
                raise LibraryError("subject body fields do not match contract")
            return library.create_subject(body["name"])
        return await execute(request, operation, status=201)

    @router.patch("/subjects/{subject_id}")
    async def rename_subject(
        subject_id: str, request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
        if_match: str | None = Header(None, alias="If-Match"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"name"}:
                raise LibraryError("subject body fields do not match contract")
            revision = expected_revision(if_match)
            return library.rename_subject(subject_id, body["name"], expected_revision=revision)
        return await execute(request, operation)

    @router.delete("/subjects/{subject_id}")
    async def delete_subject(
        subject_id: str, request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
        if_match: str | None = Header(None, alias="If-Match"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            revision = expected_revision(if_match)
            return {"deleted": library.delete_subject(subject_id, expected_revision=revision)}
        return await execute(request, operation)

    @router.get("/documents")
    async def list_documents(
        request: Request, subject_id: str | None = None,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        return await execute(request, lambda: [contract_document(item) for item in library.list_documents(subject_id=subject_id)])

    @router.post("/documents", status_code=201)
    async def upload_document(
        request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            async with request.form(max_files=1, max_fields=2, max_part_size=library.max_upload_bytes + 1) as form:
                if set(form.keys()) - {"file", "title", "subject_id"}:
                    raise LibraryError("PDF upload form fields do not match contract")
                upload = form.get("file")
                title = form.get("title")
                subject_id = form.get("subject_id")
                if upload is None or not hasattr(upload, "read") or not isinstance(title, str) or not title.strip():
                    raise LibraryError("PDF file and title are required")
                data = await upload.read(library.max_upload_bytes + 1)
                document = await library.upload_pdf_async(
                    data, str(getattr(upload, "filename", "")), title=title,
                    subject_id=str(subject_id) if subject_id is not None else None,
                )
                return contract_document(document)
        return await execute(request, operation, status=201)

    @router.get("/documents/{document_id}")
    async def get_document(
        document_id: str, request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            document = library.get_document(document_id)
            return JSONResponse(contract_document(document), headers={"ETag": f'"{document["server_revision"]}"'})
        return await execute(request, operation)

    @router.patch("/documents/{document_id}")
    async def update_document(
        document_id: str, request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
        if_match: str | None = Header(None, alias="If-Match"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            body = await request.json()
            if not isinstance(body, dict) or not set(body) <= {"title", "subject_id"} or not body:
                raise LibraryError("document update fields do not match contract")
            revision = expected_revision(if_match)
            document = library.update_document(document_id, **body, expected_revision=revision)
            return JSONResponse(contract_document(document), headers={"ETag": f'"{document["server_revision"]}"'})
        return await execute(request, operation)

    @router.delete("/documents/{document_id}")
    async def delete_document(
        document_id: str, request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
        if_match: str | None = Header(None, alias="If-Match"),
        confirm_action: str | None = Header(None, alias="X-Confirm-Action"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            revision = expected_revision(if_match)
            deleted = library.delete_document(
                document_id, confirm_action=confirm_action, expected_revision=revision
            )
            return {"deleted": deleted}
        return await execute(request, operation)

    @router.get("/documents/{document_id}/file")
    async def download_original(
        document_id: str, request: Request, version_id: str,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        return await execute(request, lambda: Response(library.download_original(document_id, version_id), media_type="application/pdf"))

    @router.get("/documents/{document_id}/pages/{page_index}")
    async def get_page(
        document_id: str, page_index: int, request: Request, version_id: str,
        parse_revision: str | None = None,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        return await execute(request, lambda: library.get_page(document_id, version_id, page_index, parse_revision))

    @router.post("/documents/{document_id}/search")
    async def search_document(
        document_id: str, request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"query", "version_id", "limit"}:
                raise LibraryError("search body fields do not match contract")
            return library.search_anchors(document_id, body["version_id"], body["query"], body["limit"])
        return await execute(request, operation)

    @router.post("/citations/verify")
    async def verify_citation(
        request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            anchor = await request.json()
            if not isinstance(anchor, dict):
                raise LibraryError("citation body must be an anchor object")
            return library.verify_citation(anchor)
        return await execute(request, operation)

    @router.get("/documents/{document_id}/annotations/snapshot")
    async def annotation_snapshot(
        document_id: str, request: Request, version_id: str,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        return await execute(request, lambda: library.snapshot(document_id, version_id))

    @router.get("/documents/{document_id}/annotations/changes")
    async def annotation_changes(
        document_id: str, request: Request, version_id: str, cursor: str, limit: int = 100,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            result = await library.changes(cursor, limit)
            if result["document_id"] != _uuid(document_id, "document") or result["version_id"] != _version(version_id):
                raise CursorExpired("sync cursor belongs to another document version")
            return result
        return await execute(request, operation)

    @router.post("/documents/{document_id}/annotations/mutations")
    async def annotation_mutations(
        document_id: str, request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            batch = await request.json()
            if not isinstance(batch, dict) or batch.get("document_id") != _uuid(document_id, "document"):
                raise LibraryError("mutation path and batch document differ")
            return await library.apply_mutations(batch)
        return await execute(request, operation)

    @router.post("/documents/{document_id}/exports", status_code=201)
    async def create_export(
        document_id: str, request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        async def operation():
            body = await request.json()
            if not isinstance(body, dict) or set(body) != {"version_id", "annotation_revision", "include_ink"}:
                raise LibraryError("export body fields do not match contract")
            return library.export_annotated_pdf(
                document_id, body["version_id"], body["annotation_revision"], include_ink=body["include_ink"]
            )
        return await execute(request, operation, status=201)

    @router.get("/exports/{export_id}/file")
    async def download_export(
        export_id: str, request: Request,
        contract: str | None = Header(None, alias="X-Mnemosyne-Contract-Version"),
    ):
        mismatch = contract_response(request, contract)
        if mismatch:
            return mismatch
        return await execute(request, lambda: Response(library.download_export(export_id), media_type="application/pdf"))

    return router
