"""数据入库脚本：知识包 JSON → 分块 → 向量化 → 写入按游戏隔离的 Collection

用法：
    python scripts/ingest.py --game genshin
    python scripts/ingest.py --game genshin --reset   # 清空重建

数据格式约定（见方案附录 A）：
    data/<game_id>/*.json，每个文件为条目数组，条目含 id/type/name 等字段。
"""
import argparse
import json
import sys
from pathlib import Path

# 允许从项目根直接运行
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.logging import setup_logging  # noqa: E402
from app.knowledge.games import registry  # noqa: E402
from app.rag.embedding import get_embedding  # noqa: E402
from app.rag.vectorstore import get_vectorstore  # noqa: E402

setup_logging()
logger = __import__("app.core.logging", fromlist=["get_logger"]).get_logger("ingest")


def load_entries(data_dir: Path) -> list[dict]:
    """读取知识包目录下全部 JSON 条目（顶层 + dynamic 动态缓存）"""
    entries: list[dict] = []
    for sub in ("", "dynamic"):
        base = data_dir / sub
        if not base.exists():
            continue
        for f in sorted(base.glob("*.json")):
            with f.open("r", encoding="utf-8") as fh:
                data = json.load(fh)
            items = data if isinstance(data, list) else [data]
            entries.extend(items)
            logger.info("载入 %s: %d 条", f, len(items))
    return entries


TYPE_LABELS = {
    "character": "角色",
    "weapon": "武器",
    "artifact": "圣遗物",
    "food": "料理",
    "material": "材料",
    "team": "配队",
    "knowledge": "知识",
}


def chunk_entry(entry: dict) -> tuple[str, str, dict]:
    """条目 → (doc_id, 检索文本, 元数据)

    检索文本 = 类型标签 + 标题 + 关键字段（摘要/效果/核心机制/标签），
    类型标签帮助语义检索区分「圣遗物/料理/配队」等类别。
    """
    doc_id = entry.get("id") or f"{entry.get('type', 'item')}_{abs(hash(str(entry)))}"
    title = entry.get("name") or entry.get("question") or doc_id
    label = TYPE_LABELS.get(entry.get("type", ""), "")
    parts = [f"【{label}】{title}" if label else str(title)]
    for key in ("title", "summary", "description", "effect", "core", "rotation", "usage"):
        v = entry.get(key)
        if isinstance(v, str) and v:
            parts.append(v)
    tags = entry.get("tags")
    if isinstance(tags, list):
        parts.append(" ".join(str(t) for t in tags))
    meta = {"title": title, "type": entry.get("type", "item"), "source": entry.get("source", "static")}
    return doc_id, "\n".join(parts), meta


def main():
    parser = argparse.ArgumentParser(description="知识包入库")
    parser.add_argument("--game", required=True, help="游戏 id（见 config/games.yaml）")
    parser.add_argument("--reset", action="store_true", help="清空该游戏集合后重建")
    args = parser.parse_args()

    game = registry.get_game(args.game)
    if not game.data_dir.exists():
        logger.error("数据目录不存在: %s", game.data_dir)
        sys.exit(1)

    logger.info("开始入库 game=%s collection=%s dir=%s", game.game_id, game.collection, game.data_dir)
    if args.reset:
        store = get_vectorstore()
        try:
            store._client.delete_collection(game.collection)
            logger.info("已清空集合 %s", game.collection)
        except Exception:
            pass

    entries = load_entries(game.data_dir)
    if not entries:
        logger.error("知识包为空，请先整理数据")
        sys.exit(1)

    ids, texts, metas = [], [], []
    for e in entries:
        doc_id, text, meta = chunk_entry(e)
        ids.append(doc_id)
        texts.append(text)
        metas.append(meta)

    logger.info("向量化 %d 条（首次加载模型约需数分钟）…", len(entries))
    emb = get_embedding()
    vectors = emb.encode(texts)

    vs = get_vectorstore()
    vs.upsert(game.collection, ids, texts, metas, vectors)
    logger.info("入库完成：%s 共 %d 条，当前总数 %d", game.game_id, len(ids), vs.count(game.collection))


if __name__ == "__main__":
    main()
