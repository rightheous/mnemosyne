"""Integrator alone composes unit adapters. /ws keeps the same native container."""

from dataclasses import dataclass

from deeptutor.mnemosyne.library import register_library
from deeptutor.mnemosyne.tutor import register_tutor
from deeptutor.reading.store import ReadingStore


@dataclass
class MnemosyneServices:
    library: object
    tutor: object


def register_mnemosyne(container, *, store=None, annotation_sync=None, learning_store=None):
    library = register_library(
        store if store is not None else ReadingStore(), annotation_sync=annotation_sync
    )
    tutor = register_tutor(container.turns, library, learning_store=learning_store)
    return MnemosyneServices(library, tutor)
