"""内置工具：知识查询 / 计算 / 时间

每个工具实现 Tool 接口：
  - name / description / parameters(JSON Schema)：注册与模型调用
  - run(args, ctx)：执行，ctx 携带当前会话（含 game_id），保证游戏参数由系统注入
"""
import json
from datetime import datetime
from typing import Any

from app.core.errors import AppError, ErrorCode
from app.core.logging import get_logger
from app.knowledge.games import Game, registry
from app.tools.base import Tool, ToolContext

logger = get_logger(__name__)


class QueryGameDataTool(Tool):
    """按游戏查询知识库结构化数据（骨架：数据加载在阶段一实现）"""

    name = "query_game_data"
    description = "查询当前游戏的知识库数据（角色、武器、圣遗物、材料、攻略），回答数据类问题"
    parameters = {
        "type": "object",
        "properties": {
            "category": {"type": "string", "enum": ["character", "weapon", "artifact", "material", "faq"]},
            "name": {"type": "string", "description": "条目名称关键词，可空"},
        },
        "required": ["category"],
    }

    def run(self, args: dict, ctx: ToolContext) -> Any:
        category = args.get("category")
        name = args.get("name")
        # TODO(阶段一)：加载 ctx.game.data_dir 下对应类型 JSON 并检索
        logger.info("query_game_data game=%s category=%s name=%s", ctx.game.game_id, category, name)
        return {
            "game": ctx.game.game_id,
            "category": category,
            "matches": [],  # 占位：数据入库后返回真实条目
        }


class CalculateTool(Tool):
    """数值计算：材料需求估算、体力规划等"""

    name = "calculate"
    description = "执行数值计算，用于材料数量估算、资源规划等场景"
    parameters = {
        "type": "object",
        "properties": {
            "expression": {"type": "string", "description": "数学表达式，如 20*3+5"},
        },
        "required": ["expression"],
    }

    def run(self, args: dict, ctx: ToolContext) -> Any:
        expr = args.get("expression", "")
        # 安全计算：仅允许数字、运算符与括号，拒绝任意代码执行
        import ast
        import operator

        allowed = {
            ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul,
            ast.Div: operator.truediv, ast.Pow: operator.pow, ast.Mod: operator.mod,
            ast.USub: operator.neg, ast.UAdd: operator.pos, ast.FloorDiv: operator.floordiv,
        }

        def _eval(node):
            if isinstance(node, ast.Expression):
                return _eval(node.body)
            if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
                return node.value
            if isinstance(node, ast.BinOp) and type(node.op) in allowed:
                return allowed[type(node.op)](_eval(node.left), _eval(node.right))
            if isinstance(node, ast.UnaryOp) and type(node.op) in allowed:
                return allowed[type(node.op)](_eval(node.operand))
            raise ValueError("不支持的表达式")

        try:
            result = _eval(ast.parse(expr, mode="eval"))
            return {"expression": expr, "result": result}
        except Exception as e:
            raise AppError(ErrorCode.TOOL_FAILED, f"计算失败: {e}") from e


class GetCurrentTimeTool(Tool):
    """当前时间：用于时效性表述"""

    name = "get_current_time"
    description = "获取当前日期与时间"
    parameters = {"type": "object", "properties": {}}

    def run(self, args: dict, ctx: ToolContext) -> Any:
        return {"now": datetime.now().strftime("%Y-%m-%d %H:%M:%S")}


# --- 工具注册表 ---
class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, Tool] = {}
        for tool in (CalculateTool(), GetCurrentTimeTool()):
            self._tools[tool.name] = tool
        # 延迟注册：避免 game_entity ↔ registry 循环导入
        from app.tools.game_entity import QueryGameEntityTool
        from app.tools.strategy_tools import AnalyzeTeamsTool, CalculateMaterialsTool, SearchGuidesTool, SearchStageGuidesTool
        from app.tools.event_tool import GetGameEventsTool

        self._tools[QueryGameEntityTool.name] = QueryGameEntityTool()
        self._tools[AnalyzeTeamsTool.name] = AnalyzeTeamsTool()
        self._tools[CalculateMaterialsTool.name] = CalculateMaterialsTool()
        self._tools[SearchGuidesTool.name] = SearchGuidesTool()
        self._tools[SearchStageGuidesTool.name] = SearchStageGuidesTool()
        self._tools[GetGameEventsTool.name] = GetGameEventsTool()

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def list(self) -> list[Tool]:
        return list(self._tools.values())

    def schemas(self) -> list[dict]:
        """供模型 Function Calling 声明的 JSON Schema 列表"""
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in self._tools.values()
        ]

    def execute(self, name: str, arguments: dict, ctx: ToolContext) -> Any:
        """执行工具：参数校验失败 / 异常统一抛 AppError，由调用方重试或兜底"""
        tool = self.get(name)
        logger.info("执行工具 %s args=%s", name, json.dumps(arguments, ensure_ascii=False)[:200])
        return tool.run(arguments, ctx)


tool_registry = ToolRegistry()
