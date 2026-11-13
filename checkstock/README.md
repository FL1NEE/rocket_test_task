# CheckStock — Где сейчас товар?

Веб-прототип учёта товара на складах фулфилмента (ФФ) с поддержкой FBS/FBO-отправок.

**Стек:** Python 3.13, FastAPI 0.162, PostgreSQL 17, SQLAlchemy 2.1, Alembic, Docker

---

## Быстрый запуск

```bash
# 1. Скопировать конфиг и выставить пароли
cp .env.example .env
# Отредактировать .env: POSTGRES_PASSWORD, CHECKSTOCK_USERNAME, CHECKSTOCK_PASSWORD

# 2. Запустить
docker compose up --build
```

Приложение: http://localhost:8000  
Swagger: http://localhost:8000/docs  
Health-check: http://localhost:8000/health (без авторизации)

При первом запуске автоматически создаются тестовые данные:
- Склады: **Север**, **Юг**
- Товары: SKU-101 (Органайзер), SKU-102 (Контейнер), SKU-103 (Корзина)
- Начальные остатки по условию задания

---

## Переменные окружения

| Переменная | Пример | Описание |
|---|---|---|
| `POSTGRES_PASSWORD` | `s3cr3t` | Пароль БД |
| `CHECKSTOCK_USERNAME` | `manager` | Логин Basic Auth |
| `CHECKSTOCK_PASSWORD` | `atleast12chars` | Пароль Basic Auth (мин. 12 символов) |
| `CHECKSTOCK_ALLOWED_HOSTS` | `localhost,127.0.0.1` | Разрешённые Host-заголовки |
| `DATABASE_URL` | — | Переопределяет строку подключения (необязательно) |

---

## Аутентификация

Все эндпоинты `/api/*` требуют HTTP Basic Auth. Логин и пароль задаются через `.env`.  
В браузере откроется стандартный диалог входа; в curl:

```bash
curl -u manager:yourpassword http://localhost:8000/api/stock
```

---

## Локальная разработка (без Docker)

```bash
# PostgreSQL уже запущен — только БД
docker compose up -d db

# Зависимости
python -m venv .venv && .venv\Scripts\activate
pip install --require-hashes --no-deps -r requirements.txt
pip install -r requirements-dev.txt

# Миграции + сид
alembic upgrade head
python -m app.seed

# Dev-сервер
uvicorn app.main:app --reload
```

### Тесты

```bash
# Убедиться, что TEST_DATABASE_URL смотрит на тестовую БД
pytest -q
```

Тесты поднимают настоящий PostgreSQL на порту 55432 (`docker compose up -d db`),  
при каждом прогоне TRUNCATE всех таблиц + сид.

---

