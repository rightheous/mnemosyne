"""Exercise the mounted Mnemosyne HTTP boundary with the checked-in PDF.

This uses temporary runtime/Library state and an in-process loopback server.
It does not fake RAG or Tutor readiness: the emitted index state is the real
result of the configured DeepTutor pipeline in the current environment.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import sys
import tempfile
import threading
import time
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "upstreams/DeepTutor"))


def run(*, allow_index_unavailable: bool) -> int:
    fixture = json.loads((ROOT / "contracts/fixtures/study-session.json").read_text())
    pdf_path = ROOT / "contracts/fixtures" / fixture["original_file"]
    pdf_bytes = pdf_path.read_bytes()
    source_hash = hashlib.sha256(pdf_bytes).hexdigest()

    with tempfile.TemporaryDirectory(prefix="mnemosyne-http-flow-") as temporary:
        runtime = Path(temporary)
        os.environ["DEEPTUTOR_HOME"] = str(runtime / "runtime")

        import httpx
        import uvicorn
        from deeptutor.mnemosyne import http as mnemosyne_http
        from deeptutor.mnemosyne.http import (
            MnemosyneAuthError,
            MnemosyneWebSocketBearerMiddleware,
            auth_error_response,
            require_mnemosyne_session,
        )
        from deeptutor.mnemosyne.http import (
            router as session_router,
        )
        from deeptutor.mnemosyne.library import build_library_router, register_library
        from deeptutor.mnemosyne.security import MnemosyneSessionStore
        from deeptutor.mnemosyne.tutor import register_tutor
        from deeptutor.reading.store import ReadingStore
        from fastapi import Depends, FastAPI

        sessions = MnemosyneSessionStore(runtime / "runtime/data/system/pairing.json")
        mnemosyne_http.MnemosyneSessionStore = lambda: sessions
        library = register_library(ReadingStore(runtime / "reading"))
        tutor = register_tutor(SimpleNamespace(event_resume_seconds=60), library)

        app = FastAPI()
        app.add_exception_handler(MnemosyneAuthError, auth_error_response)
        app.include_router(session_router)
        app.include_router(
            build_library_router(library),
            dependencies=[Depends(require_mnemosyne_session)],
        )
        app.state.mnemosyne = SimpleNamespace(library=library, tutor=tutor)

        server = uvicorn.Server(
            uvicorn.Config(
                app,
                host="127.0.0.1",
                port=0,
                log_level="error",
                lifespan="off",
            )
        )
        server_thread = threading.Thread(target=server.run, daemon=True)
        server_thread.start()
        for _ in range(100):
            if server.started:
                break
            time.sleep(0.05)
        if not server.started:
            server.should_exit = True
            raise RuntimeError("Mnemosyne integration HTTP server did not start")

        port = server.servers[0].sockets[0].getsockname()[1]
        base_url = f"http://127.0.0.1:{port}"
        contract_headers = {"X-Mnemosyne-Contract-Version": "0.1.0"}

        try:
            pairing_code, _ = sessions.issue_pairing_code()
            with httpx.Client(base_url=base_url, timeout=30) as client:
                assert client.get("/v1/readiness").status_code == 401
                paired = client.post(
                    "/v1/session/pair",
                    json={
                        "one_time_code": pairing_code,
                        "device_name": "integration-web",
                    },
                    headers={"Origin": base_url},
                )
                assert paired.status_code == 200, paired.text
                token = paired.json()["access_token"]
                assert "httponly" in paired.headers["set-cookie"].lower()
                auth_headers = {
                    **contract_headers,
                    "Authorization": f"Bearer {token}",
                }

                readiness = client.get("/v1/readiness", headers=auth_headers)
                assert readiness.status_code == 200, readiness.text
                assert readiness.json()["status"] == "degraded"
                assert readiness.json()["capabilities"] == []
                assert (
                    client.get(
                        "/v1/readiness",
                        headers={**auth_headers, "Origin": "https://invalid.example"},
                    ).status_code
                    == 403
                )
                assert (
                    client.post(
                        "/v1/session/pair",
                        json={"one_time_code": pairing_code, "device_name": "replay"},
                        headers={"Origin": base_url},
                    ).status_code
                    == 401
                )

                subject_response = client.post(
                    "/v1/subjects", json={"name": "fixture"}, headers=auth_headers
                )
                assert subject_response.status_code == 201, subject_response.text
                upload = client.post(
                    "/v1/documents",
                    files={"file": (pdf_path.name, pdf_bytes, "application/pdf")},
                    data={
                        "title": "Fixture PDF",
                        "subject_id": subject_response.json()["subject_id"],
                    },
                    headers=auth_headers,
                )
                assert upload.status_code == 201, upload.text
                document = upload.json()
                document_id = document["document_id"]
                version_id = document["version_id"]
                assert document["source_sha256"] == source_hash
                assert version_id == f"sha256:{source_hash}"
                assert document["parse_state"] == "ready"
                assert document["page_count"] == 2

                page_response = client.get(
                    f"/v1/documents/{document_id}/pages/0",
                    params={"version_id": version_id},
                    headers=auth_headers,
                )
                assert page_response.status_code == 200, page_response.text
                page = page_response.json()
                search_term = next(
                    word
                    for word in re.findall(r"[\w\u3400-\u9fff]+", page["text"])
                    if len(word) >= 4
                )
                search = client.post(
                    f"/v1/documents/{document_id}/search",
                    json={"query": search_term, "version_id": version_id, "limit": 12},
                    headers=auth_headers,
                )
                assert search.status_code == 200 and search.json(), search.text
                verified = client.post(
                    "/v1/citations/verify", json=search.json()[0], headers=auth_headers
                )
                assert verified.status_code == 200, verified.text

                annotation_id = str(uuid4())
                revision_zero = 0
                box = page["geometry"]["crop_box"]
                note = {
                    "annotation_id": annotation_id,
                    "document_id": document_id,
                    "version_id": version_id,
                    "page_index": 0,
                    "kind": "note",
                    "payload": {
                        "position": [box[0] + 20, box[1] + 20],
                        "body": "sync check",
                        "anchor": verified.json()["anchor"],
                    },
                }
                mutation = {
                    "client_mutation_id": str(uuid4()),
                    "client_id": str(uuid4()),
                    "document_id": document_id,
                    "version_id": version_id,
                    "annotation_id": annotation_id,
                    "base_revision": revision_zero,
                    "created_at": "2026-10-12T00:00:00Z",
                    "operation": "upsert",
                    "annotation": note,
                }
                batch = {
                    "contract_version": "0.1.0",
                    "document_id": document_id,
                    "version_id": version_id,
                    "mutations": [mutation],
                }
                mutation_path = f"/v1/documents/{document_id}/annotations/mutations"
                first = client.post(mutation_path, json=batch, headers=auth_headers)
                assert first.status_code == 200, first.text
                assert first.json()["results"][0]["status"] == "applied"
                retry = client.post(mutation_path, json=batch, headers=auth_headers)
                assert retry.status_code == 200, retry.text
                assert (
                    retry.json()["results"][0]["server_revision"]
                    == first.json()["results"][0]["server_revision"]
                )

                live_export = client.post(
                    f"/v1/documents/{document_id}/exports",
                    json={
                        "version_id": version_id,
                        "annotation_revision": first.json()["results"][0][
                            "server_revision"
                        ],
                        "include_ink": False,
                    },
                    headers=auth_headers,
                )
                assert live_export.status_code == 201, live_export.text
                export_file = client.get(
                    live_export.json()["download_path"], headers=auth_headers
                )
                assert export_file.status_code == 200
                assert (
                    hashlib.sha256(export_file.content).hexdigest()
                    == live_export.json()["export_sha256"]
                )
                assert live_export.json()["original_sha256"] == source_hash
                assert live_export.json()["export_sha256"] != source_hash

                deletion = {
                    key: value for key, value in mutation.items() if key != "annotation"
                }
                deletion.update(
                    {
                        "client_mutation_id": str(uuid4()),
                        "base_revision": first.json()["results"][0]["server_revision"],
                        "operation": "delete",
                    }
                )
                delete_batch = {**batch, "mutations": [deletion]}
                deleted = client.post(
                    mutation_path, json=delete_batch, headers=auth_headers
                )
                assert deleted.status_code == 200, deleted.text
                delete_retry = client.post(
                    mutation_path, json=delete_batch, headers=auth_headers
                )
                assert delete_retry.status_code == 200, delete_retry.text
                assert (
                    delete_retry.json()["results"][0]["server_revision"]
                    == deleted.json()["results"][0]["server_revision"]
                )

                snapshot = client.get(
                    f"/v1/documents/{document_id}/annotations/snapshot",
                    params={"version_id": version_id},
                    headers=auth_headers,
                )
                assert snapshot.status_code == 200, snapshot.text
                records = snapshot.json()["annotations"]
                assert not [
                    record
                    for record in records
                    if record["annotation_id"] == annotation_id
                    and not record["deleted"]
                ]
                tombstone = next(
                    record
                    for record in records
                    if record["annotation_id"] == annotation_id
                )
                assert tombstone["deleted"] and tombstone["payload"] is None

                empty_export = client.post(
                    f"/v1/documents/{document_id}/exports",
                    json={
                        "version_id": version_id,
                        "annotation_revision": deleted.json()["results"][0][
                            "server_revision"
                        ],
                        "include_ink": False,
                    },
                    headers=auth_headers,
                )
                assert empty_export.status_code == 201, empty_export.text
                original = client.get(
                    f"/v1/documents/{document_id}/file",
                    params={"version_id": version_id},
                    headers=auth_headers,
                )
                assert original.status_code == 200
                assert hashlib.sha256(original.content).hexdigest() == source_hash
                index_state = client.get(
                    f"/v1/documents/{document_id}", headers=auth_headers
                ).json()["index_state"]
                assert sessions.authenticate(token) is not None
                assert client.delete("/v1/session").status_code == 403
                assert (
                    client.delete(
                        "/v1/session",
                        headers={**auth_headers, "Origin": "https://invalid.example"},
                    ).status_code
                    == 403
                )
                revoked = client.delete(
                    "/v1/session",
                    headers={**auth_headers, "Origin": base_url},
                )
                assert revoked.status_code == 200 and revoked.json()["revoked"] is True
                assert (
                    client.get("/v1/readiness", headers=auth_headers).status_code == 401
                )
        finally:
            server.should_exit = True
            server_thread.join(timeout=5)

        if server_thread.is_alive():
            raise RuntimeError("Mnemosyne integration HTTP server did not stop")

        reopened = register_library(ReadingStore(runtime / "reading"))
        stored_document = reopened.list_documents()[0]
        restored = asyncio.run(
            reopened.snapshot(
                stored_document["document_id"], stored_document["version_id"]
            )
        )
        assert any(
            record["annotation_id"] == annotation_id
            and record["deleted"]
            and record["payload"] is None
            for record in restored["annotations"]
        )
        assert (
            hashlib.sha256(
                reopened.download_original(
                    stored_document["document_id"], stored_document["version_id"]
                )
            ).hexdigest()
            == source_hash
        )

        websocket_code, _ = sessions.issue_pairing_code()
        websocket_session = sessions.pair(websocket_code, "integration-ipad")
        assert websocket_session is not None
        bridged_scope: dict[str, object] = {}

        async def capture_websocket_scope(scope, _receive, _send):
            bridged_scope.update(dict(scope["headers"]))

        async def websocket_receive():
            return {"type": "websocket.connect"}

        async def websocket_send(_message):
            return None

        websocket_scope = {
            "type": "websocket",
            "path": "/ws",
            "headers": [
                (b"host", f"127.0.0.1:{port}".encode()),
                (
                    b"authorization",
                    f"Bearer {websocket_session['access_token']}".encode(),
                ),
                (b"origin", base_url.encode()),
            ],
            "scheme": "ws",
            "query_string": b"",
            "server": ("127.0.0.1", port),
            "client": ("127.0.0.1", 12345),
            "subprotocols": [],
            "root_path": "",
        }
        asyncio.run(
            MnemosyneWebSocketBearerMiddleware(capture_websocket_scope)(
                websocket_scope, websocket_receive, websocket_send
            )
        )
        assert b"authorization" not in bridged_scope
        assert b"mnemosyne_session" not in bridged_scope[b"cookie"]
        assert b"dt_token=" in bridged_scope[b"cookie"]

        result = {
            "result": "PASS" if index_state == "ready" else "PARTIAL",
            "path": "pairing/upload/parse/search/verified-citation/annotation-retry/tombstone/export/reopen",
            "pdf_pages": stored_document["page_count"],
            "index_state": index_state,
            "original_sha256_preserved": True,
            "tombstone_persisted": True,
            "session_revocation_and_websocket_bridge": True,
        }
        print(json.dumps(result, ensure_ascii=False))
        if index_state != "ready" and not allow_index_unavailable:
            return 2
        return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--allow-index-unavailable",
        action="store_true",
        help="return success for the Library/sync checks while reporting unavailable RAG indexing",
    )
    args = parser.parse_args()
    return run(allow_index_unavailable=args.allow_index_unavailable)


if __name__ == "__main__":
    raise SystemExit(main())
