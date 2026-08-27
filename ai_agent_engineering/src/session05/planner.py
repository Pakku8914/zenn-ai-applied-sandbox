#!/usr/bin/env python3
"""計画（Plan）とサブゴール（SubGoal）の表現・検証・依存の並べ替え。

この章の中心は「計画を LLM の自由文で持たない」ことである。計画を構造として持つと、
実行する前に妥当性を検査でき、依存を DAG として並べ替えられる。

    python src/session05/planner.py    # 参照用の計画を検証・層分けして表示する
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

MAX_SUBGOALS = 8  # これ以上に分解すると文脈が分断されやすい（本文8節）

PLAN_SCHEMA_EXAMPLE = """{
  "goal": "全体の目的を1文で",
  "subgoals": [
    {
      "id": "sg_policy",
      "goal": "このサブゴールで何を確定させるか",
      "tools": ["get_policy"],
      "needs": [],
      "consumes": [],
      "produces": ["policy"],
      "max_steps": 2
    }
  ]
}"""


class PlanError(Exception):
    """計画そのものが壊れている（JSON にならない・必須項目が無い・循環がある）。"""


@dataclass(frozen=True)
class SubGoal:
    """サブゴール1つ。

    tools     : このサブゴールで使わせるツール名（許可リストになる）
    needs     : 依存する他のサブゴールの id（DAG の辺）
    consumes  : 実行に必要な成果キー（前のサブゴールの produces で満たす）
    produces  : このサブゴールが確定させる成果キー
    max_steps : このサブゴールに許すステップ数の上限
    """

    id: str
    goal: str
    tools: tuple[str, ...] = ()
    needs: tuple[str, ...] = ()
    consumes: tuple[str, ...] = ()
    produces: tuple[str, ...] = ()
    max_steps: int = 2


@dataclass(frozen=True)
class Plan:
    goal: str = ""
    subgoals: tuple[SubGoal, ...] = field(default_factory=tuple)

    @property
    def ids(self) -> list[str]:
        return [sg.id for sg in self.subgoals]

    def get(self, sg_id: str) -> SubGoal | None:
        return next((sg for sg in self.subgoals if sg.id == sg_id), None)

    def as_text(self) -> str:
        """再計画のトリガ判定で「計画が何に触れているか」を調べるための平文。"""
        return "\n".join(f"{sg.id}: {sg.goal}" for sg in self.subgoals)


def build_plan_prompt(task: str, tool_names: list[str], context: str = "") -> str:
    """計画を立てさせるプロンプト。出力形式を JSON に固定するのが要点。"""
    return (
        "あなたは業務代行エージェントの計画担当です。次のタスクを、"
        f"{MAX_SUBGOALS} 個以内のサブゴールに分解してください。\n\n"
        f"# タスク\n{task}\n\n"
        f"# 使えるツール\n{', '.join(tool_names)}\n\n"
        f"# すでに分かっていること\n{context or '（まだ何も実行していません）'}\n\n"
        "# 出力の決まり\n"
        "- JSON だけを返す（前後に説明を書かない）\n"
        "- 各サブゴールに、使うツール・依存するサブゴール・必要な成果キー・"
        "作る成果キー・ステップ上限を書く\n"
        "- 最後のサブゴールは成果キー report を作ること\n"
        "- 他のサブゴールの結果が必要なら、needs と consumes の両方に書くこと\n\n"
        f"# 出力の形\n{PLAN_SCHEMA_EXAMPLE}\n"
    )


def parse_plan(text: str) -> Plan:
    """LLM の出力を Plan にする。計画も生成物なので、必ずパースと検査を通す。"""
    try:
        raw = json.loads(text)
    except json.JSONDecodeError as exc:
        raise PlanError(
            f"計画が JSON として読めません（{exc.msg}）。"
            "計画は JSON だけを返す必要があります。"
        ) from exc
    if not isinstance(raw, dict) or "subgoals" not in raw:
        raise PlanError('計画に "subgoals" がありません。出力の形を守らせてください。')
    if not isinstance(raw["subgoals"], list) or not raw["subgoals"]:
        raise PlanError("サブゴールが0個です。少なくとも1つ必要です。")

    subgoals: list[SubGoal] = []
    for i, item in enumerate(raw["subgoals"], start=1):
        if not isinstance(item, dict):
            raise PlanError(f"{i} 番目のサブゴールがオブジェクトではありません。")
        missing = [k for k in ("id", "goal") if not item.get(k)]
        if missing:
            raise PlanError(f"{i} 番目のサブゴールに {', '.join(missing)} がありません。")
        subgoals.append(SubGoal(
            id=str(item["id"]),
            goal=str(item["goal"]),
            tools=tuple(item.get("tools", ())),
            needs=tuple(item.get("needs", ())),
            consumes=tuple(item.get("consumes", ())),
            produces=tuple(item.get("produces", ())),
            max_steps=int(item.get("max_steps", 2)),
        ))
    return Plan(goal=str(raw.get("goal", "")), subgoals=tuple(subgoals))


def topo_layers(plan: Plan, *, done: tuple[str, ...] = ()) -> list[list[SubGoal]]:
    """依存を層に分ける。同じ層のサブゴールは互いに依存していない。

    層の中の並びは計画の記述順を保つ（実行順が環境によって変わらないようにする）。
    計画に無い依存先は無視する（それは validate_plan が別途報告する）。
    """
    in_plan = {sg.id for sg in plan.subgoals}
    waiting = {sg.id: {n for n in sg.needs
                       if n in in_plan and n not in done and n != sg.id}
               for sg in plan.subgoals}
    by_id = {sg.id: sg for sg in plan.subgoals}
    layers: list[list[SubGoal]] = []
    placed: set[str] = set()
    while waiting:
        ready = [sg.id for sg in plan.subgoals
                 if sg.id in waiting and not (waiting[sg.id] - placed)]
        if not ready:
            raise PlanError(
                f"依存に循環があります（解決できないサブゴール: {', '.join(sorted(waiting))}）。"
            )
        layers.append([by_id[i] for i in ready])
        placed |= set(ready)
        for i in ready:
            waiting.pop(i)
    return layers


def topo_order(plan: Plan, *, done: tuple[str, ...] = ()) -> list[SubGoal]:
    """実行順（層の順 → 層の中は記述順）。"""
    return [sg for layer in topo_layers(plan, done=done) for sg in layer]


def _ancestors(plan: Plan, sg_id: str) -> set[str]:
    """依存の推移閉包。循環があっても無限ループしないように visited で止める。"""
    by_id = {sg.id: sg for sg in plan.subgoals}
    seen: set[str] = set()
    stack = list(by_id[sg_id].needs) if sg_id in by_id else []
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in by_id:
            continue
        seen.add(cur)
        stack.extend(by_id[cur].needs)
    return seen


def validate_plan(plan: Plan, tool_names: list[str], *,
                  done: tuple[str, ...] = (), known: tuple[str, ...] = (),
                  requires: tuple[str, ...] = ("report",),
                  max_subgoals: int = MAX_SUBGOALS) -> list[str]:
    """実行する前に計画の妥当性を検査する。違反の一覧を返す（空なら合格）。

    done  : すでに完了したサブゴールの id（再計画のときに渡す）
    known : すでに手元にある成果キー（再計画のときに渡す）
    """
    violations: list[str] = []
    ids = plan.ids
    dup = sorted({i for i in ids if ids.count(i) > 1})
    if dup:
        violations.append(f"サブゴールの id が重複しています: {', '.join(dup)}")
    if len(plan.subgoals) > max_subgoals:
        violations.append(
            f"サブゴールが多すぎます（{len(plan.subgoals)} 個 / 上限 {max_subgoals} 個）。"
            "分解しすぎると1つあたりの文脈が薄くなります"
        )

    known_ids = set(ids) | set(done)
    for sg in plan.subgoals:
        for t in sg.tools:
            if t not in tool_names:
                violations.append(
                    f"{sg.id}: 未登録のツール '{t}' を指定しています"
                    f"（使えるツール: {', '.join(tool_names)}）"
                )
        if sg.id in sg.needs:
            violations.append(f"{sg.id}: 自分自身に依存しています")
        for n in sg.needs:
            if n != sg.id and n not in known_ids:
                violations.append(f"{sg.id}: 依存先 '{n}' が計画にありません")
        if sg.max_steps < 1:
            violations.append(f"{sg.id}: max_steps が {sg.max_steps} です（1 以上にしてください）")

    try:
        topo_layers(plan, done=done)
    except PlanError as exc:
        violations.append(str(exc))
        return violations  # 循環があると以降の検査は当てにならない

    # 未充足の入力＝文脈の分断。依存の推移閉包が produces で満たしているかを見る
    for sg in plan.subgoals:
        available = set(known)
        for anc in _ancestors(plan, sg.id):
            anc_sg = plan.get(anc)
            if anc_sg is not None:
                available |= set(anc_sg.produces)
        unmet = [k for k in sg.consumes if k not in available]
        if unmet:
            violations.append(
                f"{sg.id}: 必要な情報 {', '.join(unmet)} を作るサブゴールが依存に入っていません"
                "（needs と consumes の対応を見直してください）"
            )

    produced = {k for sg in plan.subgoals for k in sg.produces} | set(known)
    for key in requires:
        if key not in produced:
            violations.append(f"成果キー '{key}' を作るサブゴールがありません")
    return violations


def plan_cost(plan: Plan) -> dict:
    """計画そのもののコスト。実行前に見積もれる下限値。"""
    text = json.dumps(
        {"goal": plan.goal,
         "subgoals": [{"id": s.id, "goal": s.goal, "tools": list(s.tools),
                       "needs": list(s.needs), "consumes": list(s.consumes),
                       "produces": list(s.produces), "max_steps": s.max_steps}
                      for s in plan.subgoals]},
        ensure_ascii=False)
    return {
        "subgoals": len(plan.subgoals),
        "min_llm_calls": sum(sg.max_steps for sg in plan.subgoals) + 1,  # +1 は計画の呼び出し
        "approx_plan_tokens": len(text) // 3,  # 近似トークン数（比較用）
    }


def render_plan_md(plan: Plan) -> str:
    """引き継げる成果物としての計画表（Markdown）。"""
    head = f"### 計画: {plan.goal}\n\n" if plan.goal else "### 計画\n\n"
    rows = ["| id | サブゴール | 使うツール | 依存 | 必要な情報 | 作る情報 | 上限 |",
            "| :--- | :--- | :--- | :--- | :--- | :--- | --: |"]
    for sg in plan.subgoals:
        rows.append(
            f"| {sg.id} | {sg.goal} | {', '.join(sg.tools) or '-'} | "
            f"{', '.join(sg.needs) or '-'} | {', '.join(sg.consumes) or '-'} | "
            f"{', '.join(sg.produces) or '-'} | {sg.max_steps} |"
        )
    return head + "\n".join(rows) + "\n"


def mermaid_dag(plan: Plan) -> str:
    """計画の DAG を Mermaid で書き出す（設計レビューに回せる成果物）。"""
    lines = ["flowchart LR"]
    for sg in plan.subgoals:
        lines.append(f'  {sg.id}["{sg.id}<br/>{sg.goal[:18]}"]')
    for sg in plan.subgoals:
        for n in sg.needs:
            lines.append(f"  {n} --> {sg.id}")
    return "\n".join(lines)


def main() -> None:
    from plans import PLAN_FRAGMENTED, PLAN_OK, PLAN_OVERSPLIT, plan_from  # noqa: PLC0415

    tools = ["book_room", "get_employee", "get_policy", "list_expenses", "read_file",
             "search_docs", "send_message", "submit_expense", "write_file"]
    for label, raw in (("正しい計画", PLAN_OK), ("分解しすぎ", PLAN_FRAGMENTED),
                       ("過分解（10個）", PLAN_OVERSPLIT)):
        plan = plan_from(raw)
        print(f"=== {label} ===")
        print(render_plan_md(plan))
        print(f"コスト: {plan_cost(plan)}")
        violations = validate_plan(plan, tools)
        print(f"違反 {len(violations)} 件")
        for v in violations:
            print(f"  - {v}")
        try:
            layers = topo_layers(plan)
        except PlanError as exc:
            print(f"層に分けられません: {exc}")
        else:
            for i, layer in enumerate(layers):
                print(f"  層{i}: {', '.join(sg.id for sg in layer)}")
        print()
    print("=== 正しい計画の DAG（Mermaid）===")
    print(mermaid_dag(plan_from(PLAN_OK)))


if __name__ == "__main__":
    main()
