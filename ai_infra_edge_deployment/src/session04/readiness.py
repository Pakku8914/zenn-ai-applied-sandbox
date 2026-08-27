#!/usr/bin/env python3
"""ヘルスチェックの3種（起動・準備完了・生存）の状態機械（セッション4）。

「プロセスが生きている」と「受け付けてよい」は別物である。
モデルのロード中は **生存している（live）が準備完了ではない（not ready）**。
ここを1つのエンドポイントで表すと、起動直後にトラフィックを流してしまうか、
ロード中に再起動され続けるかのどちらかになる。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum


class Phase(str, Enum):
    STARTING = "starting"   # プロセスは応答するが、モデルをまだ読めていない
    LOADED = "loaded"       # モデルのロード完了。ウォームアップがまだ
    READY = "ready"         # 受け付けてよい
    DRAINING = "draining"   # 停止要求を受けた。新規は受けない
    BROKEN = "broken"       # 回復不能。再起動が必要


@dataclass(frozen=True)
class Probe:
    """1つのヘルスチェックの結果。HTTP のステータスコードに素直に写せる形にする。"""

    ok: bool
    phase: str
    detail: dict = field(default_factory=dict)


class ReadinessGate:
    """起動シーケンスの進み具合を持ち、3種のヘルスチェックに答える。

    warmup_required 回のウォームアップが終わるまで ready にならない。
    """

    def __init__(self, warmup_required: int = 2, clock=time.monotonic) -> None:
        if warmup_required < 0:
            raise ValueError("warmup_required は 0 以上にしてください")
        self.warmup_required = warmup_required
        self._clock = clock
        self._started_at = clock()
        self.phase = Phase.STARTING
        self.warmup_done = 0
        self.reason = ""

    # --- 状態を進める ------------------------------------------------------
    def mark_model_loaded(self) -> None:
        """モデルのロードが終わった。まだ受け付けてはいけない。"""
        if self.phase is Phase.STARTING:
            self.phase = Phase.LOADED
            self._maybe_ready()

    def record_warmup(self) -> None:
        """ウォームアップ1回ぶんの完了を記録する。"""
        if self.phase in (Phase.BROKEN, Phase.DRAINING):
            return
        self.warmup_done += 1
        self._maybe_ready()

    def begin_drain(self) -> None:
        """停止要求を受けた。新規は受けないが、処理中のぶんは返す。"""
        if self.phase is not Phase.BROKEN:
            self.phase = Phase.DRAINING

    def mark_broken(self, reason: str) -> None:
        """回復不能。再起動してもらうしかない状態。"""
        self.phase = Phase.BROKEN
        self.reason = reason

    def _maybe_ready(self) -> None:
        if self.phase is Phase.LOADED and self.warmup_done >= self.warmup_required:
            self.phase = Phase.READY

    # --- 3種のヘルスチェック ----------------------------------------------
    @property
    def uptime_s(self) -> float:
        return self._clock() - self._started_at

    def _detail(self) -> dict:
        return {"phase": self.phase.value,
                "warmup": f"{self.warmup_done}/{self.warmup_required}",
                "uptime_s": round(self.uptime_s, 1),
                **({"reason": self.reason} if self.reason else {})}

    def startup(self) -> Probe:
        """起動：モデルのロードが終わったか。**ここが済むまで生存判定を始めない。**"""
        ok = self.phase in (Phase.LOADED, Phase.READY, Phase.DRAINING)
        return Probe(ok, self.phase.value, self._detail())

    def ready(self) -> Probe:
        """準備完了：いま新しいリクエストを受けてよいか。

        ロード完了 **かつ** ウォームアップ完了 **かつ** 停止処理中でないこと。
        """
        return Probe(self.phase is Phase.READY, self.phase.value, self._detail())

    def live(self) -> Probe:
        """生存：プロセスが壊れていないか。

        **ロード中も true を返す。** ここで false を返すと、ロードが終わる前に
        殺されて起動し直す無限ループに入る。
        """
        return Probe(self.phase is not Phase.BROKEN, self.phase.value, self._detail())

    def snapshot(self) -> dict:
        """人が見る用のまとめ。監視は上の3つ（ステータスコード）を見る。"""
        return {"phase": self.phase.value,
                "startup": self.startup().ok,
                "ready": self.ready().ok,
                "live": self.live().ok,
                **self._detail()}


WARMUP_PROMPT = "あなたは社内ヘルプデスクの回答者です。準備確認のため「準備完了」と答えてください。"


def run_startup(gate: ReadinessGate, client, warmups: int = 2, attempts: int = 30,
                sleep_s: float = 2.0, sleep=time.sleep) -> None:
    """起動シーケンス：ロードを待つ → ウォームアップする → 準備完了にする。

    この順番を守ることが、起動直後の1発目だけ極端に遅い状態を読者に見せない条件。
    sleep を差し替えられるようにしてあるのでテストから待たずに呼べる。
    """
    for _ in range(attempts):
        if client.health():
            gate.mark_model_loaded()
            break
        sleep(sleep_s)
    else:
        gate.mark_broken(f"モデルのロードを待ちきれませんでした（{attempts} 回確認）")
        return

    for _ in range(warmups):
        result = client.generate(WARMUP_PROMPT, max_tokens=8)
        if not result.ok:
            gate.mark_broken(f"ウォームアップが失敗しました: {result.error}")
            return
        gate.record_warmup()
