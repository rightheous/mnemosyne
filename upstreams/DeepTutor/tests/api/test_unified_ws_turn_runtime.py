from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


async def _noop_async(*_args, **_kwargs):
    return None


def _fake_skill_service() -> SimpleNamespace:
    return SimpleNamespace(
        summary_entries=lambda: [],
        load_always_for_context=lambda: "",
        load_for_context=lambda _skills: "",
        list_skills=lambda: [],
    )


@pytest.fixture(autouse=True)
def _isolate_runtime_services(monkeypatch, tmp_path):
    from deeptutor.services.task_board import TaskBoardStore

    board = TaskBoardStore(tmp_path / "tasks.sqlite")
    monkeypatch.setattr(
        "deeptutor.services.task_board.get_task_board_store", lambda **_kwargs: board
    )
    # Runtime now resolves multiple skill libraries; these turn tests use an
    # empty catalog and must not inspect the developer's real skill folders.
    monkeypatch.setattr(
        "deeptutor.services.skill.runtime.skill_sources",
        lambda **kwargs: [(_fake_skill_service(), None, "account")],
    )
    # Title generation has its own tests. Fake turn providers must not start
    # an unrelated online LLM call after emitting their final stream event.
    monkeypatch.setattr(TurnRuntimeManager, "_maybe_generate_session_title", _noop_async)


def _fake_persona_service() -> SimpleNamespace:
    # Non-empty render so the resolved persona is recorded in the snapshot.
    return SimpleNamespace(
        load_for_context=lambda name: (
            f"## Active Persona\n### Persona: {name}\n\nbody" if name else ""
        )
    )


def _model_catalog() -> dict:
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "p-default",
                "active_model_id": "m-default",
                "profiles": [
                    {
                        "id": "p-default",
                        "name": "Default",
                        "binding": "openai",
                        "base_url": "https://api.openai.com/v1",
                        "api_key": "sk-test",
                        "models": [
                            {
                                "id": "m-default",
                                "name": "Default",
                                "model": "gpt-4o-mini",
                            }
                        ],
                    },
                    {
                        "id": "p-alt",
                        "name": "Alt",
                        "binding": "openrouter",
                        "base_url": "https://openrouter.ai/api/v1",
                        "api_key": "sk-alt",
                        "models": [
                            {
                                "id": "m-alt",
                                "name": "Alt Model",
                                "model": "anthropic/claude-sonnet-4",
                            }
                        ],
                    },
                ],
            }
        },
    }


@pytest.mark.parametrize(
    "consultation",
    [
        {},
        {"config": {"consult_partner_id": None, "partner_discussion_group_id": None}},
        {"consult_partner_id": "partner-1"},
        {"partner_discussion_group_id": "group-1"},
        {"config": {"consult_partner_id": "partner-1", "partner_discussion_group_id": None}},
        {"config": {"consult_partner_id": None, "partner_discussion_group_id": "group-1"}},
    ],
)
@pytest.mark.asyncio
async def test_turn_runtime_replays_events_and_materializes_messages(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    consultation,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    from deeptutor.services.task_board import CreateCard, UpdateCard, get_task_board_store

    board = get_task_board_store()
    assigned = board.create(CreateCard(title="Shared workspace task")).cards[-1]
    board.update(assigned.id, UpdateCard(workspace_id=""))
    linked = board.create(CreateCard(title="Conversation task")).cards[-1]
    requested = consultation.get("config", consultation)
    consultation = {
        **consultation,
        "config": {**consultation.get("config", {}), "linked_task_ids": [linked.id]},
    }
    captured: dict[str, object] = {}
    publish_order: list[str] = []
    original_publish = runtime._publish_live_event

    async def publish_with_status_capture(execution, event):
        publish_order.append(event.type.value)
        if event.type == StreamEventType.DONE:
            persisted_turn = await store.get_turn(execution.turn_id)
            captured["turn_status_when_done_published"] = (persisted_turn or {}).get("status")
        return await original_publish(execution, event)

    monkeypatch.setattr(runtime, "_publish_live_event", publish_with_status_capture)

    async def title_after_done(*_args, **_kwargs):
        captured["title_started_after_done"] = "done" in publish_order

    monkeypatch.setattr(runtime, "_maybe_generate_session_title", title_after_done)

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **kwargs):
            on_event = kwargs.get("on_event")
            if on_event is not None:
                await on_event(
                    StreamEvent(
                        type=StreamEventType.PROGRESS,
                        source="context",
                        stage="summarizing",
                        content="summarize context",
                    )
                )
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            captured["consult_partner_id"] = context.runtime.consult_partner_id
            captured["partner_discussion_group_id"] = context.runtime.partner_discussion_group_id
            assert "consult_partner_id" not in context.config_overrides
            assert "partner_discussion_group_id" not in context.config_overrides
            assert "linked_task_ids" not in context.config_overrides
            captured["user_message"] = context.user_message
            captured["response_language"] = context.language
            captured["content_language"] = context.content_language
            captured["metadata"] = context.metadata
            captured["config_overrides"] = context.config_overrides
            captured["source_manifest"] = context.source_manifest
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="Hello Frank",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.book.context.build_book_context",
        lambda *_args, **_kwargs: SimpleNamespace(
            text="## Page: Signal Basics\nA selected page.",
            references=[{"book_id": "book-1", "page_ids": ["page-1"]}],
            warnings=[],
        ),
    )
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "",
            emit=_noop_async,
        ),
    )
    monkeypatch.setattr(
        "deeptutor.services.skill.get_skill_service",
        _fake_skill_service,
    )
    monkeypatch.setattr(
        "deeptutor.services.persona.get_persona_service",
        _fake_persona_service,
    )

    session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "hello, i'm frank",
            "client_submission_id": "browser-submission-123",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "reply_language_override": "ko",
            "persona": "socratic",
            "memory_references": ["summary"],
            "book_references": [{"book_id": "book-1", "page_ids": ["page-1"]}],
            "mastery_path_id": "path-1",
            "mastery_answer": {"question_id": "question-1", "text": "B"},
            **consultation,
            "config": {
                **(consultation.get("config") or {}),
                "_mnemosyne_content_language": "en",
                "_mnemosyne_reader_context": {
                    "document_id": "00000000-0000-0000-0000-000000000002",
                    "version_id": "sha256:" + "a" * 64,
                    "page_index": 1,
                },
            },
        }
    )

    events = []
    async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
        events.append(event)

    # session_meta may arrive after `done` from the title generator —
    # filter it out so the timing race doesn't flake the assertion.
    assert [e["type"] for e in events if e["type"] != "session_meta"] == [
        "session",
        "tool_result",
        "content",
        "done",
    ]
    started_event = next(
        e for e in events if (e.get("metadata") or {}).get("mnemosyne", {}).get("type") == "turn.started"
    )
    assert started_event["metadata"]["mnemosyne"]["payload"] == {
        "capability": "chat",
        "response_language": "ko",
    }
    done_event = next(e for e in events if e["type"] == "done")
    assert done_event["metadata"]["status"] == "completed"
    assert captured["consult_partner_id"] == requested.get("consult_partner_id")
    assert captured["partner_discussion_group_id"] == requested.get("partner_discussion_group_id")
    assert captured["response_language"] == "ko"
    assert captured["content_language"] == "en"
    assert captured["metadata"]["mnemosyne_reader_context"] == {
        "document_id": "00000000-0000-0000-0000-000000000002",
        "version_id": "sha256:" + "a" * 64,
        "page_index": 1,
    }
    assert "_mnemosyne_reader_context" not in captured["config_overrides"]

    assert captured["turn_status_when_done_published"] == "completed"
    assert captured["title_started_after_done"] is True

    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    assert [message["role"] for message in detail["messages"]] == ["user", "assistant"]
    # DONE carries the persisted row ids so the frontend can reconcile its
    # optimistic negative ids in place instead of refetching the session.
    user_row, assistant_row = detail["messages"]
    assert done_event["metadata"]["user_message_id"] == user_row["id"]
    assert done_event["metadata"]["assistant_message_id"] == assistant_row["id"]
    assert user_row["metadata"]["client_submission_id"] == "browser-submission-123"
    assert user_row["metadata"]["turn_id"] == turn["id"]
    assert detail["messages"][0]["metadata"]["request_snapshot"]["persona"] == "socratic"
    assert detail["messages"][0]["metadata"]["request_snapshot"]["memoryReferences"] == ["summary"]
    assert detail["messages"][0]["metadata"]["request_snapshot"]["bookReferences"] == [
        {"book_id": "book-1", "page_ids": ["page-1"]}
    ]
    assert detail["messages"][0]["metadata"]["request_snapshot"]["masteryPathId"] == "path-1"
    assert detail["messages"][0]["metadata"]["request_snapshot"]["masteryAnswer"] == {
        "question_id": "question-1",
        "text": "B",
    }
    snapshot = detail["messages"][0]["metadata"]["request_snapshot"]
    assert snapshot.get("consultPartnerId") == requested.get("consult_partner_id")
    assert snapshot.get("partnerDiscussionGroupId") == requested.get("partner_discussion_group_id")

    # Chat capability now routes attached sources through the manifest +
    # ``read_source`` tool instead of inlining ``[Book Context]`` into the
    # user message. The raw user message stays raw; the book payload
    # surfaces in ``context.source_manifest`` and ``metadata.source_index``.
    assert str(captured["user_message"]) == "hello, i'm frank"
    manifest = str(captured.get("source_manifest") or "")
    assert "Shared workspace task" in manifest
    assert "Conversation task" in manifest
    assert board.read().session_links[0].task_ids == [linked.id]
    assert "[Attached Sources]" in manifest
    # Book source id is now per-book (``bk-{book_id}``) so multi-book
    # sessions can read_source each independently. The mocked book has id
    # "book-1".
    assert "bk-book-1" in manifest
    source_index = (captured.get("metadata") or {}).get("source_index") or {}
    assert "bk-book-1" in source_index
    assert "A selected page." in source_index["bk-book-1"]
    assert captured["metadata"] and captured["metadata"]["book_references"] == [
        {"book_id": "book-1", "page_ids": ["page-1"]}
    ]
    assert captured["metadata"]["mastery_path_id"] == "path-1"
    assert detail["messages"][1]["content"] == "Hello Frank"
    assert detail["preferences"] == {
        "capability": "chat",
        "tools": [],
        "knowledge_bases": [],
        "language": "ko",
        "reply_language_override": "ko",
        # Explicit persona in the payload is persisted as a session-level
        # preference (survives reloads; later turns fall back to it).
        "persona": "socratic",
        "mastery_path_id": "path-1",
        "workspace_id": None,
        # No mode is persisted here: this turn never recorded one, and an
        # unrecorded mode has to stay unrecorded — the tools read its absence
        # as "enforce nothing", which is what keeps every conversation that
        # predates modes working exactly as it did.
    }

    persisted_turn = await store.get_turn(turn["id"])
    assert persisted_turn is not None
    assert persisted_turn["status"] == "completed"
    persisted_events = await store.get_turn_events(turn["id"])
    persisted_done = next(event for event in persisted_events if event["type"] == "done")
    assert persisted_done["seq"] > 0
    assert persisted_done["metadata"]["assistant_message_id"] == assistant_row["id"]

    if requested.get("consult_partner_id") or requested.get("partner_discussion_group_id"):
        captured.pop("consult_partner_id", None)
        captured.pop("partner_discussion_group_id", None)
        _, retried = await runtime.regenerate_last_turn(session["id"])
        retry_events = [event async for event in runtime.subscribe_turn(retried["id"], after_seq=0)]
        assert not [event for event in retry_events if event["type"] == "error"]
        assert captured["consult_partner_id"] == requested.get("consult_partner_id")
        assert captured["partner_discussion_group_id"] == requested.get(
            "partner_discussion_group_id"
        )

    # A fresh runtime (the reconnect/restart shape) replays the committed DONE
    # instead of synthesizing a metadata-poor terminal event.
    replay_runtime = TurnRuntimeManager(store)
    replayed = [event async for event in replay_runtime.subscribe_turn(turn["id"])]
    replayed_done = next(event for event in replayed if event["type"] == "done")
    assert replayed_done["seq"] == persisted_done["seq"]
    assert replayed_done["metadata"]["assistant_message_id"] == assistant_row["id"]


