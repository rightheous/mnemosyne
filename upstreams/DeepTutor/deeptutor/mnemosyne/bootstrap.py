"""Integrator alone composes unit adapters. /ws keeps the same native container."""

from dataclasses import dataclass

from deeptutor.mnemosyne.library import register_library
from deeptutor.mnemosyne.learning_store import SQLiteMnemosyneLearningStore
from deeptutor.mnemosyne.provider import MnemosyneProviderRuntime
from deeptutor.mnemosyne.quiz_generation import MnemosyneQuizGenerationService
from deeptutor.mnemosyne.tutor import register_tutor
from deeptutor.reading.store import ReadingStore


@dataclass
class MnemosyneServices:
    library: object
    tutor: object
    quiz_generation: object
    provider_runtime: object


def register_mnemosyne(
    container,
    *,
    store=None,
    annotation_sync=None,
    learning_store=None,
    rag_indexer=None,
    rag_search=None,
    settings_defaults_provider=None,
    settings_secret_writer=None,
    settings_credential_reader=None,
    settings_base_url_validator=None,
):
    """Compose the adapters from the process container and explicit providers.

    Optional providers are resolved explicitly rather than replaced with fake
    implementations. A missing persistence/provider implementation leaves the
    Tutor readiness gate degraded.
    """
    reading_store = store if store is not None else ReadingStore()
    provider_runtime = MnemosyneProviderRuntime()
    learning_store = learning_store or getattr(container, "mnemosyne_learning_store", None)
    if learning_store is None:
        learning_store = SQLiteMnemosyneLearningStore(
            reading_store.root / "mnemosyne-learning" / "learning.sqlite3"
        )
    library = register_library(
        reading_store,
        annotation_sync=annotation_sync,
        rag_indexer=rag_indexer or getattr(container, "mnemosyne_rag_indexer", None),
        rag_search=rag_search or getattr(container, "mnemosyne_rag_search", None),
        settings_defaults_provider=(
            settings_defaults_provider
            or getattr(container, "mnemosyne_settings_defaults_provider", None)
            or provider_runtime.defaults
        ),
        settings_secret_writer=(
            settings_secret_writer
            or getattr(container, "mnemosyne_settings_secret_writer", None)
            or provider_runtime.write_secret
        ),
        settings_credential_reader=(
            settings_credential_reader
            or getattr(container, "mnemosyne_settings_credential_reader", None)
            or provider_runtime.has_credential
        ),
        settings_base_url_validator=(
            settings_base_url_validator
            or getattr(container, "mnemosyne_settings_base_url_validator", None)
            or provider_runtime.validate_base_url
        ),
    )
    provider_runtime.attach_library(library)
    tutor = register_tutor(container.turns, library, learning_store=learning_store)
    quiz_generation = MnemosyneQuizGenerationService(
        library, learning_store, provider_runtime=provider_runtime
    )
    return MnemosyneServices(library, tutor, quiz_generation, provider_runtime)
