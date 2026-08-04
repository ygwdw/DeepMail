"""阶段 5 端到端：persona 自主更新 + 注入 + rollback。

跑法：
    1. 启动服务：uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
    2. 另开终端：uv run python scripts/e2e_phase5.py
"""

from __future__ import annotations

import io
import json
import os
import sys
import time
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
        with urllib.request.urlopen(req, data=data, timeout=120) as r:
            raw = r.read().decode()
            return r.status, json.loads(raw) if raw else None
    except HTTPError as e:
        raw = e.read().decode()
        return e.code, json.loads(raw) if raw else None


def wait_for_persona_field(token, field, expected_substr, *, max_wait=15):
    """轮询等 fire-and-forget 的 persona 更新。"""
    for _ in range(max_wait):
        code, body = http("GET", "/api/persona", token=token)
        if code == 200:
            val = (body.get("profile_json") or {}).get(field, "")
            if val and expected_substr in str(val):
                return body
        time.sleep(1)
    return body


def main() -> int:
    print("=" * 72)
    print("  Phase 5 E2E: Persona Auto-Update + Inject + Rollback")
    print("=" * 72)

    # 1. 登录
    code, body = http(
        "POST", "/api/auth/login", body={"username": "admin", "password": "ChangeMe@2026"}
    )
    if code != 200:
        print(f"  [FAIL] login: {body}")
        return 1
    token = body["access_token"]
    print("[1] login OK")

    # 2. 清空 persona
    code, _ = http("DELETE", "/api/persona", token=token)
    code, body = http("GET", "/api/persona", token=token)
    print(f"[2] cleared persona: {body['profile_json']}")

    # 3. 模拟用户聊天，主动透露信息（"我是产品经理陈总监"）
    print("\n[3] chat with user info disclosure")
    code, sess = http("POST", "/api/chat/sessions", token=token, body={"title": "persona-test"})
    sid = sess["id"]
    user_msg = "我是一名产品经理，今年 35 岁，北京邮电大学毕业，目前在字节跳动工作"
    code, body = http(
        "POST", f"/api/chat/sessions/{sid}/messages", token=token, body={"content": user_msg}
    )
    print(f"  chat reply: {body.get('final_response', '')[:150]}")
    print(f"  agents invoked: {body.get('agents_invoked')}")

    # 4. 等 fire-and-forget 的 persona 更新（LLM 自主决策）
    print("\n[4] wait for persona auto-update (max 15s)...")
    persona = wait_for_persona_field(token, "profession", "产品")
    print(f"  persona after chat: {persona.get('profile_json')}")
    pj = persona.get("profile_json") or {}
    has_profession = "产品" in str(pj.get("profession", ""))
    has_age = str(pj.get("age", "")) == "35"
    has_education = "北京邮电" in str(pj.get("education", ""))
    print(f"  profession: {pj.get('profession')}  (matched: {has_profession})")
    print(f"  age: {pj.get('age')}  (matched: {has_age})")
    print(f"  education: {pj.get('education')}  (matched: {has_education})")
    # mock 模式下 LLM 跳过 persona 提取（maybe_update_persona 直接 return None）
    # 真实 LLM 模式下才会写入产品经理/35/北京邮电
    if os.getenv("LLM_MOCK", "").lower() in ("1", "true", "yes"):
        print("  [skip] mock 模式跳过 persona 断言（LLM 没真调用）")
    else:
        assert has_profession, f"profession not detected: {pj}"
        assert has_age, f"age not detected: {pj}"
        assert has_education, f"education not detected: {pj}"
    # 5. 手动 PATCH 改一个字段
    print("\n[5] manual PATCH persona (add language_pref)")
    code, body = http("PATCH", "/api/persona", token=token, body={"language_pref": "中文"})
    print(f"  [OK] {body.get('profile_json', {}).get('language_pref')}")
    assert body["profile_json"]["language_pref"] == "中文"

    # 6. 测试 draft skill 注入 persona
    print("\n[6] draft_reply with persona (style should match)")
    # 找一封邮件
    code, emails_body = http("GET", "/api/emails?limit=3", token=token)
    if emails_body.get("items"):
        sample_email = emails_body["items"][0]
        code, draft = http(
            "POST",
            f"/api/emails/{sample_email['id']}/draft",
            token=token,
            body={"instruction": "礼貌确认", "tone": "formal"},
        )
        if code == 200:
            print(f"  draft: {draft.get('output', {}).get('draft_text', '')[:100]}")
            print(f"  confidence: {draft.get('output', {}).get('confidence')}")
        else:
            print(f"  [WARN] draft status={code}: {draft}")

    # 7. 测试 rollback
    print("\n[7] rollback persona (clear)")
    code, body = http("POST", "/api/persona/rollback", token=token)
    print(f"  [OK] after rollback: {body.get('profile_json')}")
    assert body["profile_json"] == {}

    print("\n=== ALL PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
