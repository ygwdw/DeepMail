"""阶段 7 端到端：重点事件看板 + 用户可设 token 预算。"""

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
        with urllib.request.urlopen(req, data=data, timeout=60) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode() or "{}")


def main() -> int:
    print("=" * 72)
    print("  Phase 7 E2E: Dashboard + token_budget")
    print("=" * 72)

    # 1. login
    code, body = http(
        "POST",
        "/api/auth/login",
        body={"username": "admin", "password": "ChangeMe@2026"},
    )
    if code != 200:
        print(f"  [FAIL] login: {body}")
        return 1
    token = body["access_token"]
    print(f"  [OK] login")

    # 2. check default token_budget
    code, body = http("GET", "/api/me", token=token)
    assert body["token_budget"] == 8000, body
    print(f"  [OK] default token_budget = {body['token_budget']}")

    # 3. update token_budget
    code, body = http("PATCH", "/api/me", token=token, body={"token_budget": 16000})
    assert code == 200
    assert body["token_budget"] == 16000
    print(f"  [OK] PATCH token_budget -> {body['token_budget']}")

    # 4. restore
    code, body = http("PATCH", "/api/me", token=token, body={"token_budget": 8000})
    assert body["token_budget"] == 8000
    print(f"  [OK] restore token_budget -> {body['token_budget']}")

    # 5. create events
    for i in range(3):
        code, body = http(
            "POST",
            "/api/memory/events",
            token=token,
            body={"title": f"事件 {i+1}", "summary": f"第 {i+1} 个事件"},
        )
        assert code == 201
    print(f"  [OK] created 3 events")

    # 6. dashboard
    code, body = http("GET", "/api/dashboard/events?days=30", token=token)
    assert code == 200
    assert body["summary"]["total_events"] >= 3
    print(f"  [OK] dashboard events: {body['summary']['total_events']}")
    print(f"  by_week: {list(body['events_by_week'].keys())}")

    # 7. cleanup
    code, body = http("GET", "/api/memory/events", token=token)
    for ev in body:
        http("DELETE", f"/api/memory/events/{ev['id']}", token=token)
    print(f"  [OK] cleaned up events")

    print("\n=== ALL PASSED ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
