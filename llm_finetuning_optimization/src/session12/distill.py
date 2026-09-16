#!/usr/bin/env python3
"""応答蒸留の道具（セッション12）。**モデルを読まない部分だけ**を集める。

  python src/session12/distill.py     # 見本のレポートを出す（数秒）

ここに置くのは4つ。

  1. 教師データ（プロンプトと教師の出力のペア）の組み立て・検証・保存
  2. 教師との一致率（完全一致・区分一致）
  3. 一致率から生徒の正解率について言えることの算術
  4. 教師の誤りが生徒に伝播する様子（合成した小さな学習器で示す）

**教師（0.5B）と生徒（135M）を読む処理はここには置かない。**
`make_teacher_data.py`（教師で生成する）と `distill_student.py`（生徒を学習する）に
分けてある。2つを別プロセスで動かすことが、メモリ 5.8GB の環境で2体を同時に
抱えないための設計そのものである。
"""

from __future__ import annotations

import json
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from ftkit.data import CATEGORIES, Example, build_prompt  # noqa: E402
from ftkit.evaluate import FORMAT_RE, extract_category  # noqa: E402

SANDBOX = Path(__file__).resolve().parents[2]
DATA = SANDBOX / "data"

# 教師の出力として受け入れる上限（自由文で語り出した出力を落とすための線）
MAX_OUTPUT_CHARS = 200

# 教師データ1件に必ず入れるキー。後ろ4つは「何をどう作ったか」の記録で、
# これが無いと同じデータを二度と作れない（再現性）
REQUIRED_KEYS = ("id", "task", "question", "prompt", "output",
                 "teacher", "teacher_revision", "generated_at")

# 検証で付く問題コード。表示順を固定するためにタプルで持つ
PROBLEM_CODES = (
    "必須キーが足りない",
    "出力が空",
    "出力が長すぎる",
    "プロンプトが指示文と一致しない",
    "classify の出力が区分名そのものでない",
    "format の出力が3行の定型でない",
    "区分名が6区分の外",
    "評価セットの id が混ざっている（汚染）",
    "id が重複している",
)


# --- 1. 教師データの組み立てと検証 ------------------------------------------


def build_record(example: Example, task: str, output: str, teacher: str,
                 revision: str, generated_at: str) -> dict:
    """教師データ1件を作る。

    本体は **prompt と output の2つ**だけである。応答蒸留のデータは、それ以上の
    情報を持たない（教師の内部状態は使わない）。残りのキーは再現のための記録。
    `gold` は本書のデータセットに正解があるから入れられるだけで、実務の蒸留では
    たいてい存在しない。**gold があるなら、そもそも教師は要らない**ことに注意する。
    """
    return {
        "id": example.id,
        "task": task,
        "question": example.question,
        "prompt": build_prompt(example, task),
        "output": output.strip(),
        "teacher": teacher,
        "teacher_revision": revision,
        "generated_at": generated_at,
        "gold": example.category,
    }


def expected_prompt(record: dict, task: str) -> str:
    """記録された question から、学習・評価で使うプロンプトを作り直す。"""
    return build_prompt(
        Example(id=record.get("id", ""), question=record.get("question", ""),
                category="", answer=""), task)


def validate_record(record: dict, task: str,
                    forbidden_ids: tuple[str, ...] | set[str] = ()) -> list[str]:
    """1件を検査して、問題コードのリストを返す（空なら合格）。

    **教師データは検証してから使う。** 教師が間違えた出力・形式を外した出力・
    評価セットから作ってしまった出力（汚染）をそのまま学習させると、生徒は
    その誤りを忠実に再現する。
    """
    problems: list[str] = []
    if not all(key in record for key in REQUIRED_KEYS):
        return ["必須キーが足りない"]

    output = str(record["output"]).strip()
    if not output:
        problems.append("出力が空")
    elif len(output) > MAX_OUTPUT_CHARS:
        problems.append("出力が長すぎる")

    if record["prompt"] != expected_prompt(record, task):
        problems.append("プロンプトが指示文と一致しない")

    if output:
        if task == "classify":
            if output not in CATEGORIES:
                problems.append("classify の出力が区分名そのものでない")
        else:
            if not FORMAT_RE.match(output):
                problems.append("format の出力が3行の定型でない")
            if extract_category(output) not in CATEGORIES:
                problems.append("区分名が6区分の外")

    if record.get("id") in set(forbidden_ids):
        problems.append("評価セットの id が混ざっている（汚染）")
    return problems


