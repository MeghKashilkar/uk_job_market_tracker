"""Train and compare salary-prediction regressors on the processed dataset.

Usage::

    python -m src.train_salary_model --input data/processed/jobs_processed.csv

Saves ``models/salary_model.pkl``, ``models/salary_preprocessor.pkl``,
``models/salary_model_metadata.json``, ``reports/salary_model_comparison.csv``
and ``reports/figures/salary_predicted_vs_actual.png``.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import LinearRegression, Ridge
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
from sklearn.model_selection import KFold, cross_val_score

from src.process_data import load_processed
from src.salary_model import RANDOM_STATE, build_preprocessor, build_xy, split_data

ROOT = Path(__file__).resolve().parents[1]
MODELS_DIR = ROOT / "models"
REPORTS_DIR = ROOT / "reports"
FIGURES_DIR = REPORTS_DIR / "figures"

DEFAULT_INPUT = ROOT / "data" / "processed" / "jobs_processed.csv"
DEFAULT_CV_FOLDS = 5
MIN_ROWS_REQUIRED = 40  # below this, train/test metrics are too noisy to trust


def build_models() -> dict[str, Any]:
    """The four regressors compared on every run."""
    from xgboost import XGBRegressor

    return {
        "linear_regression": LinearRegression(),
        "ridge": Ridge(alpha=1.0, random_state=RANDOM_STATE),
        "random_forest": RandomForestRegressor(
            n_estimators=300,
            max_depth=10,
            min_samples_leaf=3,
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
        "xgboost": XGBRegressor(
            n_estimators=300,
            max_depth=4,
            learning_rate=0.05,
            subsample=0.8,
            colsample_bytree=0.8,
            random_state=RANDOM_STATE,
            n_jobs=-1,
        ),
    }


def evaluate(model: Any, features: Any, target_log: pd.Series) -> dict[str, float]:
    """Score a fitted model on both the log scale it trained on and in £."""
    predicted_log = model.predict(features)
    predicted_gbp = np.exp(predicted_log)
    actual_gbp = np.exp(target_log)

    return {
        "mae_gbp": float(mean_absolute_error(actual_gbp, predicted_gbp)),
        "rmse_gbp": float(np.sqrt(mean_squared_error(actual_gbp, predicted_gbp))),
        "r2": float(r2_score(target_log, predicted_log)),
        "mae_log": float(mean_absolute_error(target_log, predicted_log)),
    }


def save_diagnostic_plot(actual_log: pd.Series, predicted_log: np.ndarray, model_name: str) -> None:
    """Write a predicted-vs-actual scatter for the winning model."""
    import matplotlib

    matplotlib.use("Agg")  # headless: no display needed on CI or a server
    import matplotlib.pyplot as plt

    actual_gbp = np.exp(actual_log)
    figure, axes = plt.subplots(figsize=(6, 6))
    axes.scatter(actual_gbp, np.exp(predicted_log), alpha=0.4, s=15)
    limits = [float(actual_gbp.min()), float(actual_gbp.max())]
    axes.plot(limits, limits, "--", color="gray")
    axes.set_xlabel("Actual salary (£)")
    axes.set_ylabel("Predicted salary (£)")
    axes.set_title(f"Predicted vs Actual - {model_name}")
    figure.tight_layout()
    figure.savefig(FIGURES_DIR / "salary_predicted_vs_actual.png", dpi=150)
    plt.close(figure)


def train(input_path: Path | str, cv_folds: int = DEFAULT_CV_FOLDS) -> pd.DataFrame:
    """Train every candidate model, persist the best, and return the comparison."""
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    FIGURES_DIR.mkdir(parents=True, exist_ok=True)

    df = load_processed(Path(input_path))
    features, target = build_xy(df)
    print(
        f"[train_salary_model] {len(features)} rows have usable salary data "
        f"(of {len(df)} total postings)."
    )
    if len(features) < MIN_ROWS_REQUIRED:
        print(
            f"[train_salary_model] WARNING: only {len(features)} salaried rows - below the "
            f"{MIN_ROWS_REQUIRED}-row sanity threshold. Metrics below will be noisy; "
            "collect more data with src.collect_jobs before trusting this model."
        )

    x_train, x_test, y_train, y_test = split_data(features, target)
    preprocessor = build_preprocessor()
    x_train_t = preprocessor.fit_transform(x_train)
    x_test_t = preprocessor.transform(x_test)

    n_splits = min(cv_folds, max(2, len(x_train) // 10))
    cv = KFold(n_splits=n_splits, shuffle=True, random_state=RANDOM_STATE)

    results: list[dict[str, Any]] = []
    fitted: dict[str, Any] = {}
    for name, model in build_models().items():
        cv_scores = cross_val_score(model, x_train_t, y_train, cv=cv, scoring="r2")
        model.fit(x_train_t, y_train)
        metrics = evaluate(model, x_test_t, y_test)
        results.append(
            {
                "model": name,
                "cv_r2_mean": float(cv_scores.mean()),
                "cv_r2_std": float(cv_scores.std()),
                **metrics,
            }
        )
        fitted[name] = model
        print(
            f"[train_salary_model] {name}: R2={metrics['r2']:.3f}  "
            f"MAE=£{metrics['mae_gbp']:,.0f}  "
            f"CV R2={cv_scores.mean():.3f}±{cv_scores.std():.3f}"
        )

    comparison = pd.DataFrame(results).sort_values("r2", ascending=False, ignore_index=True)
    comparison.to_csv(REPORTS_DIR / "salary_model_comparison.csv", index=False)
    print("\n[train_salary_model] Comparison:\n", comparison.to_string(index=False))

    best_name = str(comparison.loc[0, "model"])
    best_model = fitted[best_name]
    print(f"\n[train_salary_model] Best model: {best_name}")

    joblib.dump(best_model, MODELS_DIR / "salary_model.pkl")
    joblib.dump(preprocessor, MODELS_DIR / "salary_preprocessor.pkl")
    (MODELS_DIR / "salary_model_metadata.json").write_text(
        json.dumps(
            {
                "best_model_name": best_name,
                "n_training_rows": len(features),
                "metrics": comparison.loc[0].drop("model").to_dict(),
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    save_diagnostic_plot(y_test, best_model.predict(x_test_t), best_name)
    print(
        f"[train_salary_model] Saved model + comparison + plot to "
        f"{MODELS_DIR}/ and {REPORTS_DIR}/"
    )
    return comparison


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Train and compare salary regression models",
    )
    parser.add_argument("--input", default=str(DEFAULT_INPUT))
    parser.add_argument("--cv-folds", type=int, default=DEFAULT_CV_FOLDS)
    args = parser.parse_args()

    train(args.input, cv_folds=args.cv_folds)


if __name__ == "__main__":
    main()
