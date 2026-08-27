#!/usr/bin/env python3
"""セッション15：運用の設定をコードの外に出す。

    python src/session15/opsconfig.py

本番で変えたくなる値（多重度・レート上限・カナリアの割合・1ジョブの上限）は、
**コードを触らずに変えられる**ようにしておく。ただし何でも設定にすると、
起動してみるまで壊れているか分からない状態になる。そこで2つだけ守る。

  ① 設定は1か所（`ops.json`）に置き、読み込み時に必ず検証する
  ② 検証は「起動時に落とす」。走り出してから落ちるより早く気づける
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, replace
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_PATH = HERE / "ops.json"


@dataclass(frozen=True)
class OpsConfig:
    """運用のつまみ。ここに無い値はコードの定数（＝運用では変えない）。"""

    workers: int = 2                      # 多重度（同時に走らせるワーカー数）
    rate_limit_per_second: int = 2        # レート上限（1秒あたりの LLM 呼び出し）
    rate_mode: str = "queue"              # queue（順番待ち）/ backoff（当たってから謝る）
    max_steps_per_job: int = 8            # 1ジョブに許すステップ数
    redelivery_seconds: int = 1           # 落ちたジョブを再配達するまでの待ち
    canary_percents: tuple[int, ...] = (5, 25, 100)   # 段階リリースの割合
    canary_strategy: str = "head"         # head（先頭から）/ stratified（型ごとに）
    min_success_rate: float = 0.98        # これを下回ったら進めない
    max_step_ratio: float = 1.2           # 手数が基準の何倍までなら許すか

    # -- 検証 ---------------------------------------------------------------
    def validate(self) -> None:
        """おかしな値は**起動時に**落とす。走り出してから落ちるより安い。"""
        if self.workers < 1:
            raise ValueError(f"workers は1以上です: {self.workers}")
        if self.rate_limit_per_second < 1:
            raise ValueError(
                f"rate_limit_per_second は1以上です: {self.rate_limit_per_second}")
        if self.rate_mode not in ("queue", "backoff"):
            raise ValueError(f"rate_mode は queue か backoff です: {self.rate_mode!r}")
        if self.max_steps_per_job < 1:
            raise ValueError(f"max_steps_per_job は1以上です: {self.max_steps_per_job}")
        if self.canary_strategy not in ("head", "stratified"):
            raise ValueError(
                f"canary_strategy は head か stratified です: {self.canary_strategy!r}")
        if not self.canary_percents:
            raise ValueError("canary_percents が空です。段階を1つ以上指定してください。")
        if list(self.canary_percents) != sorted(self.canary_percents):
            raise ValueError(
                f"canary_percents は昇順にしてください: {self.canary_percents}")
        if not 0 < self.min_success_rate <= 1.0:
            raise ValueError(f"min_success_rate は0より大きく1以下です: {self.min_success_rate}")
        if self.max_step_ratio < 1.0:
            raise ValueError(f"max_step_ratio は1.0以上です: {self.max_step_ratio}")

    # -- 読み書き -----------------------------------------------------------
    @classmethod
    def load(cls, path: Path | str | None = None) -> "OpsConfig":
        path = Path(path) if path else DEFAULT_PATH
        if not path.exists():
            raise FileNotFoundError(f"{path} がありません。設定ファイルを置いてください。")
        raw = json.loads(path.read_text(encoding="utf-8"))
        unknown = sorted(set(raw) - {f for f in cls.__dataclass_fields__})
        if unknown:
            # 知らないキーを黙って無視すると「設定したつもり」が本番で起きる
            raise ValueError(f"知らない設定キーがあります: {unknown}")
        if "canary_percents" in raw:
            raw["canary_percents"] = tuple(raw["canary_percents"])
        cfg = cls(**raw)
        cfg.validate()
        return cfg

    def with_(self, **changes) -> "OpsConfig":
        """一部だけ変えた設定を作る（実験用）。変更後も必ず検証する。"""
        cfg = replace(self, **changes)
        cfg.validate()
        return cfg

    def as_rows(self) -> list[tuple[str, str]]:
        return [(k, str(v)) for k, v in asdict(self).items()]


def main() -> None:
    cfg = OpsConfig.load()
    print(f"=== 設定（{DEFAULT_PATH.name}）===")
    print("キー | 値")
    for key, value in cfg.as_rows():
        print(f"{key} | {value}")

    print("\n=== 一部だけ変えて実験する ===")
    print(f"多重度を4にした設定: workers={cfg.with_(workers=4).workers}"
          f"（ファイルは書き換えていません）")

    print("\n=== おかしな値は起動時に落とす ===")
    for change in ({"workers": 0}, {"rate_mode": "yolo"}, {"canary_percents": (25, 5)}):
        try:
            cfg.with_(**change)
        except ValueError as exc:
            print(f"{change} -> ValueError: {exc}")


if __name__ == "__main__":
    main()
