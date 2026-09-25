# -*- coding: utf-8 -*-
"""冒烟测试：生成 3 个角色，验证 Generator→Validator 链路"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from scripts.generator.generator import Generator  # noqa: E402
from scripts.generator.llm import LLMClient  # noqa: E402
from scripts.generator.validator import Validator  # noqa: E402


def json_dump(e):
    return json.dumps(e, ensure_ascii=False)[:400]


llm = LLMClient()
gen = Generator(llm)
val = Validator(llm)

entries = gen.generate_batch(
    "character",
    "角色：名称/称号/稀有度/元素/武器类型/地区/登场版本/登场日期/特殊料理/定位/标签/简介",
    ["胡桃", "钟离", "甘雨"],
)
for e in entries:
    print(json_dump(e))

errors = val.validate("character", entries, ["胡桃", "钟离", "甘雨"], set())
print("校验错误:", errors if errors else "无 ✓")
print(llm.cost_report())
