"""阶段 3 端到端：用户发消息 → Agent 自主决策 → 工具调用 → 最终回复。

跑法：
    1. 启动服务（设 LLM_MOCK=true 走 mock 模式，避免真实 LLM 调用）
       LLM_MOCK=true uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
    2. 另开终端：uv run python scripts/e2e_phase3.py
"""

from __future__ import annotations

import io
import json
import sys
import time
import urllib.request
from urllib.error import HTTPError

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

API = "http://127.0.0.1:8765"


def http(method: str, path: str, *, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(
        API + path, method=method, headers={"Content-Type": "application/json"}
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    print(f"{data=}")
    try:
        with urllib.request.urlopen(req, data=data) as resp:
            raw = resp.read().decode()
            if resp.status == 204 or not raw:
                return resp.status, None
            return resp.status, json.loads(raw)
    except HTTPError as exc:
        raw = exc.read().decode()
        if exc.code == 204 or not raw:
            return exc.code, None
        return exc.code, json.loads(raw)


def main() -> int:
    print("=" * 72)
    print("  Phase 3 End-to-End: User chats with Agent")
    print("=" * 72)

    # 1. 登录
    print("\n[1] login admin")
    code, body = http(
        "POST", "/api/auth/login", body={"username": "admin", "password": "ChangeMe@2026"}
    )
    if code != 200:
        print(f"  [FAIL] {body}")
        return 1
    token = body["access_token"]
    print(f"  [OK] token len={len(token)}")

    # 2. 确保 30 封邮件已 sync（admin 入库 + 索引不必须）
    # code, body = http("POST", "/api/emails/sync", token=token)
    # print(f"\n[2] sync emails: {body}")

    # 3. 创建 session
    print("\n[3] create chat session")
    code, session = http("POST", "/api/chat/sessions", token=token, body={"title": "Phase3 demo"})
    if code != 201:
        print(f"  [FAIL] {body}")
        return 1
    session_id = session["id"]
    print(f"  [OK] session_id={session_id}")

    # 4. 用户发 3 个不同 query，看 agent 自主决策
    queries = [
        "今天有什么重要邮件",
        "列出我所有的待办",
        "Acme 合同的关键内容是什么",
    ]
    for i, q in enumerate(queries, 1):
        print(f"\n[4.{i}] USER: {q}")
        t0 = time.perf_counter()
        code, result = http(
            "POST",
            f"/api/chat/sessions/{session_id}/messages",
            token=token,
            body={"content": q},
        )
        elapsed = int((time.perf_counter() - t0) * 1000)
        if code != 200:
            print(f"  [FAIL] status={code} {result}")
            continue
        print(f"  [OK] {elapsed} ms")
        print(f"  agents: {result.get('agents_invoked')}")
        print(f"  intent: {result.get('current_intent')}")
        print(f"  trace_id: {result.get('trace_id')[:16]}...")
        print(f"  reply: {result.get('final_response', '')[:150]}")

    # 5. 列消息历史
    print("\n[5] list messages in session")
    code, msgs = http("GET", f"/api/chat/sessions/{session_id}/messages", token=token)
    print(f"  [OK] {len(msgs)} messages")
    for m in msgs:
        preview = m["content"][:60].replace("\n", " ")
        print(f"    [{m['role']:9s}] {preview}...")

    # 6. 列 session
    print("\n[6] list sessions")
    code, sessions = http("GET", "/api/chat/sessions", token=token)
    print(f"  [OK] {len(sessions)} sessions")
    for s in sessions[:5]:
        print(f"    - {s['title'][:30]}  (id={s['id'][:8]}...)")

    # 7. 清理
    print("\n[7] delete session")
    code, _ = http("DELETE", f"/api/chat/sessions/{session_id}", token=token)
    print(f"  [OK] status={code}")

    print("\n" + "=" * 72)
    print("  Demo complete")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
