"""Shared plumbing for the reading tools.

Split out of :mod:`deeptutor.capabilities.reading.tools` so that module (and the
figure tool beside it) stay under the repository's file-size limit. The names
here are re-exported by ``tools`` unchanged, so existing importers keep working.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolResult
from deeptutor.tools.prompting import load_prompt_hints

logger = logging.getLogger(__name__)

# Private, server-injected kwarg carrying the open material.
MATERIAL_KWARG = "_material_id"
WORKSPACE_KWARG = "_reading_workspace_id"
BINDING_KWARG = "_reading_binding"
READER_CONTEXT_KWARG = "_mnemosyne_reader_context"


def _verified_mnemosyne_citation(
    store: Any,
    material_id: str,
    locator: int,
    quote: str,
    reader_context: Any,
) -> dict[str, Any]:
    """Bind a reader quote to the open source and return UNIT-01 proof.

    The legacy reading material and Mnemosyne library have separate indexes.
    Their original bytes must agree before a contract event can target the
    library document; quote text alone is not enough to establish identity.
    """
    from deeptutor.mnemosyne.library import LibraryAdapter

    if not isinstance(reader_context, dict):
        raise ValueError("Mnemosyne reader context is unavailable")
    document_id = str(reader_context.get("document_id") or "")
    version_id = str(reader_context.get("version_id") or "")
    if not document_id or not re.fullmatch(r"sha256:[a-f0-9]{64}", version_id):
        raise ValueError("Mnemosyne reader context is malformed")

    library = LibraryAdapter(store)
    document = library.get_document(document_id, version_id)
    if (
        document.get("document_id") != document_id
        or document.get("version_id") != version_id
        or document.get("parse_state") != "ready"
        or document.get("original_available") is not True
    ):
        raise ValueError("The open Mnemosyne document version is not ready")
    source_bytes = library.download_original(document_id, version_id)
    source_digest = hashlib.sha256(source_bytes).hexdigest()
    if version_id != f"sha256:{source_digest}" or document.get("source_sha256") != source_digest:
        raise ValueError("The Mnemosyne source does not match its immutable version")
    raw_path = store.raw_path(material_id)
    if raw_path is None:
        raise ValueError("The open reading material has no original PDF")
    material_digest = hashlib.sha256(raw_path.read_bytes()).hexdigest()
    if material_digest != source_digest:
        raise ValueError("The open reading material does not match the Mnemosyne document")

    page_index = locator - 1
    page = library.get_page(document_id, version_id, page_index)
    text = page.get("text") if isinstance(page, dict) else None
    if (
        not isinstance(text, str)
        or page.get("document_id") != document_id
        or page.get("version_id") != version_id
        or page.get("page_index") != page_index
    ):
        raise ValueError("The Mnemosyne page is unavailable")
    words = re.findall(r"\S+", quote)
    if not words:
        raise ValueError("A verbatim quote is required")
    match = re.search(r"\s+".join(re.escape(word) for word in words), text)
    if match is None:
        raise ValueError("The quote does not match the Mnemosyne page text")
    start, end = match.span()
    segments = page.get("segments")
    if not isinstance(segments, list):
        raise ValueError("The Mnemosyne page has no verified geometry")
    selected = [
        segment
        for segment in segments
        if isinstance(segment, dict)
        and int(segment.get("start_scalar", -1)) < end
        and int(segment.get("end_scalar", -1)) > start
    ]
    if not selected:
        raise ValueError("The quote has no source geometry")
    anchor = {
        "document_id": document_id,
        "version_id": version_id,
        "page_index": page_index,
        "parse_revision": page.get("parse_revision"),
        "text_sha256": page.get("text_sha256"),
        "start_scalar": start,
        "end_scalar": end,
        "quote": text[start:end],
        "rects": [segment.get("rect") for segment in selected],
    }
    citation = library.verify_citation(anchor)
    if not isinstance(citation, dict) or citation.get("verified") is not True:
        raise ValueError("The source did not verify the reader citation")
    verified_anchor = citation.get("anchor")
    if (
        not isinstance(verified_anchor, dict)
        or verified_anchor.get("document_id") != document_id
        or verified_anchor.get("version_id") != version_id
        or verified_anchor.get("page_index") != page_index
        or verified_anchor.get("quote") != text[start:end]
    ):
        raise ValueError("The source returned a mismatched citation")
    return citation


class _ReadingToolBase(BaseTool):
    """Shared plumbing: resolve the injected material and the store."""

    def get_prompt_hints(self, language: str = "en"):
        return load_prompt_hints(self.name, language=language)

    @staticmethod
    def _material_id(kwargs: dict[str, Any]) -> str:
        binding = kwargs.get(BINDING_KWARG)
        bound_id = binding.get("material_id") if isinstance(binding, dict) else ""
        material_id = str(bound_id or kwargs.get(MATERIAL_KWARG) or "").strip()
        if not material_id:
            raise _NoMaterial()
        from deeptutor.multi_user.learning_access import assert_learning_material

        assert_learning_material(material_id)
        return material_id

    @staticmethod
    def _store():
        # Imported inside the call: ``reading.store`` reaches the path service,
        # which reaches the runtime and the tool registry — importing it at
        # module scope would close that cycle through the builtin registry.
        from deeptutor.reading import ReadingStore

        return ReadingStore()

    @staticmethod
    def _catalog():
        from deeptutor.reading import ReadingCatalogStore

        return ReadingCatalogStore()

    @staticmethod
    def _failure(message: str) -> ToolResult:
        return ToolResult(content=message, success=False)


class _NoMaterial(RuntimeError):
    """Raised when the turn has no open material (should be unreachable)."""


def _guard(func):
    """Turn engine errors into readable tool failures instead of turn deaths."""

    async def wrapper(self: _ReadingToolBase, **kwargs: Any) -> ToolResult:
        from deeptutor.reading import ReadingError

        try:
            return await func(self, **kwargs)
        except _NoMaterial:
            return self._failure(
                "No reading material is open. Ask the user to open a document in the reader."
            )
        except PermissionError as exc:
            return self._failure(str(exc))
        except ReadingError as exc:
            return self._failure(str(exc))
        except Exception:  # pragma: no cover - defensive
            logger.warning("reading tool %s failed", getattr(self, "name", "?"), exc_info=True)
            return self._failure("The reader could not complete that request.")

    return wrapper