@pytest.mark.asyncio
async def test_turn_runtime_persists_private_provider_response_state(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    captured: dict[str, object] = {}
    state = {"reasoning_content": "private reasoning"}

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **_kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            captured["metadata"] = context.metadata
            context.runtime.provider_response_state = state
            context.runtime.model_turn = {
                "version": 1,
                "messages": [
                    {"role": "user", "content": "prepared input"},
                    {"role": "assistant", "content": "raw model answer"},
                ],
            }
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="A direct answer",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    async def title_after_done(*_args, **_kwargs):
        return None

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(runtime, "_maybe_generate_session_title", title_after_done)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_l3_concat=lambda: "", emit=_noop_async),
    )
    monkeypatch.setattr(
        "deeptutor.services.skill.get_skill_service",
        _fake_skill_service,
    )
    monkeypatch.setattr(
        "deeptutor.services.persona.get_persona_service",
        _fake_persona_service,
    )

    session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "hello",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {},
        }
    )
    async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
        pass

    context_messages = await store.get_messages_for_context(session["id"])
    assistant = context_messages[-1]
    assert assistant["metadata"]["provider_response_state"] == state
    assert assistant["metadata"]["model_turn"]["messages"][0]["content"] == "prepared input"
    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    assert "provider_response_state" not in detail["messages"][-1]["metadata"]
    assert "model_turn" not in detail["messages"][-1]["metadata"]
    metadata = captured["metadata"]
    assert isinstance(metadata, dict)
    assert "_provider_response_state" not in metadata


@pytest.mark.asyncio
async def test_turn_runtime_persists_llm_selection_in_turn_snapshot(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    captured: dict[str, object] = {}

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **kwargs):
            captured["builder_llm_config"] = kwargs["llm_config"]
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            captured["metadata"] = context.metadata
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="Alt reply",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    def fake_activate(selection):
        captured["activated_selection"] = selection
        return SimpleNamespace(
            model="anthropic/claude-sonnet-4", provider_name="openrouter"
        ), object()

    monkeypatch.setattr(
        "deeptutor.services.config.get_model_catalog_service",
        lambda: SimpleNamespace(load=_model_catalog),
    )
    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.activate_llm_selection",
        fake_activate,
    )
    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.reset_llm_selection",
        lambda _token: captured.setdefault("reset_called", True),
    )
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "",
            emit=_noop_async,
        ),
    )
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)

    selection = {"profile_id": "p-alt", "model_id": "m-alt"}
    session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "use the alt model",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {},
            "llm_selection": selection,
        }
    )

    execution = runtime._executions[turn["id"]]
    assert execution.task is not None
    async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
        pass
    # A replay subscriber can observe DONE before the runner's finally block.
    # Model-scope reset is an execution cleanup assertion, not a stream one.
    await asyncio.wait_for(execution.task, timeout=5)

    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    assert detail["preferences"]["llm_selection"] == selection
    assert detail["messages"][0]["metadata"]["request_snapshot"]["llmSelection"] == selection
    assert captured["activated_selection"] == selection
    assert captured["builder_llm_config"].model == "anthropic/claude-sonnet-4"
    assert captured["metadata"]["llm_selection"] == selection
    assert captured["metadata"]["llm_model"] == "anthropic/claude-sonnet-4"
    assert captured["metadata"]["llm_provider"] == "openrouter"
    assert captured["reset_called"] is True


@pytest.mark.asyncio
async def test_turn_runtime_session_persona_persists_falls_back_and_clears(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """Persona is a session preference: explicit key persists (incl. ""),
    absent key falls back to the stored preference."""
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **_kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="ok",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_l3_concat=lambda: "", emit=_noop_async),
    )
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)

    async def run_turn(session_id, extra):
        session, turn = await runtime.start_turn(
            {
                "type": "start_turn",
                "content": "hi",
                "session_id": session_id,
                "capability": None,
                "tools": [],
                "knowledge_bases": [],
                "attachments": [],
                "language": "en",
                "config": {},
                **extra,
            }
        )
        async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
            pass
        return session

    # Turn 1 — explicit persona: applied to the turn AND persisted.
    session = await run_turn(None, {"persona": "socratic"})
    detail = await store.get_session_with_messages(session["id"])
    assert detail["preferences"]["persona"] == "socratic"
    assert detail["messages"][0]["metadata"]["request_snapshot"]["persona"] == "socratic"

    # Turn 2 — persona key ABSENT: falls back to the stored preference, so
    # the persona keeps applying to follow-up questions in the session.
    await run_turn(session["id"], {})
    detail = await store.get_session_with_messages(session["id"])
    assert detail["preferences"]["persona"] == "socratic"
    assert detail["messages"][2]["metadata"]["request_snapshot"]["persona"] == "socratic"

    # Turn 3 — explicit "" (Default): clears the stored preference and the
    # turn runs without a persona.
    await run_turn(session["id"], {"persona": ""})
    detail = await store.get_session_with_messages(session["id"])
    assert detail["preferences"]["persona"] == ""
    cleared_snapshot = detail["messages"][4]["metadata"]["request_snapshot"]
    assert cleared_snapshot["persona"] == ""
    assert cleared_snapshot["config"] == {}
    assert cleared_snapshot["enabledTools"] == []
    assert cleared_snapshot["knowledgeBases"] == []
    assert cleared_snapshot["memoryReferences"] == []


@pytest.mark.asyncio
async def test_turn_runtime_rejects_invalid_llm_selection(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    monkeypatch.setattr(
        "deeptutor.services.config.get_model_catalog_service",
        lambda: SimpleNamespace(load=_model_catalog),
    )

    with pytest.raises(RuntimeError, match="Invalid LLM selection"):
        await runtime.start_turn(
            {
                "type": "start_turn",
                "content": "bad model",
                "session_id": None,
                "capability": None,
                "tools": [],
                "knowledge_bases": [],
                "attachments": [],
                "language": "en",
                "config": {},
                "llm_selection": {"profile_id": "p-alt", "model_id": "m-default"},
            }
        )


@pytest.mark.asyncio
async def test_turn_runtime_allows_model_switching_within_same_session(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    activated: list[dict] = []
    metadata_seen: list[dict] = []

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **_kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            metadata_seen.append(context.metadata)
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content=f"Reply from {context.metadata['llm_model']}",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    def fake_activate(selection):
        activated.append(dict(selection or {}))
        is_alt = (selection or {}).get("profile_id") == "p-alt"
        return (
            SimpleNamespace(
                model="anthropic/claude-sonnet-4" if is_alt else "gpt-4o-mini",
                provider_name="openrouter" if is_alt else "openai",
            ),
            object(),
        )

    monkeypatch.setattr(
        "deeptutor.services.config.get_model_catalog_service",
        lambda: SimpleNamespace(load=_model_catalog),
    )
    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.activate_llm_selection",
        fake_activate,
    )
    monkeypatch.setattr(
        "deeptutor.services.model_selection.runtime.reset_llm_selection",
        lambda _token: None,
    )
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "",
            emit=_noop_async,
        ),
    )
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)

    first_selection = {"profile_id": "p-default", "model_id": "m-default"}
    second_selection = {"profile_id": "p-alt", "model_id": "m-alt"}

    session, first_turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "first model",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {},
            "llm_selection": first_selection,
        }
    )
    async for _event in runtime.subscribe_turn(first_turn["id"], after_seq=0):
        pass

    same_session, second_turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "second model",
            "session_id": session["id"],
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {},
            "llm_selection": second_selection,
        }
    )
    async for _event in runtime.subscribe_turn(second_turn["id"], after_seq=0):
        pass

    detail = await store.get_session_with_messages(session["id"])
    assert same_session["id"] == session["id"]
    assert detail is not None
    assert detail["preferences"]["llm_selection"] == second_selection
    assert activated == [first_selection, second_selection]
    assert metadata_seen[0]["llm_model"] == "gpt-4o-mini"
    assert metadata_seen[1]["llm_model"] == "anthropic/claude-sonnet-4"
    user_messages = [message for message in detail["messages"] if message["role"] == "user"]
    assert user_messages[0]["metadata"]["request_snapshot"]["llmSelection"] == first_selection
    assert user_messages[1]["metadata"]["request_snapshot"]["llmSelection"] == second_selection


@pytest.mark.asyncio
async def test_regenerate_reuses_snapshot_or_override_llm_selection(tmp_path) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    captured_payloads: list[dict] = []

    class CapturingRuntime(TurnRuntimeManager):
        async def start_turn(self, payload: dict):
            captured_payloads.append(payload)
            return {"id": payload["session_id"]}, {"id": "turn-test"}

    runtime = CapturingRuntime(store)
    session = await store.create_session(session_id="session-with-snapshot")
    await store.update_session_preferences(
        session["id"],
        {"llm_selection": {"profile_id": "p-default", "model_id": "m-default"}},
    )
    await store.add_message(
        session_id=session["id"],
        role="user",
        content="again",
        capability="chat",
        metadata={
            "request_snapshot": {
                "content": "again",
                "llmSelection": {"profile_id": "p-alt", "model_id": "m-alt"},
                "masteryAnswer": {"question_id": "question-1", "text": "B"},
            }
        },
    )

    await runtime.regenerate_last_turn(session["id"])
    assert captured_payloads[-1]["llm_selection"] == {
        "profile_id": "p-alt",
        "model_id": "m-alt",
    }

    await runtime.regenerate_last_turn(session["id"], overrides={"replay_snapshot": True})
    assert captured_payloads[-1]["mastery_answer"] == {"question_id": "question-1", "text": "B"}

    await runtime.regenerate_last_turn(
        session["id"],
        overrides={"llm_selection": {"profile_id": "p-default", "model_id": "m-default"}},
    )
    assert captured_payloads[-1]["llm_selection"] == {
        "profile_id": "p-default",
        "model_id": "m-default",
    }


