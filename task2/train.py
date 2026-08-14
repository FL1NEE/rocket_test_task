# -*- coding: utf-8 -*-
import pandas as pd
from joblib import dump
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import classification_report
from sklearn.model_selection import StratifiedKFold, cross_val_predict
from sklearn.pipeline import Pipeline

from dataset import save_dataset_csv

DATASET_PATH: str = "tz_dataset.csv"
MODEL_PATH: str = "tz_classifier.joblib"
RANDOM_STATE: int = 42
N_SPLITS: int = 5


def load_dataframe() -> pd.DataFrame:
    save_dataset_csv(DATASET_PATH)
    dataframe: pd.DataFrame = pd.read_csv(DATASET_PATH)
    return dataframe


def build_pipeline() -> Pipeline:
    vectorizer: TfidfVectorizer = TfidfVectorizer(
        analyzer = "char_wb",
        ngram_range = (3, 5),
        sublinear_tf = True,
        lowercase = True
    )
    classifier: LogisticRegression = LogisticRegression(
        max_iter = 2000,
        C = 10.0,
        class_weight = "balanced",
        random_state = RANDOM_STATE,
    )
    pipeline: Pipeline = Pipeline(
        steps = \
        [
            ("tfidf", vectorizer),
            ("clf", classifier)
        ]
    )
    return pipeline


def train_and_evaluate() -> Pipeline:
    dataframe: pd.DataFrame = load_dataframe()

    cross_validator: StratifiedKFold = StratifiedKFold(
        n_splits = N_SPLITS, shuffle = True, random_state = RANDOM_STATE
    )
    y_pred = cross_val_predict(
        build_pipeline(),
        dataframe["text"],
        dataframe["category"],
        cv = cross_validator,
    )
    report: str = classification_report(dataframe["category"], y_pred, zero_division = 0)
    print(f"Отчёт по {N_SPLITS}-fold кросс-валидации:\n", report)

    final_pipeline: Pipeline = build_pipeline()
    final_pipeline.fit(dataframe["text"], dataframe["category"])

    dump(final_pipeline, MODEL_PATH)
    print(f"Модель сохранена в {MODEL_PATH}")
    return final_pipeline


if __name__ == "__main__":
    train_and_evaluate()