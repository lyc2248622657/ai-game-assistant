# -*- coding: utf-8 -*-
"""临时修补脚本：改写 collect_special_food_links 为 ask 查询"""
import io

p = "scripts/crawler/run.py"
s = io.open(p, encoding="utf-8").read()

old = '''def collect_special_food_links(client: WikiClient, table_page: str) -> list[tuple[str, str, str]]:
    """解析特殊料理表：返回 [(角色, 原型料理, 特殊料理)]"""
    wt = client.parse_wikitext(table_page)
    rows: list[tuple[str, str, str]] = []
    for m in re.finditer(r"\\{\\{\\s*[^|\\n{]*表/行\\s*\\n(.*?)\\}\\}", wt, re.S):
        body = m.group(1)
        vals: dict[str, str] = {}
        for fm in re.finditer(r"(?:^|\\n)\\|\\s*([^=|]+?)\\s*=\\s*([^\\n|]+)", body, re.M):
            vals[fm.group(1).strip()] = clean_value(fm.group(2))
        char = vals.get("角色") or vals.get("制作者") or ""
        proto = vals.get("原型料理") or vals.get("原料理") or ""
        spec = vals.get("特殊料理") or vals.get("特色料理") or ""
        if char and spec:
            rows.append((char, proto, spec))
    logger.info("特殊料理表解析：%d 行", len(rows))
    if not rows:
        # 打印样本辅助调试
        logger.info("样本 wikitext: %s", wt[:600].replace("\\n", "⏎"))
    return rows'''

new = '''def collect_special_food_links(client: WikiClient, cfg: dict) -> list[tuple[str, str, str]]:
    """全量特殊料理映射：ask 查询 角色→特殊料理，返回 [(角色, 原型料理, 特殊料理)]"""
    rows: list[tuple[str, str, str]] = []
    items = client.ask("[[分类:角色]]|?特殊料理", limit=50)
    for it in items:
        char = it["fulltext"]
        for spec in it.get("printouts", {}).get("特殊料理", []) or []:
            if spec:
                rows.append((char, "", spec))
    logger.info("特殊料理映射：%d 行（原型料理待后续增强）", len(rows))
    return rows'''

assert old in s, "pattern not found"
s = s.replace(old, new)

# 调用处：collect_special_food_links(client, cfg["special_food_table"]) → (client, cfg)
old_call = 'links = collect_special_food_links(client, cfg["special_food_table"])'
new_call = "links = collect_special_food_links(client, cfg)"
assert old_call in s, "call pattern not found"
s = s.replace(old_call, new_call)

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("patched OK")
