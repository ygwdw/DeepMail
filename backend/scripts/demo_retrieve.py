"""检索 + 重排 体验脚本

跑法：
    1. 启动服务：uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
    2. 另开终端：uv run python scripts/demo_retrieve.py

会做：
    1. 登录 admin
    2. 索引当前用户的 30 封 mock 邮件
    3. 跑 3 个查询，每个查询展示：
       - 向量召回（top 5）
       - BM25 召回（top 5）
       - RRF 融合后（top 5）
       - Reranker 排序（top 5，或失败降级）
    4. 打印向量库统计
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
            raw = resp.read().decode()
            if resp.status == 204 or not raw:
                return resp.status, None
            return resp.status, json.loads(raw)
    except HTTPError as exc:
        raw = exc.read().decode()
        if exc.code == 204 or not raw:
            return exc.code, None
        return exc.code, json.loads(raw)


def search_explain(
    query: str,
    partition: str,
    token: str,
    *,
    top_k: int = 5,
    use_rerank: bool = True,
) -> None:
    print(f"\n  QUERY: {query!r} (partition={partition}, top_k={top_k}, rerank={use_rerank})")
    print(f"  {'-' * 70}")
    code, body = http(
        "POST",
        "/api/knowledge/search",
        token=token,
        body={
            "query": query,
            "partition": partition,
            "top_k": top_k,
            "use_rerank": use_rerank,
        },
    )
    if code != 200:
        print(f"  [FAIL] status={code} body={body}")
        return
    hits = body["hits"]
    print(f"  [OK] {len(hits)} hits")
    for i, h in enumerate(hits, 1):
        score = h["score"]
        meta = h.get("metadata", {})
        sender = meta.get("sender", "?")
        subject = meta.get("subject", "(no subject)")
        print(f"    {i}. score={score:.4f}  {sender[:30]}")
        print(f"       sub: {subject[:60]}")
        print(f"       preview: {h['content'][:55].strip()}...")


def main() -> int:
    print("=" * 72)
    print("  Retrieve + Rerank Demo")
    print("=" * 72)

    # 1. 登录
    print("\n[1] login")
    code, body = http(
        "POST",
        "/api/auth/login",
        body={"username": "admin", "password": "ChangeMe@2026"},
    )
    if code != 200:
        print(f"  [FAIL] {body}")
        return 1
    token = body["access_token"]
    print(f"  [OK] token len={len(token)}")

    # 2. 同步邮件（首次确保 30 封已入 DB）
    print("\n[2] sync emails (idempotent)")
    code, body = http("POST", "/api/emails/sync", token=token)
    print(f"  [OK] {body}")

    # 3. 索引邮件（先去重再重建，避免重复）
    print("\n[3] clear inbox partition + reindex")
    http("DELETE", "/api/knowledge/partitions/inbox", token=token)
    print("  [OK] inbox cleared")
    print("  [...reindexing 30 emails, ~17s...]")
    t0 = time.perf_counter()
    code, body = http("POST", "/api/knowledge/index/emails", token=token)
    print(f"  [OK] {body} in {int((time.perf_counter() - t0) * 1000)} ms")

    # 4. 统计
    print("\n[4] stats")
    code, stats = http("GET", "/api/knowledge/stats", token=token)
    print(f"  [OK] {stats}")

    # 5. 三个查询 demo
    print("\n[5] demo queries (vector + BM25 + RRF + Rerank)")
    search_explain("Acme 合同 服务费", "inbox", token, top_k=5, use_rerank=True)
    search_explain("自动驾驶", "inbox", token, top_k=3, use_rerank=True)
    # search_explain("客户反馈 暗黑模式", "inbox", token, top_k=3, use_rerank=True)

    # 6. 对比：相同 query 不开 rerank
    print("\n[6] same query WITHOUT rerank (对比 RRF 顺序 vs Rerank 顺序)")
    search_explain("Acme 合同 服务费", "inbox", token, top_k=5, use_rerank=False)

    print("\n" + "=" * 72)
    print("  Demo complete")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    sys.exit(main())
