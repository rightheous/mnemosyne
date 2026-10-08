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
            captured["metadata"] = context.metadata
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
            "persona": "socratic",
            "memory_references": ["summary"],
            "book_references": [{"book_id": "book-1", "page_ids": ["page-1"]}],
            "mastery_path_id": "path-1",
            "mastery_answer": {"question_id": "question-1", "text": "B"},
            "config": {},
            **consultation,
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
        "response_language": "en",
    }
    done_event = next(e for e in events if e["type"] == "done")
    assert done_event["metadata"]["status"] == "completed"
    assert captured["consult_partner_id"] == requested.get("consult_partner_id")
    assert captured["partner_discussion_group_id"] == requested.get("partner_discussion_group_id")

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
        "language": "en",
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
    assert request.language == "ko"
    assert request.reading_material_id == "abcdef12"
    assert request.reading_material_revision == 3
    assert request.reading_viewport.model_dump() == {"locator": 2, "selection": None}
    assert request.skills == ["__mnemosyne_disabled__"]
    assert request.mcp == ["__mnemosyne_disabled__"]


def test_mnemosyne_turn_mapping_rejects_invalid_identity_and_version():
    from deeptutor.mnemosyne.tutor import native_turn_request

    invalid_id = _mnemosyne_turn_request(client_mutation_id="not-a-uuid")
    with pytest.raises(ValueError, match="client_mutation_id must be a UUID"):
        native_turn_request(invalid_id, material_id="abcdef12", material_revision=1)

    invalid_version = _mnemosyne_turn_request()
    invalid_version["reader_context"]["version_id"] = "sha256:short"
    with pytest.raises(ValueError, match="full SHA-256"):
        native_turn_request(invalid_version, material_id="abcdef12", material_revision=1)


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
        await adapter.get_learning_state("00000000-0000-0000-0000-000000000002")


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

    assert started["protocol_version"] == "2.0"
    assert started["seq"] == 1
    assert "_mnemosyne_semantic" not in started["metadata"]
    assert started["metadata"]["mnemosyne"]["event_id"] == "turn_mnemosyne_1:1"
    assert delta["seq"] == 2
    assert delta["metadata"]["mnemosyne"]["payload"] == {"text": "안녕하세요."}
    assert coordinator.events == [started, delta]
    assert semantic_event(started) == started["metadata"]["mnemosyne"]
    assert semantic_event(delta) == delta["metadata"]["mnemosyne"]

    failed_stream_event = StreamEvent(
        type=StreamEventType.DONE,
        metadata={"status": "failed", "error_code": "provider_error", "retryable": True},
    )
    failed = _mnemosyne_event_extension(execution, failed_stream_event, seq=3)
    failed_frame = {
        "type": "done",
        "protocol_version": "2.0",
        "turn_id": execution.turn_id,
        "seq": 3,
        "metadata": {"status": "failed", "mnemosyne": failed},
    }
    assert semantic_event(failed_frame)["type"] == "turn.error"
    assert failed["payload"]["error"]["code"] == "provider_error"
    assert failed["payload"]["error"]["retryable"] is True

    cancelled = _mnemosyne_event_extension(
        execution,
        StreamEvent(type=StreamEventType.DONE, metadata={"status": "cancelled"}),
        seq=4,
    )
    cancelled_frame = {
        "type": "done",
        "protocol_version": "2.0",
        "turn_id": execution.turn_id,
        "seq": 4,
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

    class RecordingLearningStore:
        async def submit_attempt(self, attempt):
            observed["attempt"] = attempt
            return {"attempt_id": attempt["attempt_id"]}

        async def review_memory(self, review):
            observed["review"] = review
            return {"memory_id": review["memory_id"]}

    tutor = TutorAdapter(
        object(), SimpleNamespace(annotation_sync=object()), RecordingLearningStore()
    )
    attempt = {
        "attempt_id": "00000000-0000-0000-0000-00000000002a",
        "client_mutation_id": "00000000-0000-0000-0000-00000000006c",
        "quiz_id": "00000000-0000-0000-0000-000000000028",
        "document_id": "00000000-0000-0000-0000-000000000001",
        "version_id": "sha256:" + "a" * 64,
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

    assert await tutor.submit_attempt(attempt) == {"attempt_id": attempt["attempt_id"]}
    assert observed["attempt"] == attempt
    assert await tutor.review_memory(review) == {"memory_id": review["memory_id"]}
    assert observed["review"] == review


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
