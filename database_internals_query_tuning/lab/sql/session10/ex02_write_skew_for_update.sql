-- S10 演習: 書き込みスキューを Read Committed のまま防ぐ（確認に使う行をすべて FOR UPDATE でロックする）
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る。途中でセッションBが止まり、セッションAの COMMIT で進む。
-- count(*) には FOR UPDATE を付けられないので、行を返して数える。

-- [A1] セッションA: 当直表を作り直し、当直中の行をロックしながら読む（2行）
\i sql/session10/00_setup.sql
BEGIN;
SELECT doctor FROM s10_oncall WHERE on_call ORDER BY doctor FOR UPDATE;

-- [B1] セッションB: 同じ確認をしようとする（ここで止まる）
BEGIN;
SELECT doctor FROM s10_oncall WHERE on_call ORDER BY doctor FOR UPDATE;

-- [A2] セッションA: 佐藤が抜けてコミットする
UPDATE s10_oncall SET on_call = false WHERE doctor = '佐藤';
COMMIT;

-- [B2] セッションB: 待っていた SELECT は、更新された佐藤の行を条件で評価し直して外すので 1 行（鈴木）だけを返した。鈴木は抜けない
COMMIT;
SELECT * FROM s10_oncall ORDER BY doctor;

-- [A3] セッションA: 集約に FOR UPDATE を付けるとエラーになる（行を返す形で書く理由）
SELECT count(*) FROM s10_oncall WHERE on_call FOR UPDATE;
