from __future__ import annotations

import pytest

from deeptutor.mnemosyne.learning_store import (
    LearningIdempotencyMismatch,
    LearningRevisionConflict,
    SQLiteMnemosyneLearningStore,
)
from deeptutor.mnemosyne.quiz_generation import MnemosyneQuizGenerationService

DOCUMENT_ID = "00000000-0000-0000-0000-000000000001"
VERSION_ID = "sha256:" + "1" * 64
QUIZ_ID = "00000000-0000-0000-0000-000000000002"
QUESTION_ID = "00000000-0000-0000-0000-000000000003"
ATTEMPT_ID = "00000000-0000-0000-0000-000000000004"
MUTATION_ID = "00000000-0000-0000-0000-000000000005"
MEMORY_ID = "00000000-0000-0000-0000-000000000006"
QUIZ_MUTATION_ID = "00000000-0000-4000-8000-000000000016"
QUIZ_REQUEST_SHA256 = "a" * 64


def _quiz():
    citation = {
        "citation_id": "00000000-0000-0000-0000-000000000007",
        "verification_id": "00000000-0000-0000-0000-000000000008",
        "verified": True,
        "anchor": {"document_id": DOCUMENT_ID, "version_id": VERSION_ID},
    }
    public = {
        "quiz_id": QUIZ_ID,
        "document_id": DOCUMENT_ID,
        "version_id": VERSION_ID,
        "title": "문서 근거 퀴즈",
        "questions": [
            {
                "question_id": QUESTION_ID,
                "prompt": "전압이 두 배가 되면 에너지는 어떻게 되는가?",
                "kind": "single_choice",
                "choices": [
                    {"choice_id": "a", "text": "두 배"},
                    {"choice_id": "b", "text": "네 배"},
                    {"choice_id": "c", "text": "절반"},
                    {"choice_id": "d", "text": "변하지 않음"},
                ],
                "citations": [citation],
            }
        ],
        "response_language": "ko",
    }
    private = {
        "quiz_id": QUIZ_ID,
        "document_id": DOCUMENT_ID,
        "version_id": VERSION_ID,
        "questions": [
            {
                "question_id": QUESTION_ID,
                "answer_key": "b",
                "rubric": "전압 제곱에 비례함을 설명한다.",
                "explanation": "에너지는 전압의 제곱에 비례한다.",
                "concept_id": "capacitor-energy",
                "label_ko": "커패시터 에너지",
            }
        ],
    }
    return public, private, citation


def _attempt():
    return {
        "attempt_id": ATTEMPT_ID,
        "client_mutation_id": MUTATION_ID,
        "quiz_id": QUIZ_ID,
        "document_id": DOCUMENT_ID,
        "version_id": VERSION_ID,
        "base_learning_revision": 1,
        "submitted_at": "2026-10-12T12:00:00Z",
        "answers": [{"question_id": QUESTION_ID, "answer": "a"}],
    }


@pytest.mark.asyncio
async def test_learning_state_assessment_and_memory_review_survive_reopen(tmp_path):
    db_path = tmp_path / "learning.sqlite3"
    store = SQLiteMnemosyneLearningStore(db_path)
    public, private, citation = _quiz()
    await store.create_quiz(public, private, QUIZ_MUTATION_ID, QUIZ_REQUEST_SHA256)

    assert await store.get_quiz(QUIZ_ID) == public
    assert await store.get_grading_input(QUIZ_ID, DOCUMENT_ID, VERSION_ID) == private
    assert "answer_key" not in str(await store.get_quiz(QUIZ_ID))
    state = await store.get_state(DOCUMENT_ID, VERSION_ID)
    assert state["learning_revision"] == 1
    assert state["quiz_attempts"] == []
    assert state["progress"]["pages_read"] == []

    attempt = _attempt()
    payload_hash = "a" * 64
    assert await store.begin_attempt(attempt, payload_hash) == {"status": "claimed"}
    assert await store.begin_attempt(attempt, payload_hash) == {"status": "in_progress"}
    assessment = {
        "attempt_id": ATTEMPT_ID,
        "score": 0.25,
        "feedback_ko": "전압의 제곱 관계를 다시 확인하세요.",
        "learning_revision": 2,
        "citations": [citation],
    }
    evidence = [
        {
            "question_id": QUESTION_ID,
            "score": 0.25,
            "feedback_ko": "전압의 제곱 관계를 다시 확인하세요.",
            "concept_id": "capacitor-energy",
            "label_ko": "커패시터 에너지",
            "memory": {
                "memory_id": MEMORY_ID,
                "front_ko": "전압 두 배일 때 에너지 변화는?",
                "back_ko": "네 배입니다.",
                "due_at": "2026-10-13T12:00:00Z",
                "review_count": 0,
                "citations": [citation],
            },
        }
    ]
    assert (
        await store.commit_assessment(attempt, payload_hash, assessment, question_results=evidence)
        == assessment
    )
    replay = await store.begin_attempt(attempt, payload_hash)
    assert replay == {"status": "completed_replay", "assessment": assessment}

    state = await store.get_state(DOCUMENT_ID, VERSION_ID)
    assert state["learning_revision"] == assessment["learning_revision"]
    assert state["quiz_attempts"] == [{"attempt_id": ATTEMPT_ID, "quiz_id": QUIZ_ID, "score": 0.25}]
    assert state["mastery"][0]["evidence_attempt_ids"] == [ATTEMPT_ID]
    assert state["memory"][0]["memory_id"] == MEMORY_ID

    review = {
        "client_mutation_id": "00000000-0000-0000-0000-000000000009",
        "memory_id": MEMORY_ID,
        "base_learning_revision": 2,
        "grade": 2,
        "reviewed_at": "2026-10-12T12:01:00Z",
    }
    reviewed = await store.review_memory(review)
    assert reviewed["learning_revision"] == 3
    assert reviewed["memory"][0]["review_count"] == 1
    assert await store.review_memory(review) == reviewed

    reopened = SQLiteMnemosyneLearningStore(db_path)
    assert await reopened.get_state(DOCUMENT_ID, VERSION_ID) == reviewed
    assert await reopened.get_quiz(QUIZ_ID) == public


