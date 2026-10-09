"""練習問題1：本番用 Dockerfile の点検を関数にする。

lint_dockerfile(text) は、見つけた問題を RULES の順に返す（空なら合格）。
"""

from __future__ import annotations

RULES = (
    "FROM のタグが固定されていない",
    "USER が無いか root のまま",
    "--reload が付いている",
    "pip install に版が固定されていない名前がある",
    "CMD が exec 形式ではない",
    "COPY . で文脈を丸ごと入れている",
)

BAD_DOCKERFILE = """\
FROM python:latest
WORKDIR /app
COPY . .
RUN pip install fastapi uvicorn anthropic
EXPOSE 8000
CMD uvicorn src.session16.app:app --host 0.0.0.0 --port 8000 --reload
"""

_TAKES_VALUE = {"-r", "--requirement", "-c", "--constraint", "-i", "--index-url"}


def logical_lines(text: str) -> list[str]:
    """行末の \\ でつながった行を1行にし、コメントと空行を除く。"""
    lines: list[str] = []
    buf = ""
    for raw in text.splitlines():
        s = raw.strip()
        if not buf and (not s or s.startswith("#")):
            continue
        if s.endswith("\\"):
            buf += s[:-1] + " "
            continue
        lines.append(buf + s)
        buf = ""
    if buf:
        lines.append(buf.strip())
    return lines


def has_unpinned(segment: str) -> bool:
    """pip install の後ろに、== の付かないパッケージ名があるか（-r で渡すファイルは名前に数えない）。"""
    tokens = segment.split()
    rest = tokens[tokens.index("install") + 1:]
    skip = False
    for tok in rest:
        if skip:
            skip = False
            continue
        if tok in _TAKES_VALUE:
            skip = True
            continue
        if tok.startswith("-"):
            continue
        if "==" not in tok:
            return True
    return False


def image_is_pinned(image: str) -> bool:
    if "@" in image:  # ダイジェスト指定（@sha256:...）は固定とみなす
        return True
    name_tag = image.rsplit("/", 1)[-1]
    return ":" in name_tag and not name_tag.endswith(":latest")


def lint_dockerfile(text: str) -> list[str]:
    found: set[int] = set()
    users: list[str] = []
    cmds: list[str] = []
    for line in logical_lines(text):
        word, _, rest = line.partition(" ")
        word, rest = word.upper(), rest.strip()
        if word == "FROM" and not image_is_pinned(rest.split()[0]):
            found.add(0)
        elif word == "USER":
            users.append(rest)
        elif word == "RUN":
            for segment in rest.replace(";", "&&").split("&&"):
                if "pip install" in segment and has_unpinned(segment):
                    found.add(3)
        elif word == "CMD":
            cmds.append(rest)
        elif word == "COPY":
            args = [a for a in rest.split() if not a.startswith("--")]
            if args and args[0] in (".", "./"):
                found.add(5)
        if "--reload" in line:
            found.add(2)
    if not users or users[-1].split(":")[0] in ("root", "0"):
        found.add(1)
    if cmds and not cmds[-1].startswith("["):
        found.add(4)
    return [RULES[i] for i in sorted(found)]
