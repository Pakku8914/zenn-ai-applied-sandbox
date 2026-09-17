"""課題9: 運用に載せる前に、監視する指標と閾値を決める（発展）。

まだ運用していないので「本当のドリフト」は観測できません。決められるのは
**何をどの周期で見て、どの値を超えたら何をするか**だけです。それを先に書きます。

使い方:
    docker compose exec lab python src/final01/monitor.py
"""

from __future__ import annotations

from common import (
    DRIFT_RATIOS,
    PSI_ACT,
    PSI_WATCH,
    drift_probe,
    monitoring_plan,
)


def probe() -> dict:
    """PSI の関数が正しく動くことを、自分のデータをずらして確かめる。"""
    table = drift_probe("recency", DRIFT_RATIOS)
    values = [float(value) for value in table["psi"]]
    return {
        "table": table,
        "values": values,
        "self_psi": values[0],
        "monotonic": values == sorted(values),
        "stable_at_one": str(table.iloc[0]["judgement"]) == "安定",
        "not_stable_at_last": str(table.iloc[-1]["judgement"]) != "安定",
    }


def main() -> None:
    print("■ 1. 監視の計画（閾値を先に決めておく）")
    for index, rule in enumerate(monitoring_plan(), start=1):
        print(f"[{index}] {rule['name']}")
        print(f"    合図: {rule['rule']}")
        print(f"    周期: {rule['cycle']}")
        print(f"    対応: {rule['action']}")
    print()

    result = probe()
    print(f"■ 2. PSI の関数が動くことを確かめる（目安: {PSI_WATCH} 未満は安定 / {PSI_ACT} 以上は要再学習）")
    print("recency の分布を、自分自身と比べる → そのあと倍率をかけてずらす")
    for row in result["table"].itertuples():
        print(f"    ×{row.ratio:.1f}: PSI {row.psi:.4f} → {row.judgement}")
    print()

    print("■ 3. 確かめたこと")
    print(f"同じ分布どうしの PSI が 0 か: {result['self_psi'] == 0.0}")
    print(f"×1.0 の判定が「安定」か: {result['stable_at_one']}")
    print(f"ずらすほど PSI が大きくなるか: {result['monotonic']}")
    print(f"×{DRIFT_RATIOS[-1]:.1f} では「安定」でなくなるか: {result['not_stable_at_last']}")
    print()
    print("判断: 監視は「ずれたら気づける仕掛け」です。仕掛けが動くことを先に確かめておけば、")
    print("      3 か月後に出た数字を信じられます。正解（再購入したか）は 90 日後にしか分からないので、")
    print("      性能の監視より先に「入力の分布」を見るのが現実的です。")


if __name__ == "__main__":
    main()
