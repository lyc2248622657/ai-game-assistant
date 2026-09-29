"""知识包：游戏注册表加载与访问"""
from pathlib import Path

import yaml

from app.core.config import settings
from app.core.errors import AppError, ErrorCode


class Game:
    """单个游戏的知识包配置"""

    def __init__(self, raw: dict):
        self.game_id: str = raw["id"]
        self.name: str = raw.get("name", raw["id"])
        self.description: str = raw.get("description", "")
        self.data_dir: Path = Path(settings.games_config).parent.parent / raw["data_dir"]
        self.collection: str = raw.get("collection", f"{self.game_id}_kb")
        self.wiki_base_url: str = raw.get("wiki_base_url", "")
        self.enabled: bool = raw.get("enabled", True)
        self.dynamic_generation: bool = raw.get("dynamic_generation", True)
        # Agent 层委派声明（1.1：supervisor 委派与提示词由此派生，热插拔扩展）
        self.agent_id: str = raw.get("agent_id", f"{self.game_id}_agent")
        self.agent_label: str = raw.get("agent_label", f"{raw['name']}子代理")
        self.entity_types: list[str] = [str(t) for t in raw.get("entity_types", [])]
        self.hints: list[str] = [str(h) for h in raw.get("hints", [])]
        self.wiki_desc: str = raw.get("wiki_desc", raw.get("description", ""))

    def to_info(self) -> dict:
        return {
            "game_id": self.game_id,
            "name": self.name,
            "enabled": self.enabled,
            "description": self.description,
            "agent_id": self.agent_id,
            "agent_label": self.agent_label,
            "entity_types": self.entity_types,
            "hints": self.hints,
            "wiki_desc": self.wiki_desc,
        }


class GameRegistry:
    """游戏注册表：加载 games.yaml，提供按游戏查询知识包的能力"""

    def __init__(self):
        self._games: dict[str, Game] = {}
        self._load()

    def _load(self) -> None:
        path = Path(settings.games_config)
        if not path.exists():
            raise AppError(ErrorCode.INTERNAL, f"游戏注册表不存在: {path}", 500)
        with path.open("r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}
        for item in raw.get("games", []):
            game = Game(item)
            self._games[game.game_id] = game

    def list_games(self, only_enabled: bool = True) -> list[dict]:
        games = [g.to_info() for g in self._games.values()]
        return [g for g in games if g["enabled"]] if only_enabled else games

    def get_game(self, game_id: str, require_enabled: bool = True) -> Game:
        game = self._games.get(game_id)
        if game is None:
            raise AppError(ErrorCode.GAME_NOT_FOUND, f"未注册的游戏: {game_id}")
        if require_enabled and not game.enabled:
            raise AppError(ErrorCode.GAME_NOT_FOUND, f"游戏未启用: {game_id}")
        return game


# 全局单例
registry = GameRegistry()
