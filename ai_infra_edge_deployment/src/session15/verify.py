#!/usr/bin/env python3
"""セッション15の自己検証。

    python src/session15/verify.py

検証するのは**決定的な性質だけ**である。レイテンシのような環境依存の絶対値は
期待値に書かない（本書の全章共通の作法）。ここに出る配布時間は定数から出る
②物理計算なので、誰の環境でも同じ値になる。

外部ネットワークには一切触らない。端末はテンポラリディレクトリで模す。
"""

from __future__ import annotations

import shutil
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fleet import (BUCKET_LABELS, CLIENT_TIMEOUT_S, DELTA_RATIO, DEVICE_COUNT,
                   DEVICE_PAYLOAD_KEYS, EQ_MAX_DIFF, FAILURE_TOLERANCE, FP32_MB,
                   GB, INT8_BYTES, INT8_MB, MB, average_concurrent, check_payload,
                   device_payload, fleet_totals, max_parallel_for_timeout,
                   merge_buckets, per_device_seconds, plan_elapsed_hours,
                   quantile_bucket, release_gate, rollout_gate, sample_fleet,
                   stage_plan, telemetry_bytes, total_gb, transfer_seconds,
                   version_mix, waves)  # noqa: E402
from ota import (Device, DeviceSpec, Release, SignedRelease, check_compatibility,
                 install, rollback, sign, signed, sweep_partials, verify_signature,
                 version_lt)  # noqa: E402
from pinned_slot import (install_pinned, known_good_version, promote_known_good,
                         rollback_known_good, seed_known_good)  # noqa: E402
from update_sim import blob, release  # noqa: E402

failures: list[str] = []
checked = 0


def check(label: str, cond: bool, detail: str = "") -> None:
    global checked
    checked += 1
    print(f"{'OK' if cond else 'NG'} {label}" + (f" — {detail}" if detail else ""))
    if not cond:
        failures.append(label)


print("=== セッション15：自己検証 ===")

# --- [1] 版と互換性 ---------------------------------------------------------
print("\n[1] 版の比較と互換性")
check("版は数値の組で比べる（文字列比較では逆になる）",
      version_lt("1.9.0", "1.10.0") and not ("1.9.0" < "1.10.0"),
      "数値では True（古い）／文字列では False")

REL = Release(model_id="helpdesk-intent", version="1.3.0", sha256="0" * 64,
              size_bytes=INT8_BYTES, min_app="2.0.0", max_app=None,
              input_dim=384, n_classes=10)
SPECS = (DeviceSpec("2.1.0", 384, 10, 104_857_600),
         DeviceSpec("1.9.0", 384, 10, 104_857_600),
         DeviceSpec("2.1.0", 256, 10, 104_857_600),
         DeviceSpec("1.9.0", 384, 8, 10_485_760))
counts = [len(check_compatibility(REL, spec)) for spec in SPECS]
check("互換性の理由は打ち切らずに全部返る", counts == [0, 1, 1, 3],
      f"端末①〜④で {counts}")
# バイト数は models/onnx/classifier_int8.onnx の実サイズと一致していること。
# 表示値 17.56 MB から逆算すると 18,412,995 になるが、それは実ファイルより
# 3,496 バイト多い「丸めた表示から作った数字」なので使わない。
_int8_path = Path("models/onnx/classifier_int8.onnx")
check("INT8_BYTES が実ファイルのサイズと一致する",
      (not _int8_path.exists()) or INT8_BYTES == _int8_path.stat().st_size,
      f"定義 {INT8_BYTES:,} バイト / 二面構成なら {INT8_BYTES * 2:,} バイトを常時占有する")

# --- [2] 1台の更新 ----------------------------------------------------------
print("\n[2] 1台の更新（どの門で落ちても動いている版は変わらない）")
tmp = Path(tempfile.mkdtemp(prefix="session15-verify-"))
SPEC = DeviceSpec("2.1.0", 384, 10, 104_857_600)
KEY = b"session15-verify-key"
data12, data13 = blob("1.2.0"), blob("1.3.0")
rel12, rel13 = release("1.2.0", data12), release("1.3.0", data13)

