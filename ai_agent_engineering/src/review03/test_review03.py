"""復習03の軌跡テスト（pytest 版）。

    docker compose exec app python -m pytest src/review03 -q

固定データと決定的なオラクルを使うので、何度実行しても同じ結果になる。ここで固定して
いるのは「安全性の設計レビューの結論」——どの穴をどの層で塞ぐと、何が測れる形で
減るか——である。解答を書くファイル（`answers.py`）には依存しないので、答えを消しても
pytest は通る。

`side_effects` と `completion_check` は業務データを変える。各測定の前後で
`tools/make_data.py` を実行して初期状態に戻す（`failure_map` 側で実施）。
"""

from __future__ import annotations

from dataclasses import replace

from _paths import reset_data, setup

ROOT = setup()

import pytest  # noqa: E402

import exits  # noqa: E402
import failure_map  # noqa: E402
import findings  # noqa: E402
import gates  # noqa: E402
import spec  # noqa: E402


@pytest.fixture(scope="module", autouse=True)
def _fresh_data():
    """測定の前後で業務データを初期状態に戻す（経費6件・予約0件・送信0件）。"""
    reset_data()
    yield
    reset_data()


@pytest.fixture(scope="module")
def detected() -> list[str]:
    return findings.audit_spec(spec.AS_IS)


@pytest.fixture(scope="module")
def exit_rows() -> list[dict]:
    return exits.rows()


@pytest.fixture(scope="module")
def effects() -> list[dict]:
    return failure_map.side_effects()


# --- 仕様監査（S09〜S12 の横断）---------------------------------------------
def test_レビュー前の仕様から10件の穴が出る(detected):
    assert detected == list(findings.CATALOG)


def test_レビュー後の仕様では穴が0件になる():
    assert findings.audit_spec(spec.TO_BE) == []


def test_許可リストを絞ると2件の穴が同時に消える(detected):
    fixed = replace(spec.AS_IS, tools=spec.TASK_NEEDS)
    assert findings.audit_spec(fixed) == [f for f in detected if f not in ("F3", "F4")]


def test_塞ぐ層にプロンプトを選ばない():
    assert "プロンプト" not in findings.plan().values()
    assert findings.PRIORITY[-1] == "プロンプト"


# --- 出力検査の被覆（S09 × S12）---------------------------------------------
def test_検査を強くするほど素通しが減る(exit_rows):
    assert [row["素通しした持ち出し"] for row in exit_rows] == [3, 2, 1]


def test_どの検査も正当な操作を止めない(exit_rows):
    assert all(row["正当な操作を止めた"] == 0 for row in exit_rows)


def test_隔離実行の出口はどの検査も塞げない(exit_rows):
    assert all("③" in row["検査していない出口"] for row in exit_rows)


# --- 承認（S04 × S10）-------------------------------------------------------
def test_ツール単位の判定は止め損ないと余計な停止を同時に起こす():
    tool_row = gates.summary()[0]
    assert tool_row["止め損ない"] == ["集計コードを隔離環境で実行する"]
    assert tool_row["余計に止める"] == ["3,200 円の交通費を申請する"]


def test_操作単位で規程どおりの基準にするとずれが0件になる():
    operation_row = gates.summary()[1]
    assert operation_row["止め損ない"] == [] and operation_row["余計に止める"] == []


def test_末尾の切り落としは件数の記録がないと検出できない():
    last = gates.chain_cases()[-1]
    assert last["鎖だけの検査"] == "健全"
    assert last["件数つきの検査"] == "検出"


# --- 信頼性（S11）-----------------------------------------------------------
def test_同じメッセージでも冪等性で判断が変わる():
    rows = failure_map.decisions()
    assert rows[0]["判断"] == "人に渡す"
    assert rows[1]["判断"] == "同じ引数で再試行"


def test_無条件の再試行だけが二重申請を作る(effects):
    assert [row["増分"] for row in effects] == [2, 1, 1]


def test_モデルの申告を完了判定に使わない():
    done = failure_map.completion_check()
    assert done["stop_reason"] == "error"
    assert done["そのまま返したか"] is False
    assert done["分からない操作を挙げたか"] is True
