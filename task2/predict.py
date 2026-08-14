# -*- coding: utf-8 -*-
import sys

from joblib import load
from sklearn.pipeline import Pipeline

MODEL_PATH: str = "tz_classifier.joblib"


def load_model(path: str = MODEL_PATH) -> Pipeline:
    pipeline: Pipeline = load(path)
    return pipeline


def classify_text(text: str, pipeline: Pipeline) -> tuple[str, float]:
    predicted_category: str = pipeline.predict([text])[0]
    probabilities = pipeline.predict_proba([text])[0]
    class_index: int = list(pipeline.classes_).index(predicted_category)
    confidence: float = float(probabilities[class_index])
    return predicted_category, confidence


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print('Использование: python predict.py "текст ТЗ"')
        sys.exit(1)

    input_text: str = " ".join(sys.argv[1:])
    model: Pipeline = load_model()
    category, score = classify_text(input_text, model)
    print(f"Категория: {category} (уверенность: {score:.2%})")