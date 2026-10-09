#!/usr/bin/env python3
"""Actual ReadingStore/parser/native protocol/registration probe, isolated data."""
import asyncio
import copy
import hashlib
import json
import sys
import tempfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "upstreams/DeepTutor"))
from deeptutor.api.contracts.turn_protocol import ClientCommand, StreamEvent
from deeptutor.mnemosyne.bootstrap import register_mnemosyne
from deeptutor.mnemosyne.library import (
    extract_pdf_pages,
    normalized_rect_to_pdf,
    viewport_point,
)
from deeptutor.mnemosyne.tutor import (
    CAPABILITY_MAP,
    native_turn_request,
    semantic_event,
)
from deeptutor.reading.service import verify_quote
from deeptutor.reading.store import ReadingStore
from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_CLASSES
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from pydantic import TypeAdapter


def check_fake_provider_stream():
    """Exercise DeepTutor's real OpenAI-compatible streaming adapter locally.

    The loopback server is test-only and never forwards requests. No provider
    credential is configured; the SDK's public ``no-key`` placeholder is used.
    """
    from deeptutor.services.llm.provider_core.openai_compat_provider import (
        OpenAICompatProvider,
    )

    received = []

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *_args):
            pass

        def do_POST(self):
            if self.path != "/v1/chat/completions":
                self.send_error(404)
                return
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", "0"))))
            received.append(
                {
                    "path": self.path,
                    "placeholder_auth": self.headers.get("Authorization") == "Bearer no-key",
                    "body": body,
                }
            )
            events = [
                {
                    "id": "chatcmpl-unit06",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "unit06-fake",
                    "choices": [
                        {"index": 0, "delta": {"content": "한국어 "}, "finish_reason": None}
                    ],
                },
                {
                    "id": "chatcmpl-unit06",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "unit06-fake",
                    "choices": [
                        {"index": 0, "delta": {"content": "응답"}, "finish_reason": None}
                    ],
                },
                {
                    "id": "chatcmpl-unit06",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "unit06-fake",
                    "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
                },
                {
                    "id": "chatcmpl-unit06",
                    "object": "chat.completion.chunk",
                    "created": 1,
                    "model": "unit06-fake",
                    "choices": [],
                    "usage": {"prompt_tokens": 2, "completion_tokens": 2, "total_tokens": 4},
                },
            ]
            payload = "".join(
                f"data: {json.dumps(event, ensure_ascii=False)}\n\n" for event in events
            ) + "data: [DONE]\n\n"
            encoded = payload.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(encoded)
            self.wfile.flush()

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()

    async def request_stream():
        provider = OpenAICompatProvider(
            api_key=None,
            api_base=f"http://127.0.0.1:{server.server_port}/v1",
            default_model="unit06-fake",
            provider_name="ollama",
            wire_api="chat_completions",
            configure_env=False,
        )
        deltas = []

        async def capture_delta(text):
            deltas.append(text)

        try:
            response = await provider.chat_stream(
                [{"role": "user", "content": "fixture probe"}],
                model="unit06-fake",
                on_content_delta=capture_delta,
            )
        finally:
            await provider.aclose()
        return response, deltas

    try:
        response, deltas = asyncio.run(request_stream())
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.content == "한국어 응답", response.content
    assert deltas == ["한국어 ", "응답"], deltas
    assert response.finish_reason == "stop", response.finish_reason
    assert len(received) == 1, len(received)
    request = received[0]
    assert request["path"] == "/v1/chat/completions"
    assert request["placeholder_auth"] is True
    assert request["body"]["model"] == "unit06-fake"
    assert request["body"]["stream"] is True
    return {
        "provider": "actual-openai-compatible-adapter",
        "network": "loopback-only",
        "credential": "none",
        "content_deltas": len(deltas),
        "finish_reason": response.finish_reason,
    }


def run_integration_checks():
    fixture = json.loads((ROOT / "contracts/fixtures/study-session.json").read_text())
    pdf = ROOT / "contracts/fixtures" / fixture["original_file"]
    original_hash = hashlib.sha256(pdf.read_bytes()).hexdigest()
    pages = extract_pdf_pages(pdf, fixture["document"]["document_id"], fixture["document"]["version_id"])
    assert pages == fixture["pages"]
    with tempfile.TemporaryDirectory(prefix="mnemosyne-source-check-") as temp:
        store = ReadingStore(Path(temp))
        manifest = store.ingest(pdf)
        marker = object()
        services = register_mnemosyne(SimpleNamespace(turns=marker), store=store)
        assert services.tutor.turns is marker and not services.tutor.product_ready
        assert manifest.unit_count == len(pages)
        # Legacy source_hash is truncated. External original version always uses full SHA-256.
        assert manifest.source_hash != original_hash
        for p in pages:
            text = store.unit_text(manifest.material_id, p["page_index"]+1)
            assert text.strip() == p["text"].strip()
        for citation in fixture["citations"]:
            anchor = citation["anchor"]
            page = pages[anchor["page_index"]]
            check = verify_quote(store, manifest.material_id, page["page_index"]+1, anchor["quote"])
            assert check.verified and check.found_locator == page["page_index"]+1
            search = services.library.search(manifest.material_id, anchor["quote"])
            assert search.hits and search.hits[0].locator == page["page_index"]+1
            services.library.verify_anchor(anchor, page)
            for field, value in [("quote", "틀린 문장"), ("page_index", 0),
                                 ("version_id", "sha256:"+"0"*64), ("rects", [[1, 2, 3, 4]])]:
                bad = copy.deepcopy(anchor)
                bad[field] = value
                try:
                    services.library.verify_anchor(bad, page)
                except ValueError:
                    pass
                else:
                    raise AssertionError(f"Accepted invalid citation {field}")
        request = {"client_mutation_id": "00000000-0000-0000-0000-000000000088",
                   "message": "문서 근거로 설명해 주세요.",
                   "reader_context": {**fixture["reader_context"], "page_index": 0,
                                      "selection": None, "content_language": "en"},
                   "response_language": "ko"}
        for external, native in CAPABILITY_MAP.items():
            request["capability"] = external
            value = native_turn_request(request, material_id=manifest.material_id,
                                        material_revision=manifest.revision)
            assert value.capability == native and native in BUILTIN_CAPABILITY_CLASSES
            assert value.reply_language_override == "ko", (
                "native_turn_request must forward response_language independently: "
                f"expected reply_language_override='ko', got {value.reply_language_override!r}"
            )
            assert value.language == "en", (
                "native_turn_request must preserve reader_context.content_language "
                "separately from response_language: "
                f"content_language={request['reader_context']['content_language']!r}, "
                f"response_language={request['response_language']!r}, "
                f"expected language='en', got {value.language!r}"
            )
            assert value.reading_viewport.locator == request["reader_context"]["page_index"]+1
        raw = store.raw_path(manifest.material_id)
        assert raw is not None and hashlib.sha256(raw.read_bytes()).hexdigest() == original_hash
        async def durable_replay():
            db_path = Path(temp) / "turns.sqlite3"
            native_store = SQLiteSessionStore(db_path=db_path)
            session = await native_store.create_session(title="Synthetic fixture")
            turn = await native_store.begin_turn(session["session_id"], "immersive_reading")
            turn_id = turn["id"]
            assert turn_id.startswith("turn_")  # Native ID, not a UUID alias.
            frames = copy.deepcopy(fixture["wire"]["events"])
            for frame in frames:
                frame["turn_id"] = turn_id
                event = frame["metadata"].get("mnemosyne")
                if event is not None:
                    event["turn_id"] = turn_id
                    event["event_id"] = f'{turn_id}:{frame["seq"]}'
            await native_store.append_turn_events(turn_id, frames)
            await native_store.append_turn_events(turn_id, frames)
            reopened = SQLiteSessionStore(db_path=db_path)
            all_frames = await reopened.get_turn_events(turn_id)
            assert len(all_frames) == len(frames)
            replayed = await reopened.get_turn_events(turn_id, after_seq=6)
            assert [row["seq"] for row in replayed] == list(range(7, 13))
            for row in replayed:
                wire = StreamEvent.model_validate(row).model_dump(mode="json")
                event = semantic_event(wire)
                if event is not None:
                    assert event["event_id"] == f'{turn_id}:{row["seq"]}'
        asyncio.run(durable_replay())
    for key in ["events", "cancelled_events", "error_events"]:
        result = []
        for frame in fixture["wire"][key]:
            StreamEvent.model_validate(frame)
            e = semantic_event(frame)
            if e is not None:
                result.append(e)
        assert result == fixture[key]
    for command in fixture["wire"]["commands"]:
        TypeAdapter(ClientCommand).validate_python(command)
    for page in pages:
        g = page["geometry"]
        box = g["crop_box"]
        w, h = box[2]-box[0], box[3]-box[1]
        if g["rotation_degrees"] in (90, 270):
            w, h = h, w
        w *= g["user_unit"]
        h *= g["user_unit"]
        x, y, rw, rh = page["segments"][0]["rect"]
        points = [viewport_point([px, py], g) for px, py in [(x,y),(x+rw,y),(x,y+rh),(x+rw,y+rh)]]
        xs, ys = zip(*points)
        native = [min(xs)/w, min(ys)/h, max(xs)/w, max(ys)/h]
        canonical = normalized_rect_to_pdf(native, g)
        assert all(abs(a-b) < 1e-6 for a,b in zip(canonical, [x,y,rw,rh]))
    assert hashlib.sha256(pdf.read_bytes()).hexdigest() == original_hash
    fake_provider = check_fake_provider_stream()
    print(json.dumps({"result": "PASS", "consumer": "actual-source-adapters",
                      "pdf_pages": len(pages), "native_frames": len(fixture["wire"]["events"]),
                      "native_commands": len(fixture["wire"]["commands"]),
                      "sqlite_reopen_replay": True, "duplicate_append_creates_no_events": True,
                      "capability_mappings": len(CAPABILITY_MAP),
                      "fake_provider_stream": fake_provider, "product_ready": False}))


if __name__ == "__main__":
    run_integration_checks()
