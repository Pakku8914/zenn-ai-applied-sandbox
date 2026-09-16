#!/usr/bin/env python3
"""セッション12の自己検証：応答蒸留の道具・一致率の算術・誤りの伝播。

検証する主張（本文に書いた内容と1対1で対応させる）:
  1. 教師と生徒でトークナイザの語彙が一致しない（＝ロジット蒸留が素朴には成立しない）
  2. 教師データ（プロンプトと教師の出力のペア）の形式が検証できる
  3. 教師との一致率という指標が正しく計算でき、そこから言えることの範囲が分かる
  4. 教師の誤りは生徒に伝播する（そして「量」より「型」が効く）
  5. （任意・重い）教師で数十件だけ生成して JSONL に落とし、生徒を LoRA で学習する

**1〜4はモデルの重みを読まない**（1はトークナイザだけ、2〜4は算術と合成データ）。
数秒で終わるので、既定ではここまでを実行する。

  python src/session12/verify.py
  RUN_TEACHER=1 python src/session12/verify.py        # 5 も実行する（教師の生成があるので長い）
  RUN_TEACHER=1 TEACHER_N=12 STUDENT_STEPS=20 DISTILL_TASK=classify python src/session12/verify.py

5 では**教師と生徒を同時に保持しない**。教師で生成 → del と gc.collect() で解放 →
生徒を読んで学習、の2段構えにしてある（メモリ 5.8GB の環境で2体を抱えると落ちる）。
"""

from __future__ import annotations

import gc
import math
import os
import resource
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from distill import (  # noqa: E402
    DEMO_AGREEMENT_PAIRS, FORBIDDEN_DEMO_IDS, MAX_OUTPUT_CHARS, REQUIRED_KEYS,
    SCATTERED_MISTAKES, SYNTH_EVAL, SYNTH_TRAIN, SYSTEMATIC_MISTAKES,
    accuracy_bounds, achievable_accuracy_range, agreement, build_record, demo_records,
    keep_valid, load_jsonl, miss_probability, propagation, sample_size_for, save_jsonl,
    to_examples, validate_record, validate_records,
)

from ftkit.data import CATEGORIES, Example, build_prompt, build_target  # noqa: E402
from ftkit.models import FAST_MODEL, JA_MODEL, load_tokenizer  # noqa: E402

SEED = 20260815
HERE = Path(__file__).resolve().parent
SANDBOX = Path(__file__).resolve().parents[2]

failures: list[str] = []


def check(label: str, cond: bool, detail: str = "") -> None:
    print(f"{'OK ' if cond else 'NG '} {label}{(' — ' + detail) if detail else ''}")
    if not cond:
        failures.append(label)


def rss_gb() -> float:
    return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024


# --- 1. 語彙が一致しない（トークナイザだけ・モデルは読まない） ----------------
print("=== 1. 教師と生徒でトークナイザの語彙が一致しない ===")

tok_student = load_tokenizer(FAST_MODEL)
tok_teacher = load_tokenizer(JA_MODEL)
v_student, v_teacher = len(tok_student), len(tok_teacher)
print(f"  生徒 {FAST_MODEL}: 語彙 {v_student:,}")
print(f"  教師 {JA_MODEL}: 語彙 {v_teacher:,}")

check("語彙サイズが一致しない（ロジットのベクトルの長さが違う）", v_student != v_teacher,
      f"差 {abs(v_teacher - v_student):,} 次元")
check("本文の記載どおりの語彙サイズになっている",
      (v_student, v_teacher) == (49_152, 151_665), f"{v_student:,} / {v_teacher:,}")
check("教師の語彙は生徒の3倍以上ある", v_teacher >= 3 * v_student,
      f"{v_teacher / v_student:.2f}倍")