def test_sqlite_quiz_create_replays_duplicate_and_rejects_changed_request(tmp_path):
    store = SQLiteMnemosyneLearningStore(tmp_path / "learning.sqlite3")
    public, private, _ = _quiz()

    assert store._create_quiz(public, private, QUIZ_MUTATION_ID, QUIZ_REQUEST_SHA256) == public
    # A response lost after commit must replay the existing durable quiz.
    assert store._create_quiz(public, private, QUIZ_MUTATION_ID, QUIZ_REQUEST_SHA256) == public
    with pytest.raises(LearningIdempotencyMismatch):
        store._create_quiz(public, private, QUIZ_MUTATION_ID, "b" * 64)


@pytest.mark.asyncio
async def test_activity_mutation_is_idempotent_and_revision_checked(tmp_path):
    store = SQLiteMnemosyneLearningStore(tmp_path / "learning.sqlite3")
    activity = {
        "activity_id": "00000000-0000-0000-0000-000000000010",
        "kind": "reading",
        "turn_id": "turn_1",
        "summary_ko": "커패시터 에너지 설명 확인",
        "created_at": "2026-10-12T12:00:00Z",
    }
    mutation = "00000000-0000-0000-0000-000000000011"
    saved = await store.save_activity(
        activity,
        mutation,
        1,
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
    )
    assert saved["learning_revision"] == 2
    assert (
        await store.save_activity(
            activity,
            mutation,
            1,
            document_id=DOCUMENT_ID,
            version_id=VERSION_ID,
        )
        == saved
    )
    altered = {**activity, "summary_ko": "다른 활동"}
    try:
        await store.save_activity(
            altered,
            mutation,
            1,
            document_id=DOCUMENT_ID,
            version_id=VERSION_ID,
        )
    except LearningIdempotencyMismatch:
        pass
    else:
        raise AssertionError("same mutation ID with another payload was accepted")
    try:
        await store.save_activity(
            {**activity, "activity_id": "00000000-0000-0000-0000-000000000012"},
            "00000000-0000-0000-0000-000000000013",
            1,
            document_id=DOCUMENT_ID,
            version_id=VERSION_ID,
        )
    except LearningRevisionConflict:
        pass
    else:
        raise AssertionError("stale learning revision was accepted")


@pytest.mark.asyncio
async def test_progress_mutation_is_durable_and_deduplicates_retries(tmp_path):
    db_path = tmp_path / "learning.sqlite3"
    store = SQLiteMnemosyneLearningStore(db_path)
    mutation_id = "00000000-0000-4000-8000-000000000014"
    first = await store.record_progress(
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        mutation_id=mutation_id,
        base_revision=1,
        page_index=1,
        reading_seconds=15,
    )
    assert first["learning_revision"] == 2
    assert first["progress"] == {
        "last_page_index": 1,
        "pages_read": [1],
        "reading_seconds": 15,
        "next_review_at": first["progress"]["next_review_at"],
    }
    # A client can refresh its learning revision after losing the response and
    # replay the same immutable mutation without adding the seconds twice.
    replay = await store.record_progress(
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        mutation_id=mutation_id,
        base_revision=first["learning_revision"],
        page_index=1,
        reading_seconds=15,
    )
    assert replay == first
    reopened = SQLiteMnemosyneLearningStore(db_path)
    assert await reopened.get_state(DOCUMENT_ID, VERSION_ID) == first
    try:
        await reopened.record_progress(
            document_id=DOCUMENT_ID,
            version_id=VERSION_ID,
            mutation_id=mutation_id,
            base_revision=first["learning_revision"],
            page_index=0,
            reading_seconds=15,
        )
    except LearningIdempotencyMismatch:
        pass
    else:
        raise AssertionError("same progress mutation ID with another page was accepted")


