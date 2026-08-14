BEGIN;
CREATE TABLE companies (
    id                  BIGSERIAL PRIMARY KEY,
    name                VARCHAR(500) NOT NULL,
    inn                 VARCHAR(12) NOT NULL UNIQUE,
    kpp                 VARCHAR(9),
    company_type        VARCHAR(20) NOT NULL DEFAULT 'participant'
                            CHECK (company_type IN ('customer', 'participant', 'both')),
    registration_date   DATE,
    is_active           BOOLEAN NOT NULL DEFAULT TRUE,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMENT ON TABLE companies IS 'Компании-заказчики и компании-участники тендеров';

CREATE TABLE tenders (
    id                  BIGSERIAL PRIMARY KEY,
    customer_id         BIGINT NOT NULL REFERENCES companies (id) ON DELETE RESTRICT,
    title               VARCHAR(500) NOT NULL,
    description         TEXT,
    tender_number        VARCHAR(100) NOT NULL UNIQUE,
    status              VARCHAR(20) NOT NULL DEFAULT 'draft'
                            CHECK (status IN ('draft', 'published', 'bidding', 'completed', 'cancelled')),
    publish_date        TIMESTAMPTZ,
    submission_deadline TIMESTAMPTZ,
    total_amount        NUMERIC(15, 2) NOT NULL CHECK (total_amount >= 0),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT chk_tender_dates CHECK (submission_deadline IS NULL OR publish_date IS NULL OR submission_deadline > publish_date)
);

COMMENT ON TABLE tenders IS 'Тендеры (закупки), публикуемые компаниями-заказчиками';

CREATE TABLE lots (
    id              BIGSERIAL PRIMARY KEY,
    tender_id       BIGINT NOT NULL REFERENCES tenders (id) ON DELETE CASCADE,
    lot_number      INTEGER NOT NULL CHECK (lot_number > 0),
    title           VARCHAR(500) NOT NULL,
    category        VARCHAR(150),
    starting_price  NUMERIC(15, 2) NOT NULL CHECK (starting_price >= 0),
    final_price     NUMERIC(15, 2) CHECK (final_price IS NULL OR final_price >= 0),
    status          VARCHAR(20) NOT NULL DEFAULT 'open'
                        CHECK (status IN ('open', 'bidding_closed', 'awarded', 'cancelled')),
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (tender_id, lot_number)
);

COMMENT ON TABLE lots IS 'Лоты в составе тендера';

CREATE TABLE bids (
    id              BIGSERIAL PRIMARY KEY,
    lot_id          BIGINT NOT NULL REFERENCES lots (id) ON DELETE CASCADE,
    company_id      BIGINT NOT NULL REFERENCES companies (id) ON DELETE RESTRICT,
    amount          NUMERIC(15, 2) NOT NULL CHECK (amount >= 0),
    submitted_at    TIMESTAMPTZ NOT NULL DEFAULT now(),
    status          VARCHAR(20) NOT NULL DEFAULT 'submitted'
                        CHECK (status IN ('submitted', 'won', 'rejected', 'withdrawn')),
    UNIQUE (lot_id, company_id)
);

COMMENT ON TABLE bids IS 'Ставки участников по лотам';

CREATE TABLE executors (
    id                  BIGSERIAL PRIMARY KEY,
    lot_id              BIGINT NOT NULL UNIQUE REFERENCES lots (id) ON DELETE CASCADE,
    company_id          BIGINT NOT NULL REFERENCES companies (id) ON DELETE RESTRICT,
    winning_bid_id      BIGINT REFERENCES bids (id) ON DELETE SET NULL,
    contract_number     VARCHAR(100) NOT NULL UNIQUE,
    contract_amount     NUMERIC(15, 2) NOT NULL CHECK (contract_amount >= 0),
    contract_date       DATE NOT NULL,
    completion_date     DATE,
    execution_status    VARCHAR(20) NOT NULL DEFAULT 'in_progress'
                            CHECK (execution_status IN ('in_progress', 'completed', 'terminated')),
    CONSTRAINT chk_completion_after_contract CHECK (completion_date IS NULL OR completion_date >= contract_date)
);

COMMENT ON TABLE executors IS 'Исполнители — компании, выигравшие лот и заключившие контракт';

-- tenders
CREATE INDEX idx_tenders_customer_id ON tenders (customer_id);
CREATE INDEX idx_tenders_status ON tenders (status);
CREATE INDEX idx_tenders_publish_date ON tenders (publish_date);

-- lots
CREATE INDEX idx_lots_tender_id ON lots (tender_id);
CREATE INDEX idx_lots_status ON lots (status);
CREATE INDEX idx_lots_category ON lots (category);

-- bids
CREATE INDEX idx_bids_lot_id ON bids (lot_id);
CREATE INDEX idx_bids_company_id ON bids (company_id);
CREATE INDEX idx_bids_status ON bids (status);
CREATE INDEX idx_bids_submitted_at ON bids (submitted_at);

-- executors
CREATE INDEX idx_executors_company_id ON executors (company_id);
CREATE INDEX idx_executors_contract_date ON executors (contract_date);
CREATE INDEX idx_executors_execution_status ON executors (execution_status);

-- составной индекс под аналитический запрос №1 (топ компаний по сумме
-- выигранных контрактов за период)
CREATE INDEX idx_executors_company_date_amount ON executors (company_id, contract_date) INCLUDE (contract_amount);

COMMIT;

SELECT
    c.id                                AS company_id,
    c.name                              AS company_name,
    COUNT(e.id)                         AS contracts_won,
    SUM(e.contract_amount)              AS total_won_amount
FROM executors AS e
JOIN companies AS c ON c.id = e.company_id
WHERE e.contract_date >= (CURRENT_DATE - INTERVAL '1 month')
  AND e.contract_date < CURRENT_DATE
GROUP BY c.id, c.name
ORDER BY total_won_amount DESC
LIMIT 3;

WITH bid_stats AS (
    SELECT
        b.company_id,
        COUNT(*)                                                       AS bids_total,
        COUNT(*) FILTER (WHERE b.status = 'won')                       AS bids_won,
        AVG(
            CASE
                WHEN b.status = 'won' AND l.starting_price > 0
                    THEN (l.starting_price - b.amount) / l.starting_price * 100
            END
        )                                                               AS avg_price_reduction_pct
    FROM bids AS b
    JOIN lots AS l ON l.id = b.lot_id
    WHERE b.submitted_at >= (CURRENT_DATE - INTERVAL '12 months')
    GROUP BY b.company_id
    HAVING COUNT(*) >= 3
)
SELECT
    c.id                                        AS company_id,
    c.name                                       AS company_name,
    bs.bids_total,
    bs.bids_won,
    ROUND(bs.bids_won::NUMERIC / bs.bids_total * 100, 1)   AS win_rate_pct,
    ROUND(COALESCE(bs.avg_price_reduction_pct, 0), 1)      AS avg_price_reduction_pct,
    RANK() OVER (ORDER BY bs.bids_won::NUMERIC / bs.bids_total DESC)  AS win_rate_rank
FROM bid_stats AS bs
JOIN companies AS c ON c.id = bs.company_id
ORDER BY win_rate_rank, bs.bids_total DESC;