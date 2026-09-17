"""再学習をいつ行うかを、条件と閾値で決める（本文 8 節）。

「なんとなく古くなった気がする」で再学習しないために、条件を先に書き出します。
このデータでは PSI も性能も発火しませんが、**時間の経過とデータ量**で発火します。

使い方:
    docker compose exec lab python src/session28/retrain_policy.py
"""

from __future__ import annotations

from common import print_rules, retrain_rules, should_retrain

# 再学習したあとに必ず確かめること（順番に意味がある）
AFTER_RETRAIN = [
    "古いモデルのファイルは消さずに残す（戻せなければ「試す」ことができない）",
    "新しいモデルは、古いモデルと同じ期間・同じ指標で比べる（PR-AUC と閾値ごとの適合率・再現率）",
    "新旧の予測が食い違った件数を数え、食い違った側の何件かを目で見る",
    "メタデータの cutoff・バージョン・保存時の性能を更新する",
    "入れ替えたあとも監視は続ける（再学習は「直った」の証明ではない）",
]


def report() -> dict:
    """判断基準を並べ、発火した条件があるかを返す。"""
    rules = retrain_rules()
    return {"rules": rules, **should_retrain(rules)}


def main() -> None:
    result = report()

    print("■ 1. 再学習の判断基準（先に書いておく）")
    print_rules(result["rules"])
    print()

    print("■ 2. 判定")
    print(f"発火した条件: {result['n_fired']} / {result['n_rules']} 件（{result['fired']}）")
    print(f"結論: {'再学習する' if result['retrain'] else '再学習しない'}")
    print()

    print("■ 3. この結論の読み方")
    print("・データの分布は動いていません（PSI は 0.1 にも届かない）")
    print("・性能も下降していません（月次のばらつきの範囲）")
    print("・それでも再学習します。理由は「新しいデータを使っていないから」です")
    print("　（学習に使ったのは全体の一部だけで、その後の注文をモデルは見ていません）")
    print()

    print("■ 4. 再学習したあとに確かめること")
    for index, item in enumerate(AFTER_RETRAIN, start=1):
        print(f"{index}. {item}")


if __name__ == "__main__":
    main()
