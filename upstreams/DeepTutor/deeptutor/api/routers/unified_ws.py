"""Unified WebSocket adapter for turn execution and replayable streaming.

All mutating operations are commands on :class:`TurnApplicationService`.
Subscriptions and active-turn checks are deliberately read-only, including
when the owner worker has disappeared and leader recovery is still pending.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import TypeAdapter, ValidationError

from deeptutor.api.contracts.turn_protocol import (
    PROTOCOL_VERSION,
    ClientCommand,
    StartTurnCommand,
)
from deeptutor.mnemosyne.http import require_mnemosyne_session
from deeptutor.services.workspace.models import WorkspaceError

router = APIRouter()
logger = logging.getLogger(__name__)
_CLIENT_COMMAND_ADAPTER = TypeAdapter(ClientCommand)


def _clean_answers(value: Any) -> list[dict[str, Any]] | None:
    if not isinstance(value, list):
        return None
    cleaned: list[dict[str, Any]] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        question_id = str(entry.get("questionId") or entry.get("id") or "").strip()
        if question_id:
            cleaned.append({"questionId": question_id, "text": str(entry.get("text") or "")})
    return cleaned or None


@router.websocket("/ws")
async def unified_websocket(ws: WebSocket) -> None:
    from deeptutor.api.routers.auth import ws_auth_failed, ws_require_auth
    from deeptutor.app.container import get_application_container
    from deeptutor.multi_user.context import reset_current_user

    user_token = await ws_require_auth(ws)
    if user_token is ws_auth_failed:
        return

    await ws.accept()
    closed = False
    subscription_tasks: dict[str, asyncio.Task[None]] = {}

    # Resolve once after authentication. Context variables are copied into
    # subscription tasks, so the socket remains in one stable StoreScope.
    container = getattr(ws.app.state, "application_container", None)
    if container is None:
        container = get_application_container()
        await container.start()
    turns = container.turns
    mnemosyne = getattr(ws.app.state, "mnemosyne", None)
    tutor = getattr(mnemosyne, "tutor", None)

    async def safe_send(data: dict[str, Any]) -> None:
        nonlocal closed
        if closed:
            return
        try:
            payload = {**data, "protocol_version": PROTOCOL_VERSION}
            await ws.send_text(json.dumps(payload, ensure_ascii=False, default=str))
        except Exception:
            closed = True

    async def send_protocol_error(
        message: str,
        *,
        error_code: str,
        session_id: str = "",
        turn_id: str = "",
        retryable: bool = False,
    ) -> None:
        await safe_send(
            {
                "type": "protocol_error",
                "error_code": error_code,
                "message": message,
                "retryable": retryable,
                "session_id": session_id,
                "turn_id": turn_id,
            }
        )

    async def send_error(
        content: str,
        *,
        error_code: str,
        session_id: str = "",
        turn_id: str = "",
        retryable: bool = False,
        terminal: bool = False,
    ) -> None:
        await send_protocol_error(
            content,
            error_code=error_code,
            session_id=session_id,
            turn_id=turn_id,
            retryable=retryable or terminal,
        )

    async def send_command_ack(
        msg: dict[str, Any],
        *,
        accepted: bool,
        error_code: str = "",
        message: str = "",
    ) -> None:
        await safe_send(
            {
                "type": "command_ack",
                "command_id": str(msg["command_id"]),
                "command_type": str(msg["type"]),
                "accepted": accepted,
                "turn_id": str(msg.get("turn_id") or ""),
                "error_code": error_code,
                "message": message,
            }
        )

    async def stop_subscription(key: str) -> None:
        task = subscription_tasks.pop(key, None)
        if task is None:
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def subscribe_turn(turn_id: str, after_seq: int = 0) -> None:
        async def _forward() -> None:
            try:
                subscribe = tutor.subscribe_turn if tutor is not None else turns.subscribe_turn
                async for event in subscribe(turn_id, after_seq=after_seq):
                    await safe_send(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Turn subscription failed: %s", turn_id)
                await send_error(
                    str(exc),
                    error_code="subscription_failed",
                    turn_id=turn_id,
                    retryable=True,
                )

        await stop_subscription(turn_id)
        subscription_tasks[turn_id] = asyncio.create_task(_forward())

    async def subscribe_session(session_id: str, after_seq: int = 0) -> None:
        async def _forward() -> None:
            try:
                async for event in turns.subscribe_session(session_id, after_seq=after_seq):
                    await safe_send(event)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.exception("Session subscription failed: %s", session_id)
                await send_error(
                    str(exc),
                    error_code="subscription_failed",
                    session_id=session_id,
                    retryable=True,
                )

        key = f"session:{session_id}"
        await stop_subscription(key)
        subscription_tasks[key] = asyncio.create_task(_forward())

    try:
        while not closed:
            raw = await ws.receive_text()
            try:
                decoded = json.loads(raw)
            except json.JSONDecodeError:
                await send_protocol_error("Invalid JSON.", error_code="invalid_json")
                continue

            if not isinstance(decoded, dict):
                await send_protocol_error(
                    "WebSocket commands must be JSON objects.",
                    error_code="invalid_command",
                )
                continue
            if decoded.get("protocol_version") != PROTOCOL_VERSION:
                await send_protocol_error(
                    f"Unsupported or missing protocol_version; expected {PROTOCOL_VERSION}.",
                    error_code="unsupported_protocol_version",
                )
                continue
            try:
                command = _CLIENT_COMMAND_ADAPTER.validate_python(decoded)
            except ValidationError:
                await send_protocol_error(
                    "Command does not match the turn protocol.",
                    error_code="invalid_command",
                )
                continue

            # A continuing turn omits workspace_id to inherit its binding.
            # Filling defaults here would turn that omission into an explicit
            # null (and also turn an omitted parent into a root-branch edit).
            msg = (
                command.to_payload()
                if isinstance(command, StartTurnCommand)
                else command.model_dump(mode="python")
            )

            msg_type = msg.get("type")

            if msg_type in {"message", "start_turn"}:
                try:
                    payload = {
                        key: value
                        for key, value in msg.items()
                        if key not in {"type", "protocol_version"}
                    }
                    start = tutor.start_native_turn if tutor is not None else turns.start_turn
                    config = payload.get("config")
                    has_mnemosyne_envelope = (
                        isinstance(config, dict) and "mnemosyne" in config
                    )
                    provider_runtime = getattr(mnemosyne, "provider_runtime", None)
                    if tutor is not None and has_mnemosyne_envelope and provider_runtime is not None:
                        with provider_runtime.llm_scope():
                            _, turn = await start(payload)
                    else:
                        _, turn = await start(payload)
                except (RuntimeError, ValueError, WorkspaceError):
                    await send_error(
                        "요청을 시작할 수 없습니다. capability, 언어와 문서 준비 상태를 확인해 주세요.",
                        error_code="start_turn_rejected",
                        session_id=str(msg.get("session_id") or ""),
                        terminal=True,
                    )
                    continue
                await subscribe_turn(turn["id"])
                continue

            if msg_type == "ping":
                await safe_send({"type": "pong"})
                continue

            if msg_type in {"subscribe_turn", "resume_from"}:
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await send_error("Missing turn_id.", error_code="missing_turn_id")
                    continue
                after_seq = int(
                    (msg.get("seq") if msg_type == "resume_from" else msg.get("after_seq")) or 0
                )
                await subscribe_turn(turn_id, after_seq=after_seq)
                continue

            if msg_type == "subscribe_session":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await send_error("Missing session_id.", error_code="missing_session_id")
                    continue
                await subscribe_session(session_id, after_seq=int(msg.get("after_seq") or 0))
                continue

            if msg_type == "check_active_turn":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await send_error("Missing session_id.", error_code="missing_session_id")
                    continue
                active = await turns.check_active_turn(session_id)
                await safe_send(
                    {
                        "type": "active_turn_info",
                        "turn_id": str((active or {}).get("turn_id") or ""),
                        "status": str((active or {}).get("status") or "none"),
                        "owner_id": str((active or {}).get("owner_id") or ""),
                    }
                )
                continue

            if msg_type == "unsubscribe":
                turn_id = str(msg.get("turn_id") or "").strip()
                session_id = str(msg.get("session_id") or "").strip()
                if turn_id:
                    await stop_subscription(turn_id)
                if session_id:
                    await stop_subscription(f"session:{session_id}")
                continue

            if msg_type == "cancel_turn":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await send_error("Missing turn_id.", error_code="missing_turn_id")
                    continue
                if tutor is not None:
                    accepted = await tutor.cancel_turn(turn_id, str(msg["command_id"]))
                else:
                    accepted = await turns.cancel_turn(turn_id, command_id=str(msg["command_id"]))
                if not accepted:
                    await send_command_ack(
                        msg,
                        accepted=False,
                        error_code="turn_not_active",
                        message=f"Turn is not active or recoverable: {turn_id}",
                    )
                else:
                    await send_command_ack(msg, accepted=True)
                continue

            if msg_type == "submit_user_reply":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await send_error("Missing turn_id.", error_code="missing_turn_id")
                    continue
                text = msg.get("text")
                accepted = await turns.submit_user_reply(
                    turn_id,
                    text=str(text) if text is not None else None,
                    answers=_clean_answers(msg.get("answers")),
                    command_id=str(msg["command_id"]),
                )
                if not accepted:
                    await send_command_ack(
                        msg,
                        accepted=False,
                        error_code="turn_not_waiting_input",
                        message=f"Turn {turn_id} is not awaiting a user reply.",
                    )
                else:
                    await send_command_ack(msg, accepted=True)
                continue

            if msg_type == "regenerate":
                session_id = str(msg.get("session_id") or "").strip()
                if not session_id:
                    await send_error("Missing session_id.", error_code="missing_session_id")
                    continue
                overrides = msg.get("overrides") if isinstance(msg.get("overrides"), dict) else None
                try:
                    _, turn = await turns.regenerate_last_turn(session_id, overrides=overrides)
                except (RuntimeError, WorkspaceError) as exc:
                    await send_error(
                        str(exc),
                        error_code="regenerate_rejected",
                        session_id=session_id,
                        terminal=True,
                    )
                    continue
                await subscribe_turn(turn["id"])
                continue

            if msg_type == "user_input":
                turn_id = str(msg.get("turn_id") or "").strip()
                if not turn_id:
                    await send_error(
                        "Missing turn_id for user_input.", error_code="missing_turn_id"
                    )
                    continue
                accepted = await turns.submit_user_input(
                    turn_id,
                    str(msg.get("content") or ""),
                    command_id=str(msg["command_id"]),
                )
                if not accepted:
                    await send_command_ack(
                        msg,
                        accepted=False,
                        error_code="turn_not_active",
                        message=f"Turn is not active: {turn_id}",
                    )
                else:
                    await send_command_ack(msg, accepted=True)
                continue

            await send_protocol_error(
                f"Unknown type: {msg_type}", error_code="unknown_message_type"
            )

    except WebSocketDisconnect:
        logger.debug("Client disconnected from /ws")
    except Exception as exc:
        logger.error("Unified WS error: %s", exc, exc_info=True)
        await send_error(str(exc), error_code="internal_error", retryable=True)
    finally:
        closed = True
        for key in list(subscription_tasks):
            await stop_subscription(key)
        if user_token is not None:
            reset_current_user(user_token)


# Mnemosyne learning routes use the canonical contract DTOs, the shared
# pairing boundary, and the durable SQLite store composed at application start.
_MNEMOSYNE_CONTRACT_VERSION = "0.2.0"
_LEARNING_ERROR_MESSAGES = {
    "unauthorized": "인증이 필요합니다.",
    "forbidden": "요청 권한이 없습니다.",
    "invalid_request": "요청 형식이나 문서·버전 범위를 확인해 주세요.",
    "not_found": "요청한 학습 자료를 찾을 수 없습니다.",
    "not_ready": "학습 저장소가 아직 준비되지 않았습니다.",
    "conflict": "학습 상태가 변경되었습니다. 최신 상태를 불러온 뒤 다시 시도해 주세요.",
    "idempotency_mismatch": "같은 요청 ID가 다른 내용으로 이미 사용되었습니다.",
    "contract_mismatch": "지원하는 계약 버전은 0.2.0입니다.",
    "provider_error": "평가 처리에 실패했습니다. 잠시 후 다시 시도해 주세요.",
    "internal_error": "요청을 처리하지 못했습니다.",
}


def _learning_request_id(request: Request) -> str:
    value = getattr(request.state, "request_id", None)
    try:
        return str(UUID(str(value)))
    except (AttributeError, TypeError, ValueError):
        return str(uuid4())


def _learning_error(
    request: Request,
    *,
    status_code: int,
    code: str,
    retryable: bool = False,
) -> JSONResponse:
    request_id = _learning_request_id(request)
    return JSONResponse(
        status_code=status_code,
        content={
            "contract_version": _MNEMOSYNE_CONTRACT_VERSION,
            "code": code,
            "message_ko": _LEARNING_ERROR_MESSAGES[code],
            "request_id": request_id,
            "retryable": retryable,
            "details": {},
        },
        headers={
            "X-Request-ID": request_id,
            "X-Mnemosyne-Contract-Version": _MNEMOSYNE_CONTRACT_VERSION,
        },
    )


async def _learning_api_tutor(
    request: Request,
    contract_version: str | None,
) -> tuple[Any | None, JSONResponse | None]:
    if contract_version != _MNEMOSYNE_CONTRACT_VERSION:
        return None, _learning_error(
            request, status_code=400, code="contract_mismatch"
        )

    services = getattr(request.app.state, "mnemosyne", None)
    tutor = getattr(services, "tutor", None)
    if tutor is None:
        return None, _learning_error(
            request, status_code=503, code="not_ready", retryable=True
        )
    return tutor, None


async def _learning_json_body(
    request: Request,
) -> tuple[dict[str, Any] | None, JSONResponse | None]:
    try:
        value = await request.json()
    except (UnicodeDecodeError, ValueError):
        return None, _learning_error(
            request, status_code=400, code="invalid_request"
        )
    if not isinstance(value, dict):
        return None, _learning_error(
            request, status_code=400, code="invalid_request"
        )
    return value, None


def _same_uuid(left: Any, right: Any) -> bool:
    try:
        return UUID(str(left)) == UUID(str(right))
    except (AttributeError, TypeError, ValueError):
        return False


def _learning_exception_response(request: Request, exc: Exception) -> JSONResponse:
    from deeptutor.learning.service import MnemosyneAssessmentError
    from deeptutor.mnemosyne.provider import MnemosyneProviderNotReady
    from deeptutor.mnemosyne.tutor import LearningStateNotReady

    if isinstance(exc, MnemosyneProviderNotReady):
        return _learning_error(
            request, status_code=503, code="provider_error", retryable=True
        )
    if isinstance(exc, LearningStateNotReady):
        return _learning_error(
            request, status_code=503, code="not_ready", retryable=True
        )
    if isinstance(exc, MnemosyneAssessmentError):
        if exc.code == "idempotency_mismatch":
            return _learning_error(
                request, status_code=409, code="idempotency_mismatch"
            )
        if exc.code in {
            "learning_revision_conflict",
            "attempt_in_progress",
        }:
            return _learning_error(
                request,
                status_code=409,
                code="conflict",
                retryable=exc.retryable,
            )
        if exc.code == "invalid_attempt":
            return _learning_error(
                request, status_code=400, code="invalid_request"
            )
        if exc.code.startswith("assessment_store_") or exc.code == "assessment_commit_unavailable":
            return _learning_error(
                request, status_code=503, code="not_ready", retryable=exc.retryable
            )
        return _learning_error(
            request, status_code=503, code="provider_error", retryable=exc.retryable
        )

    code = str(getattr(exc, "code", "") or "")
    if code == "idempotency_mismatch":
        return _learning_error(
            request, status_code=409, code="idempotency_mismatch"
        )
    if code in {"learning_revision_conflict", "revision_conflict", "conflict"}:
        return _learning_error(request, status_code=409, code="conflict")
    if isinstance(exc, (KeyError, LookupError)):
        return _learning_error(request, status_code=404, code="not_found")
    if isinstance(exc, ValueError):
        return _learning_error(request, status_code=400, code="invalid_request")

    logger.error(
        "Mnemosyne learning request failed request_id=%s exception_type=%s",
        _learning_request_id(request),
        type(exc).__name__,
    )
    return _learning_error(request, status_code=500, code="internal_error")


async def _run_learning_operation(
    request: Request,
    operation: Any,
    *,
    status_code: int = 200,
) -> JSONResponse:
    try:
        result = await operation()
    except asyncio.CancelledError:
        raise
    except Exception as exc:
        return _learning_exception_response(request, exc)
    request_id = _learning_request_id(request)
    return JSONResponse(
        status_code=status_code,
        content=result,
        headers={
            "X-Request-ID": request_id,
            "X-Mnemosyne-Contract-Version": _MNEMOSYNE_CONTRACT_VERSION,
        },
    )


@router.get(
    "/v1/tutor/turns/{turn_id}",
    operation_id="getTurn",
    tags=["mnemosyne-learning"],
    dependencies=[Depends(require_mnemosyne_session)],
)
async def get_mnemosyne_turn_receipt(
    request: Request,
    turn_id: str,
    contract_version: str | None = Header(
        default=None, alias="X-Mnemosyne-Contract-Version"
    ),
) -> JSONResponse:
    tutor, error = await _learning_api_tutor(request, contract_version)
    if error is not None:
        return error
    return await _run_learning_operation(
        request,
        lambda: tutor.get_turn_receipt(turn_id),
    )


@router.get(
    "/v1/quizzes/{quiz_id}",
    operation_id="getQuiz",
    tags=["mnemosyne-learning"],
    dependencies=[Depends(require_mnemosyne_session)],
)
async def get_mnemosyne_quiz(
    request: Request,
    quiz_id: str,
    contract_version: str | None = Header(
        default=None, alias="X-Mnemosyne-Contract-Version"
    ),
) -> JSONResponse:
    tutor, error = await _learning_api_tutor(request, contract_version)
    if error is not None:
        return error
    return await _run_learning_operation(request, lambda: tutor.get_quiz(quiz_id))


@router.post(
    "/v1/quizzes/{quiz_id}/attempts",
    operation_id="submitAttempt",
    status_code=201,
    tags=["mnemosyne-learning"],
    dependencies=[Depends(require_mnemosyne_session)],
)
async def submit_mnemosyne_attempt(
    request: Request,
    quiz_id: str,
    contract_version: str | None = Header(
        default=None, alias="X-Mnemosyne-Contract-Version"
    ),
) -> JSONResponse:
    tutor, error = await _learning_api_tutor(request, contract_version)
    if error is not None:
        return error
    attempt, error = await _learning_json_body(request)
    if error is not None:
        return error
    if not _same_uuid(attempt.get("quiz_id"), quiz_id):
        return _learning_error(request, status_code=400, code="invalid_request")
    async def submit_with_provider():
        services = getattr(request.app.state, "mnemosyne", None)
        provider_runtime = getattr(services, "provider_runtime", None)
        if provider_runtime is None:
            return await tutor.submit_attempt(attempt)
        with provider_runtime.llm_scope():
            return await tutor.submit_attempt(attempt)

    return await _run_learning_operation(request, submit_with_provider, status_code=201)


@router.get(
    "/v1/documents/{document_id}/learning",
    operation_id="getLearningState",
    tags=["mnemosyne-learning"],
    dependencies=[Depends(require_mnemosyne_session)],
)
async def get_mnemosyne_learning_state(
    request: Request,
    document_id: str,
    version_id: str | None = Query(default=None),
    contract_version: str | None = Header(
        default=None, alias="X-Mnemosyne-Contract-Version"
    ),
) -> JSONResponse:
    tutor, error = await _learning_api_tutor(request, contract_version)
    if error is not None:
        return error
    if version_id is None:
        return _learning_error(request, status_code=400, code="invalid_request")
    return await _run_learning_operation(
        request,
        lambda: tutor.get_learning_state(document_id, version_id),
    )


@router.post(
    "/v1/documents/{document_id}/progress",
    operation_id="recordReadingProgress",
    tags=["mnemosyne-learning"],
    dependencies=[Depends(require_mnemosyne_session)],
)
async def record_mnemosyne_progress(
    request: Request,
    document_id: str,
    contract_version: str | None = Header(
        default=None, alias="X-Mnemosyne-Contract-Version"
    ),
) -> JSONResponse:
    tutor, error = await _learning_api_tutor(request, contract_version)
    if error is not None:
        return error
    mutation, error = await _learning_json_body(request)
    if error is not None:
        return error
    return await _run_learning_operation(
        request,
        lambda: tutor.record_progress(document_id, mutation),
    )


@router.post(
    "/v1/memory/{memory_id}/reviews",
    operation_id="reviewMemory",
    tags=["mnemosyne-learning"],
    dependencies=[Depends(require_mnemosyne_session)],
)
async def review_mnemosyne_memory(
    request: Request,
    memory_id: str,
    contract_version: str | None = Header(
        default=None, alias="X-Mnemosyne-Contract-Version"
    ),
) -> JSONResponse:
    tutor, error = await _learning_api_tutor(request, contract_version)
    if error is not None:
        return error
    review, error = await _learning_json_body(request)
    if error is not None:
        return error
    if not _same_uuid(review.get("memory_id"), memory_id):
        return _learning_error(request, status_code=400, code="invalid_request")
    return await _run_learning_operation(
        request,
        lambda: tutor.review_memory(review),
    )
