# -*- coding: utf-8 -*-
import io
import os

import anthropic
from fastapi import FastAPI, File, HTTPException, UploadFile
from pydantic import BaseModel, Field
from pypdf import PdfReader

MODEL_NAME: str = "claude-sonnet-5"
MAX_OUTPUT_TOKENS: int = 4096

client: anthropic.Anthropic = anthropic.Anthropic()

app: FastAPI = FastAPI(
    title = "Тендерный суммаризатор",
    description="Извлекает ключевые условия тендера из PDF с помощью Claude",
    version="1"
)


class Penalty(BaseModel):
    description: str = Field(description="За что налагается штраф")
    amount_or_rate: str = Field(description="Сумма или ставка штрафа (как указано в тексте)")


class TenderSummary(BaseModel):
    contract_amount: str | None = Field(
        default=None, description="Сумма контракта (НМЦК), как указано в документе"
    )
    execution_deadline: str | None = Field(
        default=None, description="Сроки выполнения работ/оказания услуг"
    )
    contractor_requirements: list[str] = Field(
        default_factory=list, description="Ключевые требования к исполнителю"
    )
    penalties: list[Penalty] = Field(
        default_factory=list, description="Список штрафов и неустоек"
    )
    summary: str = Field(description="Краткое текстовое резюме документа (3-5 предложений)")


TENDER_SUMMARY_JSON_SCHEMA: dict = \
{
    "type": "object",
    "properties": {
        "contract_amount": {"type": ["string", "null"]},
        "execution_deadline": {"type": ["string", "null"]},
        "contractor_requirements": {"type": "array", "items": {"type": "string"}},
        "penalties": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "description": {"type": "string"},
                    "amount_or_rate": {"type": "string"},
                },
                "required": ["description", "amount_or_rate"],
                "additionalProperties": False,
            },
        },
        "summary": {"type": "string"},
    },
    "required": [
        "contract_amount",
        "execution_deadline",
        "contractor_requirements",
        "penalties",
        "summary",
    ],
    "additionalProperties": False
}


def extract_text_from_pdf(file_bytes: bytes) -> str:
    reader: PdfReader = PdfReader(io.BytesIO(file_bytes))
    pages_text: list[str] = [page.extract_text() or "" for page in reader.pages]
    full_text: str = "\n\n".join(pages_text).strip()
    if not full_text:
        raise HTTPException(
            status_code=422, detail="Не удалось извлечь текст из PDF (возможно, скан без OCR-слоя)"
        )
    return full_text


def build_prompt(tender_text: str) -> str:
    prompt: str = \
    (
        "Проанализируй следующую тендерную документацию (госзакупка) и извлеки "
        "ключевую информацию строго по заданной схеме.\n\n"
        "Требования:\n"
        "- contract_amount: сумма контракта/НМЦК с валютой, как в тексте.\n"
        "- execution_deadline: сроки выполнения работ/услуг.\n"
        "- contractor_requirements: список конкретных требований к исполнителю "
        "(лицензии, опыт, квалификация, финансовые гарантии и т.п.).\n"
        "- penalties: все штрафы, пени, неустойки с указанием за что и в каком размере.\n"
        "- summary: краткое резюме документа на 3-5 предложений.\n\n"
        "Если какое-то поле не найдено в тексте — оставь null или пустой список, "
        "не придумывай данные.\n\n"
        f"Текст документа:\n{tender_text}"
    )
    return prompt


def summarize_tender(tender_text: str) -> TenderSummary:
    response = client.messages.create(
        model = MODEL_NAME,
        max_tokens = MAX_OUTPUT_TOKENS,
        output_config = \
        {
            "format": \
            {
                "type": "json_schema",
                "schema": TENDER_SUMMARY_JSON_SCHEMA
            }
        },
        messages = \
        [
            {
                "role": "user",
                "content": build_prompt(tender_text)
            }
        ]
    )

    if response.stop_reason == "refusal":
        raise HTTPException(status_code = 422, detail = "Модель отказалась обрабатывать документ")

    raw_json: str = next(block.text for block in response.content if block.type == "text")
    return TenderSummary.model_validate_json(raw_json)


@app.post("/summarize", response_model=TenderSummary)
async def summarize_endpoint(file: UploadFile = File(...)) -> TenderSummary:
    if file.content_type != "application/pdf":
        raise HTTPException(status_code=400, detail="Ожидается файл в формате PDF")

    file_bytes: bytes = await file.read()
    tender_text: str = extract_text_from_pdf(file_bytes)
    summary: TenderSummary = summarize_tender(tender_text)
    return summary


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8000)))