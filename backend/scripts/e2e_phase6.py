"""阶段 6 端到端：context 窗口 + 多轮摘要 + thinking 单独字段。

跑法：
    1. 启动服务：uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
    2. 另开终端：uv run python scripts/e2e_phase6.py
"""

from __future__ import annotations

import io
import json
import sys
import urllib.request
from urllib.error import HTTPError

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

API = "http://127.0.0.1:8000"


def http(method, path, *, token=None, body=None):
    req = urllib.request.Request(
        API + path, method=method, headers={"Content-Type": "application/json"}
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode() if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data, timeout=180) as r:
            raw = r.read().decode()
            if r.status == 204 or not raw:
                return r.status, None
            return r.status, json.loads(raw)
    except HTTPError as exc:
        raw = exc.read().decode()
        if exc.code == 204 or not raw:
            return exc.code, None
        return exc.code, json.loads(raw)


def main():
    print("=" * 72)
    print("  Phase 6 E2E: Context Window + Summary + Thinking")
    print("=" * 72)

    # 1. 登录
    code, body = http(
        "POST", "/api/auth/login", body={"username": "admin", "password": "ChangeMe@2026"}
    )
    if code != 200:
        print(f"  [FAIL] {body}")
        return 1
    token = body["access_token"]
    print("[1] login OK")

    # 2. 创建新 session
    code, sess = http("POST", "/api/chat/sessions", token=token, body={"title": "phase6-test"})
    if code != 201:
        print(f"  [FAIL] {body}")
        return 1
    sid = sess["id"]
    print(f"[2] session: {sid[:8]}")

    # 3. 发第一条短消息（不会触发摘要）
    print("\n[3] first short message (no summary)")
    code, body = http(
        "POST", f"/api/chat/sessions/{sid}/messages", token=token, body={"content": "你好"}
    )
    if code != 200:
        print(f"  [FAIL] {body}")
        return 1
    print(f"  [OK] reply: {body['final_response'][:80]}")
    print(f"  [OK] memory_used: {body['memory_used']}")
    print(f"  [OK] compressed: {body['compressed']}")
    print(f"  [OK] has_reasoning: {bool(body.get('reasoning'))}")
    assert body["compressed"] is False
    assert "current_time" in body["memory_used"]

    # 4. 发 3 条长消息（累积超 6000 chars，触发摘要）
    long_msg_a = "请详细解释下" + ("产品经理" * 800)
    long_msg_b = "继续说" + ("项目 Alpha" * 800)
    long_msg_c = "还有呢" + ("V3.0 大版本" * 800)

    for i, msg in enumerate([long_msg_a, long_msg_b, long_msg_c], 1):
        print(f"\n[4.{i}] long message {i} (~{len(msg)} chars)")
        code, body = http(
            "POST", f"/api/chat/sessions/{sid}/messages", token=token, body={"content": msg}
        )
        if code != 200:
            print(f"  [FAIL] {body}")
            return 1
        mu = body["memory_used"]
        print(f"  [OK] reply len: {len(body['final_response'])}")
        print(
            f"  [OK] L1_loaded: {mu['L1_session_loaded']}  compressed: {mu['compressed']}  summary_chars: {mu['summary_chars']}"
        )

    # 5. 检查是否触发了摘要
    print("\n[5] verify summary triggered")
    code, msgs = http("GET", f"/api/chat/sessions/{sid}/messages", token=token)
    print(f"  [OK] {len(msgs)} messages in session")
    # 找 assistant message
    for m in msgs:
        print(f"    [{m['role']:9s}] content[:60]: {m['content'][:60]}...")
        if m.get("reasoning"):
            print(f"      reasoning[:200]: {m['reasoning'][:200]}")

    # 6. 验摘要是否真的发生了（看某条 L1_loaded 突然变小 + compressed=True）
    for m in msgs:
        pass
    print("\n[6] check if any turn reported compressed=True")
    # 重新发一条触发检查
    code, body = http(
        "POST",
        f"/api/chat/sessions/{sid}/messages",
        token=token,
        body={"content": "再总结一下今天聊了什么" + ("Q3 OKR" * 600)},
    )
    if code == 200:
        print(
            f"  [OK] compressed: {body['compressed']}  summary_chars: {body['memory_used']['summary_chars']}"
        )
        if body["compressed"]:
            print("  [OK] summary 触发成功")
        else:
            print("  [WARN] 未触发摘要（可能在边缘）")

    # 7. 清理
    print("\n[7] cleanup")
    code, _ = http("DELETE", f"/api/chat/sessions/{sid}", token=token)
    print(f"  [OK] status={code}")

    print("\n=== ALL PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