@pytest.mark.asyncio
async def test_turn_runtime_bootstraps_question_followup_context_once(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    captured: dict[str, object] = {}

    class FakeContextBuilder:
        def __init__(self, session_store, *_args, **_kwargs) -> None:
            self.store = session_store

        async def build(self, **kwargs):
            messages = await self.store.get_messages_for_context(kwargs["session_id"])
            captured["history_messages"] = messages
            return SimpleNamespace(
                conversation_history=[
                    {"role": item["role"], "content": item["content"]} for item in messages
                ],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            captured["conversation_history"] = context.conversation_history
            captured["config_overrides"] = context.config_overrides
            captured["metadata"] = context.metadata
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="Let's discuss this question.",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "",
            emit=_noop_async,
        ),
    )
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)

    session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "Why is my answer wrong?",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {
                "followup_question_context": {
                    "parent_quiz_session_id": "quiz_session_1",
                    "question_id": "q_2",
                    "question_type": "choice",
                    "difficulty": "hard",
                    "concentration": "win-rate comparison",
                    "question": "Which criterion best describes density?",
                    "options": {
                        "A": "Coverage",
                        "B": "Informative value",
                        "C": "Relevant content without redundancy",
                        "D": "Credibility",
                    },
                    "user_answer": "B",
                    "correct_answer": "C",
                    "explanation": "Density focuses on including relevant content without redundancy.",
                    "knowledge_context": "Density measures whether content is relevant and non-redundant.",
                }
            },
        }
    )

    events = []
    async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
        events.append(event)

    # session_meta may arrive after `done` from the title generator —
    # filter it out so the timing race doesn't flake the assertion.
    assert [e["type"] for e in events if e["type"] != "session_meta"] == [
        "session",
        "tool_result",
        "content",
        "done",
    ]
    started_event = next(
        e for e in events if (e.get("metadata") or {}).get("mnemosyne", {}).get("type") == "turn.started"
    )
    assert started_event["metadata"]["mnemosyne"]["payload"]["capability"] == "chat"
    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    assert [message["role"] for message in detail["messages"]] == ["system", "user", "assistant"]
    assert "Question Follow-up Context" in detail["messages"][0]["content"]
    assert "Which criterion best describes density?" in detail["messages"][0]["content"]
    assert "User answer: B" in detail["messages"][0]["content"]
    assert captured["conversation_history"][0]["role"] == "system"
    assert "followup_question_context" not in captured["config_overrides"]
    assert captured["metadata"]["question_followup_context"]["question_id"] == "q_2"


@pytest.mark.asyncio
async def test_turn_runtime_rejects_deep_research_without_explicit_config(
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)

    with pytest.raises(RuntimeError, match="Invalid deep research config"):
        await runtime.start_turn(
            {
                "type": "start_turn",
                "content": "research transformers",
                "session_id": None,
                "capability": "deep_research",
                "tools": ["rag"],
                "knowledge_bases": ["research-kb"],
                "attachments": [],
                "language": "en",
                "config": {},
            }
        )


@pytest.mark.asyncio
async def test_turn_runtime_persists_deep_research_session_preference(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **_kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, _context):
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="deep_research",
                stage="reporting",
                content="Research report ready.",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="deep_research")

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "",
            emit=_noop_async,
        ),
    )
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)

    session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "research transformers",
            "session_id": None,
            "capability": "deep_research",
            "tools": ["rag", "web_search"],
            "knowledge_bases": ["research-kb"],
            "attachments": [],
            "language": "en",
            "config": {
                "mode": "report",
                "depth": "standard",
            },
        }
    )

    events = []
    async for event in runtime.subscribe_turn(turn["id"], after_seq=0):
        events.append(event)

    # session_meta may arrive after `done` from the title generator —
    # filter it out so the timing race doesn't flake the assertion.
    assert [e["type"] for e in events if e["type"] != "session_meta"] == [
        "session",
        "content",
        "done",
    ]
    detail = await store.get_session_with_messages(session["id"])
    assert detail is not None
    assert detail["preferences"]["capability"] == "deep_research"
    assert detail["preferences"]["tools"] == ["rag", "web_search"]


@pytest.mark.asyncio
async def test_turn_runtime_injects_memory_and_refreshes_after_completion(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    captured: dict[str, object] = {}

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **_kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="Recent chat summary",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            captured["conversation_history"] = context.conversation_history
            captured["memory_context"] = context.memory_context
            captured["learning_journal_context"] = context.learning_journal_context
            captured["conversation_context_text"] = context.metadata.get(
                "conversation_context_text"
            )
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="Stored reply",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    emit_calls: list[object] = []

    async def fake_emit(event):
        emit_calls.append(event)
        return None

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(
            read_l3_concat=lambda: "## Memory\n## Preferences\n- Prefer concise answers.",
            emit=fake_emit,
        ),
    )
    monkeypatch.setattr(
        "deeptutor.services.learning_journal.get_learning_journal_store",
        lambda: SimpleNamespace(
            injection_markdown=lambda: "# Learning journal\n## Mission\n- Topic: FFT",
        ),
    )
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)

    _session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "hello, i'm frank",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "memory_references": ["preferences"],
            "language": "en",
            "config": {},
        }
    )

    async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
        pass

    assert captured["memory_context"] == "## Memory\n## Preferences\n- Prefer concise answers."
    assert captured["learning_journal_context"] == ("# Learning journal\n## Mission\n- Topic: FFT")
    assert captured["conversation_history"] == []
    assert captured["conversation_context_text"] == "Recent chat summary"


@pytest.mark.asyncio
async def test_a_null_mode_on_the_wire_keeps_the_conversation_in_the_mode_it_was_in(
    tmp_path, monkeypatch
):
    """The client writes ``mastery_session_mode`` on every turn and leaves it
    null whenever it does not happen to hold the mode in memory — a reload, or
    a session loaded from the server before its preference came back.

    Reading that null as "the client said none" threw the mode away, so the
    tutor was told it was studying while the learner watched the outline mode
    highlighted above the transcript — and never switched, because it believed
    it already had.
    """
    from deeptutor.capabilities.mastery.mode import enforced_mode

    # The resolution the preparer performs, isolated: payload first, stored
    # preference when the payload said nothing.
    def resolve(payload_value, stored):
        return enforced_mode(payload_value or stored)

    assert resolve("outline", None) == "outline"
    assert resolve(None, "outline") == "outline"
    assert resolve("", "outline") == "outline"
    # An explicit switch still wins over what was stored.
    assert resolve("review", "outline") == "review"
    # And a conversation that has never had one stays unrecorded.
    assert resolve(None, None) is None


@pytest.mark.asyncio
async def test_prior_image_attachments_are_reattached_on_the_next_turn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """An image attached in turn 1 must still reach a vision model on turn 2.

    Multimodal blocks exist only on the upload turn and the source manifest
    deliberately excludes images, so without re-attachment the model loses
    the image entirely and asks the learner to resend it (#1438). The
    executor re-attaches the conversation's earlier images (URL-only; the
    multimodal layer resolves the bytes from the attachment store), and the
    new message row must not duplicate them.
    """
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    captured: list[list[SimpleNamespace]] = []

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            captured.append(list(context.attachments or []))
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="ok",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.book.context.build_book_context",
        lambda *_args, **_kwargs: SimpleNamespace(text="", references=[], warnings=[]),
    )
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_l3_concat=lambda: "", emit=_noop_async),
    )
    monkeypatch.setattr(
        "deeptutor.services.skill.get_skill_service",
        _fake_skill_service,
    )
    monkeypatch.setattr(
        "deeptutor.services.persona.get_persona_service",
        _fake_persona_service,
    )

    image_attachment = {
        "type": "image",
        "url": "/files/attachments/s1/img-1/shot.png",
        "filename": "shot.png",
        "mime_type": "image/png",
        "base64": "",
    }

    session, turn1 = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "what is in this picture?",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [image_attachment],
            "language": "en",
            "config": {},
        }
    )
    async for _event in runtime.subscribe_turn(turn1["id"], after_seq=0):
        pass

    _session2, turn2 = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "and the top left corner?",
            "session_id": session["id"],
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {},
        }
    )
    async for _event in runtime.subscribe_turn(turn2["id"], after_seq=0):
        pass

    assert [att.url for att in captured[0]] == [image_attachment["url"]]
    # Turn 2 carries no payload attachment, yet the conversation's earlier
    # image is re-attached for the model. (The payload contract has no
    # attachment id, so the URL is the stable identity across turns.)
    assert len(captured[1]) == 1
    reattached = captured[1][0]
    assert reattached.base64 == ""
    assert reattached.url == image_attachment["url"]

    # The turn-2 message row must not duplicate the attachment: the image
    # belongs to turn 1's row and the re-attachment is per-turn context only.
    rows = await store.get_messages(session["id"])
    user_rows = [m for m in rows if m.get("role") == "user"]
    assert user_rows[-1].get("attachments") == []


@pytest.mark.asyncio
async def test_reattaching_the_same_image_does_not_duplicate_it(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    captured: list[list[SimpleNamespace]] = []

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            captured.append(list(context.attachments or []))
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.book.context.build_book_context",
        lambda *_args, **_kwargs: SimpleNamespace(text="", references=[], warnings=[]),
    )
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_l3_concat=lambda: "", emit=_noop_async),
    )
    monkeypatch.setattr(
        "deeptutor.services.skill.get_skill_service",
        _fake_skill_service,
    )
    monkeypatch.setattr(
        "deeptutor.services.persona.get_persona_service",
        _fake_persona_service,
    )

    image_attachment = {
        "type": "image",
        "url": "/files/attachments/s1/img-1/shot.png",
        "filename": "shot.png",
        "mime_type": "image/png",
        "base64": "",
    }
    session, turn1 = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "look",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [image_attachment],
            "language": "en",
            "config": {},
        }
    )
    async for _event in runtime.subscribe_turn(turn1["id"], after_seq=0):
        pass

    _session2, turn2 = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "look again",
            "session_id": session["id"],
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [image_attachment],
            "language": "en",
            "config": {},
        }
    )
    async for _event in runtime.subscribe_turn(turn2["id"], after_seq=0):
        pass

    # The same file re-attached in turn 2 must not appear twice: the fresh
    # record and the re-attached prior entry share one URL, and the URL is
    # the dedupe key.
    assert [att.url for att in captured[1]] == [image_attachment["url"]]


