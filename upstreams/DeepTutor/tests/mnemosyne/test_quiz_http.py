from __future__ import annotations

from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient

from deeptutor.mnemosyne import http as mnemosyne_http


DOCUMENT_ID = "123e4567-e89b-42d3-a456-426614174001"


def _client(monkeypatch, generator):
    class SessionStore:
        def authenticate(self, token):
            return "test-device" if token == "test-token" else None

    monkeypatch.setattr(mnemosyne_http, "MnemosyneSessionStore", SessionStore)
    app = FastAPI()
    app.add_exception_handler(
        mnemosyne_http.MnemosyneAuthError,
        mnemosyne_http.auth_error_response,
    )
    app.include_router(mnemosyne_http.router)
    app.state.mnemosyne = SimpleNamespace(quiz_generation=generator)
    return TestClient(app)


def test_quiz_generation_route_requires_pairing_and_dispatches_versioned_request(monkeypatch):
    calls = []

    class Generator:
        async def create_quiz(self, **request):
            calls.append(request)
            return {
                "quiz_id": "123e4567-e89b-42d3-a456-426614174002",
                "document_id": DOCUMENT_ID,
                "version_id": request["version_id"],
                "title": "확인 문제",
                "questions": [],
                "response_language": "ko",
            }

    client = _client(monkeypatch, Generator())
    body = {
        "client_mutation_id": "123e4567-e89b-42d3-a456-426614174003",
        "version_id": "sha256:" + "a" * 64,
        "page_index": 0,
        "prompt": "이 페이지에서 핵심 문제를 만들어 주세요.",
        "response_language": "ko",
    }
    path = f"/v1/documents/{DOCUMENT_ID}/quizzes"

    unauthorized = client.post(
        path,
        json=body,
        headers={"X-Mnemosyne-Contract-Version": "0.2.0"},
    )
    assert unauthorized.status_code == 401
    assert calls == []

    response = client.post(
        path,
        json=body,
        headers={
            "Authorization": "Bearer test-token",
            "X-Mnemosyne-Contract-Version": "0.2.0",
        },
    )
    assert response.status_code == 201
    assert response.json()["document_id"] == DOCUMENT_ID
    assert response.headers["X-Mnemosyne-Contract-Version"] == "0.2.0"
    assert response.headers["X-Request-ID"]
    assert calls == [
        {
            "document_id": DOCUMENT_ID,
            "version_id": body["version_id"],
            "page_index": 0,
            "prompt": body["prompt"],
            "client_mutation_id": body["client_mutation_id"],
            "response_language": "ko",
        }
    ]


def test_quiz_generation_route_does_not_return_success_without_a_generator(monkeypatch):
    client = _client(monkeypatch, None)
    response = client.post(
        f"/v1/documents/{DOCUMENT_ID}/quizzes",
        json={
            "client_mutation_id": "123e4567-e89b-42d3-a456-426614174003",
            "version_id": "sha256:" + "a" * 64,
            "page_index": 0,
            "prompt": "퀴즈를 만들어 주세요.",
            "response_language": "ko",
        },
        headers={
            "Authorization": "Bearer test-token",
            "X-Mnemosyne-Contract-Version": "0.2.0",
        },
    )
    assert response.status_code == 503
    assert response.json()["code"] == "not_ready"
