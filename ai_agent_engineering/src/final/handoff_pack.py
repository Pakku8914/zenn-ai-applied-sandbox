#!/usr/bin/env python3
"""最終プロジェクト・成果物⑥⑦：runbook と、レビュー観点チェックリスト。

    python src/final/handoff_pack.py     # 引き継ぎパッケージを workspace/final/ に書き出す

このプロジェクトの評価は「動くか」ではなく「**他人が引き継いで運用できるか**」である。
それを口約束にしないために、引き継ぎパッケージを機械で採点する。

  - `MACHINE_CHECKS` … コードで判定できる観点（12件）。落ちたら引き渡さない
  - `HUMAN_CHECKS`   … 機械化できない観点（4件）。**できないことを明示するのが設計**

チェックリストが探す文字列は、各モジュールが公開している定数をそのまま使う
（`handover.SPEC_TABLE_HEAD` など）。文字列を二重管理すると、章を直したときに
チェックだけが通り続ける。
"""

from __future__ import annotations

from final_paths import setup

ROOT = setup()

from agentkit.biztools import WORKSPACE, write_file  # noqa: E402

import handover  # noqa: E402
from evalreport import METRIC_HEADS, PRICE_NOTE, TOKEN_NOTE, report_md  # noqa: E402
from suite import GROUPS, run_suite, suite_md, verdict  # noqa: E402
from tracing import CORRELATION_IDS, GRAIN_NOTE, trace_design_md  # noqa: E402

PACKAGE_DIR = "final"

# runbook に必ず要る節。S15 の runbook と同じ骨格に「エスカレーション」を足した
SECTIONS = ("## 検知", "## 一次判断", "## 手順", "## 進行中のジョブの扱い",
            "## 後始末", "## 再発防止", "## エスカレーション")


# ---------------------------------------------------------------------------
# 成果物⑥：runbook 3枚
# ---------------------------------------------------------------------------
STUCK = """# runbook: ジョブが進まない・上限で止まる

## 検知
- キューの滞留が 15 分を超えた、または `limited` のジョブが出た
- 見る数字: 状態ごとの件数 / 1ジョブの手数 / 同じ引数の呼び出し回数
- 一次情報: `traces/{task_id}.jsonl`（軌跡）と スパンの木

## 一次判断
- 停止理由を見る。`max_steps` は上限に当たっただけで、壊れてはいない
- 同じ (ツール名, 引数) が 3 回以上あれば「同じ操作の反復」。上限を上げても直らない
- 副作用が出ているかは**軌跡ではなくデータ側で数える**（`expenses` / `bookings` / `messages`）

## 手順
1. `docker compose exec app python src/final/suite.py` で3群のテストを流し、正常系が落ちていないか見る
2. 落ちていなければ個別のジョブの問題。軌跡から原因のステップを特定する（反復が始まった手を見る）
3. 反復なら、そのツールの説明文と失敗メッセージを読む。次の一手が書かれていなければツール側の欠陥
4. 上限に当たっただけなら、引き継ぎ書が出ていることを確認して人へ渡す
5. 30 分で切り分けが終わらなければ二次へ上げる

## 進行中のジョブの扱い
- 副作用を出していないジョブ: キャンセルしてよい（`cancelled` にして引き継ぎ書を出す）
- 副作用を出したジョブ: 走り切らせる。途中で止めると中途半端な状態が残る
- 判断に迷うジョブ: 止めずに人へ渡す

## 後始末
- 打ち切ったジョブの task_id を記録する（あとで再実行の対象になる）
- `data/` の増分（申請・予約・送信）を数え、想定と合っているか確認する

## 再発防止
- 上限は平均ではなく**手数の分布**から決め直す（成功したケースの最大 + 余裕）
- 同じ操作の反復を検出したら打ち切る規則を入れる
- 反復の原因になったツールの説明文に「使わない場面」を書き足す

## エスカレーション
- 二次（開発担当）: 軌跡から原因のステップを特定できない / runbook に無い症状
- 三次（情報システム部）: 外部システムが応答しない
"""

