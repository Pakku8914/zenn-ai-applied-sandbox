#!/usr/bin/env python3
"""横断復習04：索引の運用を1枚にする（セッション16 × セッション7 × セッション3）。

  更新の検出 -> 冪等な同期と孤児 -> 方式の選択 -> 切り替えの runbook -> 鮮度 -> 容量

Qdrant にも埋め込みモデルにも触らない。ここで確かめるのは「手順と算数」であって、
索引そのものではない（索引を触る練習はセッション16でやってある）。

実行:  docker compose exec app python src/review04/ops_math.py
"""

from __future__ import annotations

# --- 実測（2026-08-15 / aarch64 / CPU 2コア / メモリ 5.8GB / Python 3.12.13）---
CHUNKS = 673                 # fixed(400/80)
EMBED_SECONDS = 38.21        # 673 チャンクの埋め込みにかかった秒数
VECTOR_DIM = 384
FLOAT_BYTES = 4
TEXT_TO_VECTOR_RATIO = 0.54  # 本文のペイロードはベクトルの 0.54 倍
FRESHNESS_SLO_DAYS = 7       # 7日以内に反映される割合を 99% 以上に保つ

# 変更の種類 -> 選ぶ方式（セッション16の選択表）
SWITCH_TABLE: dict[str, str] = {
    "文書の追加・改訂・削除": "増分更新",
    "権限（visibility）の変更": "増分更新（ペイロードだけ更新し、点IDは変えない）",
    "同義語辞書の更新（索引側展開）": "全再索引",
    "チャンク方式・チャンクサイズの変更": "並行構築＋切り替え",
    "埋め込みモデルの変更": "並行構築＋切り替え",
}

# 孤児チャンクが生まれる3経路
ORPHAN_CAUSES: tuple[tuple[str, str], ...] = (
    ("文書が短くなってチャンク数が減った", "余ったチャンクが残る。ログは「変更なし」と出る"),
    ("文書そのものが削除された", "その文書のチャンク全部が孤児になる"),
    ("チャンク方式・パラメータを変えた", "chunk_id の体系が変わり、大量に孤児化する"),
)

# 切り替えの runbook（4段）。各段に「何を見て次へ進むか」を必ず書く
RUNBOOK: tuple[tuple[str, str], ...] = (
    ("① 点検", "孤児0・文書数一致・dry_run が0件・評価が合格ライン以上"),
    ("② 切り替え", "エイリアスの付け替えを1リクエストで（削除と作成を同時に）"),
    ("③ 監視", "切り替えから2時間、ゼロヒット率・p95・上位無クリック率を見る"),
    ("④ 切り戻し", "1つでも閾値を割ったらエイリアスを旧コレクションへ戻す（旧は消さない）"),
)

# 容量を削る順番（効く順）
COST_ORDER: tuple[tuple[str, str], ...] = (
    ("次元削減", "ベクトルの本数ではなく1本の大きさを削る。精度への影響を測ってから"),
    ("量子化", "1要素あたりのバイト数を落とす。リコールの低下を必ず測る"),
    ("チャンク数の削減", "チャンクを大きくすると Recall が落ちる（セッション4の実測）"),
)


# --- 1. 更新の検出 --------------------------------------------------------------
def diff_state(previous: dict[str, str], current: dict[str, str]) -> dict[str, list[str]]:
    """本文の指紋どうしを突き合わせて、追加・更新・削除・変更なしに分ける。"""
    both = set(current) & set(previous)
    return {
        "added": sorted(set(current) - set(previous)),
        "changed": sorted(d for d in both if current[d] != previous[d]),
        "removed": sorted(set(previous) - set(current)),
        "unchanged": sorted(d for d in both if current[d] == previous[d]),
    }


def diff_by_updated_at(updated_at: dict[str, str], since: str) -> list[str]:
    """更新日だけで差分を取る方法。削除は原理的に検出できず、直し忘れも拾えない。"""
    return sorted(doc_id for doc_id, day in updated_at.items() if day > since)


# --- 2. 方式の選択 --------------------------------------------------------------
def switch_for(change_kind: str) -> str:
    """知らない変更を勝手に「増分でいいだろう」と決めない（人が決める）。"""
    if change_kind not in SWITCH_TABLE:
        raise KeyError(f"未登録の変更です: {change_kind!r}（表に足してから運用する）")
    return SWITCH_TABLE[change_kind]


# --- 3. 鮮度 --------------------------------------------------------------------
def max_lag_days(batch_interval_days: int, detect_lag_days: int = 0) -> int:
    """遅れの上限はバッチ間隔で決まる。索引を速くしても間隔より短くならない。"""
    return batch_interval_days + detect_lag_days


