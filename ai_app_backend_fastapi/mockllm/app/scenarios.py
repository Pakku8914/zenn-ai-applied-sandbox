"""fixtures/*.json のシナリオを読み込み、リクエストに対する応答ブロックを決める。"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from . import schema_gen

DEFAULT_SCENARIO = "default"


@dataclass
class RequestFeatures:
    model: str
    last_user_text: str = ""
    step: int = 0
    tool_names: set[str] = field(default_factory=set)
    image_sizes: list[tuple[int, int] | None] = field(default_factory=list)
    pdf_pages: list[int | None] = field(default_factory=list)
    text_documents: int = 0
    output_schema: dict | None = None
    last_tool_result_text: str = ""

    @property
    def has_image(self) -> bool:
        return bool(self.image_sizes)

    @property
    def has_document(self) -> bool:
        return bool(self.pdf_pages) or self.text_documents > 0


@dataclass
class Resolved:
    scenario: str
    step: int
    content: list[dict]
    stop_reason: str


class ScenarioError(ValueError):
    pass


class ScenarioBook:
    def __init__(self, fixtures_dir: Path):
        self.fixtures_dir = fixtures_dir
        self.scenarios: dict[str, dict] = {}
        self.reload()

    def reload(self) -> None:
        scenarios: dict[str, dict] = {}
        for path in sorted(self.fixtures_dir.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            name = data.get("name") or path.stem
            if name == DEFAULT_SCENARIO:
                raise ScenarioError(f"{path.name}: シナリオ名 '{DEFAULT_SCENARIO}' は予約語です")
            if not data.get("steps"):
                raise ScenarioError(f"{path.name}: steps が空です")
            data["name"] = name
            data["_file"] = path.name
            scenarios[name] = data
        self.scenarios = scenarios

    def summary(self) -> list[dict]:
        return [
            {
                "name": s["name"],
                "file": s["_file"],
                "description": s.get("description", ""),
                "priority": s.get("priority", 0),
                "match": s.get("match", {}),
                "steps": len(s["steps"]),
            }
            for s in self._ordered()
        ]

    def _ordered(self) -> list[dict]:
        return sorted(self.scenarios.values(), key=lambda s: (-s.get("priority", 0), s["_file"]))

    @staticmethod
    def _matches(scenario: dict, f: RequestFeatures) -> bool:
        rule = scenario.get("match", {})
        text = f.last_user_text
        if rule.get("any") and not any(k in text for k in rule["any"]):
            return False
        if rule.get("all") and not all(k in text for k in rule["all"]):
            return False
        if rule.get("tools") and not set(rule["tools"]).issubset(f.tool_names):
            return False
        for flag, actual in (
            ("has_image", f.has_image),
            ("has_document", f.has_document),
            ("output_format", f.output_schema is not None),
        ):
            if flag in rule and bool(rule[flag]) != actual:
                return False
        return True

    def resolve(self, f: RequestFeatures, explicit: str | None) -> Resolved:
        if explicit:
            if explicit == DEFAULT_SCENARIO:
                return self._default(f)
            if explicit not in self.scenarios:
                raise ScenarioError(
                    f"x-mock-scenario '{explicit}' は存在しません。利用可能: "
                    + ", ".join([DEFAULT_SCENARIO, *self.scenarios])
                )
            return self._render(self.scenarios[explicit], f)
        for scenario in self._ordered():
            if self._matches(scenario, f):
                return self._render(scenario, f)
        return self._default(f)

    def _render(self, scenario: dict, f: RequestFeatures) -> Resolved:
        steps = scenario["steps"]
        idx = min(f.step, len(steps) - 1)
        step = steps[idx]
        raw = step.get("content")
        if raw is None:
            raw = [{"type": "text", "text": step.get("text", "")}]
        has_tool = any(b["type"] == "tool_use" for b in raw)

        if f.output_schema is not None and not has_tool:
            if "json" in step:
                value = step["json"]
            else:
                value = schema_gen.generate(f.output_schema, step.get("json_hints"))
            content = [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]
        else:
            content = []
            for i, block in enumerate(raw):
                if block["type"] == "text":
                    content.append({"type": "text", "text": _template(block["text"], f)})
                elif block["type"] == "tool_use":
                    seed = f"{scenario['name']}|{idx}|{i}|{f.last_user_text}"
                    content.append({
                        "type": "tool_use",
                        "id": "toolu_mock_" + hashlib.sha256(seed.encode()).hexdigest()[:20],
                        "name": block["name"],
                        "input": block.get("input", {}),
                    })
                else:
                    raise ScenarioError(f"{scenario['_file']}: 未対応のブロック型 {block['type']}")
        emitted_tool = any(b["type"] == "tool_use" for b in content)
        stop_reason = step.get("stop_reason") or ("tool_use" if emitted_tool else "end_turn")
        return Resolved(scenario["name"], idx, content, stop_reason)

    def _default(self, f: RequestFeatures) -> Resolved:
        if f.output_schema is not None:
            value = schema_gen.generate(f.output_schema)
            text = json.dumps(value, ensure_ascii=False)
        else:
            topic = f.last_user_text.strip().replace("\n", " ")
            if len(topic) > 30:
                topic = topic[:30] + "…"
            text = (
                f"（mockllm の既定応答）「{topic}」についてですね。"
                "冷蔵庫にある食材と、調理にかけられる時間を教えていただければ、献立を提案します。"
            )
        return Resolved(DEFAULT_SCENARIO, 0, [{"type": "text", "text": text}], "end_turn")


_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")


def _template(text: str, f: RequestFeatures) -> str:
    sizes = "、".join(f"{s[0]}×{s[1]}" if s else "サイズ不明" for s in f.image_sizes)
    pages = "、".join(str(p) if p is not None else "不明" for p in f.pdf_pages)
    values = {
        "last_user_text": f.last_user_text,
        "image_count": str(len(f.image_sizes)),
        "image_sizes": sizes or "なし",
        "pdf_pages": pages or "なし",
        "document_count": str(len(f.pdf_pages) + f.text_documents),
        "tool_result": f.last_tool_result_text[:200],
        "step": str(f.step),
        "model": f.model,
    }
    return _PLACEHOLDER.sub(lambda m: values.get(m.group(1), m.group(0)), text)
