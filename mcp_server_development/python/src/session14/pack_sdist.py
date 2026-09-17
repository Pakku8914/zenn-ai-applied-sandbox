"""配布物の一覧を作って検査し、sdist 相当のアーカイブを作る（ローカル完結の代替手順）

  docker compose exec python python src/session14/pack_sdist.py src/session14/docsearch_pkg

本物の sdist / wheel は `uv build`（ビルドバックエンド hatchling）が作ります。
このスクリプトは pyproject.toml の include 設定を読み、
  ① 配布物に入るファイル一覧を組み立てる
  ② 配布してはいけないファイル名が混ざっていないか
  ③ 本文に秘密情報らしき文字列が無いか
  ④ [project.scripts] のエントリーポイントが実際に import できるか
を検査したうえで、標準ライブラリの tarfile でアーカイブを作ります。

終了コード 0 = 合格 / 1 = 不合格。
"""

from __future__ import annotations

import importlib
import re
import sys
import tarfile
import tomllib
from pathlib import Path

FORBIDDEN_PATHS: list[tuple[str, re.Pattern[str]]] = [
    ("環境変数ファイル", re.compile(r"(^|/)\.env(\..+)?$")),
    ("秘密鍵・証明書", re.compile(r"\.(pem|key|p12|pfx)$")),
    ("認証情報", re.compile(r"(^|/)\.(pypirc|netrc)$")),
    ("ログ", re.compile(r"\.log$")),
    ("キャッシュ", re.compile(r"(^|/)(__pycache__|\.pytest_cache)(/|$)")),
    ("内部メモ", re.compile(r"(^|/)(notes|internal|secrets)(/|$)")),
]

SECRET_CONTENTS: list[tuple[str, re.Pattern[str]]] = [
    ("PEM 形式の秘密鍵", re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    ("AWS アクセスキー ID", re.compile(r"AKIA[0-9A-Z]{16}")),
    (
        "トークンらしき代入",
        re.compile(
            r"(token|secret|password|passwd|api[_-]?key)\s*[:=]\s*[\"']?[A-Za-z0-9_\-]{16,}",
            re.IGNORECASE,
        ),
    ),
]

SKIP_DIRS = {"__pycache__", ".git", ".venv", ".pytest_cache", "dist", "build"}
MAX_SCAN_BYTES = 1024 * 1024


def collect(project_dir: Path, includes: list[str]) -> list[Path]:
    """include の指定から配布物に入るファイルを集める（hatchling の挙動を模す）"""
    found: set[Path] = set()
    for entry in includes:
        target = project_dir / entry
        if target.is_dir():
            for path in target.rglob("*"):
                if not path.is_file():
                    continue
                if any(part in SKIP_DIRS for part in path.parts):
                    continue
                if path.suffix == ".pyc":
                    continue
                found.add(path)
        elif target.is_file():
            found.add(target)
    return sorted(found)


def check_entry_points(project_dir: Path, scripts: dict[str, str]) -> list[str]:
    """[project.scripts] の "モジュール:関数" が本当に呼び出せるかを確かめる"""
    problems: list[str] = []
    sys.path.insert(0, str(project_dir / "src"))
    for command, target in scripts.items():
        module_name, _, attribute = target.partition(":")
        try:
            module = importlib.import_module(module_name)
        except Exception as error:  # noqa: BLE001 - 原因の種類だけ出す
            problems.append(f"{command}: {module_name} を import できません（{type(error).__name__}）")
            continue
        if not callable(getattr(module, attribute, None)):
            problems.append(f"{command}: {target} が呼び出せません")
    return problems


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("使い方: python src/session14/pack_sdist.py <プロジェクトのディレクトリ>", file=sys.stderr)
        return 2

    project_dir = Path(argv[1]).resolve()
    with (project_dir / "pyproject.toml").open("rb") as handle:
        config = tomllib.load(handle)

    project = config["project"]
    scripts: dict[str, str] = project.get("scripts", {})
    includes: list[str] = (
        config.get("tool", {})
        .get("hatch", {})
        .get("build", {})
        .get("targets", {})
        .get("sdist", {})
        .get("include", [])
    )
    if not includes:
        print("NG: [tool.hatch.build.targets.sdist] の include が空です（何が入るか決まりません）")
        return 1

    files = collect(project_dir, includes)
    relatives = [str(path.relative_to(project_dir)) for path in files]

    problems = check_entry_points(project_dir, scripts)
    version = importlib.import_module("docsearch_mcp").__version__

    print(f"[check] 対象: {project_dir.name}")
    print(f"[check] パッケージ: {project['name']} {version}")
    print(f"[check] [project.scripts]: {', '.join(f'{k} -> {v}' for k, v in scripts.items())}")
    print(f"[check] 配布ファイル数: {len(relatives)}")
    for relative in relatives:
        print(f"        {relative}")

    for relative in relatives:
        for label, pattern in FORBIDDEN_PATHS:
            if pattern.search(relative):
                problems.append(f"配布してはいけないファイルが含まれています: {relative}（{label}）")

    for path, relative in zip(files, relatives, strict=True):
        if path.stat().st_size > MAX_SCAN_BYTES:
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pattern in SECRET_CONTENTS:
            if pattern.search(text):
                # 一致した値そのものは出力しない
                problems.append(f"本文に秘密情報らしき文字列が見つかりました: {label}（{relative}）")

    if problems:
        for problem in problems:
            print(f"NG: {problem}")
        print(f"NG: {len(problems)} 件の問題が見つかりました。公開してはいけません。")
        return 1

    dist_dir = project_dir / "dist"
    dist_dir.mkdir(exist_ok=True)
    archive = dist_dir / f"docsearch_mcp-{version}.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for path, relative in zip(files, relatives, strict=True):
            tar.add(path, arcname=f"docsearch_mcp-{version}/{relative}")

    print(f"[check] 作成: {archive.relative_to(project_dir.parent.parent.parent)}（サイズは環境で変わります）")
    print("OK: 配布物の中身に問題は見つかりませんでした")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
