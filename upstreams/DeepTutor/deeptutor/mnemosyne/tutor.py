"""UNIT-02: native TurnApplicationService boundary, preserving v2 /ws."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

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
REQUIRED_LEARNING_SERVICES = ("assessment", "memory", "progress", "review")


def native_turn_request(
    request: dict[str, Any], *, material_id: str, material_revision: int
) -> TurnRequest:
    context = request["reader_context"]
    capability = CAPABILITY_MAP.get(request["capability"])
    if capability is None:
        raise ValueError(
            "This action requires a learning-state service, not a native turn capability"
        )
    return TurnRequest(
        content=request["message"],
        capability=capability,
        client_submission_id=request["client_mutation_id"],
        reply_language_override=request.get("response_language", "ko"),
        language=context.get("content_language", "und"),
        reading_material_id=material_id,
        reading_material_revision=material_revision,
        reading_viewport={
            "locator": locator_for_page(context["page_index"]),
            "selection": (context.get("selection") or {}).get("quote"),
        },
    )


def semantic_event(frame: dict[str, Any]) -> dict[str, Any] | None:
    """Consume an extension only when its stable IDs agree with persisted wire IDs.

    Native error frames may be recoverable. Terminal semantics are carried only
    on native done with its authoritative status; no renumbering native frames.
    """
    event = frame.get("metadata", {}).get("mnemosyne")
    if event is None:
        return None
    if (
        frame.get("protocol_version") != "2.0"
        or event["contract_version"] != "0.1.0"
        or event["seq"] != frame["seq"]
        or event["turn_id"] != frame["turn_id"]
        or event["event_id"] != f"{frame['turn_id']}:{frame['seq']}"
    ):
        raise ValueError("Wire/semantic event mismatch")
    terminal = {"completed": "turn.done", "failed": "turn.error", "cancelled": "turn.cancelled"}
    kind = event["type"]
    if frame["type"] == "done":
        if kind != terminal.get(frame["metadata"].get("status")):
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


def register_tutor(
    turns, library, *, learning_store: LearningStateStore | None = None
) -> TutorAdapter:
    return TutorAdapter(turns, library, learning_store)
