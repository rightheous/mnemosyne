"""UNIT-02: native TurnApplicationService boundary, preserving v2 /ws."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from datetime import datetime
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
    "assessment": "deep_question",
    "mastery": "mastery_path",
    "solve": "deep_solve",
}
_NATIVE_CAPABILITY_ALIASES = {
    **CAPABILITY_MAP,
    **{name: name for name in CAPABILITY_MAP.values()},
}
SUPPORTED_CAPABILITIES = frozenset(
    {"chat", "reading", "quiz", "assessment", "mastery", "solve", "memory", "progress", "review"}
)
REQUIRED_LEARNING_SERVICES = ("assessment", "memory", "progress", "review")
_VERSION_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_CONTENT_LANGUAGE_RE = re.compile(r"^(und|[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*)$")
_CONTENT_LANGUAGE_CONFIG_KEY = "_mnemosyne_content_language"
_DATETIME_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_QUIZ_FIELDS = {
    "quiz_id",
    "document_id",
    "version_id",
    "title",
    "questions",
    "response_language",
}
_ASSESSMENT_FIELDS = {
    "attempt_id",
    "score",
    "feedback_ko",
    "learning_revision",
    "citations",
}
_LEARNING_STATE_FIELDS = {
    "document_id",
    "version_id",
    "learning_revision",
    "quiz_attempts",
    "mastery",
    "memory",
    "progress",
    "activities",
}
_ACTIVITY_KINDS = frozenset(
    {
        "chat",
        "reading",
        "quiz",
        "assessment",
        "mastery",
        "solve",
        "memory",
        "progress",
        "review",
    }
)


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


def _required_timestamp(value: Any, field: str) -> str:
    normalized = str(value or "").strip()
    if not _DATETIME_RE.fullmatch(normalized):
        raise ValueError(f"{field} must be an RFC 3339 date-time")
    try:
        datetime.fromisoformat(
            normalized[:-1] + "+00:00" if normalized.endswith("Z") else normalized
        )
    except ValueError as exc:
        raise ValueError(f"{field} must be an RFC 3339 date-time") from exc
    return normalized


def _safe_integer(value: Any, field: str, *, minimum: int) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < minimum
        or value > _MAX_SAFE_INTEGER
    ):
        raise ValueError(f"{field} must be a safe integer greater than or equal to {minimum}")
    return value


def _required_text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} is required")
    return value


def _score(value: Any, field: str) -> float | int:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field} must be between 0 and 1")
    if value < 0 or value > 1 or (isinstance(value, float) and not math.isfinite(value)):
        raise ValueError(f"{field} must be between 0 and 1")
    return value


def _exact_object(value: Any, fields: set[str], field: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise ValueError(f"{field} fields do not match the contract")
    return value


def _validate_verified_citation(
    citation: Any, *, document_id: str, version_id: str
) -> dict[str, Any]:
    if not isinstance(citation, dict) or set(citation) != {
        "citation_id",
        "verification_id",
        "verified",
        "anchor",
    }:
        raise ValueError("citation fields do not match the VerifiedCitation contract")
    if citation.get("verified") is not True:
        raise ValueError("unverified citation cannot be returned")
    _required_id(citation.get("citation_id"), "citation_id", uuid_value=True)
    _required_id(citation.get("verification_id"), "verification_id", uuid_value=True)
    anchor = citation.get("anchor")
    anchor_fields = {
        "document_id",
        "version_id",
        "page_index",
        "parse_revision",
        "text_sha256",
        "start_scalar",
        "end_scalar",
        "quote",
        "rects",
    }
    if not isinstance(anchor, dict) or set(anchor) != anchor_fields:
        raise ValueError("citation anchor fields do not match the TextAnchor contract")
    if (
        _required_id(anchor.get("document_id"), "anchor.document_id", uuid_value=True)
        != document_id
        or str(anchor.get("version_id") or "") != version_id
    ):
        raise ValueError("citation belongs to another document version")
    _safe_integer(anchor.get("page_index"), "anchor.page_index", minimum=0)
    _required_text(anchor.get("parse_revision"), "anchor.parse_revision")
    if not re.fullmatch(r"[a-f0-9]{64}", str(anchor.get("text_sha256") or "")):
        raise ValueError("anchor.text_sha256 must be a SHA-256 digest")
    start = _safe_integer(anchor.get("start_scalar"), "anchor.start_scalar", minimum=0)
    end = _safe_integer(anchor.get("end_scalar"), "anchor.end_scalar", minimum=1)
    quote = anchor.get("quote")
    if not isinstance(quote, str) or not quote or end <= start or end - start != len(quote):
        raise ValueError("citation quote range is invalid")
    rects = anchor.get("rects")
    if not isinstance(rects, list) or not rects:
        raise ValueError("citation requires at least one rectangle")
    for rect in rects:
        if (
            not isinstance(rect, list)
            or len(rect) != 4
            or any(isinstance(value, bool) or not isinstance(value, (int, float)) for value in rect)
            or any(isinstance(value, float) and not math.isfinite(value) for value in rect)
            or rect[2] <= 0
            or rect[3] <= 0
        ):
            raise ValueError("citation rectangle is invalid")
    return citation


def _verify_citation_at_source(
    library: Any, citation: Any, *, document_id: str, version_id: str
) -> dict[str, Any]:
    citation = _validate_verified_citation(
        citation, document_id=document_id, version_id=version_id
    )
    verifier = getattr(library, "verify_citation", None)
    if not callable(verifier):
        raise RuntimeError("Source citation verification is unavailable")
    verified = verifier(citation["anchor"], citation_id=citation["citation_id"])
    verified = _validate_verified_citation(
        verified, document_id=document_id, version_id=version_id
    )
    if verified["citation_id"] != citation["citation_id"]:
        raise ValueError("source verifier changed the citation ID")
    return verified


def _verify_quiz_citations(library: Any, quiz: dict[str, Any]) -> dict[str, Any]:
    verified_quiz = dict(quiz)
    verified_questions = []
    for question in quiz["questions"]:
        verified_question = dict(question)
        verified_question["citations"] = [
            _verify_citation_at_source(
                library,
                citation,
                document_id=quiz["document_id"],
                version_id=quiz["version_id"],
            )
            for citation in question["citations"]
        ]
        verified_questions.append(verified_question)
    verified_quiz["questions"] = verified_questions
    return verified_quiz


def _verify_learning_state_citations(
    library: Any, state: dict[str, Any]
) -> dict[str, Any]:
    verified_state = dict(state)
    verified_memory = []
    for item in state["memory"]:
        verified_item = dict(item)
        verified_item["citations"] = [
            _verify_citation_at_source(
                library,
                citation,
                document_id=state["document_id"],
                version_id=state["version_id"],
            )
            for citation in item["citations"]
        ]
        verified_memory.append(verified_item)
    verified_state["memory"] = verified_memory
    return verified_state


def _verify_assessment_citations(
    library: Any,
    assessment: dict[str, Any],
    *,
    document_id: str,
    version_id: str,
) -> dict[str, Any]:
    verified_assessment = dict(assessment)
    verified_assessment["citations"] = [
        _verify_citation_at_source(
            library,
            citation,
            document_id=document_id,
            version_id=version_id,
        )
        for citation in assessment["citations"]
    ]
    return verified_assessment


def _validate_public_quiz(quiz: Any) -> dict[str, Any]:
    if not isinstance(quiz, dict) or set(quiz) != _QUIZ_FIELDS:
        raise ValueError("quiz fields do not match the public Quiz contract")
    _required_id(quiz.get("quiz_id"), "quiz_id", uuid_value=True)
    document_id = _required_id(quiz.get("document_id"), "document_id", uuid_value=True)
    version_id = str(quiz.get("version_id") or "").strip()
    if not _VERSION_RE.fullmatch(version_id):
        raise ValueError("quiz.version_id must be a full SHA-256 version")
    if not isinstance(quiz.get("title"), str) or not quiz["title"].strip():
        raise ValueError("quiz.title is required")
    if not isinstance(quiz.get("response_language"), str) or not re.fullmatch(
        r"^(und|[A-Za-z]{2,8}(-[A-Za-z0-9]{1,8})*)$", quiz["response_language"]
    ):
        raise ValueError("quiz.response_language must be a BCP 47 tag or und")
    questions = quiz.get("questions")
    if not isinstance(questions, list) or not questions:
        raise ValueError("quiz.questions must contain at least one question")
    seen_question_ids: set[str] = set()
    for question in questions:
        question_fields = {"question_id", "prompt", "kind", "choices", "citations"}
        if not isinstance(question, dict) or set(question) != question_fields:
            raise ValueError("question fields do not match the public Question contract")
        question_id = _required_id(
            question.get("question_id"), "question_id", uuid_value=True
        )
        if question_id in seen_question_ids:
            raise ValueError("quiz question IDs must be unique")
        seen_question_ids.add(question_id)
        if not isinstance(question.get("prompt"), str) or not question["prompt"].strip():
            raise ValueError("question.prompt is required")
        kind = question.get("kind")
        if not isinstance(kind, str) or kind not in {"single_choice", "free_text"}:
            raise ValueError("question.kind is unsupported")
        choices = question.get("choices")
        if not isinstance(choices, list):
            raise ValueError("question.choices must be an array")
        seen_choice_ids: set[str] = set()
        for choice in choices:
            if (
                not isinstance(choice, dict)
                or set(choice) != {"choice_id", "text"}
                or not isinstance(choice.get("choice_id"), str)
                or not choice["choice_id"].strip()
                or not isinstance(choice.get("text"), str)
                or not choice["text"].strip()
            ):
                raise ValueError("question choice does not match the Choice contract")
            if choice["choice_id"] in seen_choice_ids:
                raise ValueError("question choice IDs must be unique")
            seen_choice_ids.add(choice["choice_id"])
        citations = question.get("citations")
        if not isinstance(citations, list) or not citations:
            raise ValueError("every question requires a verified citation")
        for citation in citations:
            _validate_verified_citation(
                citation, document_id=document_id, version_id=version_id
            )
    return quiz


def _validate_learning_state(
    state: Any,
    *,
    document_id: str | None = None,
    version_id: str | None = None,
) -> dict[str, Any]:
    if not isinstance(state, dict) or set(state) != _LEARNING_STATE_FIELDS:
        raise ValueError("learning state fields do not match the LearningState contract")
    resolved_document_id = _required_id(
        state.get("document_id"), "document_id", uuid_value=True
    )
    resolved_version_id = str(state.get("version_id") or "").strip()
    if not _VERSION_RE.fullmatch(resolved_version_id):
        raise ValueError("learning state version_id must be a full SHA-256 version")
    if document_id is not None and resolved_document_id != document_id:
        raise ValueError("learning state belongs to another document")
    if version_id is not None and resolved_version_id != version_id:
        raise ValueError("learning state belongs to another document version")
    _safe_integer(state.get("learning_revision"), "learning_revision", minimum=1)
    quiz_attempts = state.get("quiz_attempts")
    if not isinstance(quiz_attempts, list):
        raise ValueError("learning state quiz_attempts must be an array")
    for attempt in quiz_attempts:
        attempt = _exact_object(
            attempt, {"attempt_id", "quiz_id", "score"}, "learning state quiz attempt"
        )
        _required_id(attempt.get("attempt_id"), "quiz_attempt.attempt_id", uuid_value=True)
        _required_id(attempt.get("quiz_id"), "quiz_attempt.quiz_id", uuid_value=True)
        _score(attempt.get("score"), "quiz_attempt.score")

    mastery = state.get("mastery")
    if not isinstance(mastery, list):
        raise ValueError("learning state mastery must be an array")
    for item in mastery:
        item = _exact_object(
            item,
            {"concept_id", "label_ko", "score", "evidence_attempt_ids"},
            "learning state mastery item",
        )
        _required_text(item.get("concept_id"), "mastery.concept_id")
        _required_text(item.get("label_ko"), "mastery.label_ko")
        _score(item.get("score"), "mastery.score")
        evidence = item.get("evidence_attempt_ids")
        if not isinstance(evidence, list):
            raise ValueError("mastery.evidence_attempt_ids must be an array")
        for attempt_id in evidence:
            _required_id(attempt_id, "mastery.evidence_attempt_id", uuid_value=True)

    memory_items = state.get("memory")
    if not isinstance(memory_items, list):
        raise ValueError("learning state memory must be an array")
    for item in memory_items:
        item = _exact_object(
            item,
            {"memory_id", "front_ko", "back_ko", "due_at", "review_count", "citations"},
            "learning state memory item",
        )
        _required_id(item.get("memory_id"), "memory.memory_id", uuid_value=True)
        _required_text(item.get("front_ko"), "memory.front_ko")
        _required_text(item.get("back_ko"), "memory.back_ko")
        _required_timestamp(item.get("due_at"), "memory.due_at")
        _safe_integer(item.get("review_count"), "memory.review_count", minimum=0)
        citations = item.get("citations")
        if not isinstance(citations, list) or not citations:
            raise ValueError("memory.citations must contain at least one citation")
        for citation in citations:
            _validate_verified_citation(
                citation,
                document_id=resolved_document_id,
                version_id=resolved_version_id,
            )

    progress = _exact_object(
        state.get("progress"),
        {"last_page_index", "pages_read", "reading_seconds", "next_review_at"},
        "learning state progress",
    )
    _safe_integer(progress.get("last_page_index"), "progress.last_page_index", minimum=0)
    pages_read = progress.get("pages_read")
    if not isinstance(pages_read, list):
        raise ValueError("progress.pages_read must be an array")
    normalized_pages = [
        _safe_integer(page, "progress.pages_read[]", minimum=0) for page in pages_read
    ]
    if len(normalized_pages) != len(set(normalized_pages)):
        raise ValueError("progress.pages_read must not contain duplicate pages")
    _safe_integer(progress.get("reading_seconds"), "progress.reading_seconds", minimum=0)
    _required_timestamp(progress.get("next_review_at"), "progress.next_review_at")

    activities = state.get("activities")
    if not isinstance(activities, list):
        raise ValueError("learning state activities must be an array")
    for activity in activities:
        _validate_learning_activity(activity)
    return state


def _validate_learning_activity(activity: Any) -> dict[str, Any]:
    activity = _exact_object(
        activity,
        {"activity_id", "kind", "turn_id", "summary_ko", "created_at"},
        "learning activity",
    )
    _required_id(activity.get("activity_id"), "activity.activity_id", uuid_value=True)
    kind = activity.get("kind")
    if not isinstance(kind, str) or kind not in _ACTIVITY_KINDS:
        raise ValueError("activity.kind is unsupported")
    turn_id = activity.get("turn_id")
    if turn_id is not None and (
        not isinstance(turn_id, str)
        or not 1 <= len(turn_id) <= 256
        or not re.fullmatch(r"[A-Za-z0-9_-]+", turn_id)
    ):
        raise ValueError("activity.turn_id must be a native turn ID or null")
    if not isinstance(activity.get("summary_ko"), str):
        raise ValueError("activity.summary_ko must be a string")
    _required_timestamp(activity.get("created_at"), "activity.created_at")
    return activity


def _validate_assessment(
    assessment: Any,
    *,
    attempt: dict[str, Any],
    quiz: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(assessment, dict) or set(assessment) != _ASSESSMENT_FIELDS:
        raise ValueError("assessment fields do not match the Assessment contract")
    if _required_id(assessment.get("attempt_id"), "attempt_id", uuid_value=True) != attempt[
        "attempt_id"
    ]:
        raise ValueError("assessment belongs to another attempt")
    _score(assessment.get("score"), "assessment.score")
    feedback = assessment.get("feedback_ko")
    if not isinstance(feedback, str) or not feedback.strip():
        raise ValueError("assessment.feedback_ko is required")
    _safe_integer(assessment.get("learning_revision"), "learning_revision", minimum=1)
    citations = assessment.get("citations")
    if not isinstance(citations, list) or not citations:
        raise ValueError("assessment requires a verified citation")
    allowed = [
        (citation["citation_id"], citation["anchor"])
        for question in quiz["questions"]
        for citation in question["citations"]
    ]
    for citation in citations:
        _validate_verified_citation(
            citation, document_id=quiz["document_id"], version_id=quiz["version_id"]
        )
        if not any(
            citation_id == citation["citation_id"] and anchor == citation["anchor"]
            for citation_id, anchor in allowed
        ):
            raise ValueError("assessment cites evidence outside the submitted quiz")
    return assessment


def _learning_store(store: LearningStateStore | None) -> LearningStateStore:
    if store is None:
        raise RuntimeError("Learning state is not ready; the durable learning store is unavailable")
    return store


def native_protocol_turn_request(
    request: dict[str, Any], *, content_language: str | None = None
) -> TurnRequest:
    """Constrain an already validated native /ws start command for Mnemosyne.

    The WebSocket command schema remains DeepTutor protocol 2.0. This adapter
    applies the personal-tutor defaults and allowlist at the existing start
    boundary, so reconnects continue to subscribe to the original turn ID.
    """
    if not isinstance(request, dict):
        raise ValueError("Tutor request must be an object")
    payload = {
        key: value
        for key, value in request.items()
        if key not in {"type", "protocol_version"}
    }
    config = payload.get("config") or {}
    if not isinstance(config, dict):
        raise ValueError("Tutor config must be an object")
    config = dict(config)
    # Direct protocol clients cannot inject Mnemosyne's source-language
    # context; the adapter supplies this private bridge for Reader turns.
    config.pop(_CONTENT_LANGUAGE_CONFIG_KEY, None)
    if content_language is not None:
        normalized_content_language = str(content_language).strip()
        if not _CONTENT_LANGUAGE_RE.fullmatch(normalized_content_language):
            raise ValueError("content_language must be a valid language tag")
        config[_CONTENT_LANGUAGE_CONFIG_KEY] = normalized_content_language
    payload["config"] = config
    requested_capability = str(payload.get("capability") or "chat").strip()
    capability = _NATIVE_CAPABILITY_ALIASES.get(requested_capability)
    if capability is None:
        raise ValueError("Unsupported personal tutor capability")

    submission_id = _required_id(
        payload.get("client_submission_id") or payload.get("client_mutation_id"),
        "client_submission_id",
        uuid_value=True,
    )
    response_language = str(
        payload.get("response_language")
        or payload.get("reply_language_override")
        or payload.get("language")
        or "ko"
    ).strip().lower()
    payload.update(
        {
            "capability": capability,
            "client_submission_id": submission_id,
            "language": response_language,
            "reply_language_override": response_language,
            # Empty lists inherit the workspace's optional integrations.
            # A sentinel intersects to an empty allowlist in the personal app.
            "skills": ["__mnemosyne_disabled__"],
            "mcp": ["__mnemosyne_disabled__"],
        }
    )

    if capability == "immersive_reading":
        material_id = str(payload.get("reading_material_id") or "").strip()
        revision = payload.get("reading_material_revision")
        if (
            not material_id
            or isinstance(revision, bool)
            or not isinstance(revision, int)
            or revision < 1
        ):
            raise ValueError("Reading requires a server-resolved material and revision")
        viewport = payload.get("reading_viewport")
        if isinstance(viewport, dict):
            # The native protocol carries only a display selection string, not
            # a verified Mnemosyne TextAnchor. Do not let it become evidence.
            payload["reading_viewport"] = {**viewport, "selection": None}

    return TurnRequest.model_validate(payload)


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
    content_language = str(context.get("content_language") or "und").strip()
    if not _CONTENT_LANGUAGE_RE.fullmatch(content_language):
        raise ValueError("reader_context.content_language must be a valid language tag")
    response_language = str(
        request.get("response_language")
        or context.get("response_language")
        or "ko"
    ).strip().lower()
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
        document_id = _required_id(
            context.get("document_id"), "reader_context.document_id", uuid_value=True
        )
        version_id = str(context.get("version_id") or "")
        if not _VERSION_RE.fullmatch(version_id):
            raise ValueError("reader_context.version_id must be a full SHA-256 version")
        if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0:
            raise ValueError("reader_context.page_index must be a non-negative integer")
        if (
            not native_material_id
            or isinstance(native_revision, bool)
            or not isinstance(native_revision, int)
            or native_revision < 1
        ):
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
        # Preserve source language independently; the explicit reply override
        # continues to make Korean the response language for English material.
        language=content_language,
        reply_language_override=response_language,
        config={_CONTENT_LANGUAGE_CONFIG_KEY: content_language},
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
    assessment_service: Any | None = None

    @property
    def product_ready(self) -> bool:
        store_ready = self.learning_store is not None and all(
            callable(getattr(self.learning_store, name, None))
            for name in (
                "get_quiz",
                "get_state",
                "save_activity",
                "review_memory",
            )
        )
        assessment_service_ready = (
            self.assessment_service is not None
            and getattr(self.assessment_service, "ready", False) is True
            and callable(getattr(self.assessment_service, "submit_attempt", None))
        )
        annotation_sync = getattr(self.library, "annotation_sync", None)
        sync_ready = annotation_sync is not None and all(
            callable(getattr(annotation_sync, name, None))
            for name in ("apply_mutations", "snapshot", "changes")
        )
        return store_ready and assessment_service_ready and sync_ready

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
        return await self.turns.start_turn(
            native_protocol_turn_request(
                native.model_dump(),
                content_language=(native.config or {}).get(_CONTENT_LANGUAGE_CONFIG_KEY),
            )
        )

    async def start_native_turn(
        self, request: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        """Start from a validated DeepTutor protocol 2.0 command payload."""
        return await self.turns.start_turn(native_protocol_turn_request(request))

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

    async def get_quiz(self, quiz_id: str) -> dict[str, Any]:
        store = _learning_store(self.learning_store)
        getter = getattr(store, "get_quiz", None)
        if not callable(getter):
            raise RuntimeError("Learning state is not ready; quiz storage is unavailable")
        quiz = await getter(_required_id(quiz_id, "quiz_id", uuid_value=True))
        return _verify_quiz_citations(self.library, _validate_public_quiz(quiz))

    async def get_learning_state(self, document_id: str, version_id: str) -> dict[str, Any]:
        store = _learning_store(self.learning_store)
        normalized_document_id = _required_id(document_id, "document_id", uuid_value=True)
        normalized_version_id = str(version_id or "").strip()
        if not _VERSION_RE.fullmatch(normalized_version_id):
            raise ValueError("version_id must be a full SHA-256 version")
        state = await store.get_state(normalized_document_id, normalized_version_id)
        validated_state = _validate_learning_state(
            state, document_id=normalized_document_id, version_id=normalized_version_id
        )
        return _verify_learning_state_citations(self.library, validated_state)

    async def submit_attempt(self, attempt: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(attempt, dict):
            raise ValueError("attempt must be an object")
        fields = {
            "attempt_id",
            "client_mutation_id",
            "quiz_id",
            "document_id",
            "version_id",
            "base_learning_revision",
            "submitted_at",
            "answers",
        }
        missing = fields.difference(attempt)
        if missing:
            raise ValueError(f"attempt is missing required fields: {', '.join(sorted(missing))}")
        extra = set(attempt).difference(fields)
        if extra:
            raise ValueError(f"attempt has unsupported fields: {', '.join(sorted(extra))}")

        normalized = dict(attempt)
        for name in ("attempt_id", "client_mutation_id", "quiz_id", "document_id"):
            normalized[name] = _required_id(attempt.get(name), name, uuid_value=True)
        version_id = str(attempt.get("version_id") or "").strip()
        if not _VERSION_RE.fullmatch(version_id):
            raise ValueError("version_id must be a full SHA-256 version")
        normalized["version_id"] = version_id

        base_revision = attempt.get("base_learning_revision")
        if (
            isinstance(base_revision, bool)
            or not isinstance(base_revision, int)
            or base_revision < 0
            or base_revision > _MAX_SAFE_INTEGER
        ):
            raise ValueError("base_learning_revision must be a non-negative safe integer")
        normalized["submitted_at"] = _required_timestamp(
            attempt.get("submitted_at"), "submitted_at"
        )

        answers = attempt.get("answers")
        if not isinstance(answers, list) or not answers:
            raise ValueError("answers must contain at least one answer")
        normalized_answers: list[dict[str, str]] = []
        for answer in answers:
            if not isinstance(answer, dict) or set(answer) != {"question_id", "answer"}:
                raise ValueError("each answer must contain only question_id and answer")
            answer_text = answer.get("answer")
            if not isinstance(answer_text, str) or not answer_text.strip():
                raise ValueError("answer must not be empty")
            normalized_answers.append(
                {
                    "question_id": _required_id(
                        answer.get("question_id"), "question_id", uuid_value=True
                    ),
                    "answer": answer_text,
                }
            )
        normalized["answers"] = normalized_answers
        quiz = await self.get_quiz(normalized["quiz_id"])
        if (
            quiz["document_id"] != normalized["document_id"]
            or quiz["version_id"] != normalized["version_id"]
        ):
            raise ValueError("attempt does not match the immutable quiz document version")
        quiz_question_ids = {question["question_id"] for question in quiz["questions"]}
        answer_ids = [answer["question_id"] for answer in normalized_answers]
        if len(answer_ids) != len(set(answer_ids)):
            raise ValueError("attempt contains duplicate question answers")
        if any(question_id not in quiz_question_ids for question_id in answer_ids):
            raise ValueError("attempt contains a question outside the stored quiz")
        assessment_submitter = getattr(self.assessment_service, "submit_attempt", None)
        if not callable(assessment_submitter):
            raise RuntimeError("Learning state is not ready; private assessment service is unavailable")
        result = await assessment_submitter(normalized, quiz)
        validated_assessment = _validate_assessment(result, attempt=normalized, quiz=quiz)
        return _verify_assessment_citations(
            self.library,
            validated_assessment,
            document_id=quiz["document_id"],
            version_id=quiz["version_id"],
        )

    async def save_activity(
        self, activity: dict[str, Any], mutation_id: str, base_revision: int
    ) -> dict[str, Any]:
        if not isinstance(activity, dict):
            raise ValueError("activity must be an object")
        normalized_revision = _safe_integer(
            base_revision, "base_revision", minimum=0
        )
        normalized_activity = _validate_learning_activity(dict(activity))
        state = await _learning_store(self.learning_store).save_activity(
            normalized_activity,
            _required_id(mutation_id, "mutation_id", uuid_value=True),
            normalized_revision,
        )
        return _verify_learning_state_citations(
            self.library, _validate_learning_state(state)
        )

    async def review_memory(self, review: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(review, dict):
            raise ValueError("review must be an object")
        fields = {
            "client_mutation_id",
            "memory_id",
            "base_learning_revision",
            "grade",
            "reviewed_at",
        }
        missing = fields.difference(review)
        if missing:
            raise ValueError(f"review is missing required fields: {', '.join(sorted(missing))}")
        extra = set(review).difference(fields)
        if extra:
            raise ValueError(f"review has unsupported fields: {', '.join(sorted(extra))}")

        normalized = dict(review)
        for name in ("memory_id", "client_mutation_id"):
            normalized[name] = _required_id(review.get(name), name, uuid_value=True)
        base_revision = review.get("base_learning_revision")
        if (
            isinstance(base_revision, bool)
            or not isinstance(base_revision, int)
            or base_revision < 0
            or base_revision > _MAX_SAFE_INTEGER
        ):
            raise ValueError("base_learning_revision must be a non-negative safe integer")
        grade = review.get("grade")
        if isinstance(grade, bool) or not isinstance(grade, int) or not 0 <= grade <= 3:
            raise ValueError("grade must be an integer between 0 and 3")
        normalized["reviewed_at"] = _required_timestamp(review.get("reviewed_at"), "reviewed_at")
        state = await _learning_store(self.learning_store).review_memory(normalized)
        return _verify_learning_state_citations(
            self.library, _validate_learning_state(state)
        )


def register_tutor(
    turns,
    library,
    *,
    learning_store: LearningStateStore | None = None,
    assessment_service: Any | None = None,
) -> TutorAdapter:
    if assessment_service is None and learning_store is not None:
        from deeptutor.learning.service import MnemosyneAssessmentService

        assessment_service = MnemosyneAssessmentService(learning_store)
    return TutorAdapter(turns, library, learning_store, assessment_service)