ATTACK = """# runbook: 攻撃系のテストが落ちた・禁止された道具が呼ばれた

## 検知
- 軌跡テスト集の攻撃系が不合格、または `messages.jsonl` に社内でない宛先の行が増えた
- 見る数字: 禁止された道具の呼び出し回数 / 出力検査の遮断件数 / 入力検査の警告件数
- 一次情報: 軌跡・監査ログ・`data/messages.jsonl`

## 一次判断
- 禁止された道具の呼び出しは **1 件でも「止める」**。様子を見ない
- 遮断が 0 件のまま社外宛が出ていたら、出力検査そのものが効いていない
- 警告が 0 件のまま注入が通っていたら、入力検査が届いていない経路がある
- 注入は「検出できたか」ではなく「**出口に届いたか**」で判断する

## 手順
1. 受付を止める（新規ジョブをキューに積まない）。走行中のジョブは止めない
2. `docker compose exec app python src/final/suite.py` で攻撃系の落ち方を再現する
3. 越境の有無を**データ側**で数える（社内でない宛先の送信・機密を含む書き出し）
4. 出口に届いていれば三次へ即エスカレーションする（連絡は人が行う）
5. 届いていなければ、どの層が止めたかを1つに特定してから受付を再開する

## 進行中のジョブの扱い
- 副作用を出していないジョブ: キャンセルして入れ直す
- 送信済みのジョブ: 取り消せない。宛先の一覧を作り、訂正の連絡を人が出す
- 承認待ちのジョブ: 承認者に「保留」と伝える。期限切れに任せない

## 後始末
- 送信・書き出しの一覧を作り、影響範囲を確定する
- 攻撃に使われた経路を軌跡テスト集の攻撃系に**そのまま1件足す**（再現できる形で）

## 再発防止
- 防御は「プロンプトに書く」ではなく、権限制限・引数の確定・出力検査・人間承認の層で足す
- 層を足したら、守っていない構成との対比で効果を測る（片方だけでは効果を主張できない）
- 攻撃の再現は自分が管理する演習環境の中だけで行う

## エスカレーション
- 三次（情報システム部）: 機密が外へ出た可能性がある場合は、切り分けを待たずに上げる
"""

ROLLBACK = """# runbook: 新しい構成を出したあとに壊れた

## 検知
- 段階リリース中に、禁止された道具の呼び出し・成功率の低下・手数の増加のいずれかが出た
- 見る数字: 禁止ツールの呼び出し数 / タスク成功率 / 手数の合計（旧構成との比）
- 一次情報: 群ごとの軌跡テストの結果と、旧構成の同じタスクの軌跡

## 一次判断
- 禁止された道具の呼び出しは 1 件でも「止める」
- 成功率だけの低下なら、型ごとに割って原因の型を特定してから決める
- 軌跡の差分がゼロでも、**成果物の中身が薄くなる劣化**は起こる。中身の検査を必ず見る

## 手順
1. 新構成への振り分けを 0% にする（設定ファイルを変える。コードは触らない）
2. 新規受付は止めず、キューのジョブは旧構成で処理する
3. 5 分後に禁止ツールの呼び出しが 0 に戻ったことを確認する
4. 戻らなければワーカーを1台ずつ入れ替える（全台同時に止めない）
5. 旧構成で全件を流し、成功率と手数が基準に戻ったことを確認する

## 進行中のジョブの扱い
- 副作用を出していないジョブ: キャンセルして旧構成で入れ直す
- 副作用を出したジョブ: 走り切らせてから結果を確認する
- 承認待ちのジョブ: 承認内容は新構成のものなので、いったん却下して入れ直す

## 後始末
- 影響を受けた task_id を記録する
- 出てしまった副作用を打ち消す（打ち消せない送信は人が訂正の連絡を出す）

## 再発防止
- カナリアは割合ではなく**型で選ぶ**（壊れる型が母集団の数%しかないと、割合では当たらない）
- 差し替えの合格条件を「軌跡＋副作用＋成果物の中身」の3点で明文化する
- 受け入れ基準に「禁止された道具の呼び出し 0 件」を必ず入れる

## エスカレーション
- 二次（開発担当）: 旧構成に戻しても数字が戻らない
- 三次（情報システム部）: 外部システムに影響が出た
"""

RUNBOOKS: tuple[tuple[str, str], ...] = (
    ("runbook_stuck", STUCK),
    ("runbook_attack", ATTACK),
    ("runbook_rollback", ROLLBACK),
)


def runbook_gaps() -> list[str]:
    """runbook に足りないものを返す。空でなければ引き渡さない。"""
    gaps: list[str] = []
    for key, text in RUNBOOKS:
        for section in SECTIONS:
            if section not in text:
                gaps.append(f"{key}: {section} がありません")
        if "1. " not in text:
            gaps.append(f"{key}: 番号付きの手順がありません")
    return gaps


# ---------------------------------------------------------------------------
# 成果物⑦：レビュー観点チェックリスト
# ---------------------------------------------------------------------------
def _has_all(text: str, words) -> bool:
    return all(word in text for word in words)


