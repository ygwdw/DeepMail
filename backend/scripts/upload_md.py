"""上传本地 MD/TXT 文件到 DeepMail 知识库。

用法：
    # 单个文件（默认 partition = 文件名）
    uv run python scripts/upload_md.py --file D:\\docs\\contract.md

    # 整个目录（默认 partition = 目录名）
    uv run python scripts/upload_md.py --dir D:\\docs

    # 指定 partition
    uv run python scripts/upload_md.py --file x.md --partition my-projects

    # 多个目录（共用一个 partition）
    uv run python scripts/upload_md.py --dir D:\\a --dir D:\\b --partition shared

    # 限制文件大小 / 字符数
    uv run python scripts/upload_md.py --file big.md --max-chars 50000

要求：
    - 服务已启动（uvicorn）
    - 当前服务 API 可达
"""

from __future__ import annotations

import argparse
import io
import sys
import urllib.request
from pathlib import Path
from urllib.error import HTTPError, URLError

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

API = "http://127.0.0.1:8000"
SUPPORTED_SUFFIXES = {".md", ".txt", ".markdown"}


def http_json(
    method: str,
    path: str,
    *,
    token: str | None = None,
    body: dict | None = None,
    api_base: str | None = None,
):
    base = api_base or API
    req = urllib.request.Request(
        base + path,
        method=method,
        headers={"Content-Type": "application/json"},
    )
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    data = body.encode() if isinstance(body, (bytes, bytearray)) else None
    if body is not None and not isinstance(body, (bytes, bytearray)):
        import json as _json

        data = _json.dumps(body).encode("utf-8")
    try:
        with urllib.request.urlopen(req, data=data) as resp:
            raw = resp.read().decode()
            if resp.status == 204 or not raw:
                return resp.status, None
            return resp.status, _json.loads(raw)
    except HTTPError as exc:
        raw = exc.read().decode()
        if exc.code == 204 or not raw:
            return exc.code, None
        return exc.code, _json.loads(raw)


def upload(
    file_path: Path,
    partition: str,
    token: str,
    *,
    max_chars: int | None = None,
    api_base: str = API,
) -> tuple[int, str]:
    """上传单个文件。返回 (status, message)。"""
    if file_path.suffix.lower() not in SUPPORTED_SUFFIXES:
        return 0, f"skip (unsupported suffix {file_path.suffix})"
    try:
        text = file_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = file_path.read_text(encoding="gbk")
        except Exception as exc:
            return 0, f"read failed: {exc}"
    if not text.strip():
        return 0, "skip (empty)"
    if max_chars:
        text = text[:max_chars]

    boundary = f"boundary-deepmail-{hash(str(file_path)) & 0xFFFFFF:x}"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="partition"\r\n\r\n{partition}\r\n'
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{file_path.name}"\r\n'
        f"Content-Type: text/markdown\r\n\r\n"
        f"{text}\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    req = urllib.request.Request(
        api_base + "/api/knowledge/upload",
        method="POST",
        data=body,
        headers={
            "Content-Type": f"multipart/form-data; boundary={boundary}",
            "Authorization": f"Bearer {token}",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            import json as _json

            return resp.status, _json.loads(resp.read().decode())
    except HTTPError as exc:
        try:
            import json as _json

            return exc.code, _json.loads(exc.read().decode())
        except Exception:
            return exc.code, exc.read().decode()


def collect_files(paths: list[Path], recursive: bool) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_dir():
            glob = p.rglob if recursive else p.glob
            for f in glob("*"):
                if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES:
                    out.append(f)
        elif p.is_file():
            if p.suffix.lower() in SUPPORTED_SUFFIXES:
                out.append(p)
        else:
            print(f"  [WARN] not found: {p}")
    return sorted(out)


def main() -> int:
    global API
    parser = argparse.ArgumentParser(description="Upload MD/TXT files to DeepMail knowledge base")
    parser.add_argument("--file", "-f", type=Path, action="append", help="单个文件（可多次）")
    parser.add_argument("--dir", "-d", type=Path, action="append", help="目录（可多次；递归）")
    parser.add_argument("--partition", "-p", default=None, help="目标分区（默认按文件/目录名）")
    parser.add_argument(
        "--recursive", "-r", action="store_true", default=True, help="递归子目录（默认）"
    )
    parser.add_argument("--no-recursive", action="store_false", dest="recursive", help="仅当前目录")
    parser.add_argument("--max-chars", type=int, default=None, help="单文件最大字符数（截断）")
    parser.add_argument("--api", default=None, help="API base URL (default: http://127.0.0.1:8000)")
    parser.add_argument("--username", default="admin", help="登录用户名 (default: admin)")
    parser.add_argument(
        "--password", default="ChangeMe@2026", help="登录密码 (default: ChangeMe@2026)"
    )
    args = parser.parse_args()

    api_base = args.api or API
    if not args.file and not args.dir:
        parser.error("must specify --file or --dir")

    paths = (args.file or []) + (args.dir or [])
    files = collect_files(paths, args.recursive)
    if not files:
        print("[FAIL] no .md/.txt/.markdown files found")
        return 1

    print("[1] login")
    code, body = http_json(
        "POST",
        "/api/auth/login",
        body={"username": args.username, "password": args.password},
        api_base=api_base,
    )
    if code != 200:
        print(f"  [FAIL] {body}")
        print("  hint: 修改脚本中的默认密码或在环境里覆盖")
        return 1
    token = body["access_token"]
    print(f"  [OK] token len={len(token)}")

    # 决定 partition
    results = []
    for fp in files:
        if args.partition:
            partition = args.partition
        elif args.file:
            # 单文件：默认用文件名（去后缀）
            partition = fp.stem
        else:
            # 目录：默认最上层目录名
            partition = (args.dir[0] if args.dir else fp.parent).name

        print(f"\n[upload] {fp.name}  ->  partition={partition}")
        status, result = upload(fp, partition, token, max_chars=args.max_chars, api_base=api_base)
        if status == 201:
            n = result.get("chunks_indexed", 0) if isinstance(result, dict) else 0
            print(f"  [OK] status={status} chunks={n}")
            results.append((fp, partition, "ok", n))
        else:
            print(f"  [FAIL] status={status} {result}")
            results.append((fp, partition, "fail", 0))

    print("\n" + "=" * 60)
    print("Summary")
    print("=" * 60)
    ok = sum(1 for *_, s, _ in results if s == "ok")
    fail = len(results) - ok
    print(f"  total: {len(results)}")
    print(f"  ok: {ok}")
    print(f"  fail: {fail}")
    print(f"  partitions used: {sorted(set(r[1] for r in results))}")
    print("\n  下一步：可选执行")
    print("    检索：curl -X POST http://127.0.0.1:8000/api/knowledge/search \\")
    print("              -H 'Authorization: Bearer <token>' \\")
    print("              -H 'Content-Type: application/json' \\")
    print(
        f'              -d \'{{"query":"你的关键词","partition":"{args.partition or "你的分区"}"}}\''
    )
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except URLError as exc:
        print(f"[FAIL] cannot reach {API}: {exc}")
        print("  hint: 确认 uvicorn 已启动，且端口正确")
        sys.exit(1)