sample = "有給休暇の申請はいつまでですか"
ids_student = tok_student(sample, add_special_tokens=False)["input_ids"]
ids_teacher = tok_teacher(sample, add_special_tokens=False)["input_ids"]
print(f"  生徒の分割（{len(ids_student)} トークン）: "
      f"{' | '.join(tok_student.decode([i]) for i in ids_student)}")
print(f"  教師の分割（{len(ids_teacher)} トークン）: "
      f"{' | '.join(tok_teacher.decode([i]) for i in ids_teacher)}")

check("同じ文のトークン数が違う（位置ごとに分布を並べられない）",
      len(ids_student) != len(ids_teacher),
      f"{len(ids_student)} 対 {len(ids_teacher)} トークン（{len(sample)} 文字）")
check("生徒は同じ文を2倍以上のトークンに割る",
      len(ids_student) >= 2 * len(ids_teacher),
      f"{len(ids_student) / len(ids_teacher):.2f}倍")
try:
    cross_decoded = tok_student.decode(ids_teacher)
except Exception as exc:                      # 語彙の外の id が混ざれば復号自体が失敗する
    cross_decoded = f"(復号できない: {type(exc).__name__})"
check("教師の id 列を生徒のトークナイザで読み戻しても元の文にならない",
      cross_decoded != sample, f"{cross_decoded[:24]!r}")

vocab_student = tok_student.get_vocab()
vocab_teacher = tok_teacher.get_vocab()
shared = set(vocab_student) & set(vocab_teacher)
same_id = sum(1 for piece in shared if vocab_student[piece] == vocab_teacher[piece])
inv_student = {i: p for p, i in vocab_student.items()}
inv_teacher = {i: p for p, i in vocab_teacher.items()}
overlap = min(v_student, v_teacher)
same_at_id = sum(1 for i in range(overlap)
                 if inv_student.get(i) is not None and inv_student.get(i) == inv_teacher.get(i))
print(f"  文字列として共通の語彙: {len(shared):,} 個 / うち id まで同じ: {same_id:,} 個")
print(f"  id 0〜{overlap - 1:,} のうち同じ文字列を指す id: {same_at_id:,} 個"
      f"（{same_at_id / overlap * 100:.1f}%）")

check("文字列としては共通の語彙がある（英数字や記号は共有される）", len(shared) > 0,
      f"{len(shared):,} 個")
check("共通の語彙でも id は揃っていない", same_id < len(shared),
      f"{same_id:,} / {len(shared):,} 個だけ一致")
check("同じ id が同じ文字列を指す割合は半分に満たない（並べ替えでも対応が取れない）",
      same_at_id / overlap < 0.5, f"{same_at_id / overlap * 100:.1f}%")
print("  -> 教師のロジット（語彙数の長さのベクトル）を生徒のロジットに"
      "位置も次元も対応させられない。**ロジット蒸留は素朴には成立しない。**")

# --- 2. 教師データの形式（モデルを読まない） ---------------------------------
print("\n=== 2. 教師データ（プロンプトと教師の出力のペア）の検証 ===")

example = Example(id="V-0001", question="出張の交通費の精算はどうすればよいですか",
                  category="経費", answer="【区分】経費\n【担当】経理部\n【期限】5営業日")
valid = build_record(example, "classify", " 経費 ", JA_MODEL, "main",
                     "2026-08-15T00:00:00Z")
check("必須キーがすべて入っている", all(key in valid for key in REQUIRED_KEYS),
      str(sorted(set(REQUIRED_KEYS) - set(valid))))
check("教師の出力は前後の空白を落として記録される", valid["output"] == "経費",
      f"{valid['output']!r}")
check("記録されたプロンプトが build_prompt と完全一致する（学習・評価と同じ指示文）",
      valid["prompt"] == build_prompt(example, "classify"))
check("正しい1件は問題なしで通る", validate_record(valid, "classify") == [],
      str(validate_record(valid, "classify")))

