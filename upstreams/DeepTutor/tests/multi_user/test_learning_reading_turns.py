"""A saved reading source must obey the learner's current assignment."""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.capabilities.reading.capability import ReadingCapability
from deeptutor.capabilities.reading.capability import _explicit_annotation_request
from deeptutor.capabilities.reading.tools import (
    BINDING_KWARG,
    WORKSPACE_KWARG,
    ReaderGotoTool,
    ReadingListTabsTool,
    ReadingSwitchTabTool,
    ReadMaterialTool,
)
from deeptutor.capabilities.reading import tools as reading_tools
from deeptutor.multi_user.grants import save_grant
from deeptutor.reading import ReadingCatalogStore, ReadingStore
from deeptutor.reading.references import resolve_reading_sources
from deeptutor.services.session.source_inventory import build_inventory, render_manifest
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


def _grant(user_id: str, material_ids: list[str]) -> None:
    save_grant(
        user_id,
        {
            "learning_policy": {
                "age_band": "9-12",
                "locked_persona": "teacher",
                "allowed_capabilities": ["chat", "immersive_reading"],
                "allowed_surfaces": ["chat", "reading"],
                "reading": {
                    "allow_upload": False,
                    "material_ids": material_ids,
                    "extensions": [],
                },
            }
        },
    )


def _materials():
    store = ReadingStore()
    catalog = ReadingCatalogStore()
    allowed = store.ingest_units(
        "1" * 16,
        filename="allowed.md",
        title="Allowed title",
        units=["Allowed passage."],
    )
    revoked = store.ingest_units(
        "2" * 16,
        filename="revoked.md",
        title="Revoked title",
        units=["Revoked secret passage."],
    )
    catalog.register_manifest(allowed)
    catalog.register_manifest(revoked)
    workspace = catalog.create_workspace("Study table", [allowed.material_id, revoked.material_id])
    return store, catalog, workspace, allowed, revoked


def _reference(material) -> dict:
    return {"material_id": material.material_id, "revision": material.revision, "locators": [1]}


class _SavedReferenceStore:
    def __init__(self, reference: dict) -> None:
        self.reference = reference

    async def get_messages(self, _session_id: str):
        return [
            {
                "id": 1,
                "role": "user",
                "content": "What does this say?",
                "parent_message_id": None,
                "metadata": {"request_snapshot": {"readingReferences": [self.reference]}},
            }
        ]


@pytest.mark.asyncio
async def test_revoked_reference_disappears_from_fresh_and_historical_chat_sources(
    mu_isolated_root, seed_user, as_user
) -> None:
    seed_user("admin", role="admin")
    learner = seed_user("student")
    with as_user(learner["id"], username="student"):
        store, _, _, allowed, revoked = _materials()
        _grant(learner["id"], [allowed.material_id, revoked.material_id])
        assert (
            "Revoked secret passage."
            in resolve_reading_sources([_reference(revoked)], store=store)[0].full_text
        )

        # A historical request snapshot remains on disk after assignment is
        # revoked. It and a fresh Resend reference must now resolve alike.
        _grant(learner["id"], [allowed.material_id])
        references = [_reference(allowed), _reference(revoked)]
        assert [row.source_id for row in resolve_reading_sources(references, store=store)] == [
            f"rd-{allowed.material_id}-r{allowed.revision}-1"
        ]
        inventory = await build_inventory(
            _SavedReferenceStore(_reference(revoked)),
            session_id="s1",
            leaf_message_id=1,
            current_turn_ordinal=2,
            fresh_attachment_records=[],
            fresh_notebook_records=[],
            fresh_book_context_text="",
            fresh_book_references=[],
            fresh_history_session_ids=[],
            fresh_question_entry_ids=[],
            fresh_reading_references=references,
        )
        manifest, source_index = render_manifest(inventory)
        assert "Allowed passage." in manifest
        assert "Revoked title" not in manifest
        assert "Revoked secret passage." not in str(source_index)
        assert all(revoked.material_id not in source_id for source_id in source_index)
        _grant(learner["id"], [allowed.material_id, revoked.material_id])
        assert (
            "Revoked secret passage."
            in resolve_reading_sources([_reference(revoked)], store=store)[0].full_text
        )


