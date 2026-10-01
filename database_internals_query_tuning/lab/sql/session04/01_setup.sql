-- セッション4-1: 準備。セッション3と同じ ordered_at のインデックスを作る
-- 最初に tools/reset.sh で出発点に戻しておく（主キーと外部キーだけの状態）
CREATE INDEX orders_ordered_at_idx ON orders (ordered_at);
