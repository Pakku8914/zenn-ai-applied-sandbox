#!/usr/bin/env python3
"""セッション8: stdio で話す最小の MCP サーバー（JSON-RPC 2.0）。

標準入力から「1行 = 1件の JSON-RPC リクエスト」を読み、標準出力へ
「1行 = 1件のレスポンス」を書きます。実装するメソッドは3つだけです。

    initialize   … 何を提供するサーバーかを申告する（本サーバーは tools のみ）
    tools/list   … 道具の一覧（名前・説明・入力スキーマ）を返す
    tools/call   … 道具を実行する

**追加インストールは不要です**（標準ライブラリの json / sys / re / time だけで書いています）。
実務ではこの本体を Lambda（軽量・ステートレス）か ECS（重い・状態あり）に載せます。
stdio はローカル開発とテストのための形です（本文の判断表を参照）。

:::注意:::
標準出力は JSON-RPC の通信路です。**ここに print() で何かを書くと通信が壊れます。**
ログは必ず標準エラー出力へ書いてください（`_log()` を使う）。
"""

from __future__ import annotations

import json
import os
import re
import sys
import time

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session05")

import retriever  # noqa: E402  セッション5で決めた検索の共通入口をそのまま使う

PROTOCOL_VERSION = "2025-06-18"
SERVER_INFO = {"name": "sample-shoji-helpdesk-tools", "version": "1.0.0"}

CATEGORIES = ["IT", "経費", "人事", "セキュリティ"]
REPORT_ID = re.compile(r"^EXP-[0-9]{6}$")
EMPLOYEE_ID = re.compile(r"^EMP-[0-9]{4}$")

SEARCH_MODE = "HYBRID"
# 「何件返すか」はモデルに決めさせない。チューニング値はサーバー側の既定に持たせる
TOP_K = 3
MAX_SCAN_MS = 2000
MAX_TARGETS = 3

# 経費精算システムの代わり（実務では ECS 上のサーバーから社内 API を呼ぶ）
EXPENSE_REPORTS = {
    "EXP-000123": {"status": "承認待ち", "amount": 18400, "approver": "山田 太郎"},
    "EXP-000456": {"status": "差し戻し", "amount": 52000, "approver": "佐藤 花子"},
}

# 監視システムの代わり。attendance だけ必ず失敗させて「部分失敗」を作る
HEALTH = {
    "vpn": {"ok": True, "detail": "応答時間 42ms"},
    "attendance": {"ok": False, "detail": "認証サーバーへの接続がタイムアウト"},
    "portal": {"ok": True, "detail": "応答時間 88ms"},
}

# ---------------------------------------------------------------------------
# ツール定義（名前・説明文・入力スキーマ）
#
# **この3点がモデルとの契約です。** モデルはコードを読めないので、
# 「いつ呼ぶか」「何を渡すか」は説明文とスキーマからしか分かりません。
# ---------------------------------------------------------------------------

TOOLS: list[dict] = [
    {
        "name": "search_internal_docs",
        "description": (
            "サンプル商事の社内規程とヘルプデスク文書を検索し、出典付きの抜粋を返す。"
            "出張・宿泊費・上限・有給休暇・繰越上限・在宅勤務・パスワード・VPN など、"
            "制度や手順を問う質問では必ず呼び出すこと。"
            "query は助詞を落とし、語を半角スペースで区切ること。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "検索語。例: 有給休暇 繰越 上限",
                },
                "category": {
                    "type": "string",
                    "enum": CATEGORIES,
                    "description": "確実に分かるときだけ指定する。誤ると正解が母集団から消える",
                },
            },
            "required": ["query"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "lookup_expense_report",
        "description": (
            "経費精算システムに登録済みの申請の進捗と承認者を照会する。"
            "規程の条文は扱わない。EXP- と6けたの申請番号が判明しているときだけ使う。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "report_id": {
                    "type": "string",
                    "description": "申請番号。EXP- と6けたの数",
                }
            },
            "required": ["report_id"],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "check_service_health",
        "description": (
            "社内システム（VPN・勤怠システム・社内ポータル）の稼働状況をまとめて確認する。"
            "接続できない・遅いといった障害の切り分けに使う。"
            "targets を省略すると主要3系統をすべて確認する。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(HEALTH)},
                    "description": "確認する系統。省略すると3系統すべて",
                }
            },
            "required": [],
        },
        "annotations": {"readOnlyHint": True},
    },
    {
        "name": "reset_user_password",
        "description": (
            "指定した社員のパスワードを初期化する。書き込みを伴うため、実行前に人の承認が必要。"
            "employee_id は EMP- で始まる4けたの社員番号。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "employee_id": {
                    "type": "string",
                    "description": "社員番号。EMP- と4けたの数",
                }
            },
            "required": ["employee_id"],
        },
        "annotations": {"readOnlyHint": False, "destructiveHint": True},
    },
    {
        "name": "run_maintenance_scan",
        "description": (
            "夜間メンテナンスの走査を実行する。完了まで待たされるため、"
            "対話中の問い合わせには使わない。duration_ms は 2000 以下。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "duration_ms": {
                    "type": "integer",
                    "description": "走査にかける時間（ミリ秒）。2000 以下",
                }
            },
            "required": ["duration_ms"],
        },
        "annotations": {"readOnlyHint": True},
    },
]