MACHINE_CHECKS: tuple[tuple[str, str, object], ...] = (
    ("設計書にツール仕様表があり、宣言とレジストリが矛盾しない",
     "python src/final/handover.py",
     lambda pkg: handover.SPEC_TABLE_HEAD in pkg["design"]
     and not handover.spec_violations()),
    ("状態遷移図がコードから生成されている（手描きでない）",
     "python src/final/handover.py",
     lambda pkg: "stateDiagram-v2" in pkg["design"]
     and pkg["design"].count("-->") >= handover.JOB_TRANSITION_COUNT),
    ("すべての状態に担当があり、人へ渡す出口に到達できる",
     "python src/final/verify.py",
     lambda pkg: not handover.flow_violations()
     and handover.EXIT_REACH_NOTE in pkg["design"]),
    ("検査5カ所それぞれに引き継ぎ後の担当が書かれている",
     "python src/final/handover.py",
     lambda pkg: len(handover.CHECKPOINTS) == 5
     and all(row[2] for row in handover.CHECKPOINTS)),
    ("当番・承認者・エスカレーション先が名指しされている",
     "python src/final/handover.py",
     lambda pkg: _has_all(pkg["design"],
                          ("当番（オンコール）", "承認者（所属長）", "エスカレーション"))),
    ("軌跡テスト集に正常系・異常系・攻撃系の3群がそろっている",
     "python src/final/suite.py",
     lambda pkg: len(GROUPS) == 3
     and _has_all(pkg["suite"], [g.label for g in GROUPS])),
    ("群ごとに「落ちたときにやること」が書かれている",
     "python src/final/suite.py",
     lambda pkg: _has_all(pkg["suite"], [g.on_fail for g in GROUPS])),
    ("評価レポートに成功率・ツール選択正解率・手数・単価の4つがある",
     "python src/final/evalreport.py",
     lambda pkg: _has_all(pkg["eval"], METRIC_HEADS)),
    ("金額が仮の単価表と明記され、トークンが近似値と断ってある",
     "python src/final/evalreport.py",
     lambda pkg: _has_all(pkg["eval"], (PRICE_NOTE, TOKEN_NOTE))),
    ("トレース設計に相関ID4種と、粒度の交換関係が書かれている",
     "python src/final/tracing.py",
     lambda pkg: _has_all(pkg["trace"], CORRELATION_IDS)
     and GRAIN_NOTE in pkg["trace"]),
    ("runbook が3枚あり、必要な節と番号付きの手順がそろっている",
     "python src/final/handoff_pack.py",
     lambda pkg: len(RUNBOOKS) == 3 and not runbook_gaps()),
    ("パッケージのファイルがそろっていて、再現コマンドが書いてある",
     "ls workspace/final/",
     lambda pkg: not missing_keys(pkg) and "docker compose exec" in pkg["readme"]),
)

HUMAN_CHECKS: tuple[tuple[str, str], ...] = (
    ("依頼の意図と成果物が合っているか（成功の定義そのものが妥当か）",
     "成功の定義が間違っていても、宣言と実装が一致していれば機械は合格を出す"),
    ("承認者に見せている情報だけで、人が本当に判断できるか",
     "画面に必要な情報がそろっているかは、承認者に読ませてみないと分からない"),
    ("攻撃系のシナリオが、いま現実にありうる経路を網羅しているか",
     "書いていない経路は再現できない。網羅は人が想像するしかない"),
    ("runbook の手順が、書いた人以外でも実行できるか",
     "当番に素振りさせて詰まった場所を直す。読めることと動けることは違う"),
)


def score_package(pkg: dict[str, str]) -> dict:
    """引き継ぎパッケージを機械で採点する。`missing` に落ちた観点が入る。"""
    passed = []
    for label, _how, fn in MACHINE_CHECKS:
        try:
            ok = bool(fn(pkg))
        except Exception:  # noqa: BLE001  観点の判定で落ちたら不合格として扱う
            ok = False
        passed.append((label, ok))
    return {"passed": sum(1 for _, ok in passed if ok),
            "total": len(MACHINE_CHECKS),
            "missing": [label for label, ok in passed if not ok]}


def checklist_md() -> str:
    lines = ["# レビュー観点チェックリスト：引き継ぎパッケージ",
             "",
             "## 機械で見る観点（落ちたら引き渡さない）",
             "",
             "| # | 観点 | 根拠にするコマンド |",
             "| --: | :--- | :--- |"]
    for i, (label, how, _fn) in enumerate(MACHINE_CHECKS, start=1):
        lines.append(f"| {i} | {label} | `{how}` |")
    lines += ["",
              "## 人が見る観点（機械化できない）",
              "",
              "| 観点 | 機械化できない理由 |",
              "| :--- | :--- |"]
    for label, why in HUMAN_CHECKS:
        lines.append(f"| {label} | {why} |")
    lines += ["",
              "機械で見る観点が全部通っても、それは「引き渡せる形になっている」だけです。",
              "**中身が正しいかは、人が見る観点の側にあります。**",
              ""]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# パッケージの組み立て
