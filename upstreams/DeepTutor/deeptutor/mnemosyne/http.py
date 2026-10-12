"""HTTP registration for the Mnemosyne session boundary."""

from __future__ import annotations

import importlib.util
import uuid

from fastapi import APIRouter, Cookie, Depends, Header, Request, Response
from fastapi.responses import JSONResponse
from starlette.datastructures import Headers, MutableHeaders
from starlette.websockets import WebSocket

from deeptutor.mnemosyne.security import (
    PAIRING_COOKIE,
    MnemosyneSessionStore,
    allowed_origin,
    request_token,
)

CONTRACT_VERSION = "0.1.0"
router = APIRouter(prefix="/v1", tags=["mnemosyne"])


class MnemosyneAuthError(Exception):
    def __init__(self, status_code: int, code: str) -> None:
        self.status_code = status_code
        self.code = code


def _request_id(request: Request) -> str:
    value = request.headers.get("x-request-id", "")
    try:
        return str(uuid.UUID(value)) if value else str(uuid.uuid4())
    except ValueError:
        return str(uuid.uuid4())


def auth_error_response(request: Request, exc: MnemosyneAuthError) -> JSONResponse:
    messages = {
        "unauthorized": "인증이 필요합니다.",
        "forbidden": "허용된 출처에서 요청해 주세요.",
        "invalid_pairing_code": "페어링 코드가 만료되었거나 이미 사용되었습니다.",
        "invalid_request": "요청 형식이나 값이 올바르지 않습니다.",
        "not_ready": "서버 서비스를 시작하는 중입니다.",
    }
    request_id = _request_id(request)
    return JSONResponse(
        {
            "contract_version": CONTRACT_VERSION,
            "code": exc.code,
            "message_ko": messages.get(exc.code, "요청을 처리하지 못했습니다."),
            "request_id": request_id,
            "retryable": False,
            "details": {},
        },
        status_code=exc.status_code,
        headers={"X-Request-ID": request_id, "X-Mnemosyne-Contract-Version": CONTRACT_VERSION},
    )


async def require_mnemosyne_session(
    request: Request,
    authorization: str | None = Header(None, alias="Authorization"),
    cookie: str | None = Cookie(None, alias=PAIRING_COOKIE),
) -> str:
    token, cookie_auth = request_token(request)
    # FastAPI has already parsed the same headers, but request_token preserves
    # the distinction between browser cookie sessions and native bearer tokens.
    if authorization and not authorization.lower().startswith("bearer "):
        raise MnemosyneAuthError(401, "unauthorized")
    if cookie and token is None:
        token, cookie_auth = cookie, True
    store = MnemosyneSessionStore()
    device_id = store.authenticate(token) if token is not None else None
    if token is None or device_id is None:
        raise MnemosyneAuthError(401, "unauthorized")

    origin = request.headers.get("origin")
    if origin and not allowed_origin(request, origin):
        raise MnemosyneAuthError(403, "forbidden")
    if cookie_auth and request.method.upper() not in {"GET", "HEAD", "OPTIONS"}:
        if not origin or not allowed_origin(request, origin):
            raise MnemosyneAuthError(403, "forbidden")
    request.state.mnemosyne_device_id = device_id
    return str(device_id)


def _services(request: Request):
    services = getattr(request.app.state, "mnemosyne", None)
    if services is None:
        raise MnemosyneAuthError(503, "not_ready")
    return services


@router.post("/session/pair")
async def pair_device(request: Request, response: Response):
    origin = request.headers.get("origin")
    if origin and not allowed_origin(request, origin):
        raise MnemosyneAuthError(403, "forbidden")
    try:
        body = await request.json()
    except Exception as exc:
        raise MnemosyneAuthError(400, "invalid_request") from exc
    if (
        not isinstance(body, dict)
        or set(body) != {"one_time_code", "device_name"}
        or not isinstance(body["one_time_code"], str)
        or not 8 <= len(body["one_time_code"]) <= 128
        or not isinstance(body["device_name"], str)
        or not body["device_name"].strip()
        or len(body["device_name"].strip()) > 120
    ):
        raise MnemosyneAuthError(400, "invalid_request")
    receipt = MnemosyneSessionStore().pair(body["one_time_code"], body["device_name"])
    if receipt is None:
        raise MnemosyneAuthError(401, "invalid_pairing_code")
    response.set_cookie(
        key=PAIRING_COOKIE,
        value=receipt["access_token"],
        max_age=90 * 24 * 60 * 60,
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )
    response.headers["X-Mnemosyne-Contract-Version"] = CONTRACT_VERSION
    response.headers["X-Request-ID"] = _request_id(request)
    return {
        **receipt,
        "token_type": "Bearer",
    }


