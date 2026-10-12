"""Integrator-owned signatures. UNIT-01 owns every durable server transaction."""

from __future__ import annotations

from typing import Any, Protocol


class AnnotationSync(Protocol):
    async def apply_mutations(self, batch: dict[str, Any]) -> dict[str, Any]: ...
    async def snapshot(self, document_id: str, version_id: str) -> dict[str, Any]: ...
    async def changes(self, cursor: str, limit: int) -> dict[str, Any]: ...


class LearningStateStore(Protocol):
    async def create_quiz(
        self,
        public_quiz: dict[str, Any],
        private_grading: dict[str, Any],
        client_mutation_id: str,
        request_sha256: str,
    ) -> dict[str, Any]: ...
    async def get_quiz_for_mutation(
        self, client_mutation_id: str, request_sha256: str
    ) -> dict[str, Any] | None: ...
    async def get_quiz(self, quiz_id: str) -> dict[str, Any]: ...
    async def get_grading_input(
        self, quiz_id: str, document_id: str, version_id: str
    ) -> dict[str, Any]: ...
    async def get_state(self, document_id: str, version_id: str) -> dict[str, Any]: ...
    async def begin_attempt(self, attempt: dict[str, Any], payload_sha256: str) -> dict[str, Any]: ...
    async def commit_assessment(
        self,
        attempt: dict[str, Any],
        payload_sha256: str,
        assessment: dict[str, Any],
        *,
        question_results: list[dict[str, Any]],
    ) -> dict[str, Any]: ...
    async def release_attempt_for_retry(
        self, attempt_id: str, payload_sha256: str, safe_error_code: str
    ) -> None: ...
    async def save_activity(
        self,
        activity: dict[str, Any],
        mutation_id: str,
        base_revision: int,
        *,
        document_id: str,
        version_id: str,
    ) -> dict[str, Any]: ...
    async def record_progress(
        self,
        *,
        document_id: str,
        version_id: str,
        mutation_id: str,
        base_revision: int,
        page_index: int,
        reading_seconds: int,
    ) -> dict[str, Any]: ...
    async def review_memory(self, review: dict[str, Any]) -> dict[str, Any]: ...


class DocumentSearch(Protocol):
    def verify_anchor(self, anchor: dict[str, Any], page: dict[str, Any]) -> None: ...
    def search(self, material_id: str, query: str, limit: int = 12) -> Any: ...


class DocumentRepository(Protocol):
    async def get_document(
        self, document_id: str, version_id: str | None = None
    ) -> dict[str, Any]: ...
    async def get_page(
        self, document_id: str, version_id: str, page_index: int, parse_revision: str
    ) -> dict[str, Any]: ...
    async def get_asset(self, document_id: str, version_id: str, asset_id: str) -> Any: ...
