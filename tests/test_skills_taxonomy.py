"""Integrity checks on the curated skills taxonomy."""

from src.skills_taxonomy import (
    SKILLS_TAXONOMY,
    iter_all_skills,
    skill_count_column,
    skill_count_columns,
    skill_to_category_map,
    total_skill_count,
)


def test_taxonomy_has_no_duplicate_canonical_names_across_categories():
    seen: set[str] = set()
    for skills in SKILLS_TAXONOMY.values():
        for canonical in skills:
            assert canonical not in seen, f"'{canonical}' appears in more than one category"
            seen.add(canonical)


def test_skill_to_category_map_covers_every_skill():
    assert len(skill_to_category_map()) == total_skill_count()


def test_iter_all_skills_yields_every_alias():
    expected = sum(len(a) for skills in SKILLS_TAXONOMY.values() for a in skills.values())
    assert len(list(iter_all_skills())) == expected


def test_key_skills_present():
    mapping = skill_to_category_map()
    for expected_skill in ["Python", "SQL", "Power BI", "AWS", "Machine Learning", "dbt"]:
        assert expected_skill in mapping


def test_no_empty_aliases():
    """An empty alias would match every document and poison the demand table."""
    for _category, canonical, alias in iter_all_skills():
        assert alias.strip(), f"'{canonical}' has an empty alias"


def test_skill_count_columns_are_unique_and_sanitised():
    columns = skill_count_columns()
    assert len(columns) == len(SKILLS_TAXONOMY) == len(set(columns))
    assert all(" " not in column and "&" not in column for column in columns)


def test_skill_count_column_is_derived_from_the_category_name():
    assert skill_count_column("Machine Learning & AI") == "n_Machine_Learning_and_AI"
