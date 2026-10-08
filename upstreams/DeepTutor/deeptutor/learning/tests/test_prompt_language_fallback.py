"""Mastery Path prompts must not fall back to Chinese for every other language.

Only ``en.yaml`` and ``zh.yaml`` exist, and the old candidate list was
``[lang, "zh" if lang != "zh" else "en"]`` — so a Japanese learner got Chinese
prompt scaffolding while the rest of the book stayed Japanese (issue #712).
"""

from __future__ import annotations

import pytest

from deeptutor.learning.prompts import (
    get_learning_prompts,
    notebook_generation_prompts,
    topic_generation_prompts,
)


@pytest.mark.parametrize("code", ["ja", "fr", "de", "ru"])
def test_a_language_without_its_own_file_lands_on_english(code: str) -> None:
    assert get_learning_prompts(code) == get_learning_prompts("en")


def test_korean_mastery_prompts_are_localized() -> None:
    korean = get_learning_prompts("ko")

    assert korean != get_learning_prompts("en")
    assert "진단 평가" in korean["diagnostic"]["system"]
    assert "학습 경로" in korean["topic"]["system"]
    assert get_learning_prompts("ko-KR") == korean


def test_a_regional_chinese_code_still_gets_the_chinese_file() -> None:
    assert get_learning_prompts("zh-tw") == get_learning_prompts("zh")


def test_the_two_shipped_locales_are_unchanged() -> None:
    chinese = get_learning_prompts("zh")
    english = get_learning_prompts("en")

    assert chinese and english
    assert chinese != english


@pytest.mark.parametrize(
    ("code", "label"),
    [("ja", "日本語"), ("ko", "한국어"), ("fr", "Français")],
)
def test_notebook_prompts_ask_the_model_for_the_requested_language(code: str, label: str) -> None:
    """English scaffolding is fine; English *output* for a Japanese learner is not."""
    system_prompt, _user_prompt = notebook_generation_prompts(code, "[]")

    assert label in system_prompt


def test_notebook_prompts_still_carry_a_directive_for_the_shipped_locales() -> None:
    zh_system, _ = notebook_generation_prompts("zh", "[]")
    en_system, _ = notebook_generation_prompts("en", "[]")

    assert "中文（简体）" in zh_system
    assert "in English" in en_system


def test_korean_topic_generation_keeps_its_must_cover_instruction_korean() -> None:
    system_prompt, user_prompt = topic_generation_prompts(
        "ko",
        name="기초",
        goal="기본 개념 이해",
        sources_json="[]",
        must_cover=["원문.pdf"],
    )

    assert "한국어" in system_prompt
    assert "모두 포함하세요" in user_prompt
    assert "원문.pdf" in user_prompt