def meets_slo(batch_interval_days: int, detect_lag_days: int = 0,
              slo_days: int = FRESHNESS_SLO_DAYS) -> bool:
    return max_lag_days(batch_interval_days, detect_lag_days) <= slo_days


# --- 4. 容量と計算コスト ---------------------------------------------------------
def vector_bytes(dim: int = VECTOR_DIM) -> int:
    return dim * FLOAT_BYTES


def vector_kb(n_chunks: int) -> float:
    return n_chunks * vector_bytes() / 1024


def vector_mib(n_chunks: int) -> float:
    return n_chunks * vector_bytes() / 1024 / 1024


def vector_share() -> float:
    """ベクトル＋本文のうち、ベクトルが占める割合。"""
    return 1 / (1 + TEXT_TO_VECTOR_RATIO)


def per_chunk_seconds() -> float:
    return EMBED_SECONDS / CHUNKS


def per_chunk_ms() -> float:
    return per_chunk_seconds() * 1000


def embed_seconds(n_chunks: int) -> float:
    return n_chunks * per_chunk_seconds()


def embed_minutes(n_chunks: int) -> float:
    return embed_seconds(n_chunks) / 60


def monthly_incremental_minutes(n_chunks: int = 100_000, daily_ratio: float = 0.01,
                                days: int = 30) -> float:
    return embed_minutes(int(n_chunks * daily_ratio)) * days


def monthly_full_hours(n_chunks: int = 100_000, days: int = 30) -> float:
    return embed_minutes(n_chunks) * days / 60


def main() -> None:
    print("=== 1. 更新の検出（指紋 vs 更新日）===")
    previous = {"DOC-0001": "h1", "DOC-0002": "h2", "DOC-0003": "h3"}
    current = {"DOC-0001": "h1", "DOC-0002": "h2x", "DOC-0004": "h4"}
    # DOC-0002 は本文を直したのに updated_at を直し忘れた、という状況
    updated_at = {"DOC-0001": "2026-05-10", "DOC-0002": "2026-05-10", "DOC-0004": "2026-08-15"}
    print(f"  指紋で取る  : {diff_state(previous, current)}")
    print(f"  更新日で取る: {diff_by_updated_at(updated_at, since='2026-08-01')}"
          "（削除も、更新日の直し忘れも落ちる）")

    print("\n=== 2. 孤児チャンクが生まれる3経路 ===")
    for cause, what in ORPHAN_CAUSES:
        print(f"  - {cause}: {what}")

    print("\n=== 3. 方式の選択 ===")
    for kind in SWITCH_TABLE:
        print(f"  {kind:<26} -> {switch_for(kind)}")

    print("\n=== 4. 切り替えの runbook ===")
    for step, gate in RUNBOOK:
        print(f"  {step} {gate}")

    print("\n=== 5. 鮮度（SLO: 7日以内に反映する）===")
    for interval in (1, 7, 30):
        ok = "満たす" if meets_slo(interval) else "満たさない"
        print(f"  バッチ間隔 {interval:>2} 日 -> 遅れの上限 {max_lag_days(interval)} 日 : {ok}")

    print("\n=== 6. 容量と計算コスト ===")
    print(f"  ベクトル1本            : {VECTOR_DIM} × {FLOAT_BYTES} = {vector_bytes()} バイト")
    print(f"  {CHUNKS} チャンク         : {vector_kb(CHUNKS):,.1f} KB")
    print(f"  100,000 チャンク       : {vector_mib(100_000):.1f} MiB"
          f"（並行構築中のピークは2本ぶんで {vector_mib(100_000) * 2:.1f} MiB）")
    print(f"  本文はベクトルの        : {TEXT_TO_VECTOR_RATIO} 倍"
          f"（容量の {vector_share() * 100:.1f}% はベクトル）")
    print(f"  1チャンクの埋め込み     : {per_chunk_ms():.1f} ms")
    print(f"  全再索引（100,000）    : {embed_minutes(100_000):.1f} 分")
    print(f"  日次1%の増分（1,000）  : {embed_seconds(1_000):.1f} 秒")
    print(f"  1か月（30日）          : 増分 {monthly_incremental_minutes():.1f} 分 / "
          f"毎日全再索引 {monthly_full_hours():.1f} 時間")

    print("\n=== 7. 容量を削る順番 ===")
    for i, (move, note) in enumerate(COST_ORDER, start=1):
        print(f"  {i}. {move}: {note}")


if __name__ == "__main__":
    main()
