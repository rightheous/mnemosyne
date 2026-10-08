"""UNIT-02: native TurnApplicationService boundary, preserving v2 /ws."""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any
from uuid import UUID

from deeptutor.core.turn_request import TurnRequest
from deeptutor.mnemosyne.library import locator_for_page
from deeptutor.mnemosyne.ports import LearningStateStore

# Assessment, memory and review are state/services, not imaginary upstream capabilities.
CAPABILITY_MAP = {
    "chat": "chat",
    "reading": "immersive_reading",
    "quiz": "deep_question",
    "mastery": "mastery_path",
    "solve": "deep_solve",
}
SUPPORTED_CAPABILITIES = frozenset(
    {"chat", "reading", "quiz", "assessment", "mastery", "solve", "memory", "progress", "review"}
)
REQUIRED_LEARNING_SERVICES = ("assessment", "memory", "progress", "review")
_VERSION_RE = re.compile(r"^sha256:[a-f0-9]{64}$")


def _required_id(value: Any, field: str, *, uuid_value: bool = False) -> str:
    normalized = str(value or "").strip()
    if not normalized:
        raise ValueError(f"{field} is required")
    if uuid_value:
        try:
            UUID(normalized)
        except (ValueError, AttributeError) as exc:
            raise ValueError(f"{field} must be a UUID") from exc
    return normalized


def _learning_store(store: LearningStateStore | None) -> LearningStateStore:
    if store is None:
        raise RuntimeError("Learning state is not ready; the durable learning store is unavailable")
    return store


def native_turn_request(
    request: dict[str, Any], *, material_id: str | None = None, material_revision: int | None = None
) -> TurnRequest:
    if not isinstance(request, dict):
        raise ValueError("Tutor request must be an object")
    action = str(request.get("capability") or "").strip()
    context = request.get("reader_context") or {}
    if not isinstance(context, dict):
        raise ValueError("reader_context must be an object")
    capability = CAPABILITY_MAP.get(action)
    if capability is None:
        raise ValueError(
            "This action requires a learning-state service, not a native turn capability"
        )
    response_language = str(request.get("response_language") or "ko").strip().lower()
    message = str(request.get("message") or "").strip()
    if not message:
        raise ValueError("message is required")
    submission_id = _required_id(
        request.get("client_mutation_id"), "client_mutation_id", uuid_value=True
    )

    native_material_id = str(material_id or "").strip()
    native_revision = material_revision
    page_index = context.get("page_index")
    viewport: dict[str, Any] | None = None
    if context:
        document_id = _required_id(context.get("document_id"), "reader_context.document_id", uuid_value=True)
        version_id = str(context.get("version_id") or "")
        if not _VERSION_RE.fullmatch(version_id):
            raise ValueError("reader_context.version_id must be a full SHA-256 version")
        if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0:
            raise ValueError("reader_context.page_index must be a non-negative integer")
        if not native_material_id or isinstance(native_revision, bool) or not isinstance(native_revision, int) or native_revision < 1:
            if action == "reading":
                raise ValueError("Reading requires the server-resolved material and revision")
        else:
            # The client selection is an untrusted anchor. Do not pass its
            # quote to DeepTutor until the document-version/anchor bridge has
            # verified it through UNIT-01's citation service.
            viewport = {
                "locator": locator_for_page(page_index),
                "selection": None,
            }
    elif action == "reading":
        raise ValueError("Reading requires a verified reader context")

    return TurnRequest(
        content=message,
        capability=capability,
        client_submission_id=submission_id,
        # `language` is DeepTutor's response/UI language. Document language is
        # retained separately by the Mnemosyne request and never used here.
        language=response_language,
        reply_language_override=response_language,
        reading_material_id=native_material_id if action == "reading" else None,
        reading_material_revision=(
            native_revision if action == "reading" and native_revision else None
        ),
        reading_viewport=viewport,
        # Empty means inherit in the upstream UI. A non-matching sentinel is
        # an explicit empty allowlist for these optional extension systems.
        skills=["__mnemosyne_disabled__"],
        mcp=["__mnemosyne_disabled__"],
    )


