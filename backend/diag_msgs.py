# -*- coding: utf-8 -*-
import json, urllib.request
def req(method, path, body=None):
    r = urllib.request.Request("http://127.0.0.1:8000/api" + path, method=method,
        data=json.dumps(body).encode() if body else None, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.loads(resp.read().decode())
sessions = req("GET", "/sessions")
print("会话数:", len(sessions))
for s in sessions[:3]:
    print(f"\n=== {s['title']} ({s['session_id']}) 消息数:{s['message_count']} ===")
    msgs = req("GET", f"/sessions/{s['session_id']}/messages")
    for m in msgs["messages"][-4:]:
        print(f"[{m['role']}] {(m['content'] or '')[:200]}")
