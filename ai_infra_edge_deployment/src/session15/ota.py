#!/usr/bin/env python3
"""手元にない端末のモデルを、壊さずに入れ替える（セッション15の中核）。

    python src/session15/update_sim.py    # 1台に通しで適用してみる
    python src/session15/verify.py        # 本章の自己検証

OTA（無線経由の更新）を設計するとき、答えを持っていないといけない問いは6つある。
このファイルはその6つを、そのままの順番で関数にしてある。

  ① そのマニフェストは本物か        -> 署名（**悪意**を弾く）
  ② その端末に載せてよいか          -> 互換性（版と入出力の契約）
  ③ 書いている途中で電源が切れたら  -> `.part` + os.replace（原子的な置き換え）
  ④ 届いた中身は壊れていないか      -> チェックサム（**事故**を弾く）
  ⑤ 切り替えたあと動かなかったら    -> 二面構成（A/B）＋ 起動確認 ＋ 戻し
  ⑥ 戻しが届かない端末が残ったら    -> fleet.py の話（ここでは扱わない）

**セッション7の `fetch_weights.py`（リトライ・チェックサム・`.part` + `os.replace`）を
土台として再利用する。** 同じ作法を今度は端末側でもう一度使うのが本章の骨である。

数値の3分類は session11/edge_budget.py と同じ規律で扱う。混ぜてはいけない。

  ① 実測値   : reports/ の測定結果（測定条件つきで引用する）
  ② 物理計算 : 定数から計算できるもの（帯域と台数から出る配布時間）
  ③ 前提値   : 読者が自分の環境の値を入れるもの（台数・回線・観察時間・空き容量）
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass
from pathlib import Path

SANDBOX = Path(__file__).resolve().parents[2]
if str(SANDBOX) not in sys.path:
    sys.path.insert(0, str(SANDBOX))
_S07 = SANDBOX / "src" / "session07"
if str(_S07) not in sys.path:
    sys.path.insert(0, str(_S07))

from fetch_weights import sha256_bytes, sha256_file  # noqa: E402  セッション7から再利用

SLOTS = ("a", "b")
"""二面構成（A/B スロット）。片面が動いている間、もう片面は書き換えてよい。"""


class PowerLoss(OSError):
    """書き込み中に電源が切れた状況を模す例外（教材専用）。

    OSError の一種にしてあるのは、実機で起きる I/O の失敗と**同じ経路で扱う**
    ためである。電源断だけを特別扱いする実装は、ディスク満杯や書き込み禁止で
    同じように壊れる。
    """


# --- 版（バージョン）--------------------------------------------------------
def parse_version(text: str) -> tuple[int, int, int]:
    """`x.y.z` を数値の組にする。**文字列のまま比較してはいけない。**

    文字列比較では "1.10.0" < "1.9.0" になる（"1" < "9" と読まれる）。
    版が2桁に入った瞬間に、配ってよい端末を配れないと判定し始める。
    """
    parts = text.split(".")
    if len(parts) != 3 or not all(p.isdigit() for p in parts):
        raise ValueError(f"版は x.y.z の形式で書いてください: {text!r}")
    major, minor, patch = (int(p) for p in parts)
    return major, minor, patch


def version_lt(left: str, right: str) -> bool:
    return parse_version(left) < parse_version(right)


def version_ge(left: str, right: str) -> bool:
    return parse_version(left) >= parse_version(right)


# --- 配布物のマニフェスト ---------------------------------------------------
@dataclass(frozen=True)
class Release:
    """配る「モデル1つ」の宣言。**ファイルではなく、この宣言に署名する。**

    model_id / version : 何の版か（端末側のログとメトリクスのラベルになる）
    sha256 / size_bytes: 中身の同一性（事故の検出）
    min_app / max_app  : 載せてよいアプリ版の範囲。max_app は「その版未満」
    input_dim / n_classes: 入出力の契約（セッション12で「形状は契約」と書いたもの）
    """

    model_id: str
    version: str
    sha256: str
    size_bytes: int
    min_app: str
    max_app: str | None
    input_dim: int
    n_classes: int

    def digest(self) -> str:
        """署名の対象。**フィールドを1つでも変えるとここが変わる。**

        キーを並べ替えても同じ文字列になるように sort_keys を付ける。ここが
        揺れると「同じマニフェストなのに署名が合わない」事故になる。
        """
        payload = json.dumps(asdict(self), sort_keys=True, ensure_ascii=False,
                             separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SignedRelease:
    """マニフェストと、その署名。端末に届くのはこの組と本体ファイルである。"""

    release: Release
    signature: str


def sign(release: Release, key: bytes) -> str:
    """マニフェストに署名する（配布側だけが行う操作）。"""
    return hmac.new(key, release.digest().encode("ascii"), hashlib.sha256).hexdigest()


def signed(release: Release, key: bytes) -> SignedRelease:
    return SignedRelease(release=release, signature=sign(release, key))


def verify_signature(release: Release, signature: str, key: bytes) -> bool:
    """署名を検証する（端末側が行う操作）。

    比較に `hmac.compare_digest` を使う。`==` で比べると、一致した先頭バイト数
    で処理時間が変わるため、繰り返し試すことで正解を1バイトずつ探れてしまう。
    """
    return hmac.compare_digest(sign(release, key), signature)


# --- 端末の前提と互換性 -----------------------------------------------------
@dataclass(frozen=True)
class DeviceSpec:
    """③ 前提値。端末側が自分について知っていること。"""

    app_version: str
    input_dim: int
    n_classes: int
    free_bytes: int


def check_compatibility(release: Release, device: DeviceSpec) -> list[str]:
    """載せてよいかを判定する。**通らない理由を全部返す**（空なら互換）。

    最初の1つで打ち切らないのは、運用の理由である。「アプリ版が古い」だけを
    返すと、アプリを上げた後にもう一度「入力次元が違う」で落ちる。手元にない
    端末に対して往復を増やすのは高い。

    空き容量は**1面分**で判定する（動いていない面に書くため）。ただし二面構成は
    常時2面分のストレージを占有することを忘れないこと。
    """
    reasons: list[str] = []
    if version_lt(device.app_version, release.min_app):
        reasons.append(f"アプリ版 {device.app_version} が最低要件 {release.min_app} 未満")
    if release.max_app is not None and not version_lt(device.app_version, release.max_app):
        reasons.append(f"アプリ版 {device.app_version} が上限 {release.max_app} 以上")
    if device.input_dim != release.input_dim:
        reasons.append(f"入力次元が違う（端末 {device.input_dim} / モデル {release.input_dim}）")
    if device.n_classes != release.n_classes:
        reasons.append(f"クラス数が違う（端末 {device.n_classes} / モデル {release.n_classes}）")
    if device.free_bytes < release.size_bytes:
        reasons.append(f"空き容量不足（{device.free_bytes} バイト / 必要 {release.size_bytes} バイト）")
    return reasons


# --- 原子的な置き換え -------------------------------------------------------
def write_atomic(path: Path, data: bytes, *, cut_at: int | None = None) -> None:
    """`.part` に書いて `os.replace` で差し替える（セッション7と同じ作法）。

    `cut_at` にバイト数を渡すと、そこまで書いた時点で PowerLoss を投げる。
    **そのとき `path` にはまだ一度も触っていない**ので、動いている版は無傷である。

    真面目にやるなら親ディレクトリも fsync する（`os.replace` の結果自体を
    ディスクに固定するため）。ここでは教材の見通しを優先して省いている。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    with open(tmp, "wb") as handle:
        if cut_at is not None:
            handle.write(data[:cut_at])
            handle.flush()
            os.fsync(handle.fileno())
            raise PowerLoss(f"書き込み中に電源が切れた（{cut_at} バイトまで書いた）")
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(tmp, path)  # 同じファイルシステム内なら原子的に入れ替わる