# ---------------------------------------------------------------------------
PACKAGE_FILES: tuple[tuple[str, str], ...] = (
    ("design", "design.md"),
    ("suite", "test_suite.md"),
    ("eval", "eval_report.md"),
    ("trace", "trace_design.md"),
    ("runbook_stuck", "runbook_stuck.md"),
    ("runbook_attack", "runbook_attack.md"),
    ("runbook_rollback", "runbook_rollback.md"),
    ("checklist", "review_checklist.md"),
    ("readme", "README.md"),
)


def missing_keys(pkg: dict[str, str]) -> list[str]:
    return [key for key, _name in PACKAGE_FILES if not (pkg.get(key) or "").strip()]


def readme_md(rows: list[dict]) -> str:
    label, why = verdict(rows)
    return "\n".join([
        "# 引き継ぎパッケージ：みなと商事オペレーション代行エージェント",
        "",
        f"**いまの総合判定: {label}**（{why}）",
        "",
        "## 入っているもの",
        "",
        "| ファイル | 中身 | 何のために読むか |",
        "| :--- | :--- | :--- |",
        "| design.md | 設計書 | 止まったとき、誰が何を見て何をするかを決めるため |",
        "| test_suite.md | 軌跡テスト集 | 変更を出す前に、壊れていないことを示すため |",
        "| eval_report.md | 評価レポート | いまの成功率・手数・単価を把握するため |",
        "| trace_design.md | トレースの設計 | 失敗した1件を後から追い、手元で再現するため |",
        "| runbook_stuck.md | runbook | ジョブが進まない・上限で止まったとき |",
        "| runbook_attack.md | runbook | 禁止された道具が呼ばれたとき |",
        "| runbook_rollback.md | runbook | 新しい構成を出したあとに壊れたとき |",
        "| review_checklist.md | レビュー観点 | 引き渡してよいかを判定するため |",
        "",
        "## 作り直す手順（このパッケージはコードから生成されます）",
        "",
        "```bash",
        "docker compose up -d",
        "docker compose exec app python tools/make_data.py        # データを初期状態に戻す",
        "docker compose exec app python src/final/handover.py     # 設計書",
        "docker compose exec app python src/final/suite.py        # 軌跡テスト集",
        "docker compose exec app python src/final/evalreport.py   # 評価レポート",
        "docker compose exec app python src/final/tracing.py      # トレースの設計",
        "docker compose exec app python src/final/handoff_pack.py # パッケージ一式を書き出す",
        "docker compose exec app python src/final/verify.py       # 合否判定（非0終了で失敗）",
        "docker compose exec app python -m pytest src/final -q    # 軌跡テスト",
        "```",
        "",
        "手で直さないでください。直すのは生成元のコードです。",
        "",
    ])


def build_package(rows: list[dict] | None = None) -> dict[str, str]:
    rows = rows if rows is not None else run_suite()
    by_name = {r["name"]: r for r in rows}
    pkg = {
        "design": handover.design_md(),
        "suite": suite_md(rows),
        "eval": report_md(rows),
        "trace": trace_design_md(by_name["expense_report"]["traj"],
                                 by_name["max_steps_loop"]["traj"]),
        "checklist": checklist_md(),
        "readme": readme_md(rows),
    }
    for key, text in RUNBOOKS:
        pkg[key] = text
    return pkg


def write_package(pkg: dict[str, str] | None = None) -> list[str]:
    """`workspace/final/` に書き出す。書き込みは作業領域の中だけである。"""
    pkg = pkg if pkg is not None else build_package()
    written = []
    for key, name in PACKAGE_FILES:
        path = f"{PACKAGE_DIR}/{name}"
        write_file(path, pkg[key])
        written.append(path)
    return written


def package_dir_files() -> list[str]:
    directory = WORKSPACE / PACKAGE_DIR
    if not directory.exists():
        return []
    return sorted(p.name for p in directory.iterdir() if p.is_file())


def main() -> None:
    rows = run_suite()
    pkg = build_package(rows)
    written = write_package(pkg)
    score = score_package(pkg)

    print("=== 成果物⑥⑦：引き継ぎパッケージ ===")
    for path in written:
        print(f"workspace/{path}")
    print(f"\nrunbook の不足: {runbook_gaps() or 'なし'}")
    print(f"レビュー観点（機械）: {score['passed']}/{score['total']} "
          f"落ちた観点: {score['missing'] or 'なし'}")
    print(f"レビュー観点（人）: {len(HUMAN_CHECKS)} 件（機械化しないと決めたもの）")
    label, why = verdict(rows)
    print(f"\n総合判定: {label}（{why}）")
    print("※ パッケージの形は整っていても、軌跡テスト集が落ちていれば引き渡しません。")

    from evalspec import reset_data  # noqa: PLC0415

    reset_data()


if __name__ == "__main__":
    main()
