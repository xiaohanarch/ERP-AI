-- ============================================================
-- V1: 存量 ERP 应付模块 schema（租户/公司/组织三维 + 写路径留痕）
-- 注意：JSON 一律 TEXT 存储（演示口径，避免 Hibernate validate 类型漂移）
-- ============================================================

-- 用户/角色/权限（权限码 + 数据范围 scope_json）
CREATE TABLE erp_user (
    id            BIGSERIAL PRIMARY KEY,
    username      VARCHAR(64)  NOT NULL UNIQUE,
    password_hash VARCHAR(128) NOT NULL,
    display_name  VARCHAR(64)  NOT NULL,
    tenant_id     VARCHAR(32)  NOT NULL,
    org           VARCHAR(64)  NOT NULL,
    title         VARCHAR(64)
);
CREATE TABLE role (
    id        BIGSERIAL PRIMARY KEY,
    code      VARCHAR(64) NOT NULL UNIQUE,
    name      VARCHAR(64) NOT NULL,
    tenant_id VARCHAR(32) NOT NULL
);
CREATE TABLE user_role (
    user_id BIGINT NOT NULL REFERENCES erp_user (id),
    role_id BIGINT NOT NULL REFERENCES role (id),
    PRIMARY KEY (user_id, role_id)
);
CREATE TABLE role_permission (
    id              BIGSERIAL PRIMARY KEY,
    role_id         BIGINT       NOT NULL REFERENCES role (id),
    permission_code VARCHAR(64)  NOT NULL,
    scope_json      TEXT         NOT NULL  -- {"orgs":["ORG-X"]} 或 {"all_orgs":true}
);

-- 主数据
CREATE TABLE supplier (
    id        BIGSERIAL PRIMARY KEY,
    code      VARCHAR(32)  NOT NULL,
    name      VARCHAR(128) NOT NULL,
    region    VARCHAR(32)  NOT NULL,
    qualified BOOLEAN      NOT NULL DEFAULT TRUE,
    tenant_id VARCHAR(32)  NOT NULL
);
CREATE TABLE tax_code_config (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        VARCHAR(32) NOT NULL,
    region           VARCHAR(32) NOT NULL,
    common_tax_code  VARCHAR(32) NOT NULL,
    note             VARCHAR(255)
);
CREATE TABLE budget_occupancy (
    id              BIGSERIAL PRIMARY KEY,
    tenant_id       VARCHAR(32)   NOT NULL,
    org             VARCHAR(64)   NOT NULL,
    period          VARCHAR(16)   NOT NULL,
    budget_amount   NUMERIC(18,2) NOT NULL,
    occupied_amount NUMERIC(18,2) NOT NULL,
    UNIQUE (org, period)
);

