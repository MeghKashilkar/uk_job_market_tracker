"""Generate a SYNTHETIC sample dataset shaped like the Adzuna collector's output.

Exists purely so the rest of the pipeline (process_data -> skill extraction
-> salary model -> dashboard) can be smoke-tested end to end before you've
collected any real postings with your own Adzuna API key.

This is NOT real job market data. Every row is randomly generated from
templates. Do not use any numbers derived from this file in your CV, README
results tables, or anywhere else that implies real market research - swap in
real collected data first (`python -m src.collect_jobs`).

Usage:
    python scripts/generate_synthetic_sample.py --n 400
"""
from __future__ import annotations

import argparse
import random
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TypedDict

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = ROOT / "data" / "raw" / "sample_jobs_synthetic.csv"


class RoleTemplate(TypedDict):
    """Shape of one entry in :data:`ROLE_TEMPLATES`."""

    core_skills: list[str]
    bonus_skills: list[str]
    salary_range: tuple[int, int]

LOCATIONS = [
    ("London", "London"),
    ("Manchester", "North West England"),
    ("Edinburgh", "Scotland"),
    ("Bristol", "South West England"),
    ("Leeds", "Yorkshire and the Humber"),
    ("Birmingham", "West Midlands"),
    ("Glasgow", "Scotland"),
    ("Cambridge", "East of England"),
    ("Reading", "South East England"),
    ("Remote, UK", "Remote"),
]

COMPANIES = [
    "Brightfield Analytics", "Northbridge Data Co", "Kestrel Insurance Group",
    "Palmer & Vance Retail", "Solstice Bank", "Ferngate Health", "Orbital Logistics",
    "Marlow Digital", "Crestline Media", "Hawksmoor Consulting", "Veridian Energy",
    "Thistledown Public Sector", "Ironbridge Manufacturing", "Coppergate Fintech",
    "Willowmere Telecom",
]

ROLE_TEMPLATES: dict[str, RoleTemplate] = {
    "Data Analyst": {
        "core_skills": ["SQL", "Excel", "Power BI", "Python", "Statistical Analysis"],
        "bonus_skills": ["Tableau", "A/B Testing", "Stakeholder Management"],
        "salary_range": (28000, 48000),
    },
    "Senior Data Analyst": {
        "core_skills": [
            "SQL", "Python", "Tableau", "Power BI",
            "Statistical Analysis", "Stakeholder Management",
        ],
        "bonus_skills": ["Snowflake", "dbt", "Forecasting"],
        "salary_range": (42000, 62000),
    },
    "Data Engineer": {
        "core_skills": ["Python", "SQL", "Airflow", "Spark", "AWS", "Docker", "ETL/ELT"],
        "bonus_skills": ["Kafka", "Kubernetes", "Snowflake", "dbt", "CI/CD"],
        "salary_range": (45000, 75000),
    },
    "Senior Data Engineer": {
        "core_skills": [
            "Python", "SQL", "Spark", "Airflow", "AWS", "Docker", "Kubernetes", "ETL/ELT",
        ],
        "bonus_skills": ["Kafka", "Databricks", "CI/CD", "Git"],
        "salary_range": (65000, 95000),
    },
    "Data Scientist": {
        "core_skills": [
            "Python", "Machine Learning", "SQL", "Statistical Analysis", "scikit-learn",
        ],
        "bonus_skills": ["Deep Learning", "NLP", "A/B Testing", "TensorFlow"],
        "salary_range": (42000, 68000),
    },
    "Senior Data Scientist": {
        "core_skills": [
            "Python", "Machine Learning", "Deep Learning", "SQL",
            "scikit-learn", "Statistical Analysis",
        ],
        "bonus_skills": ["NLP", "PyTorch", "LLMs / GenAI", "MLOps"],
        "salary_range": (60000, 92000),
    },
    "Machine Learning Engineer": {
        "core_skills": ["Python", "Machine Learning", "Docker", "AWS", "MLOps", "Git"],
        "bonus_skills": ["TensorFlow", "PyTorch", "Kubernetes", "CI/CD", "LLMs / GenAI"],
        "salary_range": (55000, 90000),
    },
    "Business Intelligence Analyst": {
        "core_skills": ["SQL", "Power BI", "Excel", "Data Modeling"],
        "bonus_skills": ["Tableau", "Qlik", "Azure"],
        "salary_range": (32000, 52000),
    },
    "Analytics Engineer": {
        "core_skills": ["SQL", "dbt", "Python", "Snowflake", "Data Modeling"],
        "bonus_skills": ["Airflow", "BigQuery", "Git"],
        "salary_range": (45000, 72000),
    },
    "Head of Data": {
        "core_skills": ["Stakeholder Management", "Project Management", "SQL", "Data Modeling"],
        "bonus_skills": ["AWS", "Machine Learning", "Agile"],
        "salary_range": (80000, 130000),
    },
}

