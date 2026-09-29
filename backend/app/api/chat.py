"""聊天接口：执行 Agent 图并返回回答

- POST /api/chat          非流式（invoke 完成后返回完整回答）
- POST /api/chat/stream   SSE 流式：逐节点推送 Agent 事件，前端时间线实时刷新
"""
import asyncio
import json
import traceback

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from app.agents.graph import app_graph
from app.agents.state import initial_state
from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.core.usage import usage_stats
from app.knowledge.games import registry
from app.memory.memory_rag import memory_rag
from app.memory.session_memory import session_memory
from app.memory.store import store
from app.memory.user_memory import user_memory
from app.schemas.chat import ChatRequest, ChatResponse, Citation

logger = get_logger(__name__)
router = APIRouter(prefix="/api/chat", tags=["chat"])


def _write_memory(session_id: str, game_id: str, entities: list[str] | None = None) -> None:
    """对话结束后写入记忆（失败不阻塞主流程）：
    1) 会话摘要滚动压缩（session_memory）
    2) 用户偏好提取入库（user_memory）
    3) Memory RAG：摘要/偏好/常问实体向量化写入 Chroma（跨会话语义召回）
    """
    try:
        session_memory.refresh(session_id, game_id)
        user_memory.extract_and_store(game_id, store.get_messages(session_id))
        summary = session_memory.get_summary(session_id)
        prefs = user_memory.get_prefs(game_id)
        memory_rag.upsert_session(game_id, session_id, summary=summary, prefs=prefs, entities=entities)
    except Exception as e:  # noqa: BLE001
        logger.warning("记忆写入失败: %s", e)


def _usage_delta(before: dict) -> dict:
    """本轮对话的 LLM token 消耗（请求前/后快照差值；本地单用户口径）"""
    now = usage_stats.snapshot()
    return {
        "input_tokens": now["input_tokens"] - before["input_tokens"],
        "output_tokens": now["output_tokens"] - before["output_tokens"],
        "total_tokens": now["total_tokens"] - before["total_tokens"],
        "llm_calls": now["llm_calls"] - before["llm_calls"],
    }


def _prepare(body: ChatRequest):
    """校验游戏（可缺省：统一对话框由 Agent 判别）→ 获取/创建会话 → 组装初始状态"""
    from app.core import key_manager

    # 未配置 API Key 时给出明确引导（应用内设置界面填写后即时生效，无需重启）
    model, api_key = key_manager.resolve_runtime()
    if not api_key:
        raise AppError(ErrorCode.CONFIG_ERROR, "尚未配置 API Key：请点击右上角 ⚙ 设置，填入 DeepSeek API Key 后即可使用", 400)
    gid = (body.game_id or "").strip() or None
    if gid:
        game = registry.get_game(gid)
    else:
        # 未指定游戏：用第一个启用游戏作为会话归属（Agent plan 节点会按问题自动判别）
        enabled = registry.list_games()
        game = registry.get_game(enabled[0]["game_id"]) if enabled else registry.get_game("genshin")
    session = store.get_session(body.session_id) if body.session_id else None
    if session is None:
        session = store.create_session(game.game_id)
    history = store.get_messages(session["session_id"], limit=20)
    state = initial_state(
        game_id=game.game_id,
        session_id=session["session_id"],
        user_message=body.message,
        messages=history,
    )
    return game, session, state


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"


