from __future__ import annotations

import argparse
import os

DEFAULT_MAX_RESULTS = 5
MAX_ALLOWED_RESULTS = 20


def bounded_int(raw: str) -> int:
    """argparse の type に渡す変換関数。

    ここで ArgumentTypeError を投げると、argparse が使い方を表示して
    終了コード 2 で落ちてくれます（TypeScript 版の process.exit(2) と同じ意味）。
    """
    try:
        value = int(raw)
    except ValueError:
        raise argparse.ArgumentTypeError(f"整数を指定してください（受け取った値: {raw}）") from None
    if not 1 <= value <= MAX_ALLOWED_RESULTS:
        raise argparse.ArgumentTypeError(
            f"1 以上 {MAX_ALLOWED_RESULTS} 以下で指定してください（受け取った値: {value}）"
        )
    return value


# build_parser() に追加する。既定値を環境変数から取るのが要点
#   環境変数の検証も bounded_int に通したいので、default ではなく後段で解決する
def add_max_results(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--max-results",
        dest="max_results",
        type=bounded_int,
        default=None,
        metavar="N",
        help=f"検索結果の既定件数（1〜{MAX_ALLOWED_RESULTS}、既定 {DEFAULT_MAX_RESULTS}）",
    )


def resolve_max_results(cli_value: int | None, env: dict[str, str] | None = None) -> int:
    environ = os.environ if env is None else env
    if cli_value is not None:
        return cli_value
    raw = (environ.get("DOCSEARCH_MAX_RESULTS") or "").strip()
    if not raw:
        return DEFAULT_MAX_RESULTS
    # 環境変数も引数と同じ検証を通す。経路によって厳しさが変わってはいけない
    return bounded_int(raw)
