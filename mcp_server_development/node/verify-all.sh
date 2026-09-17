#!/bin/sh
# TypeScript 側の検証をまとめて実行する（コンテナの中で動かします）
#
#   docker compose exec node sh verify-all.sh
#   docker compose exec -e SKIP_HTTP=1 node sh verify-all.sh   # HTTP 章を飛ばす
#
# 1 つでも失敗したら非 0 で終了します（人が出力を読んで判断する形にしません）。
set -eu

AS_PID_FILE=/tmp/mcp-as.pid
PROTECTED_PID_FILE=/tmp/mcp-protected.pid
FINAL_PID_FILE=/tmp/mcp-final.pid

# HTTP 章のサーバーは待ち受けたまま残ると次回の起動がポート衝突で失敗する。
# 途中で失敗しても必ず止める。
stop_server() {
  [ -f "$1" ] || return 0
  kill "$(cat "$1")" 2>/dev/null || true
  rm -f "$1"
  sleep 1
}

cleanup() {
  stop_server "$PROTECTED_PID_FILE"
  stop_server "$FINAL_PID_FILE"
  stop_server "$AS_PID_FILE"
}
trap cleanup EXIT INT TERM

run() {
  echo "==> $*"
  "$@"
}

# fetch はステータスが 401 でも解決する。ここで見たいのは「応答が返るか」だけ。
wait_http() {
  i=0
  while [ "$i" -lt 60 ]; do
    if node -e "fetch('$1').then(() => process.exit(0)).catch(() => process.exit(1))" >/dev/null 2>&1; then
      return 0
    fi
    i=$((i + 1))
    sleep 1
  done
  echo "起動を待てませんでした: $1" >&2
  return 1
}

echo "===== 1/5 型チェック ====="
run npm run typecheck

echo "===== 2/5 単体・契約・スナップショット（vitest） ====="
# ベースラインが無いことを失敗にする（黙ってスナップショットを作らせない）
SNAPSHOT_CI=1 npx vitest run

echo "===== 3/5 E2E（Inspector CLI） ====="
run npx tsx src/session13/e2e-inspector.ts

echo "===== 4/5 セッションごとの検証スクリプト（stdio） ====="
for f in $(ls src/*/verify*.ts | sort); do
  case "$f" in
    src/session12/verify-auth.ts | src/final/verify-http.ts)
      continue # 認可サーバーと HTTP サーバーが要る。5/5 でまとめて扱う
      ;;
  esac
  run npx tsx "$f"
done

echo "===== 5/5 HTTP 章（認可サーバー ＋ MCP サーバーを起動して検証） ====="
if [ "${SKIP_HTTP:-0}" = "1" ]; then
  echo "スキップ（SKIP_HTTP=1）: src/session12/verify-auth.ts / src/final/verify-http.ts"
else
  cleanup # 前回の残骸があれば先に片付ける

  MCP_AS_DEBUG=on npx tsx src/session12/serve-auth.ts >/tmp/as.log 2>&1 &
  wait_http http://127.0.0.1:9100/.well-known/oauth-authorization-server

  npx tsx src/session12/serve-protected.ts >/tmp/protected.log 2>&1 &
  wait_http http://127.0.0.1:3939/.well-known/oauth-protected-resource/mcp
  run npx tsx src/session12/verify-auth.ts
  stop_server "$PROTECTED_PID_FILE"

  npx tsx src/final/serve.ts >/tmp/final.log 2>&1 &
  wait_http http://127.0.0.1:3939/.well-known/oauth-protected-resource/mcp
  run npx tsx src/final/verify-http.ts
  stop_server "$FINAL_PID_FILE"

  stop_server "$AS_PID_FILE"
fi

echo
echo "OK: TypeScript 側の検証がすべて通りました"