def validate_records(records: list[dict], task: str,
                     forbidden_ids: tuple[str, ...] | set[str] = ()) -> dict:
    """全件を検査する。id の重複は全件を見ないと分からないのでここで見る。"""
    seen: set[str] = set()
    per_record: list[tuple[str, list[str]]] = []
    counts: dict[str, int] = {code: 0 for code in PROBLEM_CODES}
    for record in records:
        problems = validate_record(record, task, forbidden_ids)
        record_id = str(record.get("id", "(id なし)"))
        if record_id in seen:
            problems.append("id が重複している")
        seen.add(record_id)
        for code in problems:
            counts[code] = counts.get(code, 0) + 1
        per_record.append((record_id, problems))
    ok = sum(1 for _, problems in per_record if not problems)
    return {"n": len(records), "ok": ok, "ng": len(records) - ok,
            "counts": {code: counts[code] for code in PROBLEM_CODES if counts[code]},
            "per_record": per_record}


def keep_valid(records: list[dict], task: str,
               forbidden_ids: tuple[str, ...] | set[str] = ()) -> list[dict]:
    """合格した件だけを残す。落とした件数は validate_records で数えられる。"""
    report = validate_records(records, task, forbidden_ids)
    return [record for (_, problems), record in zip(report["per_record"], records)
            if not problems]


def to_examples(records: list[dict], task: str, normalize: bool = False) -> list[Example]:
    """教師の出力を「学習させたい出力」に据える。**これが応答蒸留の実体**である。

    `ftkit.data.build_target` は classify なら `category`、format なら `answer` を
    返す。だから教師の出力をその欄に入れれば、あとは普通の SFT がそのまま回る。
    蒸留のために新しい学習ループは要らない。

    normalize=True にすると `extract_category` を通してから据える（教師の言い回しを
    削り、区分名だけにする）。そのままにするか正規化するかは設計判断である。
    """
    examples: list[Example] = []
    for record in records:
        output = str(record["output"]).strip()
        if task == "classify":
            target = extract_category(output) if normalize else output
            examples.append(Example(id=record["id"], question=record["question"],
                                    category=target, answer=target))
        else:
            examples.append(Example(id=record["id"], question=record["question"],
                                    category=extract_category(output), answer=output))
    return examples


def teacher_data_path(task: str) -> Path:
    return DATA / f"distill_teacher_{task}.jsonl"


def save_jsonl(records: list[dict], path: Path | str) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    return path


def load_jsonl(path: Path | str) -> list[dict]:
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} がありません。先に `python src/session12/make_teacher_data.py` を"
            "実行してください。")
    return [json.loads(line) for line in path.open(encoding="utf-8") if line.strip()]


# --- 2. 教師との一致率 -------------------------------------------------------


def agreement(pairs: list[tuple[str, str]]) -> dict:
    """(教師の出力, 生徒の出力) の組から一致率を出す。

    **「一致」の定義を2つ持つ**のが要点。完全一致は厳しすぎて改善が見えないことが
    あり、区分一致は緩すぎて言い回しの崩れを見逃す。両方を並べて記録する。
    """
    n = len(pairs)
    exact = sum(1 for teacher, student in pairs
                if teacher.strip() == student.strip())
    same_category = sum(1 for teacher, student in pairs
                        if extract_category(teacher) == extract_category(student))
    return {"n": n,
            "exact": exact / n if n else 0.0,
            "category": same_category / n if n else 0.0}


# --- 3. 一致率から言えること --------------------------------------------------


def accuracy_bounds(teacher_accuracy: float, agree: float) -> tuple[float, float]:
    """|生徒の正解率 − 教師の正解率| ≤ 1 − 一致率 から出る素朴な範囲。

    一致した箇所では生徒は教師と同じ答えを出しているので、正解・不正解も同じ。
    差が付くのは一致しなかった箇所だけなので、差は 1 − 一致率 で抑えられる。
    """
    gap = 1.0 - agree
    return max(0.0, teacher_accuracy - gap), min(1.0, teacher_accuracy + gap)


def achievable_accuracy_range(n: int, teacher_correct: int,
                              disagreements: int) -> tuple[float, float]:
    """教師の正解数まで分かっている場合の、生徒の正解率の取りうる範囲（列挙）。

    一致しなかった箇所のうち、**教師が正解だった箇所では生徒は必ず不正解**になる
    （答えは1つしかない）。教師が不正解だった箇所では、生徒は当たっていることも
    外していることもある。この2つだけで範囲が決まる。
    """
    teacher_wrong = n - teacher_correct
    lows: list[int] = []
    highs: list[int] = []
    for on_correct in range(disagreements + 1):
        on_wrong = disagreements - on_correct
        if on_correct > teacher_correct or on_wrong > teacher_wrong:
            continue
        base = teacher_correct - on_correct
        lows.append(base)
        highs.append(base + on_wrong)
    if not lows:
        raise ValueError("その件数の組み合わせは成立しません")
    return min(lows) / n, max(highs) / n