@router.delete("/session", dependencies=[Depends(require_mnemosyne_session)])
async def revoke_device_session(request: Request, response: Response):
    token, _ = request_token(request)
    revoked = bool(token and MnemosyneSessionStore().revoke(token))
    response.delete_cookie(
        key=PAIRING_COOKIE,
        path="/",
        secure=request.url.scheme == "https",
        httponly=True,
        samesite="strict",
    )
    response.headers["X-Mnemosyne-Contract-Version"] = CONTRACT_VERSION
    response.headers["X-Request-ID"] = _request_id(request)
    return {"revoked": revoked}


@router.get("/readiness", dependencies=[Depends(require_mnemosyne_session)])
async def readiness(request: Request):
    services = _services(request)
    library = services.library
    tutor = services.tutor
    parser_ready = importlib.util.find_spec("pymupdf") is not None
    credential_ready = False
    if library.settings_credential_reader is not None:
        try:
            credential_ready = bool(library.settings_credential_reader())
        except Exception:
            credential_ready = False
    tutor_ready = bool(getattr(tutor, "product_ready", False))
    components = {
        "database": "ready" if getattr(library, "db", None) is not None else "failed",
        "storage": "ready" if getattr(library, "db", None) is not None else "failed",
        "parser": "ready" if parser_ready else "disabled",
        "index": "ready" if getattr(library, "rag_indexer", None) is not None else "pending",
        "provider": "ready" if credential_ready else "disabled",
    }
    fully_ready = tutor_ready and all(value == "ready" for value in components.values())
    request_id = _request_id(request)
    return JSONResponse(
        {
            "contract_version": CONTRACT_VERSION,
            "status": "ready" if fully_ready else "degraded",
            "components": components,
            "capabilities": list(tutor.capabilities) if tutor_ready else [],
            # This is deliberately the guaranteed minimum. The native turn
            # store's configured retention is reported once the store exposes it.
            "event_resume_seconds": max(1, int(getattr(tutor.turns, "event_resume_seconds", 1))),
        },
        headers={"X-Request-ID": request_id, "X-Mnemosyne-Contract-Version": CONTRACT_VERSION},
    )


class MnemosyneWebSocketBearerMiddleware:
    """Bridge paired bearer/cookie sessions to DeepTutor's native `/ws` auth.

    Native iPad clients can send Authorization on the upgrade request. Browser
    WebSocket APIs cannot, so they send the HttpOnly pairing cookie instead.
    A valid Mnemosyne session is translated to an internal DeepTutor JWT only
    for this ASGI request; the pairing token is never placed in a URL or logged.
    """

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope.get("type") == "websocket" and scope.get("path") == "/ws":
            headers = Headers(scope=scope)
            authorization = headers.get("authorization", "")
            scheme, _, bearer = authorization.partition(" ")
            cookies = headers.get("cookie", "")
            cookie_token = None
            for item in cookies.split(";"):
                name, separator, value = item.strip().partition("=")
                if separator and name == PAIRING_COOKIE:
                    cookie_token = value
                    break
            bearer_token = bearer.strip() if scheme.lower() == "bearer" else ""
            token = bearer_token if bearer_token.startswith("mnemo_") else cookie_token
            if token is not None:
                sessions = MnemosyneSessionStore()
                device_id = sessions.authenticate(token)
                if device_id is None:
                    await send({"type": "websocket.close", "code": 4401})
                    return
                websocket = WebSocket(scope, receive=receive, send=send)
                origin = headers.get("origin")
                if origin and not allowed_origin(websocket, origin):
                    await send({"type": "websocket.close", "code": 4403})
                    return
                if cookie_token is not None and not origin:
                    await send({"type": "websocket.close", "code": 4403})
                    return
                from deeptutor.multi_user.models import LOCAL_ADMIN_ID, LOCAL_ADMIN_USERNAME
                from deeptutor.services.auth import create_token

                jwt = create_token(LOCAL_ADMIN_USERNAME, role="admin", user_id=LOCAL_ADMIN_ID)
                mutable = MutableHeaders(scope={"headers": list(scope.get("headers", []))})
                # Replace the original credential with a short-lived internal
                # JWT cookie that ws_require_auth already understands.
                remaining = [
                    item.strip()
                    for item in cookies.split(";")
                    if item.strip()
                    and not item.strip().startswith(f"{PAIRING_COOKIE}=")
                    and not item.strip().startswith("dt_token=")
                ]
                remaining.append(f"dt_token={jwt}")
                mutable["cookie"] = "; ".join(remaining)
                if "authorization" in mutable:
                    del mutable["authorization"]
                bridged_scope = {**scope, "headers": mutable.raw}
                await self.app(bridged_scope, receive, send)
                return
        await self.app(scope, receive, send)
