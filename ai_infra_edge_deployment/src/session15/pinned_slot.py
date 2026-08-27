"""既知良好版を面 a に固定する運用（問題8の解答）。

素の二面構成は「使っていない面」に書くので、2回更新すると
既知良好版のファイルが上書きされ、そこへ戻れなくなる。
面 a を固定し、試用は必ず面 b で行えば、いつでも戻れる。
"""
from __future__ import annotations

import json
from collections.abc import Callable

from ota import (Device, InstallResult, SignedRelease, check_compatibility,
                 sha256_file, verify_signature, write_atomic, rollback_to)

KNOWN_GOOD_SLOT = "a"   # 既知良好版。昇格のとき以外は絶対に上書きしない
TRIAL_SLOT = "b"        # 試用中の版を置く面


def seed_known_good(device: Device, version: str, data: bytes) -> None:
    """工場出荷時（または初回起動時）に既知良好版を面 a に置く。"""
    write_atomic(device.slot_file(KNOWN_GOOD_SLOT), data)
    _record(device, version)
    device.switch(KNOWN_GOOD_SLOT, version)


def known_good_version(device: Device) -> str | None:
    path = device.root / "known_good.json"
    return json.loads(path.read_text(encoding="utf-8"))["version"] if path.exists() else None


def _record(device: Device, version: str) -> None:
    write_atomic(device.root / "known_good.json",
                 json.dumps({"slot": KNOWN_GOOD_SLOT, "version": version},
                            ensure_ascii=False, sort_keys=True).encode("utf-8"))


def install_pinned(device: Device, package: SignedRelease, data: bytes, key: bytes, *,
                   probe: Callable[[bytes], bool] | None = None,
                   cut_at: int | None = None) -> InstallResult:
    """試用版を面 b に入れる。面 b が動いているときは受け付けない。"""
    before = device.active_version
    release = package.release
    if device.state()["slot"] == TRIAL_SLOT:
        return InstallResult(False, before, "試用中",
                             "面 b に試用中の版があります。昇格か戻しを先に行ってください")
    if not verify_signature(release, package.signature, key):
        return InstallResult(False, before, "署名", "マニフェストの署名が一致しません")
    reasons = check_compatibility(release, device.spec)
    if reasons:
        return InstallResult(False, before, "互換性", " / ".join(reasons))
    target = device.slot_file(TRIAL_SLOT)
    try:
        write_atomic(target, data, cut_at=cut_at)
    except OSError as exc:
        return InstallResult(False, before, "書き込み", str(exc))
    if sha256_file(target) != release.sha256 or target.stat().st_size != release.size_bytes:
        target.unlink(missing_ok=True)
        return InstallResult(False, before, "チェックサム", "照合に失敗しました")
    device.switch(TRIAL_SLOT, release.version)
    if probe is not None and not probe(data):
        did = rollback_known_good(device)
        return InstallResult(False, device.active_version, "起動確認",
                             "起動確認に失敗したので既知良好版に戻しました", rolled_back=did)
    return InstallResult(True, release.version, "完了")


def rollback_known_good(device: Device) -> bool:
    """面 a の既知良好版に戻す。何世代先に進んでいても1回で戻れる。"""
    version = known_good_version(device)
    return rollback_to(device, KNOWN_GOOD_SLOT, version) if version else False


def promote_known_good(device: Device, version: str) -> bool:
    """試用に合格した面 b の版を面 a に昇格する（原子的な置き換え）。"""
    trial = device.slot_file(TRIAL_SLOT)
    if not trial.exists():
        return False
    write_atomic(device.slot_file(KNOWN_GOOD_SLOT), trial.read_bytes())
    _record(device, version)
    device.switch(KNOWN_GOOD_SLOT, version)
    return True