TOOL_BY_NAME = {tool["name"]: tool for tool in TOOLS}


# ---------------------------------------------------------------------------
# 応答の組み立て
# ---------------------------------------------------------------------------


def _log(message: str) -> None:
    """標準エラー出力へ書く。標準出力は JSON-RPC 専用なので使ってはいけない。"""
    if os.environ.get("MCP_DEBUG"):
        print(f"[mcp-server] {message}", file=sys.stderr, flush=True)


def _result(request_id, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _error(request_id, code: int, message: str, data=None) -> dict:
    error: dict = {"code": code, "message": message}
    if data is not None:
        error["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": error}


def _tool_ok(payload: dict) -> dict:
    """ツールの成功。content は文字列なので JSON を文字列にして載せる。"""
    return {
        "content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}],
        "isError": False,
    }


def _tool_error(message: str) -> dict:
    """ツールの失敗。

    **JSON-RPC の error では返しません。** ツールの実行時エラーは「モデルが読んで
    次の一手を決める材料」なので、成功と同じ result の中に isError=True で載せます。
    JSON-RPC の error はプロトコル違反（呼び出し側のバグ）のときだけです。
    """
    return {"content": [{"type": "text", "text": message}], "isError": True}


# ---------------------------------------------------------------------------
# 引数の検証（サーバーは呼び出し側を信じない）
# ---------------------------------------------------------------------------

_TYPES = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
}


def _type_ok(expected: str, value) -> bool:
    if expected == "integer" and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES.get(expected, object))


def validate(schema: dict, arguments: dict) -> list[str]:
    """スキーマに対して引数を検証し、**人が読める指摘の一覧**を返す。

    指摘は「何が悪いか」だけでなく「どう直すか」まで書きます。
    モデルはこの文章だけを手がかりに呼び直すため、
    `ValidationError: category` のような機械向けの文言では復帰できません。
    """
    problems: list[str] = []
    properties: dict = schema.get("properties") or {}
    required = schema.get("required") or []

    for key in required:
        if key not in arguments or arguments[key] is None:
            problems.append(f"{key} は必須です。")

    for key, value in arguments.items():
        prop = properties.get(key)
        if prop is None:
            usable = " / ".join(properties) or "なし"
            problems.append(f"{key} は受け付けない引数です。使えるのは {usable} です。")
            continue
        if value is None:
            continue  # 省略と同じ扱いにする（null を渡してくるモデルがある）
        expected = prop.get("type", "string")
        if not _type_ok(expected, value):
            problems.append(f"{key} は {expected} で渡してください（受け取った値: {value!r}）。")
            continue
        if "enum" in prop and value not in prop["enum"]:
            candidates = " / ".join(str(v) for v in prop["enum"])
            problems.append(
                f"{key} に使えるのは {candidates} です（受け取った値: {value!r}）。"
                "判断できないときは省略してください。"
            )
        if expected == "array":
            item = prop.get("items") or {}
            for element in value:
                if "enum" in item and element not in item["enum"]:
                    candidates = " / ".join(str(v) for v in item["enum"])
                    problems.append(
                        f"{key} の要素に使えるのは {candidates} です"
                        f"（受け取った値: {element!r}）。"
                    )
    return problems


# ---------------------------------------------------------------------------
# 各ツールの実装
# ---------------------------------------------------------------------------

_AGENT = None


def _agent_runtime():
    """boto3 クライアントは初回の検索まで作らない（起動を軽くする）。"""
    global _AGENT
    if _AGENT is None:
        from awskit import clients

        _AGENT = clients.agent_runtime()
    return _AGENT


def _search_internal_docs(arguments: dict) -> dict:
    hits = retriever.search(
        _agent_runtime(),
        arguments["query"],
        mode=SEARCH_MODE,
        top_k=TOP_K,
        category=arguments.get("category"),
    )
    return _tool_ok(
        {
            "mode": SEARCH_MODE,
            "topK": TOP_K,
            # プロンプトの体裁（<context> で包むなど）はサーバーでは決めない。
            # ここで決めると、別のオーケストレータから使い回せなくなる
            "hits": [
                {
                    "uri": hit["uri"],
                    "title": hit["title"],
                    "category": hit["category"],
                    "updatedAt": hit["updated_at"],
                    "text": hit["text"],
                }
                for hit in hits
            ],
        }
    )


def _lookup_expense_report(arguments: dict) -> dict:
    report_id = arguments["report_id"]
    if not REPORT_ID.match(report_id):
        return _tool_error(
            f"report_id は EXP- と6けたの数で指定してください。"
            f"受け取った値 '{report_id}' では照会できません。"
            "申請番号が不明なときは、この道具を使わずに社内規程の検索を試してください。"
        )
    record = EXPENSE_REPORTS.get(report_id)
    if record is None:
        # 「見つからない」は失敗ではない。isError にするとモデルは道具が壊れたと解釈する
        return _tool_ok({"reportId": report_id, "found": False})
    return _tool_ok({"reportId": report_id, "found": True, **record})


