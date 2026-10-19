"""智能命名单测：本地规则标题 + 已命名不覆盖 + LLM 失败回退"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


from app.api.chat import _auto_title, _rule_title  # noqa: E402


def test_rule_title_strips_greetings():
    assert _rule_title("请问胡桃用什么圣遗物？") == "胡桃用什么圣遗物？"
    assert _rule_title("帮我查一下能天使的技能") == "能天使的技能"
    assert _rule_title("介绍一下那维莱特配队") == "那维莱特配队"  # 客套前缀一并去除


def test_rule_title_first_line_and_length():
    assert _rule_title("第一行标题\n第二行无关内容") == "第一行标题"
    long = "这是一个非常长的提问标题超过十四个字应该被截断处理的部分内容"
    assert len(_rule_title(long)) == 14


def test_rule_title_empty():
    assert _rule_title("") == "新会话"
    assert _rule_title("   ") == "新会话"


def test_auto_title_skips_named_session(monkeypatch):
    """已命名（含用户手动改名）的会话不覆盖标题"""
    calls = []

    class FakeStore:
        @staticmethod
        def get_session(sid):
            return {"title": "胡桃养成"}

        @staticmethod
        def update_session_title(sid, title):
            calls.append(title)

    monkeypatch.setattr("app.api.chat.store", FakeStore)
    _auto_title("s1", "胡桃用什么圣遗物？")
    assert calls == []  # 已命名 → 不触发更新


def test_auto_title_llm_fail_falls_back_to_rule(monkeypatch):
    """LLM 提炼失败 → 静默回退本地规则截断，不抛异常"""
    calls = []

    class FakeStore:
        @staticmethod
        def get_session(sid):
            return {"title": "新会话"}

        @staticmethod
        def update_session_title(sid, title):
            calls.append(title)

    class Boom:
        def invoke(self, *a, **k):
            raise RuntimeError("LLM 超时")

    monkeypatch.setattr("app.api.chat.store", FakeStore)
    monkeypatch.setattr("app.agents.llm.get_chat_model", lambda: Boom())  # 函数内 import，须 patch 源模块
    _auto_title("s2", "请问万达国际的核心思路是什么？")
    assert calls == ["万达国际的核心思路是什么？"]


def test_auto_title_llm_success(monkeypatch):
    """LLM 提炼成功 → 去引号/换行后入库"""

    class FakeStore:
        @staticmethod
        def get_session(sid):
            return {"title": "新对话"}

        @staticmethod
        def update_session_title(sid, title):
            calls.append(title)

    calls = []

    class Resp:
        content = "“胡桃圣遗物推荐”\n"

    class Ok:
        def invoke(self, *a, **k):
            return Resp()

    monkeypatch.setattr("app.api.chat.store", FakeStore)
    monkeypatch.setattr("app.agents.llm.get_chat_model", lambda: Ok())
    _auto_title("s3", "胡桃用什么圣遗物？")
    assert calls == ["胡桃圣遗物推荐"]
