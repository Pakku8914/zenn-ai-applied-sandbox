"""問題2：単価表とモデルの設定を、起動する前に突き合わせる（セッション16 × セッション13）。

フォールバック先のモデルが単価表に無いと、台帳に cost_usd=NULL（unpriced）で記録され続ける（セッション13）。
それを「警告のログで気づく」のではなく、起動時の設定の検証（セッション16の serve --check）で落とす。
"""

from __future__ import annotations

import json
import sys
from collections.abc import Mapping
from datetime import datetime
from pathlib import Path

from kondate.clock import JST

from .pricing import parse_price_table


def startup_problems(models: Mapping[str, str], path: Path, at: datetime) -> list[str]:
    """「- 名前: 理由」の行のリスト。空なら起動してよい。models は {環境変数名: モデル ID}。"""
    try:
        table = parse_price_table(json.loads(path.read_text(encoding="utf-8")))
    except OSError:
        return ["- PRICES: 単価表のファイルを読めません"]
    except json.JSONDecodeError:  # ValueError の子なので、ValueError より先に判定する
        return ["- PRICES: 単価表が JSON として読めません"]
    except KeyError as e:
        return [f"- PRICES: 単価表に項目 {e.args[0]} がありません"]
    except ValueError as e:  # pricing.py が出す、こちらで書いた日本語の理由（値に秘密は含まれない）
        return [f"- PRICES: {e}"]
    day = at.astimezone(JST).date()
    return [f"- {name}: 単価表にありません（{model}・{day} 時点）"
            for name, model in models.items() if table.price_for(model, at) is None]


def check_or_exit(models: Mapping[str, str], path: Path, at: datetime) -> None:
    """問題があれば理由を標準エラーに並べ、終了コード 1 で止まる（セッション16の load_settings_or_exit と同じ形）。"""
    problems = startup_problems(models, path, at)
    if problems:
        print(f"設定エラー：起動を中止します（{len(problems)} 件）", *problems, sep="\n", file=sys.stderr)
        raise SystemExit(1)