device = Device(root=tmp / "dev-0001", spec=SPEC)
boot = install(device, signed(rel12, KEY), data12, KEY, probe=lambda _: True)
check("初回導入が成功する", boot.ok and device.active_version == "1.2.0",
      f"面 {device.state()['slot']}")

tampered = SignedRelease(release=replace(rel13, size_bytes=len(data13) + 1),
                         signature=sign(rel13, KEY))
res = install(device, tampered, data13, KEY, probe=lambda _: True)
check("改ざんされたマニフェストは署名の門で止まる",
      res.stage == "署名" and device.active_version == "1.2.0")
check("別の鍵で作った署名は通らない",
      not verify_signature(rel13, sign(rel13, b"attacker-key"), KEY))

res = install(device, signed(release("1.3.0", data13, min_app="3.0.0"), KEY),
              data13, KEY, probe=lambda _: True)
check("載せてよくない端末は互換性の門で止まる",
      res.stage == "互換性" and device.active_version == "1.2.0")

res = install(device, signed(rel13, KEY), data13, KEY,
              probe=lambda _: True, cut_at=1000)
check("電源断でも動いている版は無傷",
      res.stage == "書き込み" and device.active_bytes() == data12,
      "旧版 1.2.0 のバイト列が変わっていない")
swept = sweep_partials(device.root)
check("失敗した配布の .part は起動時の掃除で消える",
      len(swept) == 1 and not list(device.root.rglob("*.part")),
      f"{len(swept)} 個削除")

res = install(device, signed(rel13, KEY), data13[:-1] + b"X", KEY,
              probe=lambda _: True)
check("チェックサム不一致は切替の前で止まる",
      res.stage == "チェックサム" and device.active_version == "1.2.0",
      f"段階: {res.stage}")

result = install(device, signed(rel13, KEY), data13, KEY, probe=lambda _: False)
check("起動確認の失敗で前の版に戻る",
      result.stage == "起動確認" and result.rolled_back
      and device.active_version == "1.2.0", "1.3.0 -> 1.2.0")

fresh = Device(root=tmp / "fresh", spec=SPEC)
first = install(fresh, signed(rel12, KEY), data12, KEY, probe=lambda _: False)
check("初回導入では戻せる版が無い",
      not first.rolled_back and "戻せる版がありません" in first.reason)

good = install(device, signed(rel13, KEY), data13, KEY, probe=lambda _: True)
check("正しい配布物なら新版が動く", good.ok and device.active_version == "1.3.0",
      f"面 {device.state()['slot']}")
check("二面構成は1世代しか戻れない",
      rollback(device) and device.active_version == "1.2.0"
      and rollback(device) and device.active_version == "1.3.0",
      "2回戻すと元の版に戻ってくる")

# --- [3] 段階展開と帯域 -----------------------------------------------------
print("\n[3] 段階展開と帯域（②物理計算）")
stages = stage_plan()
check("段階展開の台数は 1 / 9 / 90 / 900",
      [stage.added for stage in stages] == [1, 9, 90, 900],
      f"累積 {[stage.target for stage in stages]}")
check("段の台数の合計は総台数と一致する",
      sum(stage.added for stage in stages) == DEVICE_COUNT)
plan_seconds = sum(stage.seconds for stage in stages)
check("段に分けても配布の合計時間は変わらない",
      abs(plan_seconds - transfer_seconds(INT8_MB)) < 1e-6, f"{plan_seconds:,.1f} 秒")
check("int8 を 1,000 台に配ると 1,404.8 秒",
      abs(transfer_seconds(INT8_MB) - 1404.8) < 0.05,
      f"{transfer_seconds(INT8_MB) / 60:.1f} 分")
check("配布時間の比はサイズの比と一致する",
      abs(transfer_seconds(FP32_MB) / transfer_seconds(INT8_MB)
          - FP32_MB / INT8_MB) < 1e-9,
      f"{transfer_seconds(FP32_MB) / transfer_seconds(INT8_MB):.1f} 倍")
check("総量は int8 が 17.1 GB / fp32 が 68.5 GB",
      abs(total_gb(INT8_MB) - 17.148) < 0.01 and abs(total_gb(FP32_MB) - 68.486) < 0.01)
