"""Regression gates for the import-cheap built-in descriptors."""

from __future__ import annotations

import importlib
import json
from pathlib import Path
import subprocess
import sys

from deeptutor.runtime.bootstrap.builtin_capabilities import BUILTIN_CAPABILITY_SPECS
from deeptutor.tools.builtin_specs import BUILTIN_TOOL_SPECS
from deeptutor.runtime.registry.capability_registry import CapabilityRegistry
from deeptutor.core.context import UnifiedContext


def test_builtin_tool_descriptors_match_implementations() -> None:
    for spec in BUILTIN_TOOL_SPECS:
        assert spec.create().name == spec.name


def test_builtin_capability_descriptors_match_implementations() -> None:
    for name, spec in BUILTIN_CAPABILITY_SPECS.items():
        module_name, class_name = spec.class_path.rsplit(":", 1)
        actual = getattr(importlib.import_module(module_name), class_name).manifest
        expected = spec.manifest
        assert actual.name == name
        for field in (
            "description",
            "stages",
            "tools_used",
            "cli_aliases",
            "config_defaults",
        ):
            assert getattr(actual, field) == getattr(expected, field), (name, field)


def test_builtin_catalog_imports_keep_implementations_cold() -> None:
    repo_root = Path(__file__).resolve().parents[2]
    probe = """
import json
import sys

import deeptutor.capabilities.registry
import deeptutor.runtime.registry.capability_registry
import deeptutor.runtime.registry.tool_registry

forbidden = (
    "deeptutor.agents.chat.agentic_pipeline",
    "deeptutor.capabilities.solve.loop",
    "deeptutor.capabilities.mastery.loop",
    "deeptutor.visualizers.loop_capability",
)
print(json.dumps([name for name in forbidden if name in sys.modules]))
"""
    result = subprocess.run(
        [sys.executable, "-c", probe],
        cwd=repo_root,
        capture_output=True,
        check=True,
        text=True,
    )
    assert json.loads(result.stdout) == []


def test_personal_tutor_registry_exposes_only_its_five_native_capabilities() -> None:
    registry = CapabilityRegistry()
    registry.load_builtins()
    expected = {
        "chat",
        "immersive_reading",
        "deep_solve",
        "deep_question",
        "mastery_path",
    }

    assert set(registry.list_capabilities()) == expected
    assert registry.get("deep_research") is None


def test_personal_tutor_loop_registry_skips_external_and_unrelated_extensions(
    monkeypatch,
) -> None:
    from deeptutor.agents.loop.pipeline import AgenticLoopPipeline
    import deeptutor.capabilities.registry as loop_registry

    def fail_external_discovery():
        raise AssertionError("personal tutor must not discover entry-point extensions")

    monkeypatch.setattr(loop_registry, "discover_external_loop_capabilities", fail_external_discovery)
    context = UnifiedContext(user_message="설명해 주세요", active_capability="chat")
    pipeline = AgenticLoopPipeline.__new__(AgenticLoopPipeline)

    capabilities = pipeline._active_loop_capabilities(context)

    assert all(
        capability.name in loop_registry.MNEMOSYNE_LOOP_CAPABILITY_NAMES
        for capability in capabilities
    )
    assert "subagent" not in {capability.name for capability in capabilities}
