"""Private OpenAI-compatible provider settings for Mnemosyne Tutor calls."""

from __future__ import annotations

from contextlib import contextmanager
import ipaddress
import json
import os
from pathlib import Path
import stat
import tempfile
from typing import Any, Iterator
from urllib.parse import urlsplit


class MnemosyneProviderNotReady(RuntimeError):
    """Raised instead of returning a fabricated Tutor or quiz response."""

    code = "provider_not_ready"


def _secret_path() -> Path:
    from deeptutor.runtime.home import get_runtime_data_root

    return get_runtime_data_root() / "system" / "mnemosyne-provider.json"


class MnemosyneProviderRuntime:
    """Expose provider defaults, secret storage, URL policy, and scoped runtime config."""

    def __init__(self) -> None:
        self.library: Any | None = None

    def attach_library(self, library: Any) -> None:
        self.library = library

    @staticmethod
    def _active_llm_profile() -> tuple[dict[str, Any], dict[str, Any]]:
        from deeptutor.services.config.model_catalog import get_model_catalog_service

        service = get_model_catalog_service()
        catalog = service.load()
        profile = service.get_active_profile(catalog, "llm") or {}
        models = profile.get("models") if isinstance(profile.get("models"), list) else []
        active_model = next(
            (
                item
                for item in models
                if item.get("id")
                == catalog.get("services", {}).get("llm", {}).get("active_model_id")
            ),
            models[0] if models else {},
        )
        return profile, active_model

    @staticmethod
    def _endpoint_key(base_url: str) -> str:
        parsed = urlsplit(base_url.strip())
        host = (parsed.hostname or "").rstrip(".").lower()
        port = parsed.port
        default_port = 443 if parsed.scheme.lower() == "https" else 80
        authority = f"[{host}]" if ":" in host else host
        if port is not None and port != default_port:
            authority = f"{authority}:{port}"
        return f"{parsed.scheme.lower()}://{authority}{parsed.path.rstrip('/')}"

    def defaults(self) -> dict[str, Any]:
        try:
            profile, model = self._active_llm_profile()
        except Exception:
            profile, model = {}, {}
        configured_url = profile.get("base_url") or profile.get("api_base")
        base_url = (
            str(configured_url)
            if isinstance(configured_url, str) and self.validate_base_url(configured_url)
            else "https://api.openai.com/v1"
        )
        return {
            "provider": {
                "adapter": "openai-compatible",
                "base_url": base_url,
                "model": str(model.get("model") or "gpt-4o-mini"),
            },
            "response_language": "ko",
        }

    @staticmethod
    def _read_secret() -> dict[str, Any] | None:
        path = _secret_path()
        try:
            flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            descriptor = os.open(path, flags)
        except FileNotFoundError:
            return None
        except OSError as exc:
            raise RuntimeError("provider credential is unavailable") from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
                raise RuntimeError("provider credential permissions are too broad")
            with os.fdopen(descriptor, "r", encoding="utf-8", closefd=False) as handle:
                value = json.load(handle)
        finally:
            os.close(descriptor)
        if (
            not isinstance(value, dict)
            or value.get("version") != 2
            or not isinstance(value.get("api_key"), str)
            or not value["api_key"].strip()
            or not isinstance(value.get("provider_base_url"), str)
        ):
            raise RuntimeError("provider credential file is invalid")
        return value

    @staticmethod
    def write_secret(api_key: str, provider: dict[str, Any] | None = None) -> bool:
        if (
            not isinstance(api_key, str)
            or not api_key.strip()
            or not isinstance(provider, dict)
            or not isinstance(provider.get("base_url"), str)
        ):
            return False
        path = _secret_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        try:
            path.parent.chmod(0o700)
            descriptor, temporary = tempfile.mkstemp(
                prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
            )
            temporary_path = Path(temporary)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                    json.dump(
                        {
                            "version": 2,
                            "api_key": api_key.strip(),
                            "provider_base_url": provider["base_url"],
                        },
                        handle,
                    )
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary_path, path)
                path.chmod(0o600)
            finally:
                temporary_path.unlink(missing_ok=True)
        except OSError as exc:
            raise RuntimeError("provider credential could not be stored") from exc
        return True

    def has_credential(self, provider: dict[str, Any] | None = None) -> bool:
        try:
            if not isinstance(provider, dict) or not isinstance(provider.get("base_url"), str):
                return False
            return bool(self._api_key(provider))
        except Exception:
            return False

    @staticmethod
    def validate_base_url(base_url: str) -> bool:
        try:
            parsed = urlsplit(base_url)
            if (
                parsed.scheme not in {"http", "https"}
                or not parsed.hostname
                or parsed.username is not None
                or parsed.password is not None
                or parsed.query
                or parsed.fragment
            ):
                return False
            host = parsed.hostname.rstrip(".").lower()
            if host in {
                "metadata",
                "metadata.google.internal",
                "169.254.169.254",
                "100.100.100.200",
            }:
                return False
            allow_private = os.environ.get(
                "MNEMOSYNE_ALLOW_PRIVATE_PROVIDER_URLS", ""
            ).strip().lower() in {
                "1",
                "true",
                "yes",
            }
            try:
                address = ipaddress.ip_address(host)
            except ValueError:
                address = None
            if address is not None:
                if address.is_loopback:
                    return parsed.scheme in {"http", "https"}
                if not address.is_global and not allow_private:
                    return False
            elif host == "host.docker.internal" and not allow_private:
                return False
            elif host == "localhost" or host.endswith(".localhost"):
                return parsed.scheme in {"http", "https"}
            elif any(
                host == suffix or host.endswith(f".{suffix}")
                for suffix in ("local", "internal", "home.arpa", "test", "invalid", "example")
            ):
                if not allow_private:
                    return False
            elif parsed.scheme == "http" and not allow_private:
                return False
            # URL policy is deterministic and does not depend on executor DNS.
            # Deployments that permit private provider hosts must opt in explicitly;
            # Cloud egress policy remains the final network boundary.
            _ = parsed.port
            return True
        except (TypeError, ValueError):
            return False

    def _api_key(self, provider: dict[str, Any]) -> str:
        configured_url = provider.get("base_url")
        if not isinstance(configured_url, str):
            return ""
        endpoint_key = self._endpoint_key(configured_url)
        secret = self._read_secret()
        if secret and self._endpoint_key(secret["provider_base_url"]) == endpoint_key:
            return secret["api_key"].strip()
        try:
            profile, _ = self._active_llm_profile()
        except Exception:
            profile = {}
        profile_url = profile.get("base_url") or profile.get("api_base")
        if not isinstance(profile_url, str) or self._endpoint_key(profile_url) != endpoint_key:
            return ""
        value = profile.get("api_key")
        if isinstance(value, list):
            value = next((item for item in value if isinstance(item, str) and item.strip()), "")
        return value.strip() if isinstance(value, str) else ""

    @contextmanager
    def llm_scope(self) -> Iterator[Any]:
        if self.library is None:
            raise MnemosyneProviderNotReady("provider settings are not connected")
        settings = self.library.get_public_settings()
        provider = settings.get("provider") if isinstance(settings, dict) else None
        if not isinstance(provider, dict):
            raise MnemosyneProviderNotReady("provider settings are not ready")
        base_url = provider.get("base_url")
        model = provider.get("model")
        if (
            not isinstance(base_url, str)
            or not self.validate_base_url(base_url)
            or not isinstance(model, str)
            or not model.strip()
        ):
            raise MnemosyneProviderNotReady("provider settings are invalid")
        try:
            api_key = self._api_key(provider)
        except Exception as exc:
            raise MnemosyneProviderNotReady("provider credential is unavailable") from exc
        if not api_key:
            raise MnemosyneProviderNotReady("provider credential is not configured")
        from deeptutor.services.llm.config import (
            LLMConfig,
            reset_scoped_llm_config,
            set_scoped_llm_config,
        )

        config = LLMConfig(
            model=model.strip(),
            api_key=api_key,
            base_url=base_url,
            effective_url=base_url,
            binding="custom",
            provider_name="custom",
            provider_mode="direct",
            api_format="openai_chat",
            wire_api="chat_completions",
        )
        token = set_scoped_llm_config(config)
        try:
            yield config
        finally:
            reset_scoped_llm_config(token)


__all__ = ["MnemosyneProviderNotReady", "MnemosyneProviderRuntime"]