check("観察を含めた所要は 72.4 時間（観察 24 時間 × 3 段 ＋ 配布）",
      abs(plan_elapsed_hours(stages) - (72 + transfer_seconds(INT8_MB) / 3600)) < 1e-9,
      f"{plan_elapsed_hours(stages):.1f} 時間")
check("観察を 6 時間にすると所要が短くなる（配布時間は同じ）",
      plan_elapsed_hours(stage_plan(observe_hours=6.0)) < plan_elapsed_hours(stages),
      f"{plan_elapsed_hours(stage_plan(observe_hours=6.0)):.1f} 時間")

# --- [4] サンダリングハード -------------------------------------------------
print("\n[4] サンダリングハード（同時取得数とタイムアウト）")
check("同時 1,000 台では1台がタイムアウトを超える",
      per_device_seconds(INT8_MB, DEVICE_COUNT) > CLIENT_TIMEOUT_S,
      f"{per_device_seconds(INT8_MB, DEVICE_COUNT):,.1f} 秒 > {CLIENT_TIMEOUT_S:.0f} 秒")
limit = max_parallel_for_timeout(INT8_MB)
check("タイムアウトを守れる同時台数の上限は 213 台", limit == 213,
      f"1台あたり {per_device_seconds(INT8_MB, limit):.1f} 秒")
check("上限を1台超えるとタイムアウトする",
      per_device_seconds(INT8_MB, limit + 1) > CLIENT_TIMEOUT_S)
check("50 台ずつなら 20 波でタイムアウトしない",
      waves(DEVICE_COUNT, 50) == 20
      and per_device_seconds(INT8_MB, 50) < CLIENT_TIMEOUT_S,
      f"1台あたり {per_device_seconds(INT8_MB, 50):.1f} 秒")
check("ジッタの窓を広げると平均同時台数が下がる",
      average_concurrent(window_s=14400) < average_concurrent(window_s=60) < limit,
      f"60 秒で {average_concurrent(window_s=60):.1f} 台 / "
      f"4 時間で {average_concurrent(window_s=14400):.2f} 台")
check("差分配信は全体配信より短い（総量が減るから）",
      transfer_seconds(INT8_MB * DELTA_RATIO) < transfer_seconds(INT8_MB),
      f"{transfer_seconds(INT8_MB * DELTA_RATIO):,.1f} 秒 < "
      f"{transfer_seconds(INT8_MB):,.1f} 秒")

# --- [5] 版別の分布と門 -----------------------------------------------------
print("\n[5] 版別の分布と門")
fleet = sample_fleet()
stats = version_mix(fleet)
new, current, old = stats
check("版は新しい順に並ぶ",
      [stat.version for stat in stats] == ["1.3.0", "1.2.0", "1.1.0"])
check("台数は 100 / 850 / 50", [stat.devices for stat in stats] == [100, 850, 50],
      f"割合 {[f'{stat.ratio:.1%}' for stat in stats]}")
check("失敗率は新版 2.500% / 現行 0.500% / 旧版 1.000%",
      abs(new.failure_rate - 0.025) < 1e-9
      and abs(current.failure_rate - 0.005) < 1e-9
      and abs(old.failure_rate - 0.010) < 1e-9)
totals = fleet_totals(fleet)
check("オフラインは 100 台（分母は常に全台）",
      totals.offline == 100 and totals.devices == DEVICE_COUNT,
      f"{totals.offline_ratio:.1%}")
check("バケットは足せる（合計が全体の推論件数と一致）",
      sum(merge_buckets(fleet)) == totals.inferences, f"{totals.inferences:,} 件")
check("新版の p95 は現行より悪い区間に入る",
      BUCKET_LABELS.index(quantile_bucket(new.buckets, 0.95))
      > BUCKET_LABELS.index(quantile_bucket(current.buckets, 0.95)),
      f"{quantile_bucket(new.buckets, 0.95)} / "
      f"{quantile_bucket(current.buckets, 0.95)}")
check("配る前の門は等価性の実測で通る",
      release_gate(EQ_MAX_DIFF, clear_agree=True).ok,
      f"確率の最大差 {EQ_MAX_DIFF:.6f}（①実測・セッション12）")
