"""データ層だけの動作確認（MCP を経由しない）

サーバーを起動せずにロジックを確かめられるのが、データ層を分離した最初の恩恵です。
このスクリプトはクライアント側と同じ「ただのプログラム」なので print を使ってかまいません。

  docker compose exec python python src/session04/data_check.py
"""

import data

print("platform チーム:", ", ".join(m.id for m in data.list_members("platform")))

week = data.summarize_hours("2026-08-03", "2026-08-07")
print("合計時間:", data.format_hours(week.total_hours))
print("対象人数:", len(week.members))

only = data.summarize_hours("2026-08-03", "2026-08-07", "m-002")
print("m-002 の内訳:", data.format_hours(only.total_hours))
