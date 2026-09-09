#!/usr/bin/env python3
"""セッション11: CI/CD パイプラインに置くゲート（生成AI固有のテスト＋走査）。

    docker compose exec app python src/session11/pipeline_gates.py

**実務ではこの4つを AWS CodePipeline のステージに置きます。**
CodeBuild のビルドプロジェクトが各ゲートを実行し、非0で終われば
その先のデプロイステージには進みません。

    Source → Build → GenAI テスト → セキュリティ走査 → デプロイ（カナリア）→ 承認 → 全面

LocalStack Community に CodePipeline / CodeBuild は無いため、
ここでは**ゲートの中身**だけを Python の関数として書きます。
「どこに置くか」と「何を落とすか」は実 AWS でも同じです。

各ゲートは **失敗の一覧（空なら合格）** を返します。真偽値ではなく一覧を返すのは、
パイプラインのログに「何が落ちたか」を出すためです。
"""

from __future__ import annotations

import json
import re
import sys

sys.path.insert(0, "/workspace")
sys.path.insert(0, "/workspace/src/session06")
sys.path.insert(0, "/workspace/src/session11")

import authz  # noqa: E402
import prompt_registry as registry  # noqa: E402

# シークレット走査のパターン。実務では git-secrets / detect-secrets /
# Amazon CodeGuru Security などに任せ、**コミット前とビルド時の2か所**で回す
SECRET_PATTERNS = (
    r"AKIA[0-9A-Z]{16}",
    r"(?i)(?:secret|password|passwd|api[_-]?key|access[_-]?key)[a-z0-9_]*\s*[:=]\s*\S{8,}",
    r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
)


def gate_prompt_regression(s3, name: str) -> list[str]:
    """ゲート1: 承認済みの版が「落としてはいけない一文」を保っているか。

    プロンプトはコードと同じ資産なので、変更のたびに回帰テストが要ります。
    ここで見るのは**本番が実際に読む版**（承認済みの版）です。
    手元の下書きが通っても、承認済みの版が壊れていれば意味がありません。
    """
    version, template, _ = registry.load_approved(s3, name)
    phrases = registry.REQUIRED_PHRASES.get((name, version))
    if phrases is None:
        return [f"{name} v{version} の必須フレーズが宣言されていません"]
    return [f"{name} v{version}: 必須フレーズ「{p}」が失われています"
            for p in registry.missing_phrases(template, phrases)]


def gate_authz_matrix() -> list[str]:
    """ゲート2: 認可の期待表と、ポリシー評価の結果が一致するか。

    **権限の変更を「意図した通りか」で判定する**のが要点です。
    ポリシーを1行足したときに、別の部門の権限まで広がっていないかを機械が見ます。
    """
    failures = []
    for role, model_id, expected in authz.EXPECTED_MATRIX:
        decision = authz.can_invoke(authz.principal_for_role(role), model_id)
        if decision.allowed != expected:
            failures.append(
                f"{role} -> {model_id}: 期待 {expected} / 実際 {decision.describe()}"
            )
    return failures


def gate_secret_scan(texts: list[str]) -> list[str]:
    """ゲート3: 資格情報の直書きを検出する。

    生成AIのアプリは外部 API のキーを持ちがちです。キーは Secrets Manager に置き、
    コードには**名前だけ**を書きます。
    """
    findings = []
    for index, text in enumerate(texts):
        for pattern in SECRET_PATTERNS:
            if re.search(pattern, text):
                findings.append(f"入力[{index}]: パターン {pattern!r} に一致しました")
    return findings


def gate_audit_no_payload(entries: list[dict], forbidden: list[str]) -> list[str]:
    """ゲート4: 監査ログに本文が混ざっていないか。

    「ログに全文を出す」変更は、レビューでは見落とされ、
    個人情報の保存場所を静かに増やします。機械で止めます。
    """
    serialized = json.dumps(entries, ensure_ascii=False)
    return [f"監査ログに残してはいけない文字列が含まれています: {needle[:20]}…"
            for needle in forbidden if needle and needle in serialized]


def run_all(s3, *, prompt_name: str, texts: list[str], entries: list[dict],
            forbidden: list[str]) -> int:
    """4つのゲートを順に回す。1つでも落ちたら非0を返す（＝デプロイしない）。"""
    gates = {
        "プロンプト回帰": gate_prompt_regression(s3, prompt_name),
        "認可マトリクス": gate_authz_matrix(),
        "シークレット走査": gate_secret_scan(texts),
        "監査ログの本文混入": gate_audit_no_payload(entries, forbidden),
    }
    failed = 0
    for label, failures in gates.items():
        if failures:
            failed += 1
            print(f"  NG   {label}")
            for detail in failures:
                print(f"       - {detail}")
        else:
            print(f"  ok   {label}")
    return 1 if failed else 0


def main() -> None:
    s3 = registry.ensure_bucket()
    for version in (1, 2):
        registry.publish(s3, "helpdesk-answer", version)
    registry.approve(s3, "helpdesk-answer", 2, approver="helpdesk-owner")

    print("=== パイプラインのゲート（合格すればデプロイステージへ進む） ===")
    code = run_all(
        s3,
        prompt_name="helpdesk-answer",
        texts=["primary = amazon.nova-lite-v1:0", "promptName = helpdesk-answer"],
        entries=[{"requestId": "req-1", "decision": "allow", "inputTokens": 1}],
        forbidden=["有給休暇の繰越上限は何日ですか。"],
    )
    print(f"終了コード: {code}")

    print()
    print("=== わざと落としてみる ===")
    code = run_all(
        s3,
        prompt_name="helpdesk-answer",
        texts=["api_key = DUMMY-NOT-A-REAL-KEY-0000"],
        entries=[{"answer": "提供された資料によると、繰越上限は20日です。"}],
        forbidden=["提供された資料によると"],
    )
    print(f"終了コード: {code}（このままではデプロイに進みません）")


if __name__ == "__main__":
    main()