class _QuizLibrary:
    def __init__(self, page):
        self.page = page
        self.verified = []

    def get_document(self, document_id, version_id):
        return {"document_id": document_id, "version_id": version_id, "parse_state": "ready"}

    def get_page(self, document_id, version_id, page_index):
        assert document_id == DOCUMENT_ID and version_id == VERSION_ID and page_index == 0
        return self.page

    def verify_citation(self, anchor):
        self.verified.append(anchor)
        return {
            "citation_id": "00000000-0000-0000-0000-000000000014",
            "verification_id": "00000000-0000-0000-0000-000000000015",
            "verified": True,
            "anchor": anchor,
        }


class _QuizStore:
    def __init__(self):
        self.public = None
        self.private = None
        self.requests = {}

    async def get_quiz_for_mutation(self, mutation_id, request_sha256):
        prior = self.requests.get(mutation_id)
        if prior is None:
            return None
        prior_sha, public = prior
        if prior_sha != request_sha256:
            raise LearningIdempotencyMismatch()
        return public

    async def create_quiz(self, public, private, mutation_id, request_sha256):
        prior = self.requests.get(mutation_id)
        if prior is not None:
            prior_sha, prior_public = prior
            if prior_sha != request_sha256:
                raise LearningIdempotencyMismatch()
            return prior_public
        self.public, self.private = public, private
        self.requests[mutation_id] = (request_sha256, public)
        return public


@pytest.mark.asyncio
async def test_quiz_generation_reverifies_source_and_keeps_answer_private():
    source = "커패시터는 에너지를 저장한다. E = 1/2 C V^2."
    page = {
        "page_index": 0,
        "parse_revision": "pymupdf-1.28.2-nfc-1",
        "text_sha256": "2" * 64,
        "text": source,
        "segments": [{"start_scalar": 0, "end_scalar": len(source), "rect": [40, 100, 260, 20]}],
    }
    library, store = _QuizLibrary(page), _QuizStore()
    output = {
        "title_ko": "커패시터 에너지 확인",
        "questions": [
            {
                "prompt_ko": "전압이 두 배가 되면 에너지는 몇 배인가요?",
                "choices": ["두 배", "네 배", "절반", "같음"],
                "answer_index": 1,
                "rubric": "에너지가 전압 제곱에 비례함을 설명한다.",
                "explanation": "식에서 에너지는 V의 제곱에 비례한다.",
                "concept_id": "capacitor-energy",
                "label_ko": "커패시터 에너지",
                "source_quote": "커패시터는 에너지를 저장한다.",
            }
        ],
    }
    service = MnemosyneQuizGenerationService(library, store, evaluator=lambda _payload: output)
    quiz = await service.create_quiz(
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        page_index=0,
        prompt="전압 의존성을 확인하는 문제",
        client_mutation_id=QUIZ_MUTATION_ID,
    )
    assert quiz["questions"][0]["citations"][0]["verified"] is True
    assert (
        quiz["questions"][0]["citations"][0]["anchor"]["quote"] == "커패시터는 에너지를 저장한다."
    )
    assert "answer_key" not in str(quiz)
    assert (
        store.private["questions"][0]["answer_key"]
        == quiz["questions"][0]["choices"][1]["choice_id"]
    )
    assert library.verified[0]["start_scalar"] == 0
    replay = await service.create_quiz(
        document_id=DOCUMENT_ID,
        version_id=VERSION_ID,
        page_index=0,
        prompt="전압 의존성을 확인하는 문제",
        client_mutation_id=QUIZ_MUTATION_ID,
    )
    assert replay == quiz
    assert len(library.verified) == 1


@pytest.mark.asyncio
async def test_quiz_generation_rejects_quote_that_is_not_unique_in_pdf():
    source = "같은 문장. 다른 문장. 같은 문장."
    page = {
        "page_index": 0,
        "parse_revision": "pymupdf-1.28.2-nfc-1",
        "text_sha256": "3" * 64,
        "text": source,
        "segments": [{"start_scalar": 0, "end_scalar": len(source), "rect": [0, 0, 10, 10]}],
    }
    library, store = _QuizLibrary(page), _QuizStore()
    output = {
        "title_ko": "확인 문제",
        "questions": [
            {
                "prompt_ko": "문제",
                "choices": ["A", "B", "C", "D"],
                "answer_index": 0,
                "rubric": "근거 설명",
                "explanation": "근거 해설",
                "concept_id": "source-check",
                "label_ko": "근거 확인",
                "source_quote": "같은 문장.",
            }
        ],
    }
    service = MnemosyneQuizGenerationService(library, store, evaluator=lambda _payload: output)
    try:
        await service.create_quiz(
            document_id=DOCUMENT_ID,
            version_id=VERSION_ID,
            page_index=0,
            prompt="문제를 만들어 주세요",
            client_mutation_id="00000000-0000-4000-8000-000000000017",
        )
    except Exception as exc:
        from deeptutor.mnemosyne.quiz_generation import MnemosyneQuizGenerationError

        assert isinstance(exc, MnemosyneQuizGenerationError)
        assert exc.code == "provider_invalid_response"
    else:
        raise AssertionError("ambiguous source quote was accepted")
    assert store.public is None
