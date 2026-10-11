"""向量库运维 CLI：统计 / 脏数据清理 / 增量更新（RAG 岗演示脚本）

用法（backend 目录下，用项目 venv）：
  .venv\\Scripts\\python.exe scripts\\vector_admin.py list
  .venv\\Scripts\\python.exe scripts\\vector_admin.py stats documents
  .venv\\Scripts\\python.exe scripts\\vector_admin.py delete-doc documents 示例公司员工制度手册
  .venv\\Scripts\\python.exe scripts\\vector_admin.py rebuild 示例公司员工制度手册
  .venv\\Scripts\\python.exe scripts\\vector_admin.py purge documents
"""
import argparse
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.rag import vector_admin  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="向量库运维（统计/清理/增量重建）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("list", help="列出全部集合及块数")
    p_stats = sub.add_parser("stats", help="集合统计（总量/按文档/按来源/孤儿块）")
    p_stats.add_argument("collection", nargs="?", default="documents")
    p_del = sub.add_parser("delete-doc", help="按文档名删除向量块")
    p_del.add_argument("collection")
    p_del.add_argument("doc")
    p_rebuild = sub.add_parser("rebuild", help="增量重建文档（先删旧块再入库）")
    p_rebuild.add_argument("doc")
    p_purge = sub.add_parser("purge", help="清理孤儿块")
    p_purge.add_argument("collection", nargs="?", default="documents")

    args = parser.parse_args()
    if args.cmd == "list":
        for c in vector_admin.list_collections():
            print(f"{c['name']}\t{c['count']}")
    elif args.cmd == "stats":
        import json
        print(json.dumps(vector_admin.collection_stats(args.collection), ensure_ascii=False, indent=2))
    elif args.cmd == "delete-doc":
        print(vector_admin.delete_document(args.collection, args.doc))
    elif args.cmd == "rebuild":
        print(vector_admin.rebuild_document(args.doc))
    elif args.cmd == "purge":
        print(vector_admin.purge_orphans(args.collection))


if __name__ == "__main__":
    main()
