# -*- coding: utf-8 -*-
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path('.').resolve()))
from app.agents.graph import app_graph
from app.agents.state import initial_state
state = initial_state(game_id="genshin", session_id=None, user_message="珊比基本信息", messages=[])
result = app_graph.invoke(state)
print("plan:", result.get("plan"))
print("plan_entity:", result.get("plan_entity"))
print("task_type:", result.get("task_type"))
print("tool_results:", json.dumps(result.get("tool_results", []), ensure_ascii=False)[:600])
print("final:", (result.get("final_answer") or "")[:100])