def semantic_event(frame: dict[str, Any]) -> dict[str, Any] | None:
    """Consume an extension only when its stable IDs agree with persisted wire IDs.

    Native error frames may be recoverable. Terminal semantics are carried only
    on native done with its authoritative status; no renumbering native frames.
    """
    metadata = frame.get("metadata")
    if not isinstance(metadata, dict):
        return None
    event = metadata.get("mnemosyne")
    if event is None:
        return None
    if not isinstance(event, dict):
        raise ValueError("Malformed Mnemosyne event extension")
    try:
        protocol_version = frame["protocol_version"]
        sequence = frame["seq"]
        turn_id = frame["turn_id"]
        event_contract = event["contract_version"]
        event_seq = event["seq"]
        event_turn_id = event["turn_id"]
        event_id = event["event_id"]
        kind = event["type"]
    except KeyError as exc:
        raise ValueError("Incomplete Mnemosyne event extension") from exc
    if (
        protocol_version != "2.0"
        or event_contract != "0.1.0"
        or event_seq != sequence
        or event_turn_id != turn_id
        or event_id != f"{turn_id}:{sequence}"
    ):
        raise ValueError("Wire/semantic event mismatch")
    terminal = {"completed": "turn.done", "failed": "turn.error", "cancelled": "turn.cancelled"}
    if frame["type"] == "done":
        if kind != terminal.get(metadata.get("status")):
            raise ValueError("Terminal status mismatch")
    elif kind in terminal.values():
        raise ValueError("Premature terminal event")
    return event


@dataclass
class TutorAdapter:
    turns: Any
    library: Any
    learning_store: LearningStateStore | None

    @property
    def product_ready(self) -> bool:
        return self.learning_store is not None and self.library.annotation_sync is not None

    @property
    def capabilities(self) -> tuple[str, ...]:
        return tuple(sorted(SUPPORTED_CAPABILITIES))

    async def start_turn(
        self,
        request: dict[str, Any],
        *,
        material_id: str | None = None,
        material_revision: int | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Start one native DeepTutor turn. Repeated client IDs stay idempotent."""
        native = native_turn_request(
            request,
            material_id=material_id,
            material_revision=material_revision,
        )
        return await self.turns.start_turn(native)

    async def subscribe_turn(self, turn_id: str, after_seq: int = 0):
        """Read an existing turn from its native durable event cursor."""
        normalized_id = _required_id(turn_id, "turn_id")
        if isinstance(after_seq, bool) or not isinstance(after_seq, int) or after_seq < 0:
            raise ValueError("after_seq must be a non-negative integer")
        async for frame in self.turns.subscribe_turn(normalized_id, after_seq=after_seq):
            yield frame

    async def resume_turn(self, turn_id: str, seq: int):
        """Reconnect to an existing turn without submitting it again."""
        async for frame in self.subscribe_turn(turn_id, after_seq=seq):
            yield frame

    async def cancel_turn(self, turn_id: str, command_id: str) -> bool:
        normalized_command = _required_id(command_id, "command_id")
        return bool(
            await self.turns.cancel_turn(
                _required_id(turn_id, "turn_id"), command_id=normalized_command
            )
        )

    async def get_learning_state(self, document_id: str) -> dict[str, Any]:
        store = _learning_store(self.learning_store)
        return await store.get_state(_required_id(document_id, "document_id", uuid_value=True))

    async def submit_attempt(self, attempt: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(attempt, dict):
            raise ValueError("attempt must be an object")
        for name in ("attempt_id", "quiz_id", "document_id", "client_mutation_id"):
            _required_id(attempt.get(name), name, uuid_value=True)
        base_revision = attempt.get("base_revision")
        if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision < 0:
            raise ValueError("base_revision must be a non-negative integer")
        return await _learning_store(self.learning_store).submit_attempt(dict(attempt))

    async def save_activity(
        self, activity: dict[str, Any], mutation_id: str, base_revision: int
    ) -> dict[str, Any]:
        if not isinstance(activity, dict):
            raise ValueError("activity must be an object")
        if activity.get("kind") not in SUPPORTED_CAPABILITIES:
            raise ValueError("Unsupported learning activity kind")
        if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision < 0:
            raise ValueError("base_revision must be a non-negative integer")
        return await _learning_store(self.learning_store).save_activity(
            dict(activity), _required_id(mutation_id, "mutation_id", uuid_value=True), base_revision
        )

    async def review_memory(self, review: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(review, dict):
            raise ValueError("review must be an object")
        for name in ("memory_id", "client_mutation_id"):
            _required_id(review.get(name), name, uuid_value=True)
        base_revision = review.get("base_revision")
        if isinstance(base_revision, bool) or not isinstance(base_revision, int) or base_revision < 0:
            raise ValueError("base_revision must be a non-negative integer")
        return await _learning_store(self.learning_store).review_memory(dict(review))


def register_tutor(
    turns, library, *, learning_store: LearningStateStore | None = None
) -> TutorAdapter:
    return TutorAdapter(turns, library, learning_store)