@router.post("", response_model=ChatResponse)
def chat(body: ChatRequest):
    """发送消息，执行多智能体流程，返回回答与引用（含本轮 token 消耗）"""
    game, session, state = _prepare(body)
    usage_before = usage_stats.snapshot()

    try:
        result = app_graph.invoke(state)
    except AppError as e:
        raise e
    except Exception as e:
        logger.error("Agent 执行失败: %s\n%s", e, traceback.format_exc())
        raise AppError(ErrorCode.INTERNAL, "Agent 执行失败，请稍后重试", 500) from e

    answer = result.get("final_answer") or "（骨架）暂无回答"
    citations = [
        Citation(doc_id=c["doc_id"], title=c["title"], snippet=c.get("content", ""), source=c.get("source", ""))
        for c in result.get("citations", [])
    ]

    store.add_message(session["session_id"], "user", body.message)
    store.add_message(session["session_id"], "assistant", answer, citations=[c.model_dump() for c in citations])
    _write_memory(
        session["session_id"],
        result.get("game_id") or game.game_id,
        entities=[c.title for c in citations[:4]],
    )

    return ChatResponse(
        session_id=session["session_id"],
        game_id=result.get("game_id") or game.game_id,
        answer=answer,
        citations=citations,
        suggestions=result.get("suggestions") or [],
        image_url=result.get("entity_image"),
        related_entities=result.get("related_entities") or [],
        guides=result.get("guides"),
        usage=_usage_delta(usage_before),
    )


@router.post("/stream", response_class=StreamingResponse)
async def chat_stream(body: ChatRequest, request: Request):
    """SSE 流式聊天：Agent 各节点事件实时推送，最后推回答/引用/done。

    2.4 修复：async 生成器 + request.is_disconnected() 断连检测——
    客户端断开后立即停止拉取后续节点（不再发起新的 LLM 调用），
    避免 token 浪费；正在执行的单次同步 LLM 调用无法中途取消（语言级限制，已在日志说明）。
    """
    game, session, state = _prepare(body)

    async def gen():
        last_n = 0
        last_snapshot = None
        usage_before = usage_stats.snapshot()
        yield _sse("session", {"type": "session", "session_id": session["session_id"]})
        try:
            async for snapshot in app_graph.astream(state, stream_mode="values"):
                if await request.is_disconnected():
                    logger.info("[sse] 客户端断开连接，停止流: %s", session["session_id"])
                    return
                last_snapshot = snapshot
                events = snapshot.get("events") or []
                for ev in events[last_n:]:
                    yield _sse(ev["type"], ev)
                last_n = len(events)
                fa = snapshot.get("final_answer")
                if fa and fa not in ("（骨架）暂无回答", "（工具执行完成，未得到最终回答）"):
                    yield _sse("answer", {"type": "answer", "delta": fa})
            if last_snapshot:
                cits = last_snapshot.get("citations") or []
                yield _sse("citations", {"type": "citations", "citations": cits})
                # suggestions / image 若已在图内 emit 则重复推送无妨（前端幂等覆盖）；未 emit 时兜底
                if last_snapshot.get("suggestions"):
                    yield _sse("suggestions", {"type": "suggestions", "suggestions": last_snapshot["suggestions"]})
                if last_snapshot.get("entity_image"):
                    yield _sse("image", {"type": "image", "image_url": last_snapshot["entity_image"]})
                if last_snapshot.get("related_entities"):
                    yield _sse("related_entities", {"type": "related_entities", "related_entities": last_snapshot["related_entities"]})
                if last_snapshot.get("guides"):
                    yield _sse("guides", {"type": "guides", "guides": last_snapshot["guides"]})
                answer = last_snapshot.get("final_answer") or "（骨架）暂无回答"
                if await request.is_disconnected():
                    logger.info("[sse] 客户端断开，跳过会话落库: %s", session["session_id"])
                    return
                await asyncio.to_thread(store.add_message, session["session_id"], "user", body.message)
                await asyncio.to_thread(
                    store.add_message, session["session_id"], "assistant", answer,
                    [{"doc_id": c["doc_id"], "title": c["title"], "content": c.get("content", ""), "source": c.get("source", "")} for c in cits],
                )
                await asyncio.to_thread(
                    _write_memory,
                    session["session_id"],
                    last_snapshot.get("game_id") or game.game_id,
                    [c.get("title", "") for c in cits[:4]],
                )
            yield _sse("usage", {"type": "usage", "usage": _usage_delta(usage_before)})
            yield _sse("done", {"type": "done"})
        except Exception as e:  # noqa: BLE001
            logger.error("SSE 流异常: %s\n%s", e, traceback.format_exc())
            yield _sse("error", {"type": "error", "code": 500, "error_message": str(e)})

    return StreamingResponse(gen(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
