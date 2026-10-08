"""UNIT-01: adapter to real ReadingStore/PyMuPDF; no replacement database."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import math
from pathlib import Path
from typing import Any
import unicodedata

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


def extract_pdf_pages(path: Path, document_id: str, version_id: str) -> list[dict[str, Any]]:
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
            for block in page.get_text("blocks"):
                if block[6] != 0:
                    continue
                block_text = unicodedata.normalize("NFC", block[4])
                start = text.find(block_text, offset)
                if start < 0:
                    raise ValueError("Parser block/text mismatch")
                # Block boxes are unrotated, crop-relative top-left physical points.
                bx0, by0, bx1, by1 = block[:4]
                rect = [
                    raw_crop[0] + bx0 / unit,
                    raw_crop[3] - by1 / unit,
                    (bx1 - bx0) / unit,
                    (by1 - by0) / unit,
                ]
                end = start + len(block_text.rstrip("\n"))
                if end > start:
                    segments.append(
                        {
                            "start_scalar": start,
                            "end_scalar": end,
                            "rect": [round(v, 6) for v in rect],
                        }
                    )
                offset = start + len(block_text)
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


@dataclass
class LibraryAdapter:
    store: ReadingStore
    annotation_sync: Any = None  # UNIT-01 implements transactional sync; never fake success.

    def search(self, material_id: str, query: str, limit: int = 12):
        return search_material(self.store, material_id, query, limit=limit)

    def verify_anchor(self, anchor: dict[str, Any], page: dict[str, Any]) -> None:
        for field in ("document_id", "version_id", "page_index", "parse_revision", "text_sha256"):
            if anchor[field] != page[field]:
                raise ValueError("Citation provenance mismatch")
        start, end = anchor["start_scalar"], anchor["end_scalar"]
        if (
            not (0 <= start < end <= len(page["text"]))
            or page["text"][start:end] != anchor["quote"]
        ):
            raise ValueError("Citation text mismatch")
        expected = [
            s["rect"]
            for s in page["segments"]
            if s["start_scalar"] == start and s["end_scalar"] == end
        ]
        if not expected or anchor["rects"] != expected:
            raise ValueError("Citation geometry mismatch")


def register_library(store: ReadingStore, *, annotation_sync=None) -> LibraryAdapter:
    return LibraryAdapter(store, annotation_sync)