def sweep_partials(root: Path) -> list[Path]:
    """残った `.part` を掃除する。**端末の起動時に必ず1回やる。**

    掃除しないと、失敗した配布のたびにストレージが減っていく。手元にない端末で
    「いつのまにか空き容量が無い」という故障は、たいていこれである。
    """
    found = sorted(root.rglob("*.part"))
    for path in found:
        path.unlink()
    return found


# --- 端末（二面構成）-------------------------------------------------------
@dataclass
class Device:
    """1台の端末を模した入れ物。実体はディレクトリ1つ。

        root/slot_a/model.bin   面A の本体
        root/slot_b/model.bin   面B の本体
        root/active.json        **指し先**（どちらの面が動いているか）

    「切り替え」とは指し先の小さなファイルを差し替えることであり、モデル本体を
    移動することではない。差し替える対象が小さいほど、原子的に扱いやすい。
    """

    root: Path
    spec: DeviceSpec

    def slot_file(self, slot: str) -> Path:
        return self.root / f"slot_{slot}" / "model.bin"

    @property
    def pointer(self) -> Path:
        return self.root / "active.json"

    def state(self) -> dict:
        if not self.pointer.exists():
            return {"slot": None, "version": None, "previous": None}
        return json.loads(self.pointer.read_text(encoding="utf-8"))

    @property
    def active_version(self) -> str | None:
        return self.state()["version"]

    def active_bytes(self) -> bytes | None:
        slot = self.state()["slot"]
        return self.slot_file(slot).read_bytes() if slot else None

    def idle_slot(self) -> str:
        """いま動いていない面。**書き込んでよいのはここだけ。**"""
        return "b" if self.state()["slot"] == "a" else "a"

    def switch(self, slot: str, version: str) -> None:
        """指し先を差し替える。ここが唯一の「切り替え」である。"""
        before = self.state()
        after = {
            "slot": slot,
            "version": version,
            "previous": ({"slot": before["slot"], "version": before["version"]}
                         if before["slot"] else None),
        }
        write_atomic(self.pointer,
                     json.dumps(after, ensure_ascii=False, sort_keys=True).encode("utf-8"))


