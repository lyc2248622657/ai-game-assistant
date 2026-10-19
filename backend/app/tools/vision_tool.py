"""多模态截图识别工具：DeepSeek flash（原生多模态）识别游戏截图

用户上传游戏截图（角色面板 / 干员图鉴 / 卡池 / 背包等）后，
识别截图中的角色、干员、武器名称与关键文字，输出结构化 JSON；
下游由 Agent 继续用 query_game_entity / 检索回答"截图里是谁 / 怎么养"等。
"""
import base64
import json

from app.core import key_manager
from app.core.config import settings
from app.core.llm_json import extract_json
from app.core.logging import get_logger
from app.core.paths import ensure_upload_path
from app.tools.base import Tool, ToolContext

logger = get_logger(__name__)

# 多模态专用模型：DeepSeek V4.1 Flash（原生多模态，2026-09 起；单图按 token 计费）
VISION_MODEL = "deepseek-flash"
# 截图识别统一输出格式
VISION_PROMPT = (
    "你是游戏截图识别助手，识别《原神》/《明日方舟》的游戏截图"
    "（角色面板、干员图鉴、卡池界面、背包、活动页等）。\n"
    "只输出一个合法 JSON 对象，不要任何解释：\n"
    "{\n"
    '  "game": "genshin | arknights | unknown",\n'
    '  "entities": [{"name": "识别到的角色/干员/武器/材料名", "type": "character|weapon|artifact|material"}],\n'
    '  "summary": "截图内容一句话中文摘要",\n'
    '  "ocr_text": "截图中的关键文字（角色名、星级、卡池名、版本号、日期等，没有则为空字符串）"\n'
    "}\n"
    "entities 只列明确出现的实体名（如角色名/干员名/武器名），最多 5 个。"
)

_ALLOWED_TYPES = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
_MAX_BYTES = 10 * 1024 * 1024  # 10MB


def encode_image(image_path: str) -> str:
    """读图 → base64 data URL（附带 MIME；超大图先缩到长边 ≤1024 控制 token 与耗时）

    路径必须先通过 `ensure_upload_path` 校验：只允许读取上传目录内的截图，
    防止 image_path 被注入任意本地路径后随请求外发给模型。
    """
    p = ensure_upload_path(image_path)
    data = p.read_bytes()
    if len(data) > _MAX_BYTES:
        raise ValueError(f"截图过大（>{_MAX_BYTES // 1024 // 1024}MB），请压缩后重试")
    mime = "image/png"
    ext = p.suffix.lower()
    if ext == ".jpg" or ext == ".jpeg":
        mime = "image/jpeg"
    elif ext == ".webp":
        mime = "image/webp"
    elif ext == ".bmp":
        mime = "image/bmp"
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


def _call_vision(image_path: str, api_key: str | None, base_url: str | None) -> str:
    """调用 DeepSeek flash 多模态识别截图（OpenAI 兼容 image_url）"""
    from langchain_core.messages import HumanMessage
    from langchain_openai import ChatOpenAI

    model = ChatOpenAI(
        model=VISION_MODEL,
        api_key=api_key,
        base_url=base_url,
        temperature=0.1,
        timeout=90,
        max_retries=1,
    )
    resp = model.invoke(
        [
            HumanMessage(
                content=[
                    {"type": "text", "text": VISION_PROMPT},
                    {"type": "image_url", "image_url": {"url": encode_image(image_path)}},
                ]
            )
        ]
    )
    return resp.content or ""


def analyze_screenshot(image_path: str) -> dict:
    """识别截图 → 结构化结果；失败抛出异常由工具层兜底重试"""
    model, key = key_manager.resolve_runtime()
    if not key:
        raise RuntimeError("未配置 DeepSeek API Key，无法调用视觉模型")
    logger.info("vision analyze: %s", image_path)
    raw = _call_vision(image_path, key, settings.deepseek_base_url)
    data = extract_json(raw) or {}
    entities = []
    for e in data.get("entities") or []:
        if isinstance(e, dict) and e.get("name"):
            entities.append({"name": str(e["name"]).strip()[:60], "type": str(e.get("type") or "character")})
    result = {
        "game": str(data.get("game") or "unknown").strip().lower(),
        "entities": entities[:5],
        "summary": str(data.get("summary") or "").strip(),
        "ocr_text": str(data.get("ocr_text") or "").strip(),
        "image_path": image_path,
    }
    logger.info("vision result: %s", json.dumps(result, ensure_ascii=False)[:300])
    return result


class AnalyzeScreenshotTool(Tool):
    """识别游戏截图：提取截图中的角色/干员/武器与文字内容"""

    name = "analyze_screenshot"
    description = (
        "识别游戏截图（角色面板、干员图鉴、卡池、背包、活动页等），"
        "提取截图中出现的角色、干员、武器名称与关键文字摘要。"
        "用于用户上传游戏截图后回答「截图里是谁 / 这个角色怎么培养 / 这是什么卡池」等问题。"
    )
    parameters = {
        "type": "object",
        "properties": {
            "image_path": {"type": "string", "description": "用户上传截图的本地路径（随消息附带的 image_path）"},
        },
        "required": ["image_path"],
    }

    def run(self, args: dict, ctx: ToolContext) -> dict:
        image_path = str(args.get("image_path") or "").strip()
        if not image_path:
            raise ValueError("缺少 image_path（请先让用户上传截图）")
        return analyze_screenshot(image_path)