@pytest.mark.asyncio
async def test_selection_tutoring_never_mounts_the_learning_journal(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    """A selected-text question must not inherit a carried-over study mission (#740).

    The journal snapshot is a standing part of the system prompt, so a sidebar
    question about one passage would otherwise answer *as if* it knew what the
    learner is studying. Memory avoids this by only reading what the client
    asks for; the journal has no such client input, so it needs its own guard.
    Asserting the store is never consulted pins that guard, rather than a
    snapshot that merely happens to be empty.
    """
    store = SQLiteSessionStore(tmp_path / "chat_history.db")
    runtime = TurnRuntimeManager(store)
    captured: dict[str, object] = {}
    journal_reads: list[str] = []

    class FakeContextBuilder:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def build(self, **_kwargs):
            return SimpleNamespace(
                conversation_history=[],
                conversation_summary="",
                context_text="",
                token_count=0,
                budget=0,
            )

    class FakeOrchestrator:
        async def handle(self, context):
            captured["learning_journal_context"] = context.learning_journal_context
            yield StreamEvent(
                type=StreamEventType.CONTENT,
                source="chat",
                stage="responding",
                content="It forks the process.",
                metadata={"call_kind": "llm_final_response"},
            )
            yield StreamEvent(type=StreamEventType.DONE, source="chat")

    class FakeJournalStore:
        def injection_markdown(self) -> str:
            journal_reads.append("consulted")
            return "# Learning journal\n## Mission\n- Topic: FFT"

    monkeypatch.setattr("deeptutor.services.llm.config.get_llm_config", lambda: SimpleNamespace())
    monkeypatch.setattr(
        "deeptutor.services.session.context_builder.ContextBuilder", FakeContextBuilder
    )
    monkeypatch.setattr("deeptutor.runtime.orchestrator.ChatOrchestrator", FakeOrchestrator)
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_l3_concat=lambda: "## Preferences\n- Concise.", emit=None),
    )
    monkeypatch.setattr(
        "deeptutor.services.learning_journal.get_learning_journal_store",
        lambda: FakeJournalStore(),
    )
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", _fake_skill_service)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", _fake_persona_service)

    _session, turn = await runtime.start_turn(
        {
            "type": "start_turn",
            "content": "what does this line mean?",
            "session_id": None,
            "capability": None,
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            # Deliberately still requested: the client opting into memory must
            # not be what keeps the journal out of a selection turn.
            "memory_references": ["preferences"],
            "language": "en",
            "config": {},
            "selection_tutor_context": {
                "selected_text": "fork() returns in two processes.",
                "source_message_text": "In Unix, fork() returns in two processes.",
                "source_message_role": "assistant",
            },
        }
    )

    async for _event in runtime.subscribe_turn(turn["id"], after_seq=0):
        pass

    assert captured["learning_journal_context"] == ""
    assert journal_reads == []


def _mnemosyne_turn_request(**overrides):
    from uuid import UUID

    payload = {
        "client_mutation_id": str(UUID(int=1)),
        "capability": "reading",
        "message": "이 문단을 설명해 줘",
        "response_language": "ko",
        "reader_context": {
            "document_id": str(UUID(int=2)),
            "version_id": "sha256:" + "a" * 64,
            "page_index": 1,
            "viewport_rect": [0, 0, 100, 100],
            "selection": {
                "document_id": str(UUID(int=2)),
                "version_id": "sha256:" + "a" * 64,
                "page_index": 1,
                "parse_revision": "pymupdf-test",
                "text_sha256": "b" * 64,
                "start_scalar": 0,
                "end_scalar": 12,
                "quote": "client quote",
                "rects": [[1, 1, 10, 10]],
            },
            "content_language": "en",
            "response_language": "ko",
        },
    }
    payload.update(overrides)
    return payload


def test_mnemosyne_turn_mapping_uses_response_language_and_drops_unverified_selection():
    from deeptutor.mnemosyne.tutor import native_turn_request

    request = native_turn_request(
        _mnemosyne_turn_request(), material_id="abcdef12", material_revision=3
    )

    assert request.capability == "immersive_reading"
    assert request.language == "en"
    assert request.reply_language_override == "ko"
    assert request.config["_mnemosyne_content_language"] == "en"
    assert request.config["_mnemosyne_reader_context"] == {
        "document_id": "00000000-0000-0000-0000-000000000002",
        "version_id": "sha256:" + "a" * 64,
        "page_index": 1,
    }
    assert request.reading_material_id == "abcdef12"
    assert request.reading_material_revision == 3
    assert request.reading_viewport.model_dump() == {"locator": 2, "selection": None}
    assert request.skills == ["__mnemosyne_disabled__"]
    assert request.mcp == ["__mnemosyne_disabled__"]


@pytest.mark.asyncio
async def test_mnemosyne_reader_tools_emit_verified_events_and_confirmation_drafts(monkeypatch):
    from deeptutor.capabilities.reading.capability import ReadingCapability
    import deeptutor.capabilities.reading.tools as reading_tools
    from deeptutor.capabilities.reading.tools import ReaderAnnotateTool, ReaderGotoTool
    from deeptutor.core.context import UnifiedContext
    import deeptutor.reading

    reader_context = {
        "document_id": "00000000-0000-0000-0000-000000000002",
        "version_id": "sha256:" + "a" * 64,
        "page_index": 1,
    }
    anchor = {
        **reader_context,
        "parse_revision": "pymupdf-test",
        "text_sha256": "b" * 64,
        "start_scalar": 0,
        "end_scalar": 12,
        "quote": "source quote",
        "rects": [[10, 20, 30, 8]],
    }
    citation = {
        "citation_id": "00000000-0000-0000-0000-000000000003",
        "verification_id": "00000000-0000-0000-0000-000000000004",
        "verified": True,
        "anchor": anchor,
    }
    store = SimpleNamespace(
        manifest=lambda _material_id: SimpleNamespace(unit_count=5, unit="page", revision=7),
        save_annotation=lambda *_args: (_ for _ in ()).throw(
            AssertionError("Mnemosyne annotations require confirmation")
        ),
    )
    monkeypatch.setattr(ReaderGotoTool, "_store", staticmethod(lambda: store))
    monkeypatch.setattr(ReaderAnnotateTool, "_store", staticmethod(lambda: store))
    monkeypatch.setattr(
        "deeptutor.multi_user.learning_access.assert_learning_material", lambda _material_id: None
    )
    monkeypatch.setattr(
        deeptutor.reading,
        "verify_quote",
        lambda *_args: SimpleNamespace(verified=True, found_locator=2),
    )
    monkeypatch.setattr(deeptutor.reading, "unit_timestamps", lambda *_args: {})
    monkeypatch.setattr(
        reading_tools,
        "_verified_mnemosyne_citation",
        lambda *_args: citation,
    )
    context = UnifiedContext(
        user_message="이 문단을 형광펜으로 표시해 줘.",
        metadata={
            "reading_material_id": "abcdef12",
            "mnemosyne_reader_context": reader_context,
        },
    )
    goto_kwargs = ReadingCapability().augment_kwargs(
        "reader_goto", {"locator": 2, "quote": "source quote"}, context
    )
    annotate_kwargs = ReadingCapability().augment_kwargs(
        "reader_annotate",
        {"locator": 2, "quote": "source quote", "note": "복습할 개념"},
        context,
    )

    goto = await ReaderGotoTool().execute(**goto_kwargs)
    annotate = await ReaderAnnotateTool().execute(**annotate_kwargs)

    goto_events = goto.metadata["_mnemosyne_semantics"]
    assert [event["type"] for event in goto_events] == [
        "citation.verified",
        "reader.goto",
        "reader.highlight",
    ]
    assert goto_events[0]["payload"]["citation"]["verified"] is True
    assert goto_events[1]["payload"]["position"] == [10, 20]
    assert goto_events[2]["payload"]["persistent"] is False
    proposals = annotate.metadata["_mnemosyne_semantics"]
    assert proposals[0]["type"] == "citation.verified"
    annotations = proposals[1:]
    assert len(annotations) == 2
    assert all(event["payload"]["requires_confirmation"] is True for event in annotations)
    assert [event["payload"]["annotation"]["kind"] for event in annotations] == [
        "highlight",
        "note",
    ]


def test_reader_capability_only_injects_server_context_for_reader_tools():
    from deeptutor.capabilities.reading.capability import ReadingCapability
    from deeptutor.core.context import UnifiedContext

    reader_context = {
        "document_id": "00000000-0000-0000-0000-000000000002",
        "version_id": "sha256:" + "a" * 64,
        "page_index": 1,
    }
    context = UnifiedContext(
        user_message="설명해 줘",
        metadata={
            "reading_material_id": "abcdef12",
            "mnemosyne_reader_context": reader_context,
        },
    )
    capability = ReadingCapability()

    goto = capability.augment_kwargs("reader_goto", {"locator": 2}, context)
    read = capability.augment_kwargs("read_material", {"locator": 2}, context)

    assert goto["_mnemosyne_reader_context"] == reader_context
    assert "_mnemosyne_reader_context" not in read


def test_verified_mnemosyne_reader_citation_binds_source_bytes_and_geometry(monkeypatch, tmp_path):
    import hashlib

    from deeptutor.capabilities.reading._tool_base import _verified_mnemosyne_citation

    source = b"fixture PDF source bytes"
    source_path = tmp_path / "source.pdf"
    source_path.write_bytes(source)
    text = "Intro exact source quote footer"
    start = text.index("exact source quote")
    anchor_page = {
        "document_id": "00000000-0000-0000-0000-000000000002",
        "version_id": "sha256:" + hashlib.sha256(source).hexdigest(),
        "page_index": 1,
        "parse_revision": "pymupdf-test",
        "text_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "text": text,
        "segments": [
            {
                "start_scalar": 0,
                "end_scalar": len(text),
                "rect": [10, 20, 30, 8],
            }
        ],
    }
    verified: dict[str, object] = {}

    class FakeLibrary:
        def __init__(self, _store):
            pass

        def get_document(self, document_id, version_id):
            return {
                "document_id": document_id,
                "version_id": version_id,
                "source_sha256": hashlib.sha256(source).hexdigest(),
                "parse_state": "ready",
                "original_available": True,
            }

        def download_original(self, _document_id, _version_id):
            return source

        def get_page(self, _document_id, _version_id, _page_index):
            return anchor_page

        def verify_citation(self, anchor):
            verified["anchor"] = anchor
            return {
                "citation_id": "00000000-0000-0000-0000-000000000003",
                "verification_id": "00000000-0000-0000-0000-000000000004",
                "verified": True,
                "anchor": anchor,
            }

    monkeypatch.setattr("deeptutor.mnemosyne.library.LibraryAdapter", FakeLibrary)
    store = SimpleNamespace(raw_path=lambda _material_id: source_path)
    context = {
        "document_id": anchor_page["document_id"],
        "version_id": anchor_page["version_id"],
        "page_index": 0,
    }

    citation = _verified_mnemosyne_citation(
        store, "abcdef12", 2, "exact source quote", context
    )

    assert citation["verified"] is True
    assert verified["anchor"]["start_scalar"] == start
    assert verified["anchor"]["end_scalar"] == start + len("exact source quote")
    assert verified["anchor"]["quote"] == "exact source quote"
    assert verified["anchor"]["rects"] == [[10, 20, 30, 8]]

    source_path.write_bytes(b"different source")
    with pytest.raises(ValueError, match="does not match"):
        _verified_mnemosyne_citation(store, "abcdef12", 2, "exact source quote", context)


