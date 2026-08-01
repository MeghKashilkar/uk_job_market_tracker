"""Curated skills taxonomy for UK data/tech job postings.

Structure: ``SKILLS_TAXONOMY`` maps a category -> {canonical_skill: [aliases]}.
Aliases exist because job descriptions are inconsistent ("Power BI" vs
"PowerBI" vs "power-bi", "ML" vs "machine learning"). Everything gets matched
case-insensitively; the canonical name is what shows up in reports and the
dashboard.

This is hand-curated rather than mined from the data on purpose - it is a
domain-knowledge artifact you can defend in an interview ("here's why I
grouped dbt under data engineering and not analytics engineering tooling
alone"), and it is easy to extend as you notice gaps in real postings.
"""

from __future__ import annotations

from collections.abc import Iterator

SKILLS_TAXONOMY: dict[str, dict[str, list[str]]] = {
    "Programming Languages": {
        "Python": ["python"],
        "SQL": ["sql", "t-sql", "pl/sql", "mysql queries"],
        "R": ["r programming", " r,", " r."],
        "Java": ["java"],
        "Scala": ["scala"],
        "JavaScript": ["javascript", "js"],
        "C++": ["c++"],
        "C#": ["c#"],
        "VBA": ["vba"],
        "Bash": ["bash", "shell scripting"],
    },
    "Databases & Warehouses": {
        "PostgreSQL": ["postgresql", "postgres"],
        "MySQL": ["mysql"],
        "SQL Server": ["sql server", "microsoft sql server", "mssql"],
        "Oracle": ["oracle db", "oracle database"],
        "MongoDB": ["mongodb"],
        "Snowflake": ["snowflake"],
        "BigQuery": ["bigquery", "big query"],
        "Redshift": ["redshift"],
        "Databricks": ["databricks"],
    },
    "BI & Visualization": {
        "Power BI": ["power bi", "powerbi"],
        "Tableau": ["tableau"],
        "Looker": ["looker"],
        "Qlik": ["qlik", "qlikview", "qliksense"],
        "Excel": ["excel", "advanced excel"],
        "Google Data Studio": ["data studio", "looker studio"],
    },
    "Cloud Platforms": {
        "AWS": ["aws", "amazon web services"],
        "Azure": ["azure", "microsoft azure"],
        "GCP": ["gcp", "google cloud"],
    },
    "Data Engineering": {
        "Airflow": ["airflow"],
        "dbt": ["dbt", "data build tool"],
        "Spark": ["spark", "pyspark", "apache spark"],
        "Kafka": ["kafka"],
        "Docker": ["docker"],
        "Kubernetes": ["kubernetes", "k8s"],
        "ETL/ELT": ["etl", "elt", "data pipelines"],
        "Git": ["git", "github", "gitlab", "version control"],
        "CI/CD": ["ci/cd", "continuous integration"],
    },
    "Machine Learning & AI": {
        "Machine Learning": ["machine learning", " ml,", " ml.", "ml models"],
        "Deep Learning": ["deep learning", "neural network"],
        "NLP": ["nlp", "natural language processing"],
        "Computer Vision": ["computer vision"],
        "scikit-learn": ["scikit-learn", "sklearn"],
        "TensorFlow": ["tensorflow"],
        "PyTorch": ["pytorch"],
        "LLMs / GenAI": ["llm", "large language model", "generative ai", "genai", "gpt"],
        "MLOps": ["mlops"],
    },
    "Statistics & Analytics Methods": {
        "Statistical Analysis": ["statistical analysis", "statistics", "hypothesis testing"],
        "A/B Testing": ["a/b testing", "ab testing", "experimentation"],
        "Forecasting": ["forecasting", "time series"],
        "Data Modeling": ["data modeling", "data modelling", "dimensional modeling"],
    },
    "Methodology & Soft Skills": {
        "Agile": ["agile", "scrum", "kanban"],
        "Stakeholder Management": ["stakeholder management", "stakeholder engagement"],
        "Communication": ["communication skills", "presentation skills"],
        "Project Management": ["project management"],
    },
    "Qualifications": {
        "Degree Required": ["bachelor's degree", "degree in", "bsc", "msc", "phd"],
        "SC Clearance": ["sc clearance", "security clearance"],
    },
}


def iter_all_skills() -> Iterator[tuple[str, str, str]]:
    """Yield ``(category, canonical_skill, alias)`` for every alias."""
    for category, skills in SKILLS_TAXONOMY.items():
        for canonical, aliases in skills.items():
            for alias in aliases:
                yield category, canonical, alias


def skill_to_category_map() -> dict[str, str]:
    """Map every canonical skill name to the category that owns it."""
    return {
        canonical: category
        for category, skills in SKILLS_TAXONOMY.items()
        for canonical in skills
    }


def skill_count_column(category: str) -> str:
    """Column name holding the per-posting skill count for ``category``.

    Defined here so the processing step and the model's feature list can never
    drift apart on naming.
    """
    return f"n_{category.replace(' ', '_').replace('&', 'and')}"


def skill_count_columns() -> list[str]:
    """Skill-count column names, in taxonomy order."""
    return [skill_count_column(category) for category in SKILLS_TAXONOMY]


def total_skill_count() -> int:
    """Number of distinct canonical skills across all categories."""
    return sum(len(skills) for skills in SKILLS_TAXONOMY.values())
