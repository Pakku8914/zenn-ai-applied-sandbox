-- S10-09 書き込みスキュー：「当直は最低1人」という2行にまたがる約束を、2つのトランザクションが同時に破る
-- 【2セッション】見出しごとに、書かれた側のセッションに貼る（\i で一度に流さない）。
-- どこでも止まらない（2人は別の行を更新するので行ロックでは衝突しない）。
-- Serializable では後から書いた側がエラーになる。エラーになった側は ROLLBACK して最初からやり直す。

-- [A1] セッションA: 当直表を作り直す（佐藤・鈴木の2人とも当直）。佐藤が「もう1人いるなら抜ける」を Repeatable Read で行う
\i sql/session10/00_setup.sql
SELECT * FROM s10_oncall ORDER BY doctor;
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT count(*) FROM s10_oncall WHERE on_call;

-- [B1] セッションB: 鈴木も同時に同じ確認をする（2人いる）
BEGIN ISOLATION LEVEL REPEATABLE READ;
SELECT count(*) FROM s10_oncall WHERE on_call;

-- [A2] セッションA: 2人いるので佐藤が抜ける
UPDATE s10_oncall SET on_call = false WHERE doctor = '佐藤';
COMMIT;

-- [B2] セッションB: 鈴木も抜ける。別の行なので待たずにコミットできてしまう
UPDATE s10_oncall SET on_call = false WHERE doctor = '鈴木';
COMMIT;

-- [A3] セッションA: 当直が 0 人になった（書き込みスキュー）
SELECT * FROM s10_oncall ORDER BY doctor;

-- [A4] セッションA: 作り直して、同じ手順を Serializable で行う
\i sql/session10/00_setup.sql
BEGIN ISOLATION LEVEL SERIALIZABLE;
SELECT count(*) FROM s10_oncall WHERE on_call;

-- [B3] セッションB: Serializable で同じ確認をする
BEGIN ISOLATION LEVEL SERIALIZABLE;
SELECT count(*) FROM s10_oncall WHERE on_call;

-- [A5] セッションA: 佐藤が抜けてコミットする
UPDATE s10_oncall SET on_call = false WHERE doctor = '佐藤';
COMMIT;

-- [B4] セッションB: 鈴木が抜けようとすると、UPDATE の時点で直列化の失敗（read/write dependencies）になる
UPDATE s10_oncall SET on_call = false WHERE doctor = '鈴木';

-- [B5] セッションB: ROLLBACK して最初からやり直す。今度は当直が 1 人と分かるので、鈴木は抜けない
ROLLBACK;
BEGIN ISOLATION LEVEL SERIALIZABLE;
SELECT count(*) FROM s10_oncall WHERE on_call;
COMMIT;

-- [A6] セッションA: 当直は鈴木 1 人が残っている
SELECT * FROM s10_oncall ORDER BY doctor;