def test_mnemosyne_turn_mapping_rejects_invalid_identity_and_version():
    from deeptutor.mnemosyne.tutor import native_turn_request

    invalid_id = _mnemosyne_turn_request(client_mutation_id="not-a-uuid")
    with pytest.raises(ValueError, match="client_mutation_id must be a UUID"):
        native_turn_request(invalid_id, material_id="abcdef12", material_revision=1)

    invalid_version = _mnemosyne_turn_request()
    invalid_version["reader_context"]["version_id"] = "sha256:short"
    with pytest.raises(ValueError, match="full SHA-256"):
        native_turn_request(invalid_version, material_id="abcdef12", material_revision=1)

    invalid_language = _mnemosyne_turn_request()
    invalid_language["reader_context"]["content_language"] = "English label"
    with pytest.raises(ValueError, match="content_language"):
        native_turn_request(invalid_language, material_id="abcdef12", material_revision=1)


@pytest.mark.asyncio
async def test_tutor_adapter_delegates_start_resume_and_idempotent_cancel_to_native_turns():
    from deeptutor.mnemosyne.tutor import TutorAdapter

    class FakeTurns:
        def __init__(self):
            self.started = None
            self.subscription = None
            self.cancelled = None

        async def start_turn(self, request):
            self.started = request
            return ({"id": "session_1"}, {"id": "turn_1"})

        async def subscribe_turn(self, turn_id, after_seq=0):
            self.subscription = (turn_id, after_seq)
            yield {"type": "content", "turn_id": turn_id, "seq": after_seq + 1}

        async def cancel_turn(self, turn_id, *, command_id=None):
            self.cancelled = (turn_id, command_id)
            return True

    turns = FakeTurns()
    adapter = TutorAdapter(turns, SimpleNamespace(annotation_sync=object()), None)
    receipt = await adapter.start_turn(
        {
            "client_mutation_id": "00000000-0000-0000-0000-000000000001",
            "capability": "chat",
            "message": "설명해 줘",
        }
    )
    resumed = [frame async for frame in adapter.resume_turn("turn_1", 7)]
    cancelled = await adapter.cancel_turn(
        "turn_1", "00000000-0000-0000-0000-000000000002"
    )

    assert receipt[1]["id"] == "turn_1"
    assert turns.started.language == "ko"
    assert turns.subscription == ("turn_1", 7)
    assert resumed[0]["seq"] == 8
    assert cancelled is True
    assert turns.cancelled == ("turn_1", "00000000-0000-0000-0000-000000000002")


@pytest.mark.asyncio
async def test_learning_state_fails_closed_until_unit01_store_is_wired():
    from deeptutor.mnemosyne.tutor import TutorAdapter

    adapter = TutorAdapter(SimpleNamespace(), SimpleNamespace(annotation_sync=object()), None)
    with pytest.raises(RuntimeError, match="durable learning store is unavailable"):
        await adapter.get_learning_state(
            "00000000-0000-0000-0000-000000000002", "sha256:" + "a" * 64
        )


@pytest.mark.asyncio
async def test_mnemosyne_semantics_share_the_persisted_native_sequence(tmp_path):
    from deeptutor.mnemosyne.tutor import semantic_event
    from deeptutor.runtime.coordination.types import TurnLease
    from deeptutor.services.session._turn_runtime_shared import _TurnExecution
    from deeptutor.services.session.turns.lifecycle import _mnemosyne_event_extension

    class PersistingCoordinator:
        def __init__(self):
            self.events = []

        async def publish_event(self, turn_id, event):
            assert turn_id == event["turn_id"]
            persisted = dict(event)
            self.events.append(persisted)
            return persisted

    coordinator = PersistingCoordinator()
    runtime = TurnRuntimeManager(SQLiteSessionStore(tmp_path / "chat_history.db"))
    runtime.coordinator = coordinator
    execution = _TurnExecution(
        turn_id="turn_mnemosyne_1",
        session_id="session_1",
        capability="chat",
        payload={"language": "ko"},
        lease=TurnLease(
            turn_id="turn_mnemosyne_1",
            session_id="session_1",
            owner_id="owner_1",
            fencing_token=1,
            expires_at=1_900_000_000,
        ),
    )
    started = await runtime._publish_live_event(
        execution,
        StreamEvent(
            type=StreamEventType.TOOL_RESULT,
            source="mnemosyne",
            metadata={
                "_mnemosyne_semantic": {
                    "type": "turn.started",
                    "payload": {"capability": "chat", "response_language": "ko"},
                }
            },
        ),
    )
    delta = await runtime._publish_live_event(
        execution,
        StreamEvent(type=StreamEventType.CONTENT, source="chat", content="안녕하세요."),
    )
    reader_goto = await runtime._publish_live_event(
        execution,
        StreamEvent(
            type=StreamEventType.RESULT,
            source="mnemosyne",
            metadata={
                "_mnemosyne_semantic": {
                    "type": "reader.goto",
                    "payload": {
                        "target": {
                            "document_id": "00000000-0000-0000-0000-000000000002",
                            "version_id": "sha256:" + "a" * 64,
                            "page_index": 1,
                        },
                        "position": [10, 20],
                        "citation_id": "00000000-0000-0000-0000-000000000003",
                    },
                }
            },
        ),
    )

    assert started["protocol_version"] == "2.0"
    assert started["seq"] == 1
    assert "_mnemosyne_semantic" not in started["metadata"]
    assert started["metadata"]["mnemosyne"]["event_id"] == "turn_mnemosyne_1:1"
    assert delta["seq"] == 2
    assert delta["metadata"]["mnemosyne"]["payload"] == {"text": "안녕하세요."}
    assert reader_goto["seq"] == 3
    assert reader_goto["metadata"]["mnemosyne"]["type"] == "reader.goto"
    assert "_mnemosyne_semantic" not in reader_goto["metadata"]
    assert semantic_event(reader_goto) == reader_goto["metadata"]["mnemosyne"]
    assert coordinator.events == [started, delta, reader_goto]
    assert semantic_event(started) == started["metadata"]["mnemosyne"]
    assert semantic_event(delta) == delta["metadata"]["mnemosyne"]

    failed_stream_event = StreamEvent(
        type=StreamEventType.DONE,
        metadata={"status": "failed", "error_code": "provider_error", "retryable": True},
    )
    failed = _mnemosyne_event_extension(execution, failed_stream_event, seq=4)
    failed_frame = {
        "type": "done",
        "protocol_version": "2.0",
        "turn_id": execution.turn_id,
        "seq": 4,
        "metadata": {"status": "failed", "mnemosyne": failed},
    }
    assert semantic_event(failed_frame)["type"] == "turn.error"
    assert failed["payload"]["error"]["code"] == "provider_error"
    assert failed["payload"]["error"]["retryable"] is True

    cancelled = _mnemosyne_event_extension(
        execution,
        StreamEvent(type=StreamEventType.DONE, metadata={"status": "cancelled"}),
        seq=5,
    )
    cancelled_frame = {
        "type": "done",
        "protocol_version": "2.0",
        "turn_id": execution.turn_id,
        "seq": 5,
        "metadata": {"status": "cancelled", "mnemosyne": cancelled},
    }
    assert semantic_event(cancelled_frame)["type"] == "turn.cancelled"
    assert cancelled["payload"] == {"reason": "user_cancelled"}


def test_native_protocol_turn_adapter_defaults_to_korean_and_rejects_unneeded_capabilities():
    from deeptutor.mnemosyne.tutor import native_protocol_turn_request

    request = native_protocol_turn_request(
        {
            "content": "설명해 줘",
            "client_submission_id": "00000000-0000-0000-0000-000000000003",
            "capability": "deep_solve",
            "skills": ["external-skill"],
            "mcp": ["external-server"],
        }
    )

    assert request.capability == "deep_solve"
    assert request.language == "ko"
    assert request.reply_language_override == "ko"
    assert request.skills == ["__mnemosyne_disabled__"]
    assert request.mcp == ["__mnemosyne_disabled__"]

    with pytest.raises(ValueError, match="Unsupported personal tutor capability"):
        native_protocol_turn_request(
            {
                "content": "조사해 줘",
                "client_submission_id": "00000000-0000-0000-0000-000000000004",
                "capability": "deep_research",
            }
        )
    with pytest.raises(ValueError, match="server-resolved material"):
        native_protocol_turn_request(
            {
                "content": "이 문서를 읽어 줘",
                "client_submission_id": "00000000-0000-0000-0000-000000000005",
                "capability": "reading",
            }
        )

    reading = native_protocol_turn_request(
        {
            "content": "이 문서를 읽어 줘",
            "client_submission_id": "00000000-0000-0000-0000-000000000006",
            "capability": "reading",
            "reading_material_id": "abcdef12",
            "reading_material_revision": 3,
            "reading_viewport": {"locator": 2, "selection": "unverified selection"},
        }
    )
    assert reading.reading_viewport.model_dump() == {"locator": 2, "selection": None}

    # Raw /ws clients cannot smuggle the private reader-language bridge.
    stripped = native_protocol_turn_request(
        {
            "content": "설명해 줘",
            "client_submission_id": "00000000-0000-0000-0000-000000000007",
            "capability": "chat",
            "config": {
                "_mnemosyne_content_language": "en",
                "_mnemosyne_reader_context": {
                    "document_id": "00000000-0000-0000-0000-000000000002",
                    "version_id": "sha256:" + "a" * 64,
                    "page_index": 1,
                },
            },
        }
    )
    assert "_mnemosyne_content_language" not in stripped.config
    assert "_mnemosyne_reader_context" not in stripped.config
    trusted = native_protocol_turn_request(
        {
            "content": "설명해 줘",
            "client_submission_id": "00000000-0000-0000-0000-000000000008",
            "capability": "chat",
        },
        content_language="en",
        reader_context={
            "document_id": "00000000-0000-0000-0000-000000000002",
            "version_id": "sha256:" + "a" * 64,
            "page_index": 1,
        },
    )
    assert trusted.config["_mnemosyne_content_language"] == "en"
    assert trusted.config["_mnemosyne_reader_context"] == {
        "document_id": "00000000-0000-0000-0000-000000000002",
        "version_id": "sha256:" + "a" * 64,
        "page_index": 1,
    }