CONTRACT_TYPES = ["permanent", "contract"]
CONTRACT_TIMES = ["full_time", "part_time"]

DESCRIPTION_INTRO = [
    "We are looking for a {title} to join our growing data team in {location}.",
    "Exciting opportunity for a {title} to make an impact at a fast-growing company "
    "based in {location}.",
    "{company} is hiring a {title} to help shape our data strategy.",
]

DESCRIPTION_SKILL_INTRO = [
    "<p>Key skills and experience:</p><ul>{skill_bullets}</ul>",
    "You will bring the following: {skill_list}.",
]

DESCRIPTION_OUTRO = [
    "<p>We offer a competitive salary, hybrid working, and 25 days holiday.</p>",
    "Apply now via the link below to find out more &amp; join our team!",
    "This role offers excellent progression opportunities within a supportive team.",
]


def _build_description(
    title: str, company: str, location: str, skills: list[str], rng: random.Random
) -> str:
    """Assemble one fake advert, half with an HTML bullet list and half prose."""
    intro = rng.choice(DESCRIPTION_INTRO).format(title=title, company=company, location=location)
    if rng.random() < 0.5:
        bullets = "".join(f"<li>{s}</li>" for s in skills)
        skills_block = DESCRIPTION_SKILL_INTRO[0].format(skill_bullets=bullets)
    else:
        skills_block = DESCRIPTION_SKILL_INTRO[1].format(skill_list=", ".join(skills))
    outro = rng.choice(DESCRIPTION_OUTRO)
    return f"{intro} {skills_block} {outro}"


def generate(n: int, seed: int = 42) -> pd.DataFrame:
    """Build ``n`` deterministic synthetic postings for pipeline smoke tests."""
    rng = random.Random(seed)
    np_rng = np.random.RandomState(seed)

    role_names = list(ROLE_TEMPLATES.keys())
    now = datetime.now(UTC)

    rows = []
    for i in range(n):
        role = rng.choice(role_names)
        template = ROLE_TEMPLATES[role]
        location, region = rng.choice(LOCATIONS)
        company = rng.choice(COMPANIES)

        n_bonus = rng.randint(0, len(template["bonus_skills"]))
        skills = template["core_skills"] + rng.sample(template["bonus_skills"], n_bonus)
        rng.shuffle(skills)

        description = _build_description(role, company, location, skills, rng)

        salary_min: float | None = None
        salary_max: float | None = None
        if rng.random() < 0.55:  # Adzuna only reports salary on a subset
            low, high = template["salary_range"]
            midpoint = float(np_rng.uniform(low, high))
            spread = midpoint * 0.08
            salary_min = round(midpoint - spread, -2)
            salary_max = round(midpoint + spread, -2)

        days_ago = rng.randint(0, 42)  # spread postings over ~6 weeks for trend charts
        created = now - timedelta(days=days_ago, hours=rng.randint(0, 23))
        collected_at = created + timedelta(hours=rng.randint(1, 48))

        rows.append(
            {
                "id": f"synthetic-{i:05d}",
                "title": f"{role} - {company}" if rng.random() < 0.3 else role,
                "company": company,
                "location": location,
                "region": region,
                "description": description,
                "salary_min": salary_min,
                "salary_max": salary_max,
                "salary_is_predicted": False,
                "contract_type": rng.choice(CONTRACT_TYPES),
                "contract_time": rng.choice(CONTRACT_TIMES),
                "category": "IT Jobs",
                "created": created.isoformat(),
                "redirect_url": f"https://example-jobs.invalid/job/{i}",
                "query": role.lower(),
                "collected_at": collected_at.isoformat(),
            }
        )

    return pd.DataFrame(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate a synthetic sample job-postings dataset")
    parser.add_argument("--n", type=int, default=400)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", default=str(OUTPUT_PATH))
    args = parser.parse_args()

    df = generate(args.n, seed=args.seed)
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(out_path, index=False)
    print(f"[generate_synthetic_sample] Wrote {len(df)} SYNTHETIC rows to {out_path}")
    print("[generate_synthetic_sample] Reminder: this is fake data for pipeline testing only.")
