"""Cleaning utilities for the messy free-text job description field.

Adzuna (like most job boards) returns descriptions with stray HTML tags,
escaped entities, inconsistent bullet characters, and irregular whitespace.
This module normalizes all of that into plain, matchable text before it goes
into skill extraction or salary feature engineering.
"""

from __future__ import annotations

import html
import re

from bs4 import BeautifulSoup

BULLET_CHARS = ("•", "◦", "‣", "▪", "●", "·", "*", "-\t")

_BLANK_LINES_RE = re.compile(r"\n{3,}")
_BULLETS_RE = re.compile("|".join(re.escape(char) for char in BULLET_CHARS))
_INLINE_SPACE_RE = re.compile(r"[^\S\n]+")
_URL_RE = re.compile(r"https?://\S+")


def strip_html(text: str) -> str:
    """Drop HTML markup, returning a single-spaced plain-text string."""
    if not text:
        return ""
    return " ".join(BeautifulSoup(text, "html.parser").get_text(separator=" ").split())


def normalize_bullets(text: str) -> str:
    """Rewrite the many bullet glyphs job boards use into a plain ``- `` list."""
    return _BULLETS_RE.sub("\n- ", text)


def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs and cap consecutive blank lines at one."""
    text = _INLINE_SPACE_RE.sub(" ", text)
    return _BLANK_LINES_RE.sub("\n\n", text).strip()


def remove_urls(text: str) -> str:
    """Strip URLs, which add matchable noise but no skill signal."""
    return _URL_RE.sub(" ", text)


def clean_description(raw_text: object) -> str:
    """Full cleaning pipeline: HTML -> entities -> URLs -> bullets -> whitespace."""
    if not isinstance(raw_text, str) or not raw_text.strip():
        return ""

    text = html.unescape(raw_text)
    text = strip_html(text)
    text = remove_urls(text)
    text = normalize_bullets(text)
    return normalize_whitespace(text)


def clean_title(raw_title: object) -> str:
    """Normalize a job title, dropping bracketed location/agency noise."""
    if not isinstance(raw_title, str):
        return ""

    text = html.unescape(raw_title)
    text = strip_html(text)
    # Titles are frequently suffixed with location/agency noise in brackets,
    # e.g. "Data Analyst (London, Hybrid) - Acme Recruitment".
    text = re.sub(r"\s*[\(\[].*?[\)\]]\s*", " ", text)
    return normalize_whitespace(text)
