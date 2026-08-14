# -*- coding: utf-8 -*-
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel

from chunking import split_into_chunks
from qa import answer_question
from vector_store import VectorStore

TOP_K: int = 4

app: FastAPI = FastAPI(
    title = "RAG по базе знаний",
    description = "Загрузка текстового документа + поиск релевантного контекста + ответ через Claude",
    version = "1"
)

store: VectorStore = VectorStore()
store.load()


class IngestResponse(BaseModel):
    chunks_added: int
    total_chunks: int


class AskRequest(BaseModel):
    question: str


class Source(BaseModel):
    text: str
    score: float


class AskResponse(BaseModel):
    answer: str
    sources: list[Source]


@app.post("/ingest", response_model=IngestResponse)
async def ingest_endpoint(file: UploadFile = File(...)) -> IngestResponse:
    allowed_types: tuple[str, ...] = ("text/plain", "text/markdown", "application/octet-stream")
    if file.content_type not in allowed_types and not file.filename.endswith((".txt", ".md")):
        raise HTTPException(status_code = 400, detail = "Ожидается текстовый файл (.txt/.md)")

    raw_bytes: bytes = await file.read()
    text: str = raw_bytes.decode("utf-8", errors = "ignore")
    if not text.strip():
        raise HTTPException(status_code = 422, detail = "Файл пуст или не удалось прочитать текст")

    chunks: list[str] = split_into_chunks(text)
    store.add_texts(chunks)
    store.save()

    return IngestResponse(chunks_added = len(chunks), total_chunks = len(store.chunks))


@app.post("/ask", response_model=AskResponse)
async def ask_endpoint(request: AskRequest) -> AskResponse:
    if not request.question.strip():
        raise HTTPException(status_code = 400, detail = "Вопрос не может быть пустым")

    search_results: list[tuple[str, float]] = store.search(request.question, top_k = TOP_K)
    context_chunks: list[str] = [chunk for chunk, _ in search_results]

    answer_text: str = answer_question(request.question, context_chunks)

    sources: list[Source] = [Source(text = chunk, score = score) for chunk, score in search_results]
    return AskResponse(answer = answer_text, sources = sources)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "total_chunks": len(store.chunks)}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8001)))