check("等価性が崩れた版は配る前の門で落ちる",
      not release_gate(0.02, clear_agree=True).ok
      and not release_gate(EQ_MAX_DIFF, clear_agree=False).ok)
check("配った後の門は新版を止める", rollout_gate(new, current).verdict == "中止",
      rollout_gate(new, current).reasons[0])
check("件数が足りないときは判断しない（保留）",
      rollout_gate(replace(new, inferences=3, failures=0), current).verdict == "保留")
mild = replace(new, failures=120)
check("許容の範囲内なら続行", rollout_gate(mild, current).verdict == "続行",
      f"{mild.failure_rate:.3%} <= "
      f"{current.failure_rate * FAILURE_TOLERANCE:.3%}")

# --- [6] 集約指標 -----------------------------------------------------------
print("\n[6] 集約指標（プライバシー）")
payload = device_payload(fleet[0])
check("集約指標のキーは許可リストと一致する", set(payload) == set(DEVICE_PAYLOAD_KEYS))
try:
    check_payload({**payload, "raw_input": [0.1] * 384})
    ok = False
except ValueError:
    ok = True
check("生の入力を混ぜると検査で落ちる", ok, "許可リストに無いキーは例外にする")
check("集約すると転送量が 1,536 分の1 になる",
      telemetry_bytes(raw=True) // telemetry_bytes() == 1536,
      f"{telemetry_bytes(raw=True) / GB:.2f} GB -> {telemetry_bytes() / MB:.2f} MB")

# --- [7] 既知良好版を固定面に置く -------------------------------------------
print("\n[7] 既知良好版を固定面に置く")
data10, data11 = blob("1.0.0"), blob("1.1.0")
rel10, rel11 = release("1.0.0", data10), release("1.1.0", data11)

plain = Device(root=tmp / "plain", spec=SPEC)
install(plain, signed(rel10, KEY), data10, KEY, probe=lambda _: True)   # 面 a
install(plain, signed(rel11, KEY), data11, KEY, probe=lambda _: True)   # 面 b
install(plain, signed(rel12, KEY), data12, KEY, probe=lambda _: True)   # 面 a を上書き
check("素の二面構成では2回更新すると既知良好版のファイルが消える",
      plain.slot_file("a").read_bytes() == data12
      and plain.slot_file("a").read_bytes() != data10,
      "面 a が 1.2.0 で上書きされた")

pinned = Device(root=tmp / "pinned", spec=SPEC)
seed_known_good(pinned, "1.0.0", data10)
trial1 = install_pinned(pinned, signed(rel12, KEY), data12, KEY, probe=lambda _: True)
busy = install_pinned(pinned, signed(rel13, KEY), data13, KEY, probe=lambda _: True)
check("試用中の更新は受け付けない", busy.stage == "試用中", f"段階: {busy.stage}")
rollback_known_good(pinned)
trial2 = install_pinned(pinned, signed(rel13, KEY), data13, KEY, probe=lambda _: True)
rollback_known_good(pinned)
check("固定面なら2回の試用と戻しのあとも既知良好版が残る",
      trial1.ok and trial2.ok and pinned.active_version == "1.0.0"
      and pinned.slot_file("a").read_bytes() == data10,
      "面 a のバイト列が 1.0.0 と一致")
check("起動確認の失敗も既知良好版に戻る",
      install_pinned(pinned, signed(rel13, KEY), data13, KEY,
                     probe=lambda _: False).rolled_back
      and pinned.active_version == "1.0.0")
check("昇格すると既知良好版が入れ替わる",
      install_pinned(pinned, signed(rel13, KEY), data13, KEY,
                     probe=lambda _: True).ok
      and promote_known_good(pinned, "1.3.0")
      and pinned.slot_file("a").read_bytes() == data13
      and known_good_version(pinned) == "1.3.0",
      "面 a が 1.3.0 になった")

shutil.rmtree(tmp, ignore_errors=True)

print(f"\n検証 {checked} 件")
if failures:
    print(f"NG {len(failures)} 件: " + " / ".join(failures))
    sys.exit(1)
print("すべて OK（失敗 0 件）")
