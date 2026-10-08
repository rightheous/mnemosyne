"""Contract tests for entry-point plumbing and the personal capability gate.

The generic entry-point and manifest discovery helpers remain testable, while
the Mnemosyne turn registry must not load those external capability classes.

The test covers:

* normal loading
* missing dependencies
* load-error isolation
* the explicit no-plugin personal turn registry
"""

from __future__ import annotations

import dataclasses
import logging
from types import SimpleNamespace

import pytest

from deeptutor.core.capability_protocol import CapabilityManifest, TurnCapability
from deeptutor.core.context import UnifiedContext
import deeptutor.plugins.entry_points as ep_module
from deeptutor.plugins.loader import (
    PluginManifest,
    discover_plugins,
    load_plugin_capability,
)
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.runtime.stream_bus import StreamBus

PLUGINS_GROUP = "deeptutor.plugins"
PLUGINS_LOGGER = "deeptutor.plugins.loader"
PLUMBING_LOGGER = "deeptutor.plugins.entry_points"


class _PluginCap(TurnCapability):
    manifest = CapabilityManifest(
        name="plugin_cap",
        description="Capability provided by a plugin entry point.",
        stages=["responding"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        return None


class _OtherCap(TurnCapability):
    manifest = CapabilityManifest(
        name="other_cap",
        description="Second plugin capability with its own name.",
        stages=["responding"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        return None


def _ep(name: str, load):
    return SimpleNamespace(name=name, load=load)


def _fake_groups(groups: dict[str, list]):
    def fake_entry_points(*, group: str):
        return list(groups.get(group, []))

    return fake_entry_points


# ---------------------------------------------------------------------------
# Normal loading
# ---------------------------------------------------------------------------


def test_load_entry_point_group_returns_coerced_values_in_order(monkeypatch):
    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups({"g": [_ep("a", lambda: "A"), _ep("b", lambda: "B")]}),
    )
    loaded = ep_module.load_entry_point_group("g", lambda _name, obj: obj)
    assert loaded == ["A", "B"]


def test_discover_plugins_normal_load_from_class_and_instance(monkeypatch):
    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups(
            {
                PLUGINS_GROUP: [
                    _ep("plugin_cap", lambda: _PluginCap),
                    _ep("other_cap", lambda: _OtherCap()),
                ]
            }
        ),
    )
    manifests = discover_plugins()
    assert [m.name for m in manifests] == ["plugin_cap", "other_cap"]
    by_name = {m.name: m for m in manifests}
    for manifest in by_name.values():
        assert manifest.type == "capability"
        assert manifest.stages == ["responding"]
        assert ":" in manifest.entry
    assert by_name["plugin_cap"].entry.endswith("_PluginCap")
    assert by_name["other_cap"].entry.endswith("_OtherCap")


def test_personal_tutor_registry_skips_external_turn_capabilities(monkeypatch):
    def unexpected_discovery(**_kwargs):
        raise AssertionError("personal tutor must not enumerate turn capability entry points")

    monkeypatch.setattr(ep_module, "entry_points", unexpected_discovery)
    reg = CapabilityRegistry()
    reg.load_builtins()
    reg.load_plugins()
    assert set(reg.list_capabilities()) == {
        "chat",
        "immersive_reading",
        "deep_solve",
        "deep_question",
        "mastery_path",
    }
    assert reg.get("plugin_cap") is None


# ---------------------------------------------------------------------------
# Missing dependencies
# ---------------------------------------------------------------------------


def test_missing_dependency_entry_point_is_skipped_others_still_load(monkeypatch, caplog):
    def _missing_dep():
        raise ModuleNotFoundError("No module named 'plugin_dep'")

    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups(
            {
                PLUGINS_GROUP: [
                    _ep("needs_dep", _missing_dep),
                    _ep("plugin_cap", lambda: _PluginCap),
                ]
            }
        ),
    )
    with caplog.at_level(logging.WARNING, logger=PLUGINS_LOGGER):
        manifests = discover_plugins()
    assert [m.name for m in manifests] == ["plugin_cap"]
    assert any("needs_dep" in record.getMessage() for record in caplog.records)


def test_load_plugin_capability_propagates_missing_module():
    """Discovery isolates import failures; instantiation does not (current contract)."""

    manifest = PluginManifest(
        name="gone_cap",
        type="capability",
        entry="tests.plugins._no_such_module:Cap",
    )
    with pytest.raises(ModuleNotFoundError):
        load_plugin_capability(manifest)


# ---------------------------------------------------------------------------
# Load-error isolation
# ---------------------------------------------------------------------------


def test_entry_point_load_error_is_isolated_and_named_in_warning(monkeypatch, caplog):
    def _boom():
        raise RuntimeError("boom at import time")

    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups(
            {
                PLUGINS_GROUP: [
                    _ep("bad", _boom),
                    _ep("plugin_cap", lambda: _PluginCap),
                    _ep("worse", _boom),
                ]
            }
        ),
    )
    with caplog.at_level(logging.WARNING, logger=PLUGINS_LOGGER):
        manifests = discover_plugins()
    assert [m.name for m in manifests] == ["plugin_cap"]
    assert any(
        PLUGINS_GROUP in message and "skipping" in message
        for message in (record.getMessage() for record in caplog.records)
    )


def test_group_read_failure_returns_empty_with_warning(monkeypatch, caplog):
    def _broken_reader(*, group: str):
        raise RuntimeError("metadata reader exploded")

    monkeypatch.setattr(ep_module, "entry_points", _broken_reader)
    with caplog.at_level(logging.WARNING, logger=PLUMBING_LOGGER):
        loaded = ep_module.load_entry_point_group(PLUGINS_GROUP, lambda _name, obj: obj)
    assert loaded == []
    assert any(PLUGINS_GROUP in record.getMessage() for record in caplog.records)


def test_coercer_none_rejects_entry_point_without_error(monkeypatch):
    monkeypatch.setattr(
        ep_module,
        "entry_points",
        _fake_groups({"g": [_ep("junk", lambda: object()), _ep("keep", lambda: "kept")]}),
    )
    loaded = ep_module.load_entry_point_group(
        "g", lambda name, obj: obj if name == "keep" else None
    )
    assert loaded == ["kept"]


# ---------------------------------------------------------------------------
# Disable-gating status quo
# ---------------------------------------------------------------------------


def test_plugin_manifest_has_no_enable_disable_gate():
    """Today a plugin cannot be disabled declaratively: PluginManifest carries no
    enabled/disabled flag, and the loader consults none."""

    field_names = {f.name for f in dataclasses.fields(PluginManifest)}
    assert field_names == {
        "name",
        "type",
        "description",
        "stages",
        "version",
        "author",
        "entry",
    }
    assert not field_names & {"enabled", "disabled"}


def test_structural_gates_short_circuit_before_resolving_entry():
    """The only gates are structural (entry / type) and run before any import, so a
    gated manifest never triggers its (here broken) entry point."""

    empty_entry = PluginManifest(name="t1", type="capability", entry="")
    tool_script = PluginManifest(name="t2", type="capability", entry="tests/plugins/tool.py")
    wrong_type = PluginManifest(
        name="t3",
        type="tool",
        entry="tests.plugins._no_such_module:Cap",
    )
    assert load_plugin_capability(empty_entry) is None
    assert load_plugin_capability(tool_script) is None
    assert load_plugin_capability(wrong_type) is None