## API — ключевые эндпоинты

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/products` | Список товаров |
| GET | `/api/warehouses` | Список складов |
| POST | `/api/warehouses` | Создать склад |
| DELETE | `/api/warehouses/{id}` | Мягкое удаление склада |
| POST | `/api/receipts` | Приход товара |
| GET | `/api/stock` | Матрица остатков |
| GET | `/api/stock/reconcile` | Проверка сходимости остатков |
| GET | `/api/stock/in-transit` | Товар в пути |
| POST | `/api/movements` | Создать перемещение |
| PATCH | `/api/movements/{id}/confirm` | Подтвердить прибытие |
| POST | `/api/fbs` | Создать FBS-заказ |
| POST | `/api/fbs/allocate` | Зарезервировать товар под FBS |
| PATCH | `/api/fbs/{id}/ship` | Отправить FBS-заказ |
| PATCH | `/api/fbs/{id}/deliver` | Доставить FBS-заказ |
| PATCH | `/api/fbs/{id}/cancel` | Отменить FBS-заказ |
| POST | `/api/fbo` | Создать FBO-отправку |
| PATCH | `/api/fbo/{id}/accept` | Принято МП |
| GET | `/api/operations` | История операций |

---

## Сценарии для проверки

### 1. Приход товара
Вкладка **Склады** → **Приход товара** → выбрать товар, склад, количество → «Принять».

### 2. Резерв FBS и отправка
Вкладка **FBS** → **Зарезервировать** (qty ≤ доступного) → **Отправить**.  
При нехватке на выбранном складе API возвращает список альтернатив с доступным количеством.  
Кнопки «взять с другого склада» и «разделить резерв» доступны в интерфейсе.

### 3. Перемещение между ФФ
Вкладка **Перемещения** → откуда/куда/товар/qty → **Отправить**.  
Товар числится в пути (виден на вкладке «Остатки»). **Подтвердить** — приход на склад назначения.

### 4. Отправка FBO
Вкладка **FBO** → создать → товар покидает ФФ и едет на склад МП. **Принято МП** — финальный статус.

### 5. Удаление склада
Склады → «Удалить» — двойное подтверждение (4 с). Мягкое удаление: остатки и история сохраняются.  
Удалённый склад остаётся в матрице, пока на нём есть физический товар.

### 6. Сверка остатков
`GET /api/stock/reconcile` проверяет, что:  
`принято = на_складе + в_пути + отправлено_fbo + отправлено_fbs`  
а также, что зарезервировано_fbs совпадает с открытыми FBS-заказами.

---

## Ключевые технические решения

### Модель остатков
`Inventory(product, warehouse)` хранит `physical_qty` и `reserved_fbs_qty`.  
`available = physical − reserved` — вычисляется как свойство. CheckConstraint в БД не даёт уйти в минус.

### Порядок блокировок (deadlock prevention)
Всегда: склад → документ → остаток. `SELECT FOR UPDATE` по каждому уровню.  
`INSERT … ON CONFLICT DO NOTHING` + `SELECT FOR UPDATE` решает гонку при первом создании строки остатков.

### Идемпотентность
`_lock_document()` захватывает строку документа *перед* проверкой статуса — параллельные запросы встают в очередь, а не создают дубликаты.

### Операционный журнал
`OperationLog` — append-only. PostgreSQL-триггер блокирует UPDATE/DELETE на этой таблице.

---

## Структура проекта

```
checkstock/
├── app/
│   ├── config.py         # Настройки из окружения
│   ├── database.py       # SQLAlchemy engine/session, NAMING_CONVENTION
│   ├── errors.py         # DomainError, NotFound, Conflict, InvalidState, InsufficientStock
│   ├── main.py           # FastAPI app, middleware, обработчики ошибок
│   ├── models.py         # ORM-модели (lazy="raise" на всех relations)
│   ├── schemas.py        # Pydantic v2, StrictInt, extra="forbid"
│   ├── seed.py           # Идемпотентный сид тестовых данных
│   ├── security.py       # Basic Auth, CSRF-check, BodySizeLimitMiddleware
│   ├── routers/          # Тонкие роутеры по доменам
│   └── services/
│       ├── commands.py   # Write-side: мутации с блокировками
│       └── queries.py    # Read-side: матрица, сверка, история
├── migrations/
│   └── versions/
│       ├── 0001_initial_schema.py
│       └── 0002_append_only_journal.py
├── static/
│   ├── index.html
│   ├── app.css
│   └── app.js            # esc() XSS-защита, event delegation
├── tests/
│   ├── conftest.py
│   ├── test_accounting.py
│   ├── test_fbs_shortage.py
│   ├── test_idempotency.py
│   ├── test_security.py
│   ├── test_validation.py
│   └── test_warehouses.py
├── .env.example
├── alembic.ini
├── docker-compose.yml
├── Dockerfile
├── requirements.in
├── requirements.txt       # hash-pinned
├── requirements-dev.in
└── requirements-dev.txt
```

---

## Безопасность

**OWASP Top 10:2025**

| Категория | Реализация |
|---|---|
| A01 Broken Access Control | Basic Auth на всех `/api/*`; `/health` публичный |
| A02 Cryptographic Failures | `secrets.compare_digest` (constant-time), пароль ≥ 12 символов |
| A03 Injection | SQLAlchemy ORM (параметризованные запросы); `esc()` + CSP в фронте |
| A04 Insecure Design | CQRS, доменные ошибки, reconcile-сверка, append-only журнал |
| A05 Security Misconfiguration | CSP / COOP / CORP / Permissions-Policy; Docker non-root + read-only FS |
| A06 Vulnerable Components | `pip-audit` → 0 CVE; зависимости закреплены по хешам |
| A07 Auth Failures | Единый 401, WWW-Authenticate, constant-time сравнение |
| A08 Integrity Failures | Hash-pinned lock-files; триггер append-only; `pip check` в Dockerfile |
| A09 Logging Failures | Структурированный `OperationLog` (JSONB) на каждую мутацию |
| A10 SSRF | Не применимо — приложение не делает внешних запросов |

**Дополнительно:**
- Лимит тела запроса 64 КБ (включая chunked), таймауты БД
- `TrustedHostMiddleware`, CSRF-проверка (`Sec-Fetch-Site` / `Origin`)
- 503 + `Retry-After` при lock contention (pgcode 55P03/40001/40P01)
- `Cache-Control: no-store` на всех API-ответах
