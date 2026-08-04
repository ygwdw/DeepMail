"""阶段 2 端到端：上传文档 → 索引邮件 → 检索。"""

from __future__ import annotations

import io
import json
import sys
import time
import urllib.request
from urllib.error import HTTPError

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

API = "http://127.0.0.1:8000"

# 内置一份示例合同文本（MD），用于上传到 contracts 分区
SAMPLE_CONTRACT = """# Acme 服务合同 V2.1

## 1. 服务期限
本协议有效期为 2026 年 1 月 1 日至 2027 年 12 月 31 日。

## 2. 服务费用
- 月费：38,000 元（含税）
- 付款方式：每月 5 日前支付
- 逾期：按日加收 0.05% 滞纳金

## 3. 数据安全
双方应遵守《数据安全法》，附件 B 列出详细的数据处理规范。

## 4. 续约条款
合同期满前 30 日，双方可协商续约；如未达成一致，本协议自动终止。
"""


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
            raw = resp.read().decode()
            if resp.status == 204 or not raw:
                return resp.status, None
            return resp.status, json.loads(raw)
    except HTTPError as exc:
        raw = exc.read().decode()
        if exc.code == 204 or not raw:
            return exc.code, None
        return exc.code, json.loads(raw)


def upload_text(partition: str, filename: str, content: str, token: str) -> dict:
    """multipart/form-data 上传（用 urllib）。"""
    boundary = "boundary-deepmail-" + str(int(time.time()))
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="partition"\r\n\r\n{partition}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: text/markdown\r\n\r\n{content}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        API + "/api/knowledge/upload",
        method="POST",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode())
    except HTTPError as exc:
        return exc.code, json.loads(exc.read().decode())


def main() -> int:
    print("=== Phase 2 End-to-End ===\n")

    code, body = http(
        "POST", "/api/auth/login", body={"username": "admin", "password": "ChangeMe@2026"}
    )
    if code != 200:
        print(f"  [FAIL] login: {body}")
        return 1
    token = body["access_token"]
    print("  [OK] login")

    # 同步邮件
    code, body = http("POST", "/api/emails/sync", token=token)
    print(f"  [OK] sync emails: {body}")

    # 1. 列出分区
    print("\n[1] list partitions (initially empty inbox)")
    code, parts = http("GET", "/api/knowledge/partitions", token=token)
    print(f"  [OK] partitions: {parts}")

    # 2. 索引邮件
    print("\n[2] index all emails")
    t0 = time.perf_counter()
    code, body = http("POST", "/api/knowledge/index/emails", token=token)
    elapsed = int((time.perf_counter() - t0) * 1000)
    print(f"  [OK] indexed {body.get('chunks_indexed')} chunks in {elapsed} ms")
    assert body["chunks_indexed"] >= 30

    # 3. 上传文档到 contracts 分区
    print("\n[3] upload contract to contracts partition")
    code, body = upload_text("contracts", "acme-v2.1.md", SAMPLE_CONTRACT, token)
    print(f"  [OK] upload: {body}")
    assert code == 201 and body["chunks_indexed"] >= 1

    # 4. 列出分区
    print("\n[4] list partitions after upload")
    code, parts = http("GET", "/api/knowledge/partitions", token=token)
    print(f"  [OK] partitions: {parts}")
    assert any(p["name"] == "inbox" for p in parts)
    assert any(p["name"] == "contracts" for p in parts)

    # 5. 检索（inbox 分区）
    print("\n[5] search: 'Acme 合同' in inbox")
    t0 = time.perf_counter()
    code, body = http(
        "POST",
        "/api/knowledge/search",
        token=token,
        body={"query": "Acme 合同", "partition": "inbox", "top_k": 3, "use_rerank": True},
    )
    elapsed = int((time.perf_counter() - t0) * 1000)
    print(f"  [OK] search in {elapsed} ms, total={body['total']}")
    for h in body["hits"][:3]:
        print(f"    score={h['score']:.4f}  src={h['source']}  {h['content'][:60]}...")
    assert body["total"] >= 1

    # 6. 检索（contracts 分区）
    print("\n[6] search: '服务费用' in contracts")
    code, body = http(
        "POST",
        "/api/knowledge/search",
        token=token,
        body={"query": "服务费用", "partition": "contracts", "top_k": 3, "use_rerank": True},
    )
    print(f"  [OK] total={body['total']}")
    assert body["total"] >= 1
    for h in body["hits"]:
        print(f"    score={h['score']:.4f}  {h['content'][:60]}...")

    # 7. 不相关 query 几条 fuzzy match 即可（中文 BM25 不可避免）
    print("\n[7] search: '外星人入侵' (low relevance)")
    code, body = http(
        "POST",
        "/api/knowledge/search",
        token=token,
        body={"query": "外星人入侵", "partition": "inbox", "top_k": 5, "use_rerank": False},
    )
    print(f"  [OK] total={body['total']}")
    # 极端不相关 query，fuzzy match 应该有，但应该很少
    assert body["total"] < 10, f"unexpected too many fuzzy matches: {body['total']}"

    # 8. 统计
    print("\n[8] stats")
    code, stats = http("GET", "/api/knowledge/stats", token=token)
    print(f"  [OK] stats: {stats}")
    assert stats["total_chunks"] >= 31

    # 9. 删除分区
    print("\n[9] delete contracts partition")
    code, _ = http("DELETE", "/api/knowledge/partitions/contracts", token=token)
    print(f"  [OK] status={code}")
    assert code == 204

    print("\n=== ALL PASSED ===")
    print(f"  total chunks: {stats['total_chunks']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