broken_prompt = dict(valid, prompt=valid["prompt"].replace("問い合わせ:", "質問:"))
missing_key = {k: v for k, v in valid.items() if k != "generated_at"}
empty = dict(valid, output="")
chatty = dict(valid, output="たぶん経費だと思います")
long_format = build_record(example, "format", "あ" * (MAX_OUTPUT_CHARS + 1),
                           JA_MODEL, "main", "2026-08-15T00:00:00Z")
good_format = build_record(example, "format", example.answer, JA_MODEL, "main",
                           "2026-08-15T00:00:00Z")
odd_format = build_record(example, "format", "【区分】不明\n【担当】-\n【期限】-",
                          JA_MODEL, "main", "2026-08-15T00:00:00Z")

cases = [
    (broken_prompt, "classify", "プロンプトが指示文と一致しない"),
    (missing_key, "classify", "必須キーが足りない"),
    (empty, "classify", "出力が空"),
    (chatty, "classify", "classify の出力が区分名そのものでない"),
    (long_format, "format", "出力が長すぎる"),
    (odd_format, "format", "区分名が6区分の外"),
]
for record, task, expected in cases:
    problems = validate_record(record, task)
    check(f"検出できる: {expected}", expected in problems, str(problems))

check("format の3行の定型は問題なしで通る", validate_record(good_format, "format") == [],
      str(validate_record(good_format, "format")))
check("形式が崩れた format の出力を弾く",
      "format の出力が3行の定型でない"
      in validate_record(dict(good_format, output="区分は経費です"), "format"))
check("評価セットの id が混ざっていたら弾く（汚染）",
      "評価セットの id が混ざっている（汚染）"
      in validate_record(valid, "classify", forbidden_ids=("V-0001",)))

report = validate_records(demo_records(), "classify", FORBIDDEN_DEMO_IDS)
print(f"  見本6件の検証: 合格 {report['ok']} / 不合格 {report['ng']}")
for code, count in report["counts"].items():
    print(f"    - {code}: {count} 件")
check("見本6件のうち合格は2件・不合格は4件",
      (report["ok"], report["ng"], report["n"]) == (2, 4, 6), str(report["counts"]))
check("id の重複は全件を見て検出される（1件ずつでは分からない）",
      report["counts"].get("id が重複している") == 1)
check("keep_valid は合格した件だけを残す",
      len(keep_valid(demo_records(), "classify", FORBIDDEN_DEMO_IDS)) == 2)

tmp = SANDBOX / "data" / "distill_teacher_selftest.jsonl"
saved = save_jsonl([valid, good_format], tmp)
check("JSONL に保存して読み戻すと同じ内容になる",
      load_jsonl(saved) == [valid, good_format], str(saved))

classify_examples = to_examples([valid], "classify")
format_examples = to_examples([good_format], "format")
check("classify では教師の出力がそのまま学習ターゲットになる",
      build_target(classify_examples[0], "classify") == valid["output"],
      f"{build_target(classify_examples[0], 'classify')!r}")
check("format では教師の出力がそのまま学習ターゲットになる",
      build_target(format_examples[0], "format") == good_format["output"])
check("質問文は元のまま引き継がれる（プロンプトを作り直せる）",
      build_prompt(classify_examples[0], "classify") == valid["prompt"])
normalized = to_examples([chatty], "classify", normalize=True)
check("normalize=True にすると教師の言い回しを削って区分名だけにする",
      build_target(normalized[0], "classify") == "経費",
      f"{build_target(normalized[0], 'classify')!r}")
check("normalize=False では教師の言い回しごと学習ターゲットになる",
      build_target(to_examples([chatty], "classify")[0], "classify")
      == "たぶん経費だと思います")

student_src = (HERE / "distill_student.py").read_text(encoding="utf-8")
teacher_src = (HERE / "make_teacher_data.py").read_text(encoding="utf-8")
check("生徒を学習するスクリプトは教師モデルを読まない（2段構えの構造）",
      "JA_MODEL" not in student_src)
