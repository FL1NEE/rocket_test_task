# -*- coding: utf-8 -*-
import json
import os

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer

EMBEDDING_MODEL_NAME: str = "paraphrase-multilingual-MiniLM-L12-v2"
INDEX_DIR: str = "data"
INDEX_PATH: str = os.path.join(INDEX_DIR, "index.faiss")
CHUNKS_PATH: str = os.path.join(INDEX_DIR, "chunks.json")

_embedding_model: SentenceTransformer | None = None


def get_embedding_model() -> SentenceTransformer:
    global _embedding_model
    if _embedding_model is None:
        _embedding_model = SentenceTransformer(EMBEDDING_MODEL_NAME)
    return _embedding_model


class VectorStore:
    def __init__(self) -> None:
        self.model: SentenceTransformer = get_embedding_model()
        self.dimension: int = self.model.get_sentence_embedding_dimension()
        self.index: faiss.IndexFlatIP = faiss.IndexFlatIP(self.dimension)
        self.chunks: list[str] = []

    def embed(self, texts: list[str]) -> np.ndarray:
        embeddings: np.ndarray = self.model.encode(
            texts, convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
        )
        return embeddings.astype("float32")

    def add_texts(self, texts: list[str]) -> None:
        if not texts:
            return
        vectors: np.ndarray = self.embed(texts)
        self.index.add(vectors)
        self.chunks.extend(texts)

    def search(self, query: str, top_k: int = 4) -> list[tuple[str, float]]:
        if self.index.ntotal == 0:
            return []
        query_vector: np.ndarray = self.embed([query])
        scores, indices = self.index.search(query_vector, min(top_k, self.index.ntotal))
        results: list[tuple[str, float]] = [
            (self.chunks[idx], float(score))
            for idx, score in zip(indices[0], scores[0])
            if idx != -1
        ]
        return results

    def save(self) -> None:
        os.makedirs(INDEX_DIR, exist_ok=True)
        faiss.write_index(self.index, INDEX_PATH)
        with open(CHUNKS_PATH, mode="w", encoding="utf-8") as chunks_file:
            json.dump(self.chunks, chunks_file, ensure_ascii=False)

    def load(self) -> bool:
        if not (os.path.exists(INDEX_PATH) and os.path.exists(CHUNKS_PATH)):
            return False
        self.index = faiss.read_index(INDEX_PATH)
        with open(CHUNKS_PATH, mode="r", encoding="utf-8") as chunks_file:
            self.chunks = json.load(chunks_file)
        return True