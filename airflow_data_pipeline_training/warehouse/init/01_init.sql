-- ============================================================================
-- 分析用データベース（warehouse）の初期化
-- ----------------------------------------------------------------------------
-- warehouse コンテナが初回起動したときに一度だけ実行される。
--   raw  : 取り込んだ生データを置く層（加工しない）
--   mart : 集計・加工済みで分析にすぐ使える層
-- 「生データは壊さず取っておき、加工結果はいつでも作り直せるようにする」という
-- 本書のパイプライン設計方針を、スキーマの分け方で表現している。
-- ============================================================================

CREATE SCHEMA IF NOT EXISTS raw;
CREATE SCHEMA IF NOT EXISTS mart;

COMMENT ON SCHEMA raw  IS '取り込んだままの生データを置く層';
COMMENT ON SCHEMA mart IS '集計・加工済みのデータを置く層';

-- 動作確認用テーブル。
-- (dag_id, logical_date) を主キーにしているのがポイント。
-- 「同じ実行対象の記録は1行だけ」と決めておけば、何度再実行しても行が増えない
-- ＝冪等なパイプラインになる（本書を通じて何度も使う考え方）。
CREATE TABLE IF NOT EXISTS raw.lab_healthcheck (
    dag_id          text        NOT NULL,
    logical_date    timestamptz NOT NULL,
    airflow_version text        NOT NULL,
    checked_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (dag_id, logical_date)
);

COMMENT ON TABLE raw.lab_healthcheck IS '環境の動作確認用。同じ logical_date なら常に1行（冪等性の確認）';