def miss_probability(n: int, bad: int, k: int) -> float:
    """誤りが bad 件混ざった n 件から k 件を抜き取って、1件も当たらない確率。"""
    if bad <= 0:
        return 1.0
    if k > n - bad:
        return 0.0
    return math.comb(n - bad, k) / math.comb(n, k)


def sample_size_for(n: int, bad: int, target_miss: float) -> int:
    """見逃し確率を target_miss 以下にするために、人が見るべき件数。"""
    for k in range(1, n + 1):
        if miss_probability(n, bad, k) <= target_miss:
            return k
    return n


# --- 4. 教師の誤りの伝播（合成した小さな学習器） ------------------------------

KEYWORDS = {"経費": "精算", "勤怠": "有給", "PC": "パソコン",
            "アカウント": "パスワード", "オフィス": "会議室", "セキュリティ": "ウイルス"}
TRAIN_PHRASES = ("{kw}の手続きを教えてください",
                 "{kw}について相談したいです",
                 "{kw}の窓口はどこですか")
EVAL_PHRASES = ("{kw}の件で確認したいことがあります",)
NEXT_CATEGORY = {c: CATEGORIES[(i + 1) % len(CATEGORIES)]
                 for i, c in enumerate(CATEGORIES)}


def _synth(prefix: str, phrases: tuple[str, ...]) -> list[tuple[str, str, str]]:
    """(id, 正解, 質問) の一覧を作る。区分ごとに特徴語が1つ入る。"""
    items: list[tuple[str, str, str]] = []
    for category, keyword in KEYWORDS.items():
        for index, phrase in enumerate(phrases, start=1):
            items.append((f"{prefix}-{category}-{index}", category,
                          phrase.format(kw=keyword)))
    return items


SYNTH_TRAIN = _synth("T", TRAIN_PHRASES)     # 18 件（6区分 × 3件）
SYNTH_EVAL = _synth("E", EVAL_PHRASES)       # 6 件（6区分 × 1件・言い回しは別）

# 散発誤り：各区分の1件目だけを隣の区分に間違える（6件）
SCATTERED_MISTAKES = {f"T-{c}-1": NEXT_CATEGORY[c] for c in CATEGORIES}
# 系統誤り：PC の3件すべてを「アカウント」と間違える（3件）
SYSTEMATIC_MISTAKES = {f"T-PC-{i}": "アカウント" for i in (1, 2, 3)}


def find_keyword(question: str) -> str:
    for keyword in KEYWORDS.values():
        if keyword in question:
            return keyword
    return ""


def fit(labeled: list[tuple[str, str, str, str]]) -> dict[str, str]:
    """「特徴語 → 教師が付けたラベルの多数決」を覚えるだけの学習器。

    本物のモデルではないが、**学習は与えられたラベルの多数派に寄る**という性質は
    同じなので、誤りの伝播を数分ではなく一瞬で観察できる。
    """
    votes: dict[str, dict[str, int]] = {}
    for _, question, _, label in labeled:
        keyword = find_keyword(question)
        counts = votes.setdefault(keyword, {})
        counts[label] = counts.get(label, 0) + 1
    # 同数のときは先に現れたラベルを採る（決定的にするため）
    return {keyword: max(counts, key=lambda label: counts[label])
            for keyword, counts in votes.items()}


def predict(model: dict[str, str], question: str) -> str:
    return model.get(find_keyword(question), "")


def propagation(mistakes: dict[str, str]) -> dict:
    """教師の誤りを注入した教師データで学習させ、生徒の側に何が出るかを測る。"""
    labeled = [(item_id, question, gold, mistakes.get(item_id, gold))
               for item_id, gold, question in SYNTH_TRAIN]
    teacher_wrong = sum(1 for _, _, gold, label in labeled if label != gold)
    teacher_pairs = {(gold, label) for _, _, gold, label in labeled if label != gold}

    model = fit(labeled)
    rows = [(item_id, gold, predict(model, question))
            for item_id, gold, question in SYNTH_EVAL]
    wrong_rows = [(i, g, p) for i, g, p in rows if p != g]
    same_shape = sum(1 for _, gold, pred in wrong_rows if (gold, pred) in teacher_pairs)
    return {"teacher_error_rate": teacher_wrong / len(labeled),
            "teacher_wrong": teacher_wrong,
            "student_accuracy": (len(rows) - len(wrong_rows)) / len(rows),
            "student_wrong": len(wrong_rows),
            "same_shape": same_shape,
            "rows": rows}


