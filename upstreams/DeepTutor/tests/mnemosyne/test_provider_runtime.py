from __future__ import annotations

import stat

from deeptutor.mnemosyne import provider as provider_module
from deeptutor.mnemosyne.provider import MnemosyneProviderRuntime


def test_provider_url_policy_blocks_private_and_metadata_targets(monkeypatch):
    monkeypatch.delenv("MNEMOSYNE_ALLOW_PRIVATE_PROVIDER_URLS", raising=False)
    assert MnemosyneProviderRuntime.validate_base_url("https://api.openai.com/v1")
    assert MnemosyneProviderRuntime.validate_base_url("http://127.0.0.1:11434/v1")
    assert not MnemosyneProviderRuntime.validate_base_url("http://api.openai.com/v1")
    assert not MnemosyneProviderRuntime.validate_base_url("https://10.0.0.7/v1")
    assert not MnemosyneProviderRuntime.validate_base_url("http://169.254.169.254/latest/meta-data")
    assert not MnemosyneProviderRuntime.validate_base_url("https://metadata.google.internal/v1")
    assert not MnemosyneProviderRuntime.validate_base_url("https://api.example.com/v1?key=secret")

    monkeypatch.setenv("MNEMOSYNE_ALLOW_PRIVATE_PROVIDER_URLS", "1")
    assert MnemosyneProviderRuntime.validate_base_url("https://10.0.0.7/v1")
    assert MnemosyneProviderRuntime.validate_base_url("http://host.docker.internal:11434/v1")
    assert not MnemosyneProviderRuntime.validate_base_url("http://169.254.169.254/latest/meta-data")


def test_provider_secret_is_private_and_scoped_to_the_configured_endpoint(tmp_path, monkeypatch):
    secret_path = tmp_path / "system" / "mnemosyne-provider.json"
    monkeypatch.setattr(provider_module, "_secret_path", lambda: secret_path)
    monkeypatch.setattr(
        MnemosyneProviderRuntime, "_active_llm_profile", staticmethod(lambda: ({}, {}))
    )
    runtime = MnemosyneProviderRuntime()
    provider = {
        "adapter": "openai-compatible",
        "base_url": "https://api.example.com/v1/",
        "model": "model-a",
    }
    other_provider = {**provider, "base_url": "https://attacker.example/v1"}

    assert runtime.write_secret("test-secret", provider)
    assert runtime.has_credential(provider)
    assert runtime._api_key(provider) == "test-secret"
    assert not runtime.has_credential(other_provider)
    assert runtime._api_key(other_provider) == ""
    assert stat.S_IMODE(secret_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(secret_path.parent.stat().st_mode) == 0o700


def test_provider_runtime_installs_valid_openai_chat_config(tmp_path, monkeypatch):
    secret_path = tmp_path / "system" / "mnemosyne-provider.json"
    monkeypatch.setattr(provider_module, "_secret_path", lambda: secret_path)
    provider = {
        "adapter": "openai-compatible",
        "base_url": "https://api.openai.com/v1",
        "model": "model-a",
    }
    runtime = MnemosyneProviderRuntime()
    runtime.write_secret("test-secret", provider)

    class Library:
        def get_public_settings(self):
            return {"provider": provider, "response_language": "ko"}

    runtime.attach_library(Library())
    with runtime.llm_scope():
        from deeptutor.services.llm.config import get_llm_config

        config = get_llm_config()
        assert config.binding == "custom"
        assert config.provider_name == "custom"
        assert config.api_format == "openai_chat"
        assert config.wire_api == "chat_completions"
        assert config.model == "model-a"
        assert config.get_api_key() == "test-secret"