@pytest.mark.asyncio
async def test_native_tutor_consumes_versioned_mnemosyne_web_envelope():
    from deeptutor.mnemosyne.tutor import TutorAdapter

    captured = {}

    class FakeTurns:
        async def start_turn(self, request):
            captured["request"] = request
            return {"session_id": request.session_id}, {"id": "turn-1"}

    request = {
        "type": "start_turn",
        "protocol_version": "2.0",
        "content": "설명해 줘",
        "client_submission_id": "00000000-0000-0000-0000-000000000011",
        "session_id": "session-1",
        "capability": "chat",
        "language": "en",
        "reply_language_override": "ko",
        "config": {
            "_mnemosyne_content_language": "attacker-value",
            "mnemosyne": {
                "contract_version": "0.1.0",
                "turn_request": {
                    "client_mutation_id": "00000000-0000-0000-0000-000000000011",
                    "capability": "quiz",
                    "message": "설명해 줘",
                    "reader_context": {
                        "document_id": "00000000-0000-0000-0000-000000000002",
                        "version_id": "sha256:" + "a" * 64,
                        "page_index": 1,
                        "viewport_rect": [0, 0, 612, 792],
                        "selection": {"quote": "client supplied text"},
                        "content_language": "en",
                        "response_language": "ko",
                    },
                    "response_language": "ko",
                },
            },
        },
    }

    adapter = TutorAdapter(turns=FakeTurns(), library=None, learning_store=None)
    session, turn = await adapter.start_native_turn(request)

    native = captured["request"]
    assert session == {"session_id": "session-1"}
    assert turn == {"id": "turn-1"}
    assert native.session_id == "session-1"
    assert native.capability == "deep_question"
    assert native.content == "설명해 줘"
    assert native.client_submission_id == "00000000-0000-0000-0000-000000000011"
    assert native.language == "ko"
    assert native.reply_language_override == "ko"
    assert native.skills == ["__mnemosyne_disabled__"]
    assert native.mcp == ["__mnemosyne_disabled__"]
    assert native.config == {
        "_mnemosyne_content_language": "en",
        "_mnemosyne_reader_context": {
            "document_id": "00000000-0000-0000-0000-000000000002",
            "version_id": "sha256:" + "a" * 64,
            "page_index": 1,
        },
    }


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (lambda request: request["config"]["mnemosyne"].update(contract_version="0.2.0"), "Unsupported Mnemosyne"),
        (lambda request: request["config"]["mnemosyne"]["turn_request"].update(client_mutation_id="00000000-0000-0000-0000-000000000099"), "submission IDs do not match"),
        (lambda request: request["config"]["mnemosyne"]["turn_request"].update(capability="memory"), "learning-state operation"),
        (lambda request: request["config"]["mnemosyne"]["turn_request"].update(capability="reading"), "server-resolved material"),
    ],
)
@pytest.mark.asyncio
async def test_native_tutor_rejects_invalid_or_unresolved_mnemosyne_actions(mutate, message):
    from deeptutor.mnemosyne.tutor import TutorAdapter

    class FakeTurns:
        async def start_turn(self, _request):
            raise AssertionError("invalid Mnemosyne requests must not start a turn")

    request = {
        "type": "start_turn",
        "protocol_version": "2.0",
        "content": "설명해 줘",
        "client_submission_id": "00000000-0000-0000-0000-000000000011",
        "session_id": "session-1",
        "capability": "chat",
        "config": {
            "mnemosyne": {
                "contract_version": "0.1.0",
                "turn_request": {
                    "client_mutation_id": "00000000-0000-0000-0000-000000000011",
                    "capability": "quiz",
                    "message": "설명해 줘",
                    "reader_context": {
                        "document_id": "00000000-0000-0000-0000-000000000002",
                        "version_id": "sha256:" + "a" * 64,
                        "page_index": 1,
                        "viewport_rect": [0, 0, 612, 792],
                        "selection": None,
                        "content_language": "en",
                        "response_language": "ko",
                    },
                    "response_language": "ko",
                },
            }
        },
    }
    mutate(request)
    adapter = TutorAdapter(turns=FakeTurns(), library=None, learning_store=None)

    with pytest.raises(ValueError, match=message):
        await adapter.start_native_turn(request)


@pytest.mark.asyncio
async def test_unified_ws_uses_registered_tutor_for_start_cancel_and_reconnect(monkeypatch):
    import json

    from fastapi import WebSocketDisconnect

    from deeptutor.api.routers import auth, unified_ws

    observed: dict[str, object] = {}

    class FakeTurns:
        async def start_turn(self, _request):
            raise AssertionError("the native route bypassed the registered tutor")

        async def subscribe_turn(self, *_args, **_kwargs):
            raise AssertionError("the native route bypassed the registered tutor")
            yield {}

        async def cancel_turn(self, *_args, **_kwargs):
            raise AssertionError("the native route bypassed the registered tutor")

    class RecordingTurns:
        async def start_turn(self, request):
            observed["start"] = request
            return {"id": "session_1"}, {"id": "turn_1"}

        async def subscribe_turn(self, turn_id, *, after_seq=0):
            observed.setdefault("subscribe", []).append((turn_id, after_seq))
            await asyncio.Event().wait()
            if False:
                yield {}

        async def cancel_turn(self, turn_id, *, command_id=None):
            observed["cancel"] = (turn_id, command_id)
            return True

    from deeptutor.mnemosyne.tutor import TutorAdapter

    tutor = TutorAdapter(
        RecordingTurns(), SimpleNamespace(annotation_sync=object()), learning_store=None
    )

    class FakeWebSocket:
        def __init__(self):
            self.app = SimpleNamespace(
                state=SimpleNamespace(
                    application_container=SimpleNamespace(turns=FakeTurns()),
                    mnemosyne=SimpleNamespace(tutor=tutor),
                )
            )
            self.messages = iter(
                [
                    json.dumps(
                        {
                            "type": "start_turn",
                            "protocol_version": "2.0",
                            "content": "개념을 설명해 줘",
                            "client_submission_id": "00000000-0000-0000-0000-000000000007",
                            "capability": "chat",
                        }
                    ),
                    json.dumps(
                        {
                            "type": "resume_from",
                            "protocol_version": "2.0",
                            "turn_id": "turn_1",
                            "seq": 7,
                        }
                    ),
                    json.dumps(
                        {
                            "type": "cancel_turn",
                            "protocol_version": "2.0",
                            "turn_id": "turn_1",
                            "command_id": "cancel-command-1",
                        }
                    ),
                ]
            )
            self.sent: list[dict[str, object]] = []

        async def accept(self):
            return None

        async def receive_text(self):
            await asyncio.sleep(0)
            try:
                return next(self.messages)
            except StopIteration as exc:
                raise WebSocketDisconnect(code=1000) from exc

        async def send_text(self, value):
            self.sent.append(json.loads(value))

    async def allow_auth(_websocket):
        return None

    monkeypatch.setattr(auth, "ws_require_auth", allow_auth)
    websocket = FakeWebSocket()
    await unified_ws.unified_websocket(websocket)

    assert observed["start"].client_submission_id == "00000000-0000-0000-0000-000000000007"
    assert observed["start"].language == "ko"
    assert observed["subscribe"] == [("turn_1", 0), ("turn_1", 7)]
    assert observed["cancel"] == ("turn_1", "cancel-command-1")
    assert websocket.sent[-1]["accepted"] is True


@pytest.mark.asyncio
async def test_tutor_learning_mutations_match_contract_revision_fields():
    from deeptutor.mnemosyne.tutor import TutorAdapter

    observed: dict[str, object] = {}
    document_id = "00000000-0000-0000-0000-000000000001"
    version_id = "sha256:" + "a" * 64
    citation = {
        "citation_id": "00000000-0000-0000-0000-000000000032",
        "verification_id": "00000000-0000-0000-0000-000000000033",
        "verified": True,
        "anchor": {
            "document_id": document_id,
            "version_id": version_id,
            "page_index": 1,
            "parse_revision": "pymupdf-test-nfc-1",
            "text_sha256": "b" * 64,
            "start_scalar": 0,
            "end_scalar": 4,
            "quote": "E=mc",
            "rects": [[40.0, 100.0, 25.0, 12.0]],
        },
    }
    quiz = {
        "quiz_id": "00000000-0000-0000-0000-000000000028",
        "document_id": document_id,
        "version_id": version_id,
        "title": "에너지 확인",
        "questions": [
            {
                "question_id": "00000000-0000-0000-0000-000000000029",
                "prompt": "식에서 질량을 나타내는 문자는 무엇인가요?",
                "kind": "free_text",
                "choices": [],
                "citations": [citation],
            }
        ],
        "response_language": "ko",
    }
    assessment = {
        "attempt_id": "00000000-0000-0000-0000-00000000002a",
        "score": 1.0,
        "feedback_ko": "맞습니다. 식에서 m이 질량을 나타냅니다.",
        "learning_revision": 2,
        "citations": [citation],
    }
    activity = {
        "activity_id": "00000000-0000-0000-0000-000000000034",
        "kind": "chat",
        "turn_id": "turn_mnemosyne_1",
        "summary_ko": "에너지와 질량의 관계를 복습했습니다.",
        "created_at": "2026-10-08T07:02:00Z",
    }
    state = {
        "document_id": document_id,
        "version_id": version_id,
        "learning_revision": 2,
        "quiz_attempts": [
            {
                "attempt_id": assessment["attempt_id"],
                "quiz_id": quiz["quiz_id"],
                "score": 1.0,
            }
        ],
        "mastery": [
            {
                "concept_id": "mass-energy",
                "label_ko": "질량과 에너지",
                "score": 1.0,
                "evidence_attempt_ids": [assessment["attempt_id"]],
            }
        ],
        "memory": [
            {
                "memory_id": "00000000-0000-0000-0000-000000000035",
                "front_ko": "식 E=mc²에서 m은 무엇을 뜻하나요?",
                "back_ko": "질량을 뜻합니다.",
                "due_at": "2026-10-09T07:00:00Z",
                "review_count": 0,
                "citations": [citation],
            }
        ],
        "progress": {
            "last_page_index": 1,
            "pages_read": [0, 1],
            "reading_seconds": 180,
            "next_review_at": "2026-10-09T07:00:00Z",
        },
        "activities": [activity],
    }

    class RecordingLearningStore:
        async def get_quiz(self, quiz_id):
            assert quiz_id == quiz["quiz_id"]
            return quiz

        async def review_memory(self, review):
            observed["review"] = review
            return state

        async def save_activity(self, saved_activity, mutation_id, base_revision):
            observed["activity"] = saved_activity
            observed["activity_mutation"] = (mutation_id, base_revision)
            return state

    class RecordingLibrary:
        annotation_sync = object()

        def __init__(self):
            self.verification_count = 0

        def verify_citation(self, anchor, *, citation_id=None):
            self.verification_count += 1
            return {
                "citation_id": citation_id,
                "verification_id": f"00000000-0000-0000-0000-{36 + self.verification_count:012d}",
                "verified": True,
                "anchor": dict(anchor),
            }

    library = RecordingLibrary()

    class RecordingAssessmentService:
        async def submit_attempt(self, submitted_attempt, public_quiz):
            observed["attempt"] = submitted_attempt
            observed["assessment_quiz"] = public_quiz
            return assessment

    tutor = TutorAdapter(
        object(),
        library,
        RecordingLearningStore(),
        RecordingAssessmentService(),
    )
    attempt = {
        "attempt_id": "00000000-0000-0000-0000-00000000002a",
        "client_mutation_id": "00000000-0000-0000-0000-00000000006c",
        "quiz_id": "00000000-0000-0000-0000-000000000028",
        "document_id": document_id,
        "version_id": version_id,
        "base_learning_revision": 1,
        "submitted_at": "2026-10-08T07:00:00Z",
        "answers": [
            {
                "question_id": "00000000-0000-0000-0000-000000000029",
                "answer": "  learner answer  ",
            }
        ],
    }
    review = {
        "client_mutation_id": "00000000-0000-0000-0000-00000000006d",
        "memory_id": "00000000-0000-0000-0000-00000000006e",
        "base_learning_revision": 1,
        "grade": 3,
        "reviewed_at": "2026-10-08T07:01:00Z",
    }
    activity_mutation_id = "00000000-0000-0000-0000-000000000036"

    submitted_assessment = await tutor.submit_attempt(attempt)
    assert submitted_assessment["attempt_id"] == assessment["attempt_id"]
    assert submitted_assessment["citations"][0]["verification_id"].endswith("000000000038")
    assert observed["attempt"] == attempt
    assert observed["assessment_quiz"]["questions"][0]["citations"][0]["verification_id"].endswith(
        "000000000037"
    )
    reviewed_state = await tutor.review_memory(review)
    assert observed["review"] == review
    assert reviewed_state["memory"][0]["citations"][0]["verification_id"].endswith(
        "000000000039"
    )
    saved_state = await tutor.save_activity(activity, activity_mutation_id, 1)
    assert observed["activity"] == activity
    assert observed["activity_mutation"] == (activity_mutation_id, 1)
    assert saved_state["memory"][0]["citations"][0]["verification_id"].endswith(
        "000000000040"
    )