def _check_service_health(arguments: dict) -> dict:
    targets = arguments.get("targets")
    if not targets:
        targets = list(HEALTH)
    if len(targets) > MAX_TARGETS:
        return _tool_error(
            f"targets は一度に {MAX_TARGETS} 件までです。分けて呼び出してください。"
        )
    ok: list[dict] = []
    failed: list[dict] = []
    for target in targets:
        entry = HEALTH[target]
        (ok if entry["ok"] else failed).append(
            {"target": target, "detail": entry["detail"]}
        )
    # 一部が失敗しても isError にしない。成功分をモデルに使わせるほうが役に立つ
    return _tool_ok(
        {
            "checked": len(targets),
            "ok": ok,
            "failed": failed,
            "partial": bool(ok and failed),
        }
    )


def _reset_user_password(arguments: dict) -> dict:
    employee_id = arguments["employee_id"]
    if not EMPLOYEE_ID.match(employee_id):
        return _tool_error(
            f"employee_id は EMP- と4けたの数で指定してください。"
            f"受け取った値 '{employee_id}' は使えません。"
        )
    # 実務では ID プロバイダの API を呼ぶ。ここは書き込み系の代役
    return _tool_ok(
        {
            "employeeId": employee_id,
            "result": "パスワードを初期化しました",
            "handoverMinutes": 30,
        }
    )


def _run_maintenance_scan(arguments: dict) -> dict:
    duration_ms = arguments["duration_ms"]
    if duration_ms < 0 or duration_ms > MAX_SCAN_MS:
        return _tool_error(
            f"duration_ms は 0 以上 {MAX_SCAN_MS} 以下で指定してください"
            f"（受け取った値: {duration_ms}）。"
        )
    # サーバー自身が上限を持つ。これが「時間の暴走」を止める最初の層
    time.sleep(duration_ms / 1000)
    return _tool_ok({"durationMs": duration_ms, "scanned": 128, "findings": 0})


HANDLERS = {
    "search_internal_docs": _search_internal_docs,
    "lookup_expense_report": _lookup_expense_report,
    "check_service_health": _check_service_health,
    "reset_user_password": _reset_user_password,
    "run_maintenance_scan": _run_maintenance_scan,
}


# ---------------------------------------------------------------------------
# ディスパッチ
# ---------------------------------------------------------------------------


def _call_tool(request_id, params: dict) -> dict:
    name = params.get("name")
    arguments = params.get("arguments")
    if arguments is None:
        arguments = {}
    tool = TOOL_BY_NAME.get(name)
    if tool is None:
        # 存在しない道具の呼び出しは呼び出し側のバグ。JSON-RPC の error で返す
        return _error(
            request_id,
            -32602,
            f"未知のツールです: {name}。使えるのは {', '.join(TOOL_BY_NAME)} です。",
        )
    if not isinstance(arguments, dict):
        return _error(request_id, -32602, "arguments はオブジェクトで渡してください。")
    problems = validate(tool["inputSchema"], arguments)
    if problems:
        _log(f"invalid arguments for {name}: {problems}")
        return _result(
            request_id,
            _tool_error("引数を直してから呼び直してください。" + " ".join(problems)),
        )
    return _result(request_id, HANDLERS[name](arguments))


def handle(request: dict, state: dict) -> dict | None:
    """1件のリクエストを処理する。応答不要なら None を返す。"""
    request_id = request.get("id")
    method = request.get("method")

    if request.get("jsonrpc") != "2.0":
        return _error(request_id, -32600, "jsonrpc は '2.0' である必要があります。")

    if request_id is None:
        # 通知（notification）には応答しない。ここで返すと
        # クライアント側の「1リクエスト1レスポンス」の対応付けが崩れる
        _log(f"notification: {method}")
        return None

    if method == "initialize":
        state["initialized"] = True
        return _result(
            request_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )

    if not state.get("initialized"):
        # -32099〜-32000 は実装が自由に使える範囲（JSON-RPC 2.0 の予約帯）
        return _error(request_id, -32002, "initialize を先に呼んでください。")

    if method == "tools/list":
        return _result(request_id, {"tools": TOOLS})

    if method == "tools/call":
        return _call_tool(request_id, request.get("params") or {})

    return _error(request_id, -32601, f"未対応のメソッドです: {method}")


def _write(payload: dict) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def main() -> int:
    state: dict = {"initialized": False}
    while True:
        line = sys.stdin.readline()
        if line == "":
            break  # 標準入力が閉じられた（クライアントの正常終了）
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError as error:
            _write(_error(None, -32700, f"JSON として読めません: {error}"))
            continue
        try:
            response = handle(request, state)
        except Exception as error:  # noqa: BLE001 — 落ちたら以後の通信が全部止まる
            response = _error(request.get("id"), -32603, f"サーバー内部エラー: {error}")
        if response is not None:
            _write(response)
    return 0


if __name__ == "__main__":
    sys.exit(main())
