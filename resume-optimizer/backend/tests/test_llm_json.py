"""Stage B P4: the single robust LLM-JSON extractor used by all agents/endpoints."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from utils.llm_json import extract_json, parse_llm_json


def test_plain_object():
    assert parse_llm_json('{"a": 1}') == {"a": 1}


def test_plain_array():
    assert parse_llm_json('[1, 2]', kind="array") == [1, 2]


def test_markdown_fenced_object():
    text = '```json\n{"a": 1}\n```'
    assert parse_llm_json(text) == {"a": 1}


def test_fenced_without_language_tag():
    text = '```\n{"a": 1}\n```'
    assert parse_llm_json(text) == {"a": 1}


def test_object_wrapped_in_prose():
    text = 'Sure! Here is your JSON:\n{"a": 1}\nHope that helps.'
    assert parse_llm_json(text) == {"a": 1}


def test_array_wrapped_in_prose():
    text = 'The scores are:\n[{"id": "x"}]\nLet me know.'
    assert parse_llm_json(text, kind="array") == [{"id": "x"}]


def test_thinking_tags_stripped():
    text = '<thinking>{"decoy": true} reasoning…</thinking>{"a": 1}'
    assert parse_llm_json(text) == {"a": 1}


def test_garbage_raises_value_error():
    with pytest.raises(ValueError):
        parse_llm_json("no json here at all")


def test_wrong_shape_raises_value_error():
    with pytest.raises(ValueError):
        parse_llm_json('{"a": 1}', kind="array")
    with pytest.raises(ValueError):
        parse_llm_json('[1, 2]', kind="object")


def test_extract_json_returns_raw_when_no_match():
    # extract_json is best-effort: parse_llm_json is the strict gate
    assert extract_json("plain text") == "plain text"
