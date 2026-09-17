"""mid01 のドメイン層を session09 から読み込むためのブリッジ

中間プロジェクト1 のコードは 1 行も書き換えません。パッケージ化していないため
sys.path を足して読み込みます（実務ではパッケージにします ―― セッション14）。
"""

import sys
from pathlib import Path

_MID01 = Path(__file__).resolve().parents[1] / "mid01"
if str(_MID01) not in sys.path:
    sys.path.insert(0, str(_MID01))

import docs_domain as domain  # noqa: E402

__all__ = ["domain"]
