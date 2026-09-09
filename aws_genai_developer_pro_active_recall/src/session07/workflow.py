#!/usr/bin/env python3
"""セッション7: 停止条件をワークフロー側（AWS Step Functions）にも置く。

アプリのループに書いた停止条件は、**そのプロセスが生きている間だけ**効きます。
デプロイが古い／プロセスが落ちた／誰かが `while True` に書き換えた、のいずれでも
効かなくなります。長時間・多段のエージェントは反復そのものを状態機械にして、
外側から止めるほうが確実です。

この定義は本章では登録も実行もしません（同梱の LocalStack Community に Lambda が無く、
Bedrock も自作モックで代替しているため）。代わりに**定義そのものを検査対象**にします。
停止条件は「消しても動いてしまう」種類の設定なので、回帰テストで守る価値があります。
"""

from __future__ import annotations

# Amazon States Language（ASL）の定義。反復のたびに CheckBudget へ戻るのが要点
STATE_MACHINE: dict = {
    "Comment": "社内ヘルプデスクのエージェント（反復を外側から止める）",
    "StartAt": "Init",
    # 状態機械全体の上限。ここが最後の砦になる
    "TimeoutSeconds": 120,
    "States": {
        "Init": {
            "Type": "Pass",
            "Parameters": {
                "question.$": "$.question",
                "messages.$": "$.messages",
                "iteration": 0,
                "maxIterations": 4,
            },
            "Next": "CheckBudget",
        },
        "CheckBudget": {
            "Type": "Choice",
            "Choices": [
                {
                    "Variable": "$.iteration",
                    "NumericLessThanPath": "$.maxIterations",
                    "Next": "Think",
                }
            ],
            "Default": "StoppedByMaxIterations",
        },
        "Think": {
            "Type": "Task",
            "Resource": "arn:aws:states:::bedrock:invokeModel",
            "Parameters": {
                "ModelId": "amazon.nova-lite-v1:0",
                "Body": {"messages.$": "$.messages"},
            },
            "TimeoutSeconds": 30,
            "Retry": [
                {
                    "ErrorEquals": ["Bedrock.ThrottlingException"],
                    "IntervalSeconds": 2,
                    "MaxAttempts": 3,
                    "BackoffRate": 2.0,
                }
            ],
            "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "StoppedByError"}],
            "Next": "ToolNeeded",
        },
        "ToolNeeded": {
            "Type": "Choice",
            "Choices": [
                {"Variable": "$.stopReason", "StringEquals": "tool_use", "Next": "RunTool"}
            ],
            "Default": "Done",
        },
        "RunTool": {
            "Type": "Task",
            # ツールは別の権限で動かす。エージェント本体の実行ロールに
            # 書き込み権限を与えないための分離
            "Resource": "arn:aws:states:::lambda:invoke",
            "Parameters": {
                "FunctionName": "sample-shoji-helpdesk-tools",
                "Payload.$": "$.toolUse",
            },
            "TimeoutSeconds": 15,
            "Retry": [
                {
                    "ErrorEquals": ["Lambda.TooManyRequestsException"],
                    "IntervalSeconds": 1,
                    "MaxAttempts": 2,
                    "BackoffRate": 2.0,
                }
            ],
            "Catch": [{"ErrorEquals": ["States.ALL"], "Next": "StoppedByError"}],
            "Next": "Increment",
        },
        "Increment": {
            "Type": "Pass",
            "Parameters": {
                "iteration.$": "States.MathAdd($.iteration, 1)",
                "maxIterations.$": "$.maxIterations",
                "messages.$": "$.messages",
            },
            "Next": "CheckBudget",
        },
        "Done": {"Type": "Succeed"},
        "StoppedByMaxIterations": {
            "Type": "Fail",
            "Error": "MaxIterationsExceeded",
            "Cause": "最大反復に達したため打ち切りました",
        },
        "StoppedByError": {
            "Type": "Fail",
            "Error": "AgentStepFailed",
            "Cause": "モデルまたはツールの呼び出しが失敗しました",
        },
    },
}

# Task 状態に必ず要るもの。1つでも欠けると「終わらない実行」が作れてしまう
REQUIRED_TASK_GUARDS = ("TimeoutSeconds", "Retry", "Catch")


def audit(definition: dict) -> list[str]:
    """停止条件のうち欠けているものを列挙する。空リストなら合格。"""
    findings: list[str] = []

    if not definition.get("TimeoutSeconds"):
        findings.append("状態機械全体の TimeoutSeconds がない")

    states: dict = definition.get("States") or {}
    for name, state in states.items():
        if state.get("Type") != "Task":
            continue
        for guard in REQUIRED_TASK_GUARDS:
            if guard not in state:
                findings.append(f"{name}: Task に {guard} がない")
        for retry in state.get("Retry", []):
            if not retry.get("MaxAttempts"):
                findings.append(f"{name}: Retry に MaxAttempts がない")

    caps = [
        state
        for state in states.values()
        if state.get("Type") == "Choice"
        and any("iteration" in str(choice) for choice in state.get("Choices", []))
    ]
    if not caps:
        findings.append("反復回数を判定する Choice がない")
    else:
        default = caps[0].get("Default")
        if states.get(default, {}).get("Type") != "Fail":
            findings.append("反復上限を超えたときに Fail へ落ちない")

    return findings
