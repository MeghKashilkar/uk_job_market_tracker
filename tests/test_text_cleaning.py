"""Tests for HTML/entity/whitespace cleanup of raw job descriptions."""

from src.text_cleaning import clean_description, clean_title, normalize_whitespace, strip_html


def test_strip_html_removes_tags():
    assert strip_html("<p>Hello <b>World</b></p>") == "Hello World"


def test_normalize_whitespace_collapses_spaces_and_blank_lines():
    text = "Hello    World\n\n\n\nBye"
    result = normalize_whitespace(text)
    assert "    " not in result
    assert "\n\n\n" not in result


def test_clean_description_handles_html_entities_and_urls():
    raw = "<p>Great role &amp; team.</p> Apply at https://example.com/job/1 today."
    result = clean_description(raw)
    assert "&amp;" not in result
    assert "&" in result  # entity was decoded, not deleted
    assert "https://" not in result
    assert "<p>" not in result


def test_clean_description_empty_input():
    assert clean_description("") == ""
    assert clean_description(None) == ""


def test_clean_title_strips_bracketed_noise():
    result = clean_title("Data Analyst (London, Hybrid) - Acme Recruitment")
    assert "(" not in result
    assert "London" not in result
    assert "Data Analyst" in result
