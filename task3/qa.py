# -*- coding: utf-8 -*-
import anthropic

MODEL_NAME: str = "claude-sonnet-5"
MAX_OUTPUT_TOKENS: int = 1024

client: anthropic.Anthropic = anthropic.Anthropic()


def build_qa_prompt(question: str, context_chunks: list[str]) -> str:
    numbered_context: str = "\n\n".join(
        f"[Фрагмент {i + 1}]\n{chunk}" for i, chunk in enumerate(context_chunks)
    )
    prompt: str = \
    (
        "Ты — ассистент, отвечающий на вопросы строго на основе предоставленных "
        "фрагментов документа (регламента компании). Не используй знания извне "
        "документа. Если ответа в фрагментах нет — прямо скажи, что информация "
        "в документе отсутствует.\n\n"
        f"Фрагменты документа:\n{numbered_context}\n\n"
        f"Вопрос: {question}\n\n"
        "Дай точный ответ и укажи, на какие фрагменты (по номеру) ты опираешься."
    )
    return prompt


def answer_question(question: str, context_chunks: list[str]) -> str:
    if not context_chunks:
        return "В базе знаний пока нет загруженных документов."

    response = client.messages.create(
        model = MODEL_NAME,
        max_tokens = MAX_OUTPUT_TOKENS,
        messages = \
        [
            {
                "role": "user",
                "content": build_qa_prompt(question, context_chunks)
            }
        ]
    )

    if response.stop_reason == "refusal":
        return "Модель отказалась отвечать на этот вопрос."

    answer_text: str = next(block.text for block in response.content if block.type == "text")
    return answer_text