# Задание 1: Умный суммаризатор тендерной документации

FastAPI-сервис, принимающий PDF-файл тендерной документации и возвращающий
структурированную выжимку с помощью Claude (Anthropic API).

## Запуск

```bash
pip install -r requirements.txt
cp .env.example .env   # и вписать ANTHROPIC_API_KEY
uvicorn main:app --reload
```

## Использование

```bash
curl -X POST http://localhost:8000/summarize \
  -F "file=@tender.pdf"
```

Ответ (пример):

```json
{
  "contract_amount": "12 500 000 руб.",
  "execution_deadline": "до 31.12.2026",
  "contractor_requirements": [
    "Опыт выполнения аналогичных работ не менее 3 лет",
    "Наличие СРО-допуска"
  ],
  "penalties": [
    {"description": "Просрочка исполнения обязательств", "amount_or_rate": "0.1% от суммы контракта за каждый день"}
  ],
  "summary": "Тендер на выполнение..."
}
```

## Ограничения

- Работает только с PDF, содержащими текстовый слой (не сканы без OCR).
- Модель по умолчанию: `claude-sonnet-5`.