@pytest.mark.asyncio
async def test_tutor_revalidates_bilingual_quiz_citations_against_source_pdf(tmp_path):
    import copy
    from pathlib import Path

    from deeptutor.mnemosyne.library import LibraryAdapter, LibraryError
    from deeptutor.mnemosyne.tutor import TutorAdapter
    from deeptutor.reading.store import ReadingStore

    repository_root = Path(__file__).resolve().parents[4]
    source = repository_root / "contracts" / "fixtures" / "bilingual-geometry.pdf"
    library = LibraryAdapter(ReadingStore(tmp_path / "reading"))
    document = library.upload_pdf(
        source.read_bytes(), "bilingual-geometry.pdf", title="Bilingual fixture"
    )
    document_id, version_id = document["document_id"], document["version_id"]

    def source_citation(page_index: int, quote: str) -> tuple[dict, dict]:
        page = library.get_page(document_id, version_id, page_index)
        start = page["text"].index(quote)
        end = start + len(quote)
        segments = [
            segment
            for segment in page["segments"]
            if segment["start_scalar"] < end and segment["end_scalar"] > start
        ]
        assert segments
        anchor = {
            "document_id": document_id,
            "version_id": version_id,
            "page_index": page_index,
            "parse_revision": page["parse_revision"],
            "text_sha256": page["text_sha256"],
            "start_scalar": start,
            "end_scalar": end,
            "quote": quote,
            "rects": [segment["rect"] for segment in segments],
        }
        return anchor, library.verify_citation(anchor)

    english_anchor, english_citation = source_citation(0, "capacitor")
    korean_anchor, korean_citation = source_citation(1, "커패시터는")
    quiz = {
        "quiz_id": "00000000-0000-0000-0000-000000000128",
        "document_id": document_id,
        "version_id": version_id,
        "title": "에너지 확인",
        "questions": [
            {
                "question_id": "00000000-0000-0000-0000-000000000129",
                "prompt": "영문 교재에서 capacitor는 무엇을 저장하나요?",
                "kind": "free_text",
                "choices": [],
                "citations": [english_citation],
            },
            {
                "question_id": "00000000-0000-0000-0000-000000000130",
                "prompt": "한글 교재에서 커패시터는 무엇을 저장하나요?",
                "kind": "free_text",
                "choices": [],
                "citations": [korean_citation],
            },
        ],
        "response_language": "ko",
    }

    class LearningStore:
        async def get_quiz(self, _quiz_id):
            return quiz

    tutor = TutorAdapter(object(), library, LearningStore())
    verified_quiz = await tutor.get_quiz(quiz["quiz_id"])
    citations = [question["citations"][0] for question in verified_quiz["questions"]]
    original_citations = [english_citation, korean_citation]
    expected_anchors = [english_anchor, korean_anchor]
    assert verified_quiz["response_language"] == "ko"
    assert [citation["anchor"]["page_index"] for citation in citations] == [0, 1]
    for verified, original, expected_anchor in zip(citations, original_citations, expected_anchors):
        assert verified["citation_id"] == original["citation_id"]
        assert verified["verification_id"] != original["verification_id"]
        assert library.require_verified_citation(verified) == expected_anchor

    tampered_quiz = copy.deepcopy(quiz)
    tampered = tampered_quiz["questions"][0]["citations"][0]
    tampered["anchor"]["quote"] = "X" * len(tampered["anchor"]["quote"])
    quiz.clear()
    quiz.update(tampered_quiz)
    with pytest.raises(LibraryError, match="citation text"):
        await tutor.get_quiz(tampered_quiz["quiz_id"])


@pytest.mark.asyncio
async def test_tutor_learning_mutations_reject_legacy_revision_and_invalid_review_grade():
    from deeptutor.mnemosyne.tutor import TutorAdapter

    class RecordingLearningStore:
        async def submit_attempt(self, _attempt):
            raise AssertionError("invalid attempts must not reach the store")

        async def review_memory(self, _review):
            raise AssertionError("invalid reviews must not reach the store")

    tutor = TutorAdapter(
        object(), SimpleNamespace(annotation_sync=object()), RecordingLearningStore()
    )
    attempt = {
        "attempt_id": "00000000-0000-0000-0000-00000000002a",
        "client_mutation_id": "00000000-0000-0000-0000-00000000006c",
        "quiz_id": "00000000-0000-0000-0000-000000000028",
        "document_id": "00000000-0000-0000-0000-000000000001",
        "version_id": "sha256:" + "a" * 64,
        "base_revision": 1,
        "submitted_at": "2026-10-08T07:00:00Z",
        "answers": [
            {
                "question_id": "00000000-0000-0000-0000-000000000029",
                "answer": "learner answer",
            }
        ],
    }
    review = {
        "client_mutation_id": "00000000-0000-0000-0000-00000000006d",
        "memory_id": "00000000-0000-0000-0000-00000000006e",
        "base_learning_revision": 1,
        "grade": True,
        "reviewed_at": "2026-10-08T07:01:00Z",
    }

    with pytest.raises(ValueError, match="base_learning_revision"):
        await tutor.submit_attempt(attempt)
    with pytest.raises(ValueError, match="grade"):
        await tutor.review_memory(review)


@pytest.mark.asyncio
async def test_tutor_quiz_and_learning_state_fail_closed_on_private_or_wrong_version_data():
    from deeptutor.mnemosyne.tutor import TutorAdapter

    quiz = {
        "quiz_id": "00000000-0000-0000-0000-000000000028",
        "document_id": "00000000-0000-0000-0000-000000000001",
        "version_id": "sha256:" + "a" * 64,
        "title": "확인 문제",
        "questions": [],
        "response_language": "ko",
        "answer_key": {"secret": "b"},
    }

    class LearningStore:
        async def get_quiz(self, _quiz_id):
            return quiz

        async def get_state(self, document_id, _version_id):
            return {
                "document_id": document_id,
                "version_id": "sha256:" + "b" * 64,
                "learning_revision": 1,
                "quiz_attempts": [],
                "mastery": [],
                "memory": [],
                "progress": {},
                "activities": [],
            }

    tutor = TutorAdapter(object(), SimpleNamespace(annotation_sync=object()), LearningStore())

    with pytest.raises(ValueError, match="public Quiz contract"):
        await tutor.get_quiz(quiz["quiz_id"])
    with pytest.raises(ValueError, match="another document version"):
        await tutor.get_learning_state(
            "00000000-0000-0000-0000-000000000001", "sha256:" + "a" * 64
        )


@pytest.mark.asyncio
async def test_tutor_learning_state_rejects_invalid_nested_entries_and_activity_ids():
    from deeptutor.mnemosyne.tutor import TutorAdapter

    document_id = "00000000-0000-0000-0000-000000000001"
    version_id = "sha256:" + "a" * 64
    state = {
        "document_id": document_id,
        "version_id": version_id,
        "learning_revision": 1,
        "quiz_attempts": [
            {
                "attempt_id": "00000000-0000-0000-0000-00000000002a",
                "quiz_id": "00000000-0000-0000-0000-000000000028",
                "score": True,
            }
        ],
        "mastery": [],
        "memory": [],
        "progress": {
            "last_page_index": 0,
            "pages_read": [],
            "reading_seconds": 0,
            "next_review_at": "2026-10-09T07:00:00Z",
        },
        "activities": [],
    }

    class LearningStore:
        async def get_state(self, _document_id, _version_id):
            return state

    tutor = TutorAdapter(object(), SimpleNamespace(annotation_sync=object()), LearningStore())
    with pytest.raises(ValueError, match="quiz_attempt.score"):
        await tutor.get_learning_state(document_id, version_id)

    state["quiz_attempts"] = []
    state["activities"] = [
        {
            "activity_id": "00000000-0000-0000-0000-000000000034",
            "kind": "chat",
            "turn_id": "turn with spaces",
            "summary_ko": "복습",
            "created_at": "2026-10-09T07:00:00Z",
        }
    ]
    with pytest.raises(ValueError, match="activity.turn_id"):
        await tutor.get_learning_state(document_id, version_id)


@pytest.mark.asyncio
async def test_tutor_save_activity_rejects_malformed_activity_before_store_write():
    from deeptutor.mnemosyne.tutor import TutorAdapter

    class LearningStore:
        async def save_activity(self, *_args):
            raise AssertionError("malformed activity reached the store")

    tutor = TutorAdapter(object(), SimpleNamespace(annotation_sync=object()), LearningStore())
    with pytest.raises(ValueError, match="turn_id"):
        await tutor.save_activity(
            {
                "activity_id": "00000000-0000-0000-0000-000000000034",
                "kind": "chat",
                "turn_id": "invalid turn id",
                "summary_ko": "복습",
                "created_at": "2026-10-09T07:00:00Z",
            },
            "00000000-0000-0000-0000-000000000036",
            0,
        )


