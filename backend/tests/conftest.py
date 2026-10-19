"""pytest 全局夹具：所有测试必须跑在临时目录，绝不写真实数据。

历史问题：`store.py` / `user_memory.py` / `session_memory.py` / `memory_rag.py`
在 import 时就会建表、建目录；`test_a2a` 还会真实读写 Chroma。
没有隔离时，跑一次测试就会往真实的 `data/chroma` 与 `sessions.db` 里塞测试数据。

做法：在**任何 app 模块被导入之前**把路径型环境变量指向临时目录
（`Settings` 是进程级单例，导入后再改就无效了）。
"""
import os
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parent.parent
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_TMP = Path(tempfile.mkdtemp(prefix="aiga-test-"))

os.environ["SQLITE_PATH"] = str(_TMP / "sessions.db")
os.environ["CHROMA_DIR"] = str(_TMP / "chroma")
os.environ["DOCUMENTS_DIR"] = str(_TMP / "documents")
os.environ["EMBEDDING_CACHE_DIR"] = str(_TMP / "embeddings")
# 阻断所有 Key 回退链（app_data/key.txt、cwd/key.txt、桌面 key.txt），
# 保证测试永不真实调用外部模型（会花钱、且结果不可复现）
os.environ["APP_DATA_DIR"] = str(_TMP / "app_data")
os.environ["USERPROFILE"] = str(_TMP / "home")
os.environ["HOME"] = str(_TMP / "home")
os.environ["DEEPSEEK_API_KEY"] = ""

# 接口鉴权：测试固定一个令牌，并关闭"回环免令牌"，
# 这样每个 API 用例都在**真实鉴权链路**下运行（忘带令牌会立刻失败）。
os.environ["API_TOKEN"] = "test-token-please-change"
os.environ["TRUST_LOOPBACK"] = "0"


def pytest_sessionfinish(session, exitstatus):  # noqa: ANN001
    """会话结束后清理临时目录（Chroma 会留下 sqlite 文件）"""
    import shutil

    shutil.rmtree(_TMP, ignore_errors=True)
