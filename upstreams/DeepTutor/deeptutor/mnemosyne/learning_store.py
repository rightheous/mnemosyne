"""Durable SQLite storage for Mnemosyne quizzes and learning state.

The store is scoped to the paired personal workspace and shares its data root
with the Library, while keeping grading keys and learner answers out of the
public Library database and API DTOs.
"""

from __future__ import annotations

import asyncio
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3
import stat
from typing import Any, Iterator
from uuid import UUID

_VERSION_RE = re.compile(r"^sha256:[a-f0-9]{64}$")
_DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_LEASE_SECONDS = 300
_MAX_REVIEW_INTERVAL_SECONDS = 180 * 24 * 60 * 60


class LearningStoreError(RuntimeError):
    """A safe persistence error that can be mapped to a contract response."""

    def __init__(self, message: str, *, code: str = "learning_store_error") -> None:
        super().__init__(message)
        self.code = code


class LearningRevisionConflict(LearningStoreError):
    def __init__(self) -> None:
        super().__init__("learning revision changed", code="learning_revision_conflict")


class LearningIdempotencyMismatch(LearningStoreError):
    def __init__(self) -> None:
        super().__init__(
            "mutation ID was already used with another payload", code="idempotency_mismatch"
        )


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _timestamp(value: datetime | None = None) -> str:
    current = (value or _now()).astimezone(timezone.utc)
    return current.isoformat(timespec="seconds").replace("+00:00", "Z")


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def _uuid(value: Any, field: str) -> str:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise ValueError(f"{field} must be a UUID") from exc


def _scope(document_id: Any, version_id: Any) -> tuple[str, str]:
    document = _uuid(document_id, "document_id")
    version = str(version_id or "")
    if not _VERSION_RE.fullmatch(version):
        raise ValueError("version_id must be a full SHA-256 version")
    return document, version


def _safe_revision(value: Any) -> int:
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 0
        or value > _MAX_SAFE_INTEGER
    ):
        raise ValueError("learning revision must be a non-negative safe integer")
    return value


def _initial_state(document_id: str, version_id: str) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "version_id": version_id,
        "learning_revision": 1,
        "quiz_attempts": [],
        "mastery": [],
        "memory": [],
        "progress": {
            "last_page_index": 0,
            "pages_read": [],
            "reading_seconds": 0,
            "next_review_at": _timestamp(),
        },
        "activities": [],
    }