check("教師データを作るスクリプトは生徒モデルを読まない",
      "FAST_MODEL" not in teacher_src)
check("教師データを作る側だけが教師モデルを読む", "JA_MODEL" in teacher_src)

# --- 3. 教師との一致率（モデルを読まない） -----------------------------------
print("\n=== 3. 教師との一致率と、そこから言えること ===")

demo = agreement(DEMO_AGREEMENT_PAIRS)
print(f"  見本5件: n={demo['n']} 完全一致={demo['exact']:.3f} "
      f"区分一致={demo['category']:.3f}")
check("完全一致は 0.600（言い回しが違う1件と誤答1件が落ちる）",
      round(demo["exact"], 3) == 0.600, f"{demo['exact']:.3f}")
check("区分一致は 0.800（言い回しの違いは許す）",
      round(demo["category"], 3) == 0.800, f"{demo['category']:.3f}")
check("同じ列を2つ渡せば一致率は 1.000",
      agreement([(a, a) for a, _ in DEMO_AGREEMENT_PAIRS])["exact"] == 1.0)
check("区分一致は完全一致以上になる（緩い定義なので下回らない）",
      demo["category"] >= demo["exact"])
check("空のリストでは 0.0 を返す（ゼロ除算しない）",
      agreement([])["exact"] == 0.0)

n, teacher_correct, disagreements = 30, 25, 9
agree = (n - disagreements) / n
teacher_accuracy = teacher_correct / n
low, high = accuracy_bounds(teacher_accuracy, agree)
achievable = achievable_accuracy_range(n, teacher_correct, disagreements)
perfect = achievable_accuracy_range(n, teacher_correct, 0)
print(f"  n={n} 教師の正解率={teacher_accuracy:.3f} 一致率={agree:.3f}")
print(f"    不等式から: {low:.3f} 〜 {high:.3f}")
print(f"    実際に取りうる範囲: {achievable[0]:.3f} 〜 {achievable[1]:.3f}")

check("不等式の範囲は 0.533〜1.000", (round(low, 3), round(high, 3)) == (0.533, 1.000),
      f"{low:.3f}〜{high:.3f}")
check("列挙で出る範囲は 0.533〜0.867（教師の誤りが5件しかないので上は伸びない）",
      (round(achievable[0], 3), round(achievable[1], 3)) == (0.533, 0.867),
      f"{achievable[0]:.3f}〜{achievable[1]:.3f}")
check("一致率 1.000 なら生徒の正解率は教師と厳密に一致する（教師を超えられない）",
      perfect == (teacher_accuracy, teacher_accuracy),
      f"{perfect[0]:.3f}〜{perfect[1]:.3f}")
check("列挙で出る範囲は必ず不等式の範囲に収まる",
      low - 1e-9 <= achievable[0] and achievable[1] <= high + 1e-9)

for d in range(0, n - teacher_correct + 1):
    a = (n - d) / n
    lo2, hi2 = accuracy_bounds(teacher_accuracy, a)
    alo, ahi = achievable_accuracy_range(n, teacher_correct, d)
    if not (lo2 - 1e-9 <= alo and ahi <= hi2 + 1e-9):
        check(f"不等式が d={d} で破れている", False, f"{alo:.3f}〜{ahi:.3f}")
        break
else:
    check("一致しない件数を 0〜5 まで振っても不等式は破れない", True)

low_teacher = achievable_accuracy_range(30, 6, 0)
check("教師の正解率が 0.200 なら一致率 1.000 の生徒も 0.200 にしかならない",
      round(low_teacher[0], 3) == 0.200, f"{low_teacher[0]:.3f}")

# --- 4. 教師の誤りの伝播（合成・モデルを読まない） ---------------------------
print("\n=== 4. 教師の誤りは生徒に伝播するか ===")

check("合成データは 18 件の学習用と 6 件の評価用（言い回しは別）",
      (len(SYNTH_TRAIN), len(SYNTH_EVAL)) == (18, 6))