@pytest.mark.asyncio
async def test_turn_rejects_explicit_and_workspace_default_revoked_material(
    mu_isolated_root, seed_user, as_user, monkeypatch
) -> None:
    seed_user("admin", role="admin")
    learner = seed_user("student")
    with as_user(learner["id"], username="student"):
        _, catalog, workspace, allowed, revoked = _materials()
        _grant(learner["id"], [allowed.material_id])
        runtime = TurnRuntimeManager(SQLiteSessionStore(mu_isolated_root / "turns.sqlite3"))

        async def _noop_run_turn(_execution) -> None:
            return None

        monkeypatch.setattr(runtime, "_run_turn", _noop_run_turn)
        base = {
            "capability": "immersive_reading",
            "workspace_mode": "immersive_reading",
            "reading_workspace_id": workspace.workspace_id,
            "content": "Read this",
            "tools": [],
            "knowledge_bases": [],
            "attachments": [],
            "language": "en",
            "config": {},
        }
        with pytest.raises(RuntimeError, match="not assigned"):
            await runtime.start_turn({**base, "reading_material_id": revoked.material_id})

        catalog.set_active_material(workspace.workspace_id, revoked.material_id)
        with pytest.raises(RuntimeError, match="not assigned"):
            await runtime.start_turn(base)


def test_reading_tools_hide_and_block_revoked_tabs(mu_isolated_root, seed_user, as_user) -> None:
    seed_user("admin", role="admin")
    learner = seed_user("student")
    with as_user(learner["id"], username="student"):
        _, _, workspace, allowed, revoked = _materials()
        _grant(learner["id"], [allowed.material_id])
        binding = {"material_id": allowed.material_id}
        listed = asyncio.run(
            ReadingListTabsTool().execute(**{WORKSPACE_KWARG: workspace.workspace_id})
        )
        assert listed.success
        assert [row["material_id"] for row in listed.metadata["tabs"]] == [allowed.material_id]
        assert "Revoked title" not in listed.content
        assert "Revoked title" not in ReadingCapability._workspace_facts(workspace.workspace_id)

        switched = asyncio.run(
            ReadingSwitchTabTool().execute(
                material_id=revoked.material_id,
                **{WORKSPACE_KWARG: workspace.workspace_id, BINDING_KWARG: binding},
            )
        )
        assert not switched.success
        assert "not assigned" in switched.content
        assert binding["material_id"] == allowed.material_id

        read = asyncio.run(
            ReadMaterialTool().execute(
                locators="1", **{BINDING_KWARG: {"material_id": revoked.material_id}}
            )
        )
        assert not read.success
        assert "not assigned" in read.content
        assert "Revoked secret passage." not in read.content


@pytest.mark.parametrize(
    "message",
    [
        "이 문장에 밑줄 쳐줘",
        "여기에 주석을 달아주세요",
        "Please highlight this passage",
        "Could you add a note to this?",
    ],
)
def test_persistent_annotation_requires_a_clear_positive_request(message: str) -> None:
    assert _explicit_annotation_request(message)


@pytest.mark.parametrize(
    "message",
    [
        "하이라이트 하지 마",
        "밑줄 치지 말아 주세요",
        "이 부분은 강조하지 않아도 돼",
        "Please don't highlight this passage",
        "Please highlight this passage, but do not save it",
        "Can you explain how annotations work?",
        "",
    ],
)
def test_persistent_annotation_rejects_negated_or_implicit_requests(message: str) -> None:
    assert not _explicit_annotation_request(message)


@pytest.mark.asyncio
async def test_reader_goto_refuses_unverified_quotes_without_moving(
    tmp_path, monkeypatch
) -> None:
    store = ReadingStore(tmp_path / "reading")
    material = store.ingest_units(
        "3" * 16,
        filename="source.md",
        title="Source",
        units=["An exact source passage."],
    )
    monkeypatch.setattr(
        reading_tools._ReadingToolBase,
        "_store",
        staticmethod(lambda: store),
    )

    result = await ReaderGotoTool().execute(
        _material_id=material.material_id,
        locator=1,
        quote="a paraphrase that is absent",
    )

    assert result.success is False
    assert "reader_action" not in (result.metadata or {})
    assert "reader was not moved" in result.content
