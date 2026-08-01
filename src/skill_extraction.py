"""NLP skill extraction over the curated taxonomy.

Matches :mod:`src.skills_taxonomy` against cleaned job description text using
spaCy's ``PhraseMatcher``, then aggregates the result across a dataset into the
demand tables the dashboard reads.

Why ``PhraseMatcher`` instead of a trained NER model: with no labeled UK job-ad
dataset available, a supervised model would need hand-annotation before it
could beat a well-curated dictionary. ``PhraseMatcher`` over lowercased tokens
gets high-precision matches on multi-word technical terms (e.g. "power bi",
"machine learning") without that labeling cost — a deliberate, defensible
trade-off, not an accidental shortcut.

The spaCy pipeline and matcher are built once and reused; only the tokenizer is
needed, so the tagger/parser/NER/lemmatizer components are disabled for speed.
"""

from __future__ import annotations

from collections import Counter
from typing import TYPE_CHECKING

import pandas as pd

from src.skills_taxonomy import iter_all_skills, skill_to_category_map

if TYPE_CHECKING:  # pragma: no cover - import-time typing only
    from spacy.language import Language
    from spacy.matcher import PhraseMatcher

SPACY_MODEL = "en_core_web_sm"
_DISABLED_PIPES = ("ner", "parser", "tagger", "lemmatizer", "attribute_ruler")

_NLP: Language | None = None
_MATCHER: PhraseMatcher | None = None


def _get_nlp() -> Language:
    """Load (once) a tokenizer-only spaCy pipeline."""
    global _NLP
    if _NLP is None:
        import spacy

        try:
            _NLP = spacy.load(SPACY_MODEL, disable=list(_DISABLED_PIPES))
        except OSError as exc:  # pragma: no cover - environment-dependent
            raise OSError(
                f"spaCy model '{SPACY_MODEL}' not found. Install it with:\n"
                "  pip install https://github.com/explosion/spacy-models/releases/download/"
                "en_core_web_sm-3.7.1/en_core_web_sm-3.7.1-py3-none-any.whl"
            ) from exc
    return _NLP


def _get_matcher() -> PhraseMatcher:
    """Build (once) a ``PhraseMatcher`` holding every taxonomy alias."""
    global _MATCHER
    if _MATCHER is None:
        from spacy.matcher import PhraseMatcher

        nlp = _get_nlp()
        matcher = PhraseMatcher(nlp.vocab, attr="LOWER")
        for _category, canonical, alias in iter_all_skills():
            matcher.add(canonical, [nlp.make_doc(alias.strip())])
        _MATCHER = matcher
    return _MATCHER


def extract_skills(text: str) -> list[str]:
    """Return the sorted unique canonical skills found in one cleaned description."""
    if not text:
        return []
    nlp = _get_nlp()
    matcher = _get_matcher()
    matches = matcher(nlp(text.lower()))
    return sorted({nlp.vocab.strings[match_id] for match_id, _start, _end in matches})


def extract_skills_batch(texts: pd.Series, batch_size: int = 64) -> pd.Series:
    """Vectorized :func:`extract_skills` for a whole column.

    Uses ``nlp.pipe`` so tokenization is batched, which is roughly an order of
    magnitude faster than calling ``nlp()`` per row on a few thousand postings.
    """
    nlp = _get_nlp()
    matcher = _get_matcher()
    strings = nlp.vocab.strings

    results = [
        sorted({strings[match_id] for match_id, _start, _end in matcher(doc)})
        for doc in nlp.pipe(texts.fillna("").str.lower(), batch_size=batch_size)
    ]
    return pd.Series(results, index=texts.index, dtype=object)


def skill_demand_table(skills_series: pd.Series) -> pd.DataFrame:
    """Rank skills by how many postings mention them.

    Returns columns ``skill``, ``category``, ``postings_mentioning`` and
    ``pct_of_postings``, sorted most-mentioned first.
    """
    columns = ["skill", "category", "postings_mentioning", "pct_of_postings"]
    total_postings = len(skills_series)
    counter = Counter(skill for skills in skills_series for skill in skills)
    if not counter:
        return pd.DataFrame(columns=columns)

    category_of = skill_to_category_map()
    rows = [
        {
            "skill": skill,
            "category": category_of.get(skill, "Other"),
            "postings_mentioning": count,
            "pct_of_postings": round(100 * count / total_postings, 1),
        }
        for skill, count in counter.most_common()
    ]
    return pd.DataFrame(rows, columns=columns)


def skill_trend_table(
    df: pd.DataFrame,
    skills_col: str = "skills",
    date_col: str = "collected_at",
    freq: str = "W",
) -> pd.DataFrame:
    """Count skill mentions per time bucket, for "is this skill trending" charts.

    ``df[skills_col]`` must already hold real lists (see
    :func:`src.process_data.load_processed`).
    """
    columns = ["period", "skill", "mentions"]
    exploded = df[[date_col, skills_col]].explode(skills_col).dropna(subset=[skills_col])
    if exploded.empty:
        return pd.DataFrame(columns=columns)

    periods = pd.to_datetime(exploded[date_col], errors="coerce", utc=True)
    exploded = exploded.assign(period=periods.dt.tz_localize(None).dt.to_period(freq).dt.start_time)
    exploded = exploded.dropna(subset=["period"])

    trend = (
        exploded.groupby(["period", skills_col], observed=True)
        .size()
        .reset_index(name="mentions")
        .rename(columns={skills_col: "skill"})
    )
    return trend[columns].sort_values(["period", "skill"], ignore_index=True)
