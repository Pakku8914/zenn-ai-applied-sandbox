#!/usr/bin/env python3
"""セッション16：仮の単価表とコストの計算。

    python src/session16/prices.py

**実在するモデルの料金は1つも書かない。** 料金は本書の中で最も速く腐る情報であり、
本文に書いた時点で誤情報になる。ここで宣言するのは「相対値」であって金額ではない。
上位と下位の比（10倍）と、入力と出力の比（5倍）だけが意味を持つ。
実際の金額は各社の公式の料金ページと、姉妹教材『LLMアプリの評価と運用』で確認すること。

単位は「コスト単位（cu）」。近似トークン1つあたりの**整数**で宣言してあるので、
コストは必ず整数になり、丸めで数字がぶれない（S14 の単価表と同じ作法）。

近似トークン数はプロンプトの文字数 ÷ 3（比較用）であり、実 API の計測値ではない。
"""

from __future__ import annotations

from dataclasses import dataclass, replace


@dataclass(frozen=True)
class PriceTable:
    """仮の単価表。**金額ではなく相対値**である。

    cached_in_per_token は「前方一致でキャッシュが効いた入力」の単価。
    下位モデルは 0.1 cu になるはずだが、本書は整数で扱うので 0（無料）に丸めてある。
    キャッシュの節では上位モデルだけを見ること。
    """

    label: str
    in_per_token: int
    out_per_token: int
    cached_in_per_token: int = 0

    def cost(self, tokens_in: int, tokens_out: int, cached_in: int = 0) -> int:
        if cached_in > tokens_in:
            raise ValueError(
                f"キャッシュされた入力 {cached_in} が入力の合計 {tokens_in} を超えています。")
        fresh = tokens_in - cached_in
        return (fresh * self.in_per_token
                + cached_in * self.cached_in_per_token
                + tokens_out * self.out_per_token)

    def describe(self) -> str:
        return (f"{self.label}: 入力 {self.in_per_token} cu / 出力 {self.out_per_token} cu / "
                f"キャッシュ入力 {self.cached_in_per_token} cu（いずれも近似トークン1つあたり）")


# 2階層のモデル。判断は上位・整形は下位に回す（節4）
HIGH = PriceTable("上位（判断向け）", 10, 50, 1)
LOW = PriceTable("下位（整形向け）", 1, 5, 0)

# 感度分析用。出力単価だけを差し替えて「支配要因が入れ替わるか」を見る（節2）
SENSITIVITY = (
    replace(HIGH, label="A 出力＝入力の5倍（本書の既定）"),
    replace(HIGH, label="B 出力＝入力の20倍", out_per_token=200),
    replace(HIGH, label="C 出力＝入力の30倍", out_per_token=300),
)


def traj_cost(traj, table: PriceTable = HIGH, cached_in: int = 0) -> int:
    """軌跡1本ぶんのコスト（cu）。"""
    total = traj.total_tokens
    return table.cost(total["input"], total["output"], cached_in)


def step_costs(traj, table: PriceTable = HIGH) -> list[int]:
    """ステップ別のコスト（cu）。**どこに乗っているか**を見るための分解。"""
    return [table.cost(s.usage.get("input_tokens", 0), s.usage.get("output_tokens", 0))
            for s in traj.steps]


def io_split(traj, table: PriceTable = HIGH) -> tuple[int, int]:
    """(入力ぶんのコスト, 出力ぶんのコスト)。"""
    total = traj.total_tokens
    return (total["input"] * table.in_per_token, total["output"] * table.out_per_token)


def dominant(traj, table: PriceTable = HIGH) -> str:
    """支配要因。単価表を差し替えると入れ替わることがある（S14 と同じ性質）。"""
    in_cost, out_cost = io_split(traj, table)
    return "入力" if in_cost >= out_cost else "出力"


def crossover_out_rate(traj, table: PriceTable = HIGH) -> int:
    """出力が支配的になる最小の出力単価（cu/トークン）。

    出力単価がここに届かない限り、いくら単価表を変えても支配要因は入力のままである。
    「出力を短くすればコストが下がる」が効かない理由がこの1行で決まる。
    """
    total = traj.total_tokens
    return total["input"] * table.in_per_token // total["output"] + 1


def shares(values: list[int]) -> list[float]:
    """割合（%）。合計が 0 のときは 0 を返す。"""
    total = sum(values) or 1
    return [v / total * 100 for v in values]


def main() -> None:
    from costshape import detail_trajectory  # noqa: PLC0415（循環 import を避けるため関数内）

    traj = detail_trajectory()
    total = traj.total_tokens
    print("=== 仮の単価表（相対値。実在モデルの料金ではない）===")
    for table in (HIGH, LOW):
        print(f"  {table.describe()}")

    print(f"\n=== 対象の軌跡: {traj.task_id} "
          f"手数={len(traj.steps)} 入力={total['input']} 出力={total['output']} ===")
    print(f"上位で通す: {traj_cost(traj, HIGH):>6} cu")
    print(f"下位で通す: {traj_cost(traj, LOW):>6} cu（上位の 1/10）")

    print("\n=== 支配要因は単価表で決まる（S14 の単価表と同じ話）===")
    print(f"{'単価表':<26}{'入力(cu)':>10}{'出力(cu)':>10}{'合計':>9}{'入力%':>8}{'出力%':>8}  支配")
    for table in SENSITIVITY:
        in_cost, out_cost = io_split(traj, table)
        p_in, p_out = shares([in_cost, out_cost])
        print(f"{table.label:<26}{in_cost:>10}{out_cost:>10}{in_cost + out_cost:>9}"
              f"{p_in:>8.1f}{p_out:>8.1f}  {dominant(traj, table)}")

    rate = crossover_out_rate(traj, HIGH)
    print(f"\n出力が支配的になるのは、出力単価が {rate} cu/トークン"
          f"（入力単価の {rate / HIGH.in_per_token:.1f} 倍）を超えたとき。")
    print("→ 現実的な単価表では入力が支配的。**削るべきは出力ではなく履歴**。")


if __name__ == "__main__":
    import sys
    from pathlib import Path

    for _p in (str(Path(__file__).resolve().parents[2]), str(Path(__file__).resolve().parent)):
        if _p not in sys.path:
            sys.path.insert(0, _p)
    main()
