"""工具基类（独立模块，避免 registry ↔ 具体工具循环导入）"""
from abc import ABC, abstractmethod
from typing import Any

from app.knowledge.games import Game


class ToolContext:
    """工具执行上下文：由 Agent 运行时注入，前端不可直接指定"""

    def __init__(self, game: Game):
        self.game = game


class Tool(ABC):
    name: str = ""
    description: str = ""
    parameters: dict = {}

    @abstractmethod
    def run(self, args: dict, ctx: ToolContext) -> Any:
        """执行工具并返回可 JSON 序列化结果"""