check("評価用の質問は学習用と文字列として一致しない（汚染していない）",
      not (set(q for _, _, q in SYNTH_TRAIN) & set(q for _, _, q in SYNTH_EVAL)))

clean = propagation({})
scattered = propagation(SCATTERED_MISTAKES)
systematic = propagation(SYSTEMATIC_MISTAKES)
for label, row in (("誤りなし", clean), ("散発誤り", scattered), ("系統誤り", systematic)):
    print(f"  [{label}] 教師の誤り率={row['teacher_error_rate']:.3f} "
          f"生徒の正解率={row['student_accuracy']:.3f} "
          f"生徒の誤り={row['student_wrong']} 件"
          f"（うち教師と同じ型={row['same_shape']} 件）")

check("誤りのない教師データなら生徒は 1.000",
      (round(clean["teacher_error_rate"], 3), round(clean["student_accuracy"], 3))
      == (0.000, 1.000))
check("散発誤り（6/18 = 0.333）は多数決で消える（生徒は 1.000）",
      (round(scattered["teacher_error_rate"], 3),
       round(scattered["student_accuracy"], 3)) == (0.333, 1.000),
      f"{scattered['teacher_error_rate']:.3f} -> {scattered['student_accuracy']:.3f}")
check("系統誤り（3/18 = 0.167）は残る（生徒は 0.833）",
      (round(systematic["teacher_error_rate"], 3),
       round(systematic["student_accuracy"], 3)) == (0.167, 0.833),
      f"{systematic['teacher_error_rate']:.3f} -> {systematic['student_accuracy']:.3f}")
check("誤りが少ない方が生徒は悪い ― 効くのは誤りの量ではなく型",
      systematic["teacher_error_rate"] < scattered["teacher_error_rate"]
      and systematic["student_accuracy"] < scattered["student_accuracy"])
check("生徒の誤りは教師と同じ型（PC を「アカウント」と答える）",
      systematic["student_wrong"] == systematic["same_shape"] == 1,
      str([(g, p) for _, g, p in systematic["rows"] if g != p]))
check("生徒の誤答も6区分のどれか（形式は守れている＝形式だけ見ても気づけない）",
      all(p in CATEGORIES for _, _, p in systematic["rows"]))

print("  抜き取り検証（18件のうち誤りが3件）")
misses = {k: miss_probability(18, 3, k) for k in (4, 6, 9)}
for k, miss in misses.items():
    print(f"    {k:>2} 件見る -> 見逃し={miss:.3f} 検出={1 - miss:.3f}")
needed = sample_size_for(18, 3, 0.05)
print(f"    見逃しを 0.05 以下にするには {needed} 件")
print(f"    誤りが 6 件あるなら 4 件で検出={1 - miss_probability(18, 6, 4):.3f}")

check("4件見たときの見逃しは 0.446（＝検出は 0.554）",
      round(misses[4], 3) == 0.446, f"{misses[4]:.3f}")
check("9件見たときの見逃しは 0.103", round(misses[9], 3) == 0.103, f"{misses[9]:.3f}")
check("見逃し確率は見る件数について単調に減る",
      misses[4] > misses[6] > misses[9])
check("見逃しを 0.05 以下にするには 11 件必要（18件中の6割を人が見る）",
      needed == 11, f"{needed} 件")
check("組み合わせの計算と一致する（C(15,4)/C(18,4)）",
      abs(misses[4] - math.comb(15, 4) / math.comb(18, 4)) < 1e-12)
check("誤りが多いほど抜き取りで見つけやすい",
      miss_probability(18, 6, 4) < miss_probability(18, 3, 4),
      f"{miss_probability(18, 6, 4):.3f} < {miss_probability(18, 3, 4):.3f}")