-- 单据（三单匹配：PO / GR / Invoice）
CREATE TABLE purchase_order (
    id          BIGSERIAL PRIMARY KEY,
    po_no       VARCHAR(32) NOT NULL UNIQUE,
    supplier_id BIGINT REFERENCES supplier (id),
    org         VARCHAR(64) NOT NULL,
    tenant_id   VARCHAR(32) NOT NULL,
    status      VARCHAR(16) NOT NULL,
    order_date  DATE
);
CREATE TABLE po_line (
    id         BIGSERIAL PRIMARY KEY,
    po_id      BIGINT        NOT NULL REFERENCES purchase_order (id),
    line_no    INT           NOT NULL,
    item       VARCHAR(128)  NOT NULL,
    qty        NUMERIC(18,4) NOT NULL,
    unit_price NUMERIC(18,4) NOT NULL
);
CREATE TABLE goods_receipt (
    id           BIGSERIAL PRIMARY KEY,
    gr_no        VARCHAR(32) NOT NULL UNIQUE,
    po_id        BIGINT REFERENCES purchase_order (id),
    org          VARCHAR(64) NOT NULL,
    tenant_id    VARCHAR(32) NOT NULL,
    receipt_date DATE
);
CREATE TABLE gr_line (
    id         BIGSERIAL PRIMARY KEY,
    gr_id      BIGINT        NOT NULL REFERENCES goods_receipt (id),
    po_line_id BIGINT REFERENCES po_line (id),
    item       VARCHAR(128)  NOT NULL,
    qty        NUMERIC(18,4) NOT NULL
);
CREATE TABLE invoice (
    id                BIGSERIAL PRIMARY KEY,
    invoice_no        VARCHAR(32)   NOT NULL UNIQUE,
    supplier_id       BIGINT REFERENCES supplier (id),
    po_id             BIGINT REFERENCES purchase_order (id),
    gr_id             BIGINT REFERENCES goods_receipt (id),
    org               VARCHAR(64)   NOT NULL,
    company           VARCHAR(64)   NOT NULL DEFAULT '',
    tenant_id         VARCHAR(32)   NOT NULL,
    amount_cny        NUMERIC(18,2) NOT NULL,
    tax_code          VARCHAR(32),
    status            VARCHAR(16)   NOT NULL,  -- DRAFT/POSTED/VOIDED
    validation_status VARCHAR(16)   NOT NULL,  -- PASSED/WARNED/BLOCKED/UNEVALUATED
    is_accrual        BOOLEAN       NOT NULL DEFAULT FALSE,
    period            VARCHAR(16)   NOT NULL,
    paid_cny          NUMERIC(18,2) NOT NULL DEFAULT 0,
    created_at        TIMESTAMPTZ   NOT NULL DEFAULT now()
);
CREATE INDEX idx_invoice_tenant_org ON invoice (tenant_id, org);
CREATE INDEX idx_invoice_validation ON invoice (tenant_id, validation_status);
CREATE TABLE invoice_line (
    id          BIGSERIAL PRIMARY KEY,
    invoice_id  BIGINT        NOT NULL REFERENCES invoice (id),
    line_no     INT           NOT NULL,
    item        VARCHAR(128)  NOT NULL,
    qty         NUMERIC(18,4) NOT NULL,
    unit_price  NUMERIC(18,4) NOT NULL,
    po_line_id  BIGINT REFERENCES po_line (id),
    gr_line_id  BIGINT REFERENCES gr_line (id)
);

-- 写路径留痕
CREATE TABLE invoice_tax_change (
    id                BIGSERIAL PRIMARY KEY,
    tenant_id         VARCHAR(32) NOT NULL,
    invoice_no        VARCHAR(32) NOT NULL,
    previous_tax_code VARCHAR(32),
    new_tax_code      VARCHAR(32) NOT NULL,
    reason            VARCHAR(512) NOT NULL,
    account_period    VARCHAR(16)  NOT NULL,
    requested_by      VARCHAR(64)  NOT NULL,
    decided_by        VARCHAR(64),
    approval_ref      VARCHAR(64),
    applied_at        TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE TABLE idempotency_record (
    id           BIGSERIAL PRIMARY KEY,
    tenant_id    VARCHAR(32)  NOT NULL,
    business_key VARCHAR(255) NOT NULL UNIQUE, -- 发票号+税码+会计期间
    tool_name    VARCHAR(64)  NOT NULL,
    params_hash  VARCHAR(128) NOT NULL,
    status       VARCHAR(16)  NOT NULL,        -- COMPLETED / IN_PROGRESS
    result_json  TEXT,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now()
);
CREATE TABLE payment (
    id               BIGSERIAL PRIMARY KEY,
    tenant_id        VARCHAR(32)   NOT NULL,
    payment_order_no VARCHAR(64)   NOT NULL UNIQUE,
    invoice_no       VARCHAR(32)   NOT NULL,
    amount_cny       NUMERIC(18,2) NOT NULL,
    executed_at      TIMESTAMPTZ   NOT NULL DEFAULT now(),
    is_mock          BOOLEAN       NOT NULL DEFAULT TRUE
);

-- Open API 凭据（appid 直连、租户级 —— 事故端点口径的根源）
CREATE TABLE openapi_credential (
    id          BIGSERIAL PRIMARY KEY,
    app_id      VARCHAR(64)  NOT NULL UNIQUE,
    secret_hash VARCHAR(128) NOT NULL,
    tenant_id   VARCHAR(32)  NOT NULL,
    all_orgs    BOOLEAN      NOT NULL DEFAULT TRUE
);

-- 事件 outbox（ap.invoice.blocked 等）
CREATE TABLE outbox_event (
    id           BIGSERIAL PRIMARY KEY,
    event_key    VARCHAR(128) NOT NULL UNIQUE,
    event_type   VARCHAR(64)  NOT NULL,
    payload_json TEXT         NOT NULL,
    created_at   TIMESTAMPTZ  NOT NULL DEFAULT now(),
    consumed     BOOLEAN      NOT NULL DEFAULT FALSE
);
