"""docsearch-mcp ― コンソールスクリプトの入口（[project.scripts] が指す先）

  docsearch-mcp --docs-root /abs/path/to/docs
  DOCSEARCH_ROOT=/abs/path/to/docs docsearch-mcp

stdout は JSON-RPC の通信路なので、サーバーとして動き始めたあとは print しません。
--help / --version は「サーバーではないモード」なので stdout でかまいません。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__

PROGRAM = "docsearch-mcp"


def resolve_docs_root(cli_value: str | None, env: dict[str, str] | None = None) -> Path | None:
    """① 引数 → ② 環境変数 DOCSEARCH_ROOT の順で決める。

    TypeScript 版と違って「既定値」を持ちません。配布物では作業ディレクトリを
    ホストが決めるため、相対パスの既定値は当たらないからです（7 節）。
    """
    environ = os.environ if env is None else env
    if cli_value:
        return Path(cli_value).expanduser().resolve()
    from_env = environ.get("DOCSEARCH_ROOT")
    if from_env:
        return Path(from_env).expanduser().resolve()
    return None


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROGRAM,
        description="社内 Markdown を全文検索する読み取り専用の MCP サーバー（stdio）",
        epilog="手で起動すると何も表示されずに待機しますが異常ではありません（Ctrl+C で終了）。",
    )
    # 位置引数も受け付ける（開発中の起動方法との互換）
    parser.add_argument("docs_root", nargs="?", default=None, help=argparse.SUPPRESS)
    parser.add_argument(
        "--docs-root",
        dest="docs_root_option",
        default=None,
        metavar="DIR",
        help="検索対象の Markdown が置かれたディレクトリ（絶対パスを推奨）",
    )
    parser.add_argument("--version", action="version", version=f"{PROGRAM} {__version__}")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = resolve_docs_root(args.docs_root_option or args.docs_root)

    if root is None:
        print(
            f"{PROGRAM}: 検索対象ディレクトリが指定されていません。\n"
            "--docs-root <DIR> を渡すか、環境変数 DOCSEARCH_ROOT を設定してください。",
            file=sys.stderr,
        )
        return 2
    if not root.is_dir():
        print(
            f"{PROGRAM}: 検索対象ディレクトリが見つかりません: {root}\n"
            "相対パスの基準はホストが決めた作業ディレクトリです。絶対パスを推奨します。",
            file=sys.stderr,
        )
        return 2

    # 重い import は main の中で行う。--version や引数エラーが速くなり、
    # 依存が壊れていても「使い方」を表示できる
    from .create_server import create_docsearch_server

    print(f"[{PROGRAM}] v{__version__} / docs_root={root}", file=sys.stderr)
    create_docsearch_server(root).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