@pytest.mark.asyncio
async def test_mnemosyne_assessment_service_keeps_grading_private_and_replays_persisted_result():
    from datetime import datetime, timezone

    from deeptutor.learning.service import MnemosyneAssessmentService

    document_id = "00000000-0000-0000-0000-000000000001"
    quiz_id = "00000000-0000-0000-0000-000000000028"
    question_id = "00000000-0000-0000-0000-000000000029"
    version_id = "sha256:" + "a" * 64
    citation = {
        "citation_id": "00000000-0000-0000-0000-000000000032",
        "verification_id": "00000000-0000-0000-0000-000000000033",
        "verified": True,
        "anchor": {
            "document_id": document_id,
            "version_id": version_id,
            "page_index": 0,
            "parse_revision": "fixture-v1",
            "text_sha256": "b" * 64,
            "start_scalar": 0,
            "end_scalar": 4,
            "quote": "E=mc",
            "rects": [[1, 2, 3, 4]],
        },
    }
    quiz = {
        "quiz_id": quiz_id,
        "document_id": document_id,
        "version_id": version_id,
        "title": "질량과 에너지",
        "questions": [
            {
                "question_id": question_id,
                "prompt": "식에서 m은 무엇을 뜻하나요?",
                "kind": "free_text",
                "choices": [],
                "citations": [citation],
            }
        ],
        "response_language": "ko",
    }
    attempt = {
        "attempt_id": "00000000-0000-0000-0000-00000000002a",
        "client_mutation_id": "00000000-0000-0000-0000-00000000006c",
        "quiz_id": quiz_id,
        "document_id": document_id,
        "version_id": version_id,
        "base_learning_revision": 5,
        "submitted_at": "2026-10-09T07:00:00Z",
        "answers": [{"question_id": question_id, "answer": "질량입니다."}],
    }
    grading_input = {
        "quiz_id": quiz_id,
        "document_id": document_id,
        "version_id": version_id,
        "questions": [
            {
                "question_id": question_id,
                "answer_key": "질량",
                "rubric": "질량이라고 설명하면 정답입니다.",
                "explanation": "m은 질량을 나타냅니다.",
                "concept_id": "mass-energy",
                "label_ko": "질량과 에너지 관계",
            }
        ],
    }
    observed: dict[str, object] = {}

    class AssessmentStore:
        def __init__(self):
            self.assessment = None
            self.claim_count = 0

        async def begin_attempt(self, submitted_attempt, payload_sha256):
            observed["payload_sha256"] = payload_sha256
            self.claim_count += 1
            if self.assessment is not None:
                return {"status": "completed_replay", "assessment": self.assessment}
            return {"status": "claimed"}

        async def get_grading_input(self, submitted_quiz_id, submitted_document_id, submitted_version_id):
            assert (submitted_quiz_id, submitted_document_id, submitted_version_id) == (
                quiz_id,
                document_id,
                version_id,
            )
            return grading_input

        async def commit_assessment(
            self, submitted_attempt, payload_sha256, assessment, *, question_results
        ):
            observed["question_results"] = question_results
            observed["committed_hash"] = payload_sha256
            self.assessment = assessment
            return assessment

        async def release_attempt_for_retry(self, *_args):
            raise AssertionError("successful grading must not release its claim")

    async def evaluate(payload):
        observed["provider_payload"] = payload
        return {
            "results": [
                {
                    "question_id": question_id,
                    "score": 0.75,
                    "feedback_ko": "핵심 개념을 이해했습니다. 기호 m의 역할도 함께 설명해 보세요.",
                    "memory_front_ko": "식 E=mc에서 m은 무엇을 뜻하나요?",
                    "memory_back_ko": "질량을 뜻합니다.",
                }
            ]
        }

    store = AssessmentStore()
    service = MnemosyneAssessmentService(
        store,
        evaluator=evaluate,
        clock=lambda: datetime(2026, 10, 9, 7, tzinfo=timezone.utc),
    )
    assert service.ready is True

    assessment = await service.submit_attempt(attempt, quiz)
    replay = await service.submit_attempt(attempt, quiz)

    assert assessment == replay
    assert assessment["score"] == 0.75
    assert assessment["learning_revision"] == 6
    assert assessment["citations"] == [citation]
    assert store.claim_count == 2
    assert observed["provider_payload"]["questions"][0]["answer_key"] == "질량"
    assert "answer_key" not in observed["question_results"][0]
    assert observed["question_results"][0]["concept_id"] == "mass-energy"
    assert observed["question_results"][0]["score"] == 0.75
    assert observed["question_results"][0]["memory"]["due_at"] == "2026-10-10T07:00:00Z"
    assert observed["question_results"][0]["memory"]["citations"] == [citation]


@pytest.mark.asyncio
async def test_mnemosyne_assessment_service_releases_invalid_private_claim_without_leaking_data():
    from deeptutor.learning.service import MnemosyneAssessmentError, MnemosyneAssessmentService

    observed: dict[str, object] = {}

    class AssessmentStore:
        async def begin_attempt(self, *_args):
            return {"status": "claimed"}

        async def get_grading_input(self, *_args):
            return {"invalid": "private key must not appear in errors"}

        async def commit_assessment(self, *_args, **_kwargs):
            raise AssertionError("invalid private grading input reached commit")

        async def release_attempt_for_retry(self, attempt_id, payload_sha256, error_code):
            observed["release"] = (attempt_id, payload_sha256, error_code)

    quiz = {
        "quiz_id": "00000000-0000-0000-0000-000000000028",
        "document_id": "00000000-0000-0000-0000-000000000001",
        "version_id": "sha256:" + "a" * 64,
        "questions": [
            {
                "question_id": "00000000-0000-0000-0000-000000000029",
                "prompt": "문제",
                "kind": "free_text",
                "choices": [],
                "citations": [{"citation_id": "c", "verification_id": "v", "verified": True, "anchor": {}}],
            }
        ],
    }
    attempt = {
        "attempt_id": "00000000-0000-0000-0000-00000000002a",
        "client_mutation_id": "00000000-0000-0000-0000-00000000006c",
        "quiz_id": quiz["quiz_id"],
        "document_id": quiz["document_id"],
        "version_id": quiz["version_id"],
        "base_learning_revision": 0,
        "submitted_at": "2026-10-09T07:00:00Z",
        "answers": [
            {
                "question_id": "00000000-0000-0000-0000-000000000029",
                "answer": "학습자 답",
            }
        ],
    }

    service = MnemosyneAssessmentService(AssessmentStore(), evaluator=lambda _payload: None)
    with pytest.raises(MnemosyneAssessmentError) as captured:
        await service.submit_attempt(attempt, quiz)

    assert captured.value.code == "assessment_failed"
    assert "private key" not in str(captured.value)
    assert observed["release"][2] == "assessment_failed"


@pytest.mark.asyncio
@pytest.mark.parametrize("failure_phase", ["provider", "commit"])
async def test_mnemosyne_assessment_service_releases_failed_claim_for_retry(failure_phase):
    from deeptutor.learning.service import MnemosyneAssessmentError, MnemosyneAssessmentService

    question_id = "00000000-0000-0000-0000-000000000029"
    quiz = {
        "quiz_id": "00000000-0000-0000-0000-000000000028",
        "document_id": "00000000-0000-0000-0000-000000000001",
        "version_id": "sha256:" + "a" * 64,
        "questions": [
            {
                "question_id": question_id,
                "prompt": "문제",
                "kind": "free_text",
                "choices": [],
                "citations": [
                    {
                        "citation_id": "00000000-0000-0000-0000-000000000032",
                        "verification_id": "00000000-0000-0000-0000-000000000033",
                        "verified": True,
                        "anchor": {"quote": "원문"},
                    }
                ],
            }
        ],
    }
    attempt = {
        "attempt_id": "00000000-0000-0000-0000-00000000002a",
        "client_mutation_id": "00000000-0000-0000-0000-00000000006c",
        "quiz_id": quiz["quiz_id"],
        "document_id": quiz["document_id"],
        "version_id": quiz["version_id"],
        "base_learning_revision": 0,
        "submitted_at": "2026-10-09T07:00:00Z",
        "answers": [{"question_id": question_id, "answer": "답"}],
    }
    grading_input = {
        "quiz_id": quiz["quiz_id"],
        "document_id": quiz["document_id"],
        "version_id": quiz["version_id"],
        "questions": [
            {
                "question_id": question_id,
                "answer_key": "비공개 답안",
                "rubric": "기준",
                "explanation": "설명",
                "concept_id": "concept-a",
                "label_ko": "개념 A",
            }
        ],
    }
    observed: dict[str, object] = {}

    class AssessmentStore:
        async def begin_attempt(self, *_args):
            return {"status": "claimed"}

        async def get_grading_input(self, *_args):
            return grading_input

        async def commit_assessment(self, *_args, **_kwargs):
            if failure_phase == "provider":
                raise AssertionError("provider failure must not commit")
            raise RuntimeError("private commit diagnostic")

        async def release_attempt_for_retry(self, attempt_id, payload_sha256, error_code):
            observed["release"] = (attempt_id, payload_sha256, error_code)

    async def fail_provider(_payload):
        if failure_phase == "provider":
            raise RuntimeError("private provider diagnostic")
        return {
            "results": [
                {
                    "question_id": question_id,
                    "score": 1,
                    "feedback_ko": "정답입니다.",
                    "memory_front_ko": "",
                    "memory_back_ko": "",
                }
            ]
        }

    service = MnemosyneAssessmentService(AssessmentStore(), evaluator=fail_provider)
    with pytest.raises(MnemosyneAssessmentError) as captured:
        await service.submit_attempt(attempt, quiz)

    expected_code = (
        "assessment_failed" if failure_phase == "provider" else "assessment_commit_unavailable"
    )
    expected_release_code = (
        "assessment_failed" if failure_phase == "provider" else "assessment_commit_failed"
    )
    assert captured.value.code == expected_code
    assert captured.value.retryable is True
    assert "private" not in str(captured.value)
    assert observed["release"][2] == expected_release_code


def test_next_mnemosyne_memory_due_at_uses_grade_and_server_clock():
    from datetime import datetime, timezone

    from deeptutor.learning.service import next_mnemosyne_memory_due_at

    now = datetime(2026, 10, 9, 7, tzinfo=timezone.utc)
    assert next_mnemosyne_memory_due_at(0, 0, now=now) == (
        "2026-10-09T07:10:00Z",
        1,
    )
    assert next_mnemosyne_memory_due_at(1, 0, now=now) == (
        "2026-10-10T07:00:00Z",
        1,
    )
    assert next_mnemosyne_memory_due_at(2, 2, now=now) == (
        "2026-10-21T07:00:00Z",
        3,
    )
    assert next_mnemosyne_memory_due_at(2, 5, now=now) == (
        "2027-01-07T07:00:00Z",
        6,
    )
    assert next_mnemosyne_memory_due_at(3, 5, now=now) == (
        "2027-04-07T07:00:00Z",
        6,
    )


@pytest.mark.parametrize("grade", [True, -1, 4, 1.0])
def test_next_mnemosyne_memory_due_at_rejects_invalid_grades(grade):
    from deeptutor.learning.service import next_mnemosyne_memory_due_at

    with pytest.raises(ValueError):
        next_mnemosyne_memory_due_at(grade, 0)


@pytest.mark.parametrize("review_count", [True, -1, 9_007_199_254_740_991])
def test_next_mnemosyne_memory_due_at_rejects_unsafe_review_count(review_count):
    from deeptutor.learning.service import next_mnemosyne_memory_due_at

    with pytest.raises(ValueError):
        next_mnemosyne_memory_due_at(1, review_count)


def test_next_mnemosyne_memory_due_at_rejects_naive_clock():
    from datetime import datetime

    from deeptutor.learning.service import next_mnemosyne_memory_due_at

    with pytest.raises(ValueError):
        next_mnemosyne_memory_due_at(1, 0, now=datetime(2026, 10, 9, 7))
