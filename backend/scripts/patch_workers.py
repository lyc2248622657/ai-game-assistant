# -*- coding: utf-8 -*-
import io

p = "scripts/crawler/run.py"
s = io.open(p, encoding="utf-8").read()
old = 'parser.add_argument("--workers", type=int, default=4)'
new = 'parser.add_argument("--workers", type=int, default=2)'
assert old in s, "not found"
s = s.replace(old, new)

# 类型间加短暂间隔，避免切换时的突发请求
old2 = """            save(entries, game_dir, entry_type)
            counts[entry_type] = len(entries)"""
new2 = """            save(entries, game_dir, entry_type)
            counts[entry_type] = len(entries)
            time.sleep(2)  # 类型切换间隔，降低限流风险"""
assert old2 in s, "not found2"
s = s.replace(old2, new2)

io.open(p, "w", encoding="utf-8", newline="").write(s)
print("patched")
