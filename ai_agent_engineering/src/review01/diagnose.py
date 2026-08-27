#!/usr/bin/env python3
"""症状から原因へ切り分ける（S02＋S03＋S04＋S05 の合わせ技）。

障害報告は「途中で止まる」「同じことを繰り返す」で来る。それは**症状**であって
原因ではない。原因は次の6つに分かれ、手当てをするセッションが違う。

  上限不足             … 正常な手数に届く前に打ち切っている（S03）
  道具のエラーが不親切 … 失敗しても次の行動が決まらない（S04）
  道具の粒度が粗い     … 自由文字列1引数の道具に当てにいっている（S04）
  モデルが直せない     … 良いエラーを返しても同じ誤りを繰り返す（S05）
  計画がない           … 失敗していないのに進まない（S05）
  報告が実態と違う     … done なのに、やっていないことを報告する（S02）

判定に使う道具はすべて既習のものである。
  - `failure_modes.classify()`（S02）… 症状を5つの失敗モードに落とす
  - `Trajectory.stop_reason`（S03）  … 自分で止まったのか外から止められたのか
  - `goodtools.is_actionable()`（S04）… エラーが「次の行動を決められる」形か
  - ツールのスキーマ（S04）          … 自由文字列1引数かどうか
"""

from __future__ import annotations

from _paths import setup

ROOT = setup()

from agentkit.models import Trajectory  # noqa: E402
from failure_modes import classify  # noqa: E402  (src/session02)
from goodtools import is_actionable  # noqa: E402  (src/session04)

# 表示順を固定する（人によって並びが変わると比較できない）
CAUSES = ("上限不足", "道具のエラーが不親切", "道具の粒度が粗い",
          "モデルが直せない", "計画がない", "報告が実態と違う")

# 原因ごとに「どのセッションの手当てをするか」。診断の出口を1つに決める
TREATMENT = {
    "上限不足": "S03（上限は深さ＋余裕＋報告で決める）",
    "道具のエラーが不親切": "S04（エラーに許容値と次の一手を書く）",
    "道具の粒度が粗い": "S04（自由文字列1引数をやめてスキーマで縛る）",
    "モデルが直せない": "S05（サブゴールを分けるか人間に渡す）",
    "計画がない": "S05（再計画のトリガを設計する）",
    "報告が実態と違う": "S02（最終回答をツール結果で裏取りする）",
}


def free_text_tool(tool) -> bool:
    """引数が「自由文字列1つ」の道具か（モデルが形式を当てにいく道具か）。"""
    if tool is None:
        return False
    props = tool.schema.get("properties", {})
    if len(props) != 1:
        return False
    (spec,) = props.values()
    return (spec.get("type") == "string"
            and "enum" not in spec and "maxLength" not in spec)


def failed_pairs(traj: Trajectory) -> list[tuple]:
    """失敗した（呼び出し, 結果）の組を、呼ばれた順に返す。"""
    return [(call, result)
            for step in traj.steps
            for call, result in zip(step.calls, step.results)
            if not result.ok]


def repeated_failure(pairs: list[tuple]) -> bool:
    """同じツールが2回以上失敗しているか（1回の失敗と繰り返しを区別する）。"""
    names = [call.name for call, _result in pairs]
    return any(names.count(name) >= 2 for name in set(names))


def diagnose(traj: Trajectory, *, registry, allowed_tools, needed_steps: int) -> list[str]:
    """軌跡と道具から原因を挙げる。`CAUSES` の順に並べて返す。

    needed_steps は「正常に終わるのに必要な手数（報告の1手を含む）」の見積り。
    軌跡だけでは上限不足と暴走を区別できないので、設計時の見積りを外から渡す。
    """
    found: set[str] = set()
    modes = classify(traj, allowed_tools=set(allowed_tools), registry=registry)
    pairs = failed_pairs(traj)

    if traj.stop_reason in ("max_steps", "budget"):
        if needed_steps > len(traj.steps):
            # 正常な手数に届く前に打ち切っている。道具もモデルも悪くない
            found.add("上限不足")
        elif pairs:
            actionable = [is_actionable(result.error or "") for _call, result in pairs]
            if not all(actionable):
                found.add("道具のエラーが不親切")
            if any(free_text_tool(registry.get(call.name)) for call, _r in pairs):
                found.add("道具の粒度が粗い")
            if all(actionable) and repeated_failure(pairs):
                # 道具は直っている。ここから先は道具では直らない
                found.add("モデルが直せない")
        elif "停滞" in modes:
            # 1回も失敗していないのに進まない＝次に何をするかが決まっていない
            found.add("計画がない")
    elif {"幻覚", "誤選択"} & set(modes):
        found.add("報告が実態と違う")

    return [cause for cause in CAUSES if cause in found]


def untrusted_reasons(traj: Trajectory, *, registry, allowed_tools) -> list[str]:
    """最終回答を信用してはいけない理由を並べる。空なら信用してよい。"""
    reasons: list[str] = []
    if traj.stop_reason != "done":
        reasons.append(f"停止理由が done ではない（{traj.stop_reason}）")
    if not traj.final:
        reasons.append("最終回答が空")
    reasons += [f"失敗モード: {mode}"
                for mode in classify(traj, allowed_tools=set(allowed_tools),
                                     registry=registry)]
    return reasons


def is_trustworthy_done(traj: Trajectory, *, registry, allowed_tools) -> bool:
    """`stop_reason == "done"` を鵜呑みにせず、裏取りできたときだけ True。"""
    return not untrusted_reasons(traj, registry=registry, allowed_tools=allowed_tools)


def cause_label(causes: list[str], trustworthy: bool) -> str:
    """原因が挙がらなかったときに「異常なし」と「説明できない」を区別する。"""
    if causes:
        return ", ".join(causes)
    return "異常なし" if trustworthy else "この6つでは説明できない"


def main() -> None:
    import traces  # 循環参照を避けるため、実行時にだけ読み込む

    print("=== 症状 → 原因 → 手当て ===")
    print("軌跡 | 停止理由 | 失敗モード | 原因 | 手当て")
    for case in traces.build_cases():
        kwargs = {"registry": case.registry, "allowed_tools": case.allowed}
        modes = classify(case.traj, allowed_tools=set(case.allowed), registry=case.registry)
        causes = diagnose(case.traj, needed_steps=case.needed_steps, **kwargs)
        print(f"{case.label} | {case.traj.stop_reason} | "
              f"{', '.join(modes) or '検出なし'} | "
              f"{cause_label(causes, is_trustworthy_done(case.traj, **kwargs))} | "
              f"{', '.join(dict.fromkeys(TREATMENT[c] for c in causes)) or '手当てなし'}")


if __name__ == "__main__":
    main()