# --- 見本のレポート ----------------------------------------------------------

DEMO_TEACHER_OUTPUTS = [
    ("D-0001", "出張の交通費の精算はどうすればよいですか", "経費", "経費"),
    ("D-0002", "有給休暇の申請はいつまでですか", "勤怠", "勤怠"),
    ("D-0003", "パソコンが起動しません", "PC", ""),
    ("D-0004", "パスワードを忘れました", "アカウント", "たぶんアカウントだと思います"),
    ("D-0005", "会議室の予約を変更したいです", "オフィス", "オフィス"),
    ("D-0001", "出張の交通費の精算はどうすればよいですか", "経費", "経費"),
]
FORBIDDEN_DEMO_IDS = ("D-0005",)
DEMO_AGREEMENT_PAIRS = [
    ("経費", "経費"),
    ("勤怠", "区分は勤怠です"),
    ("PC", "アカウント"),
    ("オフィス", "オフィス "),
    ("セキュリティ", "セキュリティ"),
]


def demo_records() -> list[dict]:
    return [build_record(Example(id=record_id, question=question, category=gold,
                                answer=""),
                         "classify", output, "（見本）", "main",
                         "1970-01-01T00:00:00Z")
            for record_id, question, gold, output in DEMO_TEACHER_OUTPUTS]


def main() -> None:
    print("=== 1. 教師データの検証（見本6件・モデルを読まない） ===")
    records = demo_records()
    report = validate_records(records, "classify", FORBIDDEN_DEMO_IDS)
    print(f"  合格 {report['ok']} 件 / 不合格 {report['ng']} 件（全 {report['n']} 件）")
    for code, count in report["counts"].items():
        print(f"  - {code}: {count} 件")
    print(f"  学習に使うのは {len(keep_valid(records, 'classify', FORBIDDEN_DEMO_IDS))} 件"
          "（不合格は落とす）")

    print("\n=== 2. 教師との一致率（見本5件） ===")
    result = agreement(DEMO_AGREEMENT_PAIRS)
    print(f"  n={result['n']} 完全一致={result['exact']:.3f} "
          f"区分一致={result['category']:.3f}")

    print("\n=== 3. 一致率から生徒の正解率について言えること ===")
    n, teacher_correct, disagreements = 30, 25, 9
    agree = (n - disagreements) / n
    teacher_accuracy = teacher_correct / n
    low, high = accuracy_bounds(teacher_accuracy, agree)
    achievable = achievable_accuracy_range(n, teacher_correct, disagreements)
    perfect = achievable_accuracy_range(n, teacher_correct, 0)
    print(f"  n={n} 教師の正解率={teacher_accuracy:.3f} 一致率={agree:.3f}")
    print(f"  不等式から: {low:.3f} 〜 {high:.3f}")
    print(f"  実際に取りうる範囲（列挙）: {achievable[0]:.3f} 〜 {achievable[1]:.3f}")
    print(f"  一致率 1.000 のとき: {perfect[0]:.3f} 〜 {perfect[1]:.3f}"
          "（生徒は教師を超えられない）")

    print("\n=== 4. 教師の誤りは生徒に伝播するか（合成・多数決の学習器） ===")
    for label, mistakes in (("誤りなし", {}),
                            ("散発誤り（各区分の1件目）", SCATTERED_MISTAKES),
                            ("系統誤り（PC の3件すべて）", SYSTEMATIC_MISTAKES)):
        row = propagation(mistakes)
        print(f"  [{label}] 教師の誤り率={row['teacher_error_rate']:.3f} "
              f"生徒の正解率={row['student_accuracy']:.3f} "
              f"生徒の誤り={row['student_wrong']} 件"
              f"（うち教師と同じ型={row['same_shape']} 件）")

    print("\n=== 5. 抜き取り検証の設計（18件のうち誤りが3件・系統誤り） ===")
    for k in (4, 6, 9):
        miss = miss_probability(18, 3, k)
        print(f"  {k:>2} 件見る -> 見逃し={miss:.3f} 検出={1 - miss:.3f}")
    print(f"  見逃しを 0.05 以下にするには {sample_size_for(18, 3, 0.05)} 件"
          "見る必要がある")
    miss_scattered = miss_probability(18, 6, 4)
    print(f"  誤りが 6 件あるなら 4 件見れば検出={1 - miss_scattered:.3f}"
          "（誤りが多いほど見つけやすい）")


if __name__ == "__main__":
    main()