class SQLiteMnemosyneLearningStore:
    """SQLite implementation of the private quiz and learning-state ports."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self.db_path.parent.chmod(0o700)
        self._migrate()

    def _secure_db_permissions(self) -> None:
        for path in (
            self.db_path,
            Path(f"{self.db_path}-wal"),
            Path(f"{self.db_path}-shm"),
        ):
            try:
                info = path.lstat()
            except FileNotFoundError:
                continue
            if not stat.S_ISREG(info.st_mode):
                raise LearningStoreError("learning database files must be regular files")
            os.chmod(path, 0o600, follow_symlinks=False)

    @contextmanager
    def _connect(self, *, write: bool = False) -> Iterator[sqlite3.Connection]:
        self._secure_db_permissions()
        conn = sqlite3.connect(self.db_path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        if write:
            conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            if write:
                conn.commit()
        except BaseException:
            if write:
                conn.rollback()
            raise
        finally:
            conn.close()
            self._secure_db_permissions()

    def _migrate(self) -> None:
        with sqlite3.connect(self.db_path, timeout=30, isolation_level=None) as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=30000")
            conn.execute("BEGIN IMMEDIATE")
            try:
                version = int(conn.execute("PRAGMA user_version").fetchone()[0])
                if version > 2:
                    raise LearningStoreError("learning database schema is newer than this server")
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS mnemosyne_learning_quizzes (
                        quiz_id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL,
                        version_id TEXT NOT NULL,
                        public_quiz_json TEXT NOT NULL,
                        private_grading_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        client_mutation_id TEXT,
                        request_sha256 TEXT
                    )"""
                )
                quiz_columns = {
                    str(row[1])
                    for row in conn.execute("PRAGMA table_info(mnemosyne_learning_quizzes)")
                }
                if "client_mutation_id" not in quiz_columns:
                    conn.execute(
                        "ALTER TABLE mnemosyne_learning_quizzes ADD COLUMN client_mutation_id TEXT"
                    )
                if "request_sha256" not in quiz_columns:
                    conn.execute(
                        "ALTER TABLE mnemosyne_learning_quizzes ADD COLUMN request_sha256 TEXT"
                    )
                conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_mnemosyne_quiz_mutation "
                    "ON mnemosyne_learning_quizzes(client_mutation_id)"
                )
                conn.execute(
                    """CREATE INDEX IF NOT EXISTS idx_mnemosyne_quiz_scope
                        ON mnemosyne_learning_quizzes(document_id, version_id)"""
                )
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS mnemosyne_learning_state (
                        document_id TEXT NOT NULL,
                        version_id TEXT NOT NULL,
                        learning_revision INTEGER NOT NULL CHECK (learning_revision >= 1),
                        state_json TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        PRIMARY KEY(document_id, version_id)
                    )"""
                )
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS mnemosyne_learning_attempts (
                        attempt_id TEXT PRIMARY KEY,
                        client_mutation_id TEXT NOT NULL UNIQUE,
                        payload_sha256 TEXT NOT NULL,
                        quiz_id TEXT NOT NULL REFERENCES mnemosyne_learning_quizzes(quiz_id),
                        document_id TEXT NOT NULL,
                        version_id TEXT NOT NULL,
                        base_learning_revision INTEGER NOT NULL CHECK (base_learning_revision >= 0),
                        status TEXT NOT NULL CHECK (status IN ('in_progress','retryable','completed')),
                        request_json TEXT NOT NULL,
                        assessment_json TEXT,
                        safe_error_code TEXT,
                        lease_expires_at REAL NOT NULL,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        CHECK ((status = 'completed') = (assessment_json IS NOT NULL))
                    )"""
                )
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS mnemosyne_question_evidence (
                        attempt_id TEXT NOT NULL REFERENCES mnemosyne_learning_attempts(attempt_id),
                        question_id TEXT NOT NULL,
                        concept_id TEXT NOT NULL,
                        label_ko TEXT NOT NULL,
                        score REAL NOT NULL CHECK (score >= 0 AND score <= 1),
                        feedback_ko TEXT NOT NULL,
                        memory_json TEXT,
                        PRIMARY KEY(attempt_id, question_id)
                    )"""
                )
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS mnemosyne_learning_mutations (
                        client_mutation_id TEXT PRIMARY KEY,
                        payload_sha256 TEXT NOT NULL,
                        document_id TEXT NOT NULL,
                        version_id TEXT NOT NULL,
                        result_revision INTEGER NOT NULL,
                        created_at TEXT NOT NULL
                    )"""
                )
                conn.execute(
                    """CREATE TABLE IF NOT EXISTS mnemosyne_learning_memory_index (
                        memory_id TEXT PRIMARY KEY,
                        document_id TEXT NOT NULL,
                        version_id TEXT NOT NULL
                    )"""
                )
                conn.execute("PRAGMA user_version=2")
                conn.commit()
            except BaseException:
                conn.rollback()
                raise
        self._secure_db_permissions()

    @staticmethod
    def _load_state(conn: sqlite3.Connection, document_id: str, version_id: str) -> dict[str, Any]:
        row = conn.execute(
            "SELECT state_json FROM mnemosyne_learning_state WHERE document_id=? AND version_id=?",
            (document_id, version_id),
        ).fetchone()
        if row is None:
            state = _initial_state(document_id, version_id)
            conn.execute(
                "INSERT INTO mnemosyne_learning_state VALUES (?, ?, ?, ?, ?)",
                (document_id, version_id, 1, _json(state), _timestamp()),
            )
            return state
        return json.loads(row["state_json"])

    @staticmethod
    def _save_state(conn: sqlite3.Connection, state: dict[str, Any]) -> None:
        document_id, version_id = _scope(state.get("document_id"), state.get("version_id"))
        revision = state.get("learning_revision")
        if (
            isinstance(revision, bool)
            or not isinstance(revision, int)
            or not 1 <= revision <= _MAX_SAFE_INTEGER
        ):
            raise ValueError("learning_revision must be a positive safe integer")
        conn.execute(
            """INSERT INTO mnemosyne_learning_state
                (document_id, version_id, learning_revision, state_json, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(document_id, version_id) DO UPDATE SET
                    learning_revision=excluded.learning_revision,
                    state_json=excluded.state_json,
                    updated_at=excluded.updated_at""",
            (document_id, version_id, revision, _json(state), _timestamp()),
        )

    @staticmethod
    def _remember_mutation(
        conn: sqlite3.Connection,
        mutation_id: str,
        payload_sha256: str,
        document_id: str,
        version_id: str,
        revision: int,
    ) -> None:
        conn.execute(
            "INSERT INTO mnemosyne_learning_mutations VALUES (?, ?, ?, ?, ?, ?)",
            (mutation_id, payload_sha256, document_id, version_id, revision, _timestamp()),
        )

    async def create_quiz(
        self,
        public_quiz: dict[str, Any],
        private_grading: dict[str, Any],
        client_mutation_id: str,
        request_sha256: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._create_quiz,
            public_quiz,
            private_grading,
            client_mutation_id,
            request_sha256,
        )

    def _create_quiz(
        self,
        public_quiz: dict[str, Any],
        private_grading: dict[str, Any],
        client_mutation_id: str,
        request_sha256: str,
    ) -> dict[str, Any]:
        if not isinstance(public_quiz, dict) or not isinstance(private_grading, dict):
            raise ValueError("quiz payloads must be objects")
        client_mutation_id = _uuid(client_mutation_id, "client_mutation_id")
        if not isinstance(request_sha256, str) or not _DIGEST_RE.fullmatch(request_sha256):
            raise ValueError("request_sha256 must be a SHA-256 digest")
        quiz_id = _uuid(public_quiz.get("quiz_id"), "quiz_id")
        document_id, version_id = _scope(
            public_quiz.get("document_id"), public_quiz.get("version_id")
        )
        if (
            private_grading.get("quiz_id") != quiz_id
            or private_grading.get("document_id") != document_id
            or private_grading.get("version_id") != version_id
        ):
            raise ValueError("private grading input does not match the public quiz")
        public_questions = public_quiz.get("questions")
        private_questions = private_grading.get("questions")
        if (
            not isinstance(public_questions, list)
            or not isinstance(private_questions, list)
            or not public_questions
        ):
            raise ValueError("quiz questions are required")
        public_ids = [_uuid(item.get("question_id"), "question_id") for item in public_questions]
        private_ids = [_uuid(item.get("question_id"), "question_id") for item in private_questions]
        if len(set(public_ids)) != len(public_ids) or set(public_ids) != set(private_ids):
            raise ValueError("private grading questions do not match the public quiz")
        if any(
            not isinstance(item.get("answer_key"), str) or not item["answer_key"].strip()
            for item in private_questions
        ):
            raise ValueError("private answer keys are required")
        now = _timestamp()
        with self._connect(write=True) as conn:
            try:
                conn.execute(
                    """INSERT INTO mnemosyne_learning_quizzes
                        (quiz_id, document_id, version_id, public_quiz_json,
                         private_grading_json, created_at, client_mutation_id, request_sha256)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        quiz_id,
                        document_id,
                        version_id,
                        _json(public_quiz),
                        _json(private_grading),
                        now,
                        client_mutation_id,
                        request_sha256,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                row = conn.execute(
                    "SELECT document_id, version_id, public_quiz_json, request_sha256 "
                    "FROM mnemosyne_learning_quizzes WHERE quiz_id=? OR client_mutation_id=?",
                    (quiz_id, client_mutation_id),
                ).fetchone()
                if (
                    row
                    and row["document_id"] == document_id
                    and row["version_id"] == version_id
                    and row["request_sha256"] == request_sha256
                ):
                    return json.loads(row["public_quiz_json"])
                raise LearningIdempotencyMismatch() from exc
        return public_quiz

    async def get_quiz_for_mutation(
        self, client_mutation_id: str, request_sha256: str
    ) -> dict[str, Any] | None:
        return await asyncio.to_thread(
            self._get_quiz_for_mutation, client_mutation_id, request_sha256
        )

    def _get_quiz_for_mutation(
        self, client_mutation_id: str, request_sha256: str
    ) -> dict[str, Any] | None:
        mutation_id = _uuid(client_mutation_id, "client_mutation_id")
        if not isinstance(request_sha256, str) or not _DIGEST_RE.fullmatch(request_sha256):
            raise ValueError("request_sha256 must be a SHA-256 digest")
        with self._connect() as conn:
            row = conn.execute(
                "SELECT public_quiz_json, request_sha256 FROM mnemosyne_learning_quizzes "
                "WHERE client_mutation_id=?",
                (mutation_id,),
            ).fetchone()
        if row is None:
            return None
        if row["request_sha256"] != request_sha256:
            raise LearningIdempotencyMismatch()
        return json.loads(row["public_quiz_json"])

    async def get_quiz(self, quiz_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_quiz, quiz_id)

    def _get_quiz(self, quiz_id: str) -> dict[str, Any]:
        with self._connect() as conn:
            row = conn.execute(
                "SELECT public_quiz_json FROM mnemosyne_learning_quizzes WHERE quiz_id=?",
                (_uuid(quiz_id, "quiz_id"),),
            ).fetchone()
        if row is None:
            raise LookupError("quiz not found")
        return json.loads(row["public_quiz_json"])

    async def get_grading_input(
        self, quiz_id: str, document_id: str, version_id: str
    ) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_grading_input, quiz_id, document_id, version_id)

    def _get_grading_input(self, quiz_id: str, document_id: str, version_id: str) -> dict[str, Any]:
        scope = _scope(document_id, version_id)
        with self._connect() as conn:
            row = conn.execute(
                """SELECT private_grading_json FROM mnemosyne_learning_quizzes
                    WHERE quiz_id=? AND document_id=? AND version_id=?""",
                (_uuid(quiz_id, "quiz_id"), *scope),
            ).fetchone()
        if row is None:
            raise LookupError("quiz grading input not found")
        return json.loads(row["private_grading_json"])

    async def get_state(self, document_id: str, version_id: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._get_state, document_id, version_id)

    def _get_state(self, document_id: str, version_id: str) -> dict[str, Any]:
        scope = _scope(document_id, version_id)
        with self._connect(write=True) as conn:
            return self._load_state(conn, *scope)

    async def begin_attempt(self, attempt: dict[str, Any], payload_sha256: str) -> dict[str, Any]:
        return await asyncio.to_thread(self._begin_attempt, attempt, payload_sha256)

    def _begin_attempt(self, attempt: dict[str, Any], payload_sha256: str) -> dict[str, Any]:
        attempt_id = _uuid(attempt.get("attempt_id"), "attempt_id")
        mutation_id = _uuid(attempt.get("client_mutation_id"), "client_mutation_id")
        quiz_id = _uuid(attempt.get("quiz_id"), "quiz_id")
        document_id, version_id = _scope(attempt.get("document_id"), attempt.get("version_id"))
        base_revision = _safe_revision(attempt.get("base_learning_revision"))
        now = _now()
        with self._connect(write=True) as conn:
            row = conn.execute(
                "SELECT * FROM mnemosyne_learning_attempts WHERE client_mutation_id=? OR attempt_id=?",
                (mutation_id, attempt_id),
            ).fetchone()
            if row is not None:
                if (
                    row["client_mutation_id"] != mutation_id
                    or row["payload_sha256"] != payload_sha256
                ):
                    return {"status": "payload_conflict"}
                if row["status"] == "completed":
                    return {
                        "status": "completed_replay",
                        "assessment": json.loads(row["assessment_json"]),
                    }
                if (
                    row["status"] == "in_progress"
                    and float(row["lease_expires_at"]) > now.timestamp()
                ):
                    return {"status": "in_progress"}
                state = self._load_state(conn, document_id, version_id)
                if state["learning_revision"] != base_revision:
                    return {"status": "revision_conflict"}
                conn.execute(
                    "UPDATE mnemosyne_learning_attempts SET status='in_progress', safe_error_code=NULL, lease_expires_at=?, updated_at=? WHERE attempt_id=?",
                    (now.timestamp() + _LEASE_SECONDS, _timestamp(now), attempt_id),
                )
                return {"status": "claimed"}

            quiz = conn.execute(
                "SELECT document_id, version_id FROM mnemosyne_learning_quizzes WHERE quiz_id=?",
                (quiz_id,),
            ).fetchone()
            if (
                quiz is None
                or quiz["document_id"] != document_id
                or quiz["version_id"] != version_id
            ):
                raise LookupError("quiz not found for this document version")
            state = self._load_state(conn, document_id, version_id)
            if state["learning_revision"] != base_revision:
                return {"status": "revision_conflict"}
            conn.execute(
                """INSERT INTO mnemosyne_learning_attempts
                    (attempt_id, client_mutation_id, payload_sha256, quiz_id, document_id,
                     version_id, base_learning_revision, status, request_json, assessment_json,
                     safe_error_code, lease_expires_at, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, 'in_progress', ?, NULL, NULL, ?, ?, ?)""",
                (
                    attempt_id,
                    mutation_id,
                    payload_sha256,
                    quiz_id,
                    document_id,
                    version_id,
                    base_revision,
                    _json(attempt),
                    now.timestamp() + _LEASE_SECONDS,
                    _timestamp(now),
                    _timestamp(now),
                ),
            )
            return {"status": "claimed"}

    async def release_attempt_for_retry(
        self, attempt_id: str, payload_sha256: str, safe_error_code: str
    ) -> None:
        await asyncio.to_thread(
            self._release_attempt_for_retry, attempt_id, payload_sha256, safe_error_code
        )

    def _release_attempt_for_retry(
        self, attempt_id: str, payload_sha256: str, safe_error_code: str
    ) -> None:
        with self._connect(write=True) as conn:
            conn.execute(
                """UPDATE mnemosyne_learning_attempts
                    SET status='retryable', safe_error_code=?, lease_expires_at=0, updated_at=?
                    WHERE attempt_id=? AND payload_sha256=? AND status='in_progress'""",
                (
                    str(safe_error_code)[:80],
                    _timestamp(),
                    _uuid(attempt_id, "attempt_id"),
                    payload_sha256,
                ),
            )

    async def commit_assessment(
        self,
        attempt: dict[str, Any],
        payload_sha256: str,
        assessment: dict[str, Any],
        *,
        question_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._commit_assessment, attempt, payload_sha256, assessment, question_results
        )

    def _commit_assessment(
        self,
        attempt: dict[str, Any],
        payload_sha256: str,
        assessment: dict[str, Any],
        question_results: list[dict[str, Any]],
    ) -> dict[str, Any]:
        attempt_id = _uuid(attempt.get("attempt_id"), "attempt_id")
        document_id, version_id = _scope(attempt.get("document_id"), attempt.get("version_id"))
        base_revision = _safe_revision(attempt.get("base_learning_revision"))
        next_revision = base_revision + 1
        if (
            next_revision > _MAX_SAFE_INTEGER
            or assessment.get("learning_revision") != next_revision
        ):
            raise ValueError("assessment revision does not match the current learning revision")
        now = _timestamp()
        with self._connect(write=True) as conn:
            claim = conn.execute(
                "SELECT * FROM mnemosyne_learning_attempts WHERE attempt_id=?",
                (attempt_id,),
            ).fetchone()
            if claim is None or claim["payload_sha256"] != payload_sha256:
                raise LearningStoreError(
                    "assessment claim is missing or changed", code="assessment_store_invalid"
                )
            if claim["status"] == "completed":
                return json.loads(claim["assessment_json"])
            if claim["status"] != "in_progress":
                raise LearningStoreError(
                    "assessment claim is not active", code="assessment_store_invalid"
                )
            state = self._load_state(conn, document_id, version_id)
            if state["learning_revision"] != base_revision:
                raise LearningRevisionConflict()
            if claim["document_id"] != document_id or claim["version_id"] != version_id:
                raise LearningStoreError(
                    "assessment claim scope changed", code="assessment_store_invalid"
                )

            quiz_attempt = {
                "attempt_id": attempt_id,
                "quiz_id": _uuid(attempt.get("quiz_id"), "quiz_id"),
                "score": assessment["score"],
            }
            state["quiz_attempts"].append(quiz_attempt)
            mastery_by_id = {item["concept_id"]: item for item in state["mastery"]}
            grouped: dict[str, list[dict[str, Any]]] = {}
            for item in question_results:
                grouped.setdefault(item["concept_id"], []).append(item)
                memory = item.get("memory")
                if memory is not None:
                    memory_id = _uuid(memory.get("memory_id"), "memory_id")
                    if any(existing["memory_id"] == memory_id for existing in state["memory"]):
                        raise LearningStoreError(
                            "memory ID already exists", code="idempotency_mismatch"
                        )
                    state["memory"].append(memory)
                    conn.execute(
                        "INSERT INTO mnemosyne_learning_memory_index VALUES (?, ?, ?)",
                        (memory_id, document_id, version_id),
                    )
                conn.execute(
                    "INSERT INTO mnemosyne_question_evidence VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        attempt_id,
                        item["question_id"],
                        item["concept_id"],
                        item["label_ko"],
                        item["score"],
                        item["feedback_ko"],
                        _json(memory) if memory is not None else None,
                    ),
                )
            for concept_id, evidence in grouped.items():
                new_score = sum(float(item["score"]) for item in evidence) / len(evidence)
                current = mastery_by_id.get(concept_id)
                if current is None:
                    current = {
                        "concept_id": concept_id,
                        "label_ko": evidence[0]["label_ko"],
                        "score": new_score,
                        "evidence_attempt_ids": [attempt_id],
                    }
                    state["mastery"].append(current)
                    mastery_by_id[concept_id] = current
                else:
                    if current["label_ko"] != evidence[0]["label_ko"]:
                        current["label_ko"] = evidence[0]["label_ko"]
                    prior_count = len(current["evidence_attempt_ids"])
                    current["score"] = (float(current["score"]) * prior_count + new_score) / (
                        prior_count + 1
                    )
                    if attempt_id not in current["evidence_attempt_ids"]:
                        current["evidence_attempt_ids"].append(attempt_id)
            submitted_at = attempt["submitted_at"]
            state["activities"].append(
                {
                    "activity_id": attempt_id,
                    "kind": "quiz",
                    "turn_id": None,
                    "summary_ko": f"퀴즈 응시: {round(float(assessment['score']) * 100)}%",
                    "created_at": submitted_at,
                }
            )
            state["learning_revision"] = next_revision
            memory_due = sorted(item["due_at"] for item in state["memory"])
            if memory_due:
                state["progress"]["next_review_at"] = memory_due[0]
            self._save_state(conn, state)
            conn.execute(
                "UPDATE mnemosyne_learning_attempts SET status='completed', assessment_json=?, safe_error_code=NULL, lease_expires_at=0, updated_at=? WHERE attempt_id=?",
                (_json(assessment), now, attempt_id),
            )
        return assessment

    async def save_activity(
        self,
        activity: dict[str, Any],
        mutation_id: str,
        base_revision: int,
        *,
        document_id: str,
        version_id: str,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._save_activity, activity, mutation_id, base_revision, document_id, version_id
        )

    async def record_progress(
        self,
        *,
        document_id: str,
        version_id: str,
        mutation_id: str,
        base_revision: int,
        page_index: int,
        reading_seconds: int,
    ) -> dict[str, Any]:
        return await asyncio.to_thread(
            self._record_progress,
            document_id,
            version_id,
            mutation_id,
            base_revision,
            page_index,
            reading_seconds,
        )

    def _record_progress(
        self,
        document_id: str,
        version_id: str,
        mutation_id: str,
        base_revision: int,
        page_index: int,
        reading_seconds: int,
    ) -> dict[str, Any]:
        mutation = _uuid(mutation_id, "client_mutation_id")
        document_id, version_id = _scope(document_id, version_id)
        base_revision = _safe_revision(base_revision)
        if isinstance(page_index, bool) or not isinstance(page_index, int) or page_index < 0:
            raise ValueError("page_index must be a non-negative integer")
        if (
            isinstance(reading_seconds, bool)
            or not isinstance(reading_seconds, int)
            or not 0 <= reading_seconds <= 300
        ):
            raise ValueError("reading_seconds must be an integer between 0 and 300")
        payload_hash = _digest(
            {
                "document_id": document_id,
                "version_id": version_id,
                "page_index": page_index,
                "reading_seconds": reading_seconds,
            }
        )
        with self._connect(write=True) as conn:
            prior = conn.execute(
                "SELECT * FROM mnemosyne_learning_mutations WHERE client_mutation_id=?",
                (mutation,),
            ).fetchone()
            if prior is not None:
                if (
                    prior["payload_sha256"] != payload_hash
                    or prior["document_id"] != document_id
                    or prior["version_id"] != version_id
                ):
                    raise LearningIdempotencyMismatch()
                return self._load_state(conn, document_id, version_id)
            state = self._load_state(conn, document_id, version_id)
            if state["learning_revision"] != base_revision:
                raise LearningRevisionConflict()
            progress = state["progress"]
            pages_read = set(progress["pages_read"])
            changed = (
                page_index not in pages_read
                or progress["last_page_index"] != page_index
                or reading_seconds > 0
            )
            progress["pages_read"] = sorted(pages_read | {page_index})
            progress["last_page_index"] = page_index
            if progress["reading_seconds"] + reading_seconds > _MAX_SAFE_INTEGER:
                raise ValueError("reading_seconds exceeds the safe integer range")
            progress["reading_seconds"] += reading_seconds
            if changed:
                state["learning_revision"] += 1
                self._save_state(conn, state)
            self._remember_mutation(
                conn,
                mutation,
                payload_hash,
                document_id,
                version_id,
                state["learning_revision"],
            )
            return state

    def _save_activity(
        self,
        activity: dict[str, Any],
        mutation_id: str,
        base_revision: int,
        document_id: str,
        version_id: str,
    ) -> dict[str, Any]:
        mutation = _uuid(mutation_id, "mutation_id")
        document_id, version_id = _scope(document_id, version_id)
        base_revision = _safe_revision(base_revision)
        payload_hash = _digest(
            {"activity": activity, "document_id": document_id, "version_id": version_id}
        )
        with self._connect(write=True) as conn:
            prior = conn.execute(
                "SELECT * FROM mnemosyne_learning_mutations WHERE client_mutation_id=?", (mutation,)
            ).fetchone()
            if prior is not None:
                if (
                    prior["payload_sha256"] != payload_hash
                    or prior["document_id"] != document_id
                    or prior["version_id"] != version_id
                ):
                    raise LearningIdempotencyMismatch()
                return self._load_state(conn, document_id, version_id)
            state = self._load_state(conn, document_id, version_id)
            if state["learning_revision"] != base_revision:
                raise LearningRevisionConflict()
            existing = next(
                (
                    item
                    for item in state["activities"]
                    if item["activity_id"] == activity["activity_id"]
                ),
                None,
            )
            if existing is not None and existing != activity:
                raise LearningIdempotencyMismatch()
            if existing is None:
                state["activities"].append(activity)
            state["learning_revision"] += 1
            self._save_state(conn, state)
            self._remember_mutation(
                conn, mutation, payload_hash, document_id, version_id, state["learning_revision"]
            )
            return state

    async def review_memory(self, review: dict[str, Any]) -> dict[str, Any]:
        return await asyncio.to_thread(self._review_memory, review)

    def _review_memory(self, review: dict[str, Any]) -> dict[str, Any]:
        mutation = _uuid(review.get("client_mutation_id"), "client_mutation_id")
        memory_id = _uuid(review.get("memory_id"), "memory_id")
        base_revision = _safe_revision(review.get("base_learning_revision"))
        payload_hash = _digest(review)
        grade = review.get("grade")
        if isinstance(grade, bool) or not isinstance(grade, int) or not 0 <= grade <= 3:
            raise ValueError("grade must be an integer between 0 and 3")
        with self._connect(write=True) as conn:
            prior = conn.execute(
                "SELECT * FROM mnemosyne_learning_mutations WHERE client_mutation_id=?", (mutation,)
            ).fetchone()
            if prior is not None:
                if prior["payload_sha256"] != payload_hash:
                    raise LearningIdempotencyMismatch()
                return self._load_state(conn, prior["document_id"], prior["version_id"])
            indexed = conn.execute(
                "SELECT document_id, version_id FROM mnemosyne_learning_memory_index WHERE memory_id=?",
                (memory_id,),
            ).fetchone()
            if indexed is None:
                raise LookupError("memory not found")
            document_id, version_id = indexed["document_id"], indexed["version_id"]
            state = self._load_state(conn, document_id, version_id)
            if state["learning_revision"] != base_revision:
                raise LearningRevisionConflict()
            memory = next(
                (item for item in state["memory"] if item["memory_id"] == memory_id), None
            )
            if memory is None:
                raise LookupError("memory not found")
            now = _now()
            count = int(memory["review_count"])
            if grade == 0:
                interval = 10 * 60
            elif grade == 1:
                interval = 24 * 60 * 60
            elif grade == 2:
                interval = 3 * 24 * 60 * 60 * (2 ** min(count, 5))
            else:
                interval = 7 * 24 * 60 * 60 * (2 ** min(count, 5))
            interval = min(interval, _MAX_REVIEW_INTERVAL_SECONDS)
            memory["review_count"] = count + 1
            memory["due_at"] = _timestamp(now + timedelta(seconds=interval))
            state["activities"].append(
                {
                    "activity_id": mutation,
                    "kind": "review",
                    "turn_id": None,
                    "summary_ko": "기억 카드 복습",
                    "created_at": _timestamp(now),
                }
            )
            state["progress"]["next_review_at"] = min(item["due_at"] for item in state["memory"])
            state["learning_revision"] += 1
            self._save_state(conn, state)
            self._remember_mutation(
                conn, mutation, payload_hash, document_id, version_id, state["learning_revision"]
            )
            return state


__all__ = [
    "LearningIdempotencyMismatch",
    "LearningRevisionConflict",
    "LearningStoreError",
    "SQLiteMnemosyneLearningStore",
]
