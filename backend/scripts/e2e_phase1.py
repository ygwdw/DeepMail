"""阶段 1 端到端验证：批量对 30 封 mock 邮件跑 process + 校验。

用法：
    # 1. 启动服务
    cd backend && uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

    # 2. 跑此脚本
    uv run python scripts/e2e_phase1.py
"""

from __future__ import annotations

import io
import json
import sys
import time
import urllib.request
from urllib.error import HTTPError

# Windows GBK 编码：强制 stdout 用 UTF-8
if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

API = "http://127.0.0.1:8000"


def http(method: str, path: str, *, token: str | None = None, body: dict | None = None):
    req = urllib.request.Request(
        API + path,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        with urllib.request.urlopen(req, data=data) as resp:
            return resp.status, json.loads(resp.read().decode())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def main() -> int:
    print("=== Phase 1 End-to-End ===\n")

    # 1. 登录
    print("[1] login admin ...")
    code, body = http(
        "POST", "/api/auth/login", body={"username": "admin", "password": "ChangeMe@2026"}
    )
    if code != 200:
        print(f"  [FAIL] login: {code} {body}")
        return 1
    token = body["access_token"]
    print(f"  [OK] token ({len(token)} chars)")

    # 2. 同步邮件
    print("\n[2] sync mock emails ...")
    code, body = http("POST", "/api/emails/sync", token=token)
    print(f"  [OK] sync: {body}")

    # 3. 列出所有邮件
    print("\n[3] list emails ...")
    code, body = http("GET", "/api/emails?limit=100", token=token)
    if code != 200:
        print(f"  [FAIL] list: {code} {body}")
        return 1
    emails = body["items"]
    total = body["total"]
    print(f"  [OK] total: {total}")
    assert total == 30, f"expected 30, got {total}"

    # 4. 检查默认分类
    print("\n[4] check default categories ...")
    code, cats = http("GET", "/api/categories", token=token)
    assert code == 200
    cat_names = [c["name"] for c in cats]
    spam_cats = [c["name"] for c in cats if c["is_spam_category"]]
    print(f"  [OK] categories: {cat_names}")
    print(f"  [OK] spam categories: {spam_cats}")
    assert len(cats) == 4
    assert set(spam_cats) == {"广告推销", "有害信息"}

    # 5. 批量跑 process
    print(f"\n[5] run process for {len(emails)} emails ...")
    t0 = time.perf_counter()
    success = 0
    failures: list[str] = []
    total_tokens = 0
    total_calls = 0
    folder_stats: dict[str, int] = {"inbox": 0, "spam": 0, "sent": 0, "trash": 0}

    for em in emails:
        code, body = http("POST", f"/api/emails/{em['id']}/process", token=token)
        if code == 200:
            success += 1
            total_calls += body["summary"]["total_llm_calls"]
            total_tokens += body["summary"]["total_tokens"]
        else:
            failures.append(f"{em['id']}: {code} {body}")

    elapsed_ms = int((time.perf_counter() - t0) * 1000)
    print(f"  [OK] success: {success}/{len(emails)} in {elapsed_ms} ms")
    print(f"  [OK] total LLM calls: {total_calls}")
    print(f"  [OK] total tokens: {total_tokens}")
    if failures:
        print(f"  [FAIL] failures: {len(failures)}")
        for f in failures[:3]:
            print(f"    - {f}")
        return 1

    # 6. 校验 folder 计算
    print("\n[6] verify folder ...")
    code, all_emails = http("GET", "/api/emails?folder=all&limit=100", token=token)
    folder_stats = {"inbox": 0, "spam": 0, "sent": 0, "trash": 0}
    for em in all_emails["items"]:
        f = em.get("folder", "?")
        folder_stats[f] = folder_stats.get(f, 0) + 1
    print(f"  [OK] folder stats: {folder_stats}")

    # 7. 校验 spam folder 过滤
    print("\n[7] verify spam filter ...")
    code, spam_emails = http("GET", "/api/emails?folder=spam&limit=100", token=token)
    print(f"  [OK] /api/emails?folder=spam: total={spam_emails['total']}")
    assert spam_emails["total"] == folder_stats["spam"], "spam filter mismatch"

    # 8. 校验 todos 落库
    print("\n[8] verify todos ...")
    code, todos_body = http("GET", "/api/todos?limit=200", token=token)
    print(f"  [OK] total todos: {todos_body['total']}")

    # 9. usage_logs 写入校验（间接：分类 API 还能调用即服务正常）
    print("\n[9] verify service alive ...")
    code, _ = http("GET", "/api/categories", token=token)
    assert code == 200

    # 10. 起草
    print("\n[10] draft endpoint ...")
    sample = emails[0]
    code, body = http(
        "POST",
        f"/api/emails/{sample['id']}/draft",
        token=token,
        body={"instruction": "礼貌回复并提议下周再约", "tone": "formal"},
    )
    print(f"  [OK] draft status={code}, error={body.get('error')}")
    assert code == 200 and body.get("output") is not None, body

    # 11. 打标两步
    print("\n[11] tag recommend + confirm ...")
    code, rec = http("POST", f"/api/emails/{sample['id']}/tag/recommend", token=token)
    print(f"  [OK] recommend status={code}, keys={list(rec.get('output', {}).keys())}")
    assert code == 200 and rec.get("error") is None
    code, conf = http(
        "POST",
        f"/api/emails/{sample['id']}/labels",
        token=token,
        body={"labels": ["work", "feedback"]},
    )
    print(f"  [OK] confirm status={code}, labels={conf.get('labels')}")
    assert code == 200

    print("\n=== ALL PASSED ===")
    print(f"  emails processed: {success}/{len(emails)}")
    print(f"  LLM calls total: {total_calls}")
    print(f"  tokens total: {total_tokens}")
    print(f"  folder stats: {folder_stats}")
    print(f"  todos saved: {todos_body['total']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
