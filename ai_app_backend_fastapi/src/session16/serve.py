"""本番の起動口。設定を検証してから uvicorn を起動する（--reload は付けない）。

    python -m src.session16.serve           # 起動（Dockerfile.prod の CMD）
    python -m src.session16.serve --check   # 設定の検証だけして終わる（0=OK・1=NG）。秘密の値は表示しない

uvicorn の CLI ではなく Python から起動するのは、ワーカー数や猶予の秒数を「検証済みの設定」から渡すため。
Dockerfile の exec 形式の CMD には環境変数を展開する仕組みが無く、シェルを挟むと SIGTERM が届かない書き方になりやすい。
"""

from __future__ import annotations

import sys

import uvicorn

from .config import load_settings_or_exit

APP = "src.session16.app:app"  # --workers を使うときは、アプリを「import できる文字列」で渡す


def main(argv: list[str]) -> int:
    settings = load_settings_or_exit()  # 足りなければここで終了コード 1。uvicorn もワーカーも起動しない
    if "--check" in argv:
        print(f"設定 OK：{settings.summary()}")
        return 0
    uvicorn.run(
        APP,
        host="0.0.0.0",
        port=8000,
        workers=settings.web_workers,
        timeout_graceful_shutdown=settings.graceful_timeout_seconds,
        timeout_keep_alive=5,
        access_log=False,  # アクセスログは RequestIdMiddleware の request_finished（JSON）に一本化する
        server_header=False,  # Server: uvicorn を返さない（使っているソフトを宣伝しない）
    )
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