# --- 5. 実物で1往復（任意・重い） --------------------------------------------
if os.environ.get("RUN_TEACHER") != "1":
    print("\nRUN_TEACHER=1 を付けると、教師で数十件生成して生徒を学習する検証（5）も"
          "実行します（教師の生成があるので長い・既定では飛ばします）。")
else:
    print("\n=== 5. 教師で生成 → 解放 → 生徒を学習（2段構え） ===")
    import torch  # noqa: E402

    from make_teacher_data import generate_records  # noqa: E402

    from ftkit.data import load  # noqa: E402
    from ftkit.models import attach_lora, load_model  # noqa: E402
    from ftkit.train import TrainConfig, set_seed, train  # noqa: E402
    from distill_student import measure_agreement  # noqa: E402

    task = os.environ.get("DISTILL_TASK", "classify")
    n_teacher = int(os.environ.get("TEACHER_N", "6"))
    steps = int(os.environ.get("STUDENT_STEPS", "10"))
    examples = load("train")[:n_teacher]
    forbidden = {ex.id for ex in load("test")}

    print(f"  第1段：教師 {JA_MODEL}（bf16）で {n_teacher} 件・task={task}")
    records = generate_records(examples, task, dtype=torch.bfloat16)
    gc.collect()
    print(f"  教師を解放した時点の peak RSS: {rss_gb():.2f} GB")

    stage1 = validate_records(records, task, forbidden)
    print(f"  検証: 合格 {stage1['ok']} / 不合格 {stage1['ng']}")
    for code, count in stage1["counts"].items():
        print(f"    - {code}: {count} 件")
    path = save_jsonl(keep_valid(records, task, forbidden) or records,
                      SANDBOX / "data" / f"distill_teacher_verify_{task}.jsonl")
    reloaded = load_jsonl(path)
    check("教師データが JSONL に落ちて読み戻せる", len(reloaded) >= 1, str(path))
    check("生成した件数が指定と一致する", len(records) == n_teacher,
          f"{len(records)} 件")
    check("すべての件に教師名と生成時刻が入っている",
          all(r["teacher"] == JA_MODEL and r["generated_at"] for r in records))

    usable = to_examples(reloaded, task)
    if stage1["ok"] == 0:
        print("  （検証を通った件が0でした。素の教師の出力をそのまま使うと"
              "こうなることがあります。ここでは全件を使って先に進みます。）")

    print(f"  第2段：生徒 {FAST_MODEL} を LoRA で {steps} step")
    epochs = max(1, math.ceil(steps * 2 / max(len(usable), 1)))
    tokenizer = load_tokenizer(FAST_MODEL)
    set_seed(SEED)                       # モデル構築の前に呼ぶ
    model = attach_lora(load_model(FAST_MODEL), r=8, alpha=16)
    result = train(model, tokenizer, usable,
                   TrainConfig(task=task, epochs=epochs, batch_size=2,
                               max_length=320, max_steps=steps, log_every=5,
                               seed=SEED))
    print(f"  {result.summary()}")
    check(f"{steps} step 走った", result.steps == steps, f"{result.steps} step")
    check("loss が nan になっていない（採点対象が残っている）",
          all(x == x for x in result.losses))

    agree = measure_agreement(model, tokenizer, reloaded, task, limit=3)
    print(f"  教師との一致率: n={agree['n']} 完全一致={agree['exact']:.3f} "
          f"区分一致={agree['category']:.3f}")
    check("一致率が 0.0〜1.0 の範囲に収まる",
          0.0 <= agree["exact"] <= 1.0 and 0.0 <= agree["category"] <= 1.0)
    print("  （この数値は件数も step も本番より小さいので、本文には書きません。"
          "自分の環境で測って記録してください。）")

    del model
    gc.collect()
    print(f"  終了時の peak RSS: {rss_gb():.2f} GB")

if failures:
    print(f"\n{len(failures)} 件の検証に失敗しました: {failures}")
    sys.exit(1)
print("\nセッション12の検証はすべて成功しました。")
