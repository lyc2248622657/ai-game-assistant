# -*- coding: utf-8 -*-
"""测试按需实体查询链路：奥黛塔（未收录 → LLM 生成 + wiki 交叉验证 + 缓存）

验证：链路通 / wiki 验证差异 / token 使用情况 / 二次命中缓存
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.knowledge.games import registry  # noqa: E402
from app.tools.game_entity import QueryGameEntityTool, _Lazy  # noqa: E402
from app.tools.registry import ToolContext  # noqa: E402

game = registry.get_game("genshin")
tool = QueryGameEntityTool()
ctx = ToolContext(game)

print("=" * 60)
print("① 首次查询「奥黛塔」（预期：未命中 → 动态生成 + wiki 验证 + 缓存）")
print("=" * 60)
r1 = tool.run({"type": "character", "name": "奥黛塔"}, ctx)
print("found:", r1.get("found"))
meta = r1.get("_meta", {})
print("来源:", meta.get("source"))
print("wiki 验证:", "通过" if meta.get("wiki_checked") else "未执行")
diffs = meta.get("diffs", [])
print("交叉验证修正/差异:", json.dumps(diffs, ensure_ascii=False) if diffs else "无")
entity = r1.get("entity", {})
for k in ("name", "title", "rarity", "element", "weapon_type", "region", "debut_version", "debut_date", "role", "summary"):
    v = entity.get(k)
    print(f"  {k}: {v if not isinstance(v, str) or len(v) < 80 else v[:80] + '…'}")

llm = _Lazy.get_llm("")
print("-" * 60)
print("token 使用（本轮全部 LLM 调用）:")
print(llm.cost_report())

print()
print("=" * 60)
print("② 二次查询（预期：直接命中动态缓存，零 LLM 调用）")
print("=" * 60)
before = dict(llm.usage_total)
r2 = tool.run({"type": "character", "name": "奥黛塔"}, ctx)
after = dict(llm.usage_total)
print("found:", r2.get("found"))
print("来源:", (r2.get("_meta") or {}).get("source"))
print("token 增量:", after["prompt_tokens"] - before["prompt_tokens"], "prompt /",
      after["completion_tokens"] - before["completion_tokens"], "completion")