# --- 適用と戻し -------------------------------------------------------------
@dataclass(frozen=True)
class InstallResult:
    ok: bool
    version: str | None   # 適用が終わった時点で動いている版
    stage: str            # どこで止まったか（署名／互換性／書き込み／チェックサム／起動確認／完了）
    reason: str = ""
    rolled_back: bool = False


def install(device: Device, package: SignedRelease, data: bytes, key: bytes, *,
            probe: Callable[[bytes], bool] | None = None,
            cut_at: int | None = None) -> InstallResult:
    """届いた配布物を端末に適用する。**順番が設計そのものである。**

    署名 → 互換性 → 書き込み（使っていない面）→ チェックサム → 切替 → 起動確認。

    どの段で落ちても、**動いている版は変わらない**（切替より前で落ちるか、
    切替の後なら戻す）。これが「壊さずに更新する」の意味である。
    """
    before = device.active_version
    release = package.release

    # ① 署名：マニフェストが本物か。ここを飛ばすと以降の検査は全部無意味になる
    if not verify_signature(release, package.signature, key):
        return InstallResult(False, before, "署名", "マニフェストの署名が一致しません")

    # ② 互換性：この端末に載せてよいか
    reasons = check_compatibility(release, device.spec)
    if reasons:
        return InstallResult(False, before, "互換性", " / ".join(reasons))

    # ③ 書き込み：動いていない面に書く。ここで電源が切れても動いている面は無傷
    slot = device.idle_slot()
    target = device.slot_file(slot)
    try:
        write_atomic(target, data, cut_at=cut_at)
    except OSError as exc:
        return InstallResult(False, before, "書き込み", str(exc))

    # ④ チェックサム：書けたファイルを読み直して照合する。
    #    サイズが合っていても中身が違うことがある（1バイトの化けはサイズに出ない）
    digest = sha256_file(target)
    size = target.stat().st_size
    if digest != release.sha256 or size != release.size_bytes:
        target.unlink(missing_ok=True)
        return InstallResult(False, before, "チェックサム",
                             f"照合に失敗（宣言 {release.size_bytes} バイト / 届いた {size} バイト）")

    # ⑤ 切替：指し先を原子的に差し替える
    device.switch(slot, release.version)

    # ⑥ 起動確認：実際に1回動かす。落ちたら前の面に戻す
    if probe is not None and not probe(data):
        did = rollback(device)
        reason = ("起動確認に失敗したので前の版に戻しました" if did
                  else "起動確認に失敗しましたが戻せる版がありません（初回導入）")
        return InstallResult(False, device.active_version, "起動確認", reason, rolled_back=did)

    return InstallResult(True, release.version, "完了")


def rollback(device: Device) -> bool:
    """1つ前の面に戻す。**前の面のファイルが残っていることが前提。**

    二面構成は1世代しか戻れない。戻した直後の「戻せる先」は、いま失敗した版に
    なる。2世代前に戻したいなら rollback_to で面を明示するか、面を増やす。
    """
    previous = device.state().get("previous")
    if not previous or not previous.get("slot"):
        return False
    if not device.slot_file(previous["slot"]).exists():
        return False
    device.switch(previous["slot"], previous["version"])
    return True


def rollback_to(device: Device, slot: str, version: str) -> bool:
    """戻す先を明示して戻す（既知良好版を固定の面に置いておく運用で使う）。"""
    if not device.slot_file(slot).exists():
        return False
    device.switch(slot, version)
    return True


__all__ = [
    "SLOTS", "PowerLoss", "parse_version", "version_lt", "version_ge",
    "Release", "SignedRelease", "sign", "signed", "verify_signature",
    "DeviceSpec", "check_compatibility", "write_atomic", "sweep_partials",
    "Device", "InstallResult", "install", "rollback", "rollback_to",
    "sha256_bytes", "sha256_file",
]
