"""一键全量 e2e：按顺序跑 phase1-7 脚本。

前置：服务已启动（8000 端口），且 mock 模式（避免真实 LLM 慢/失败）。
"""

from __future__ import annotations

import io
import subprocess
import sys
import time
from pathlib import Path

if hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

SCRIPTS = [
    "e2e_phase1.py",
    "e2e_phase2.py",
    "e2e_phase3.py",
    "e2e_phase4.py",
    "e2e_phase5.py",
    "e2e_phase6.py",
    "e2e_phase7.py",
]

BACKEND_DIR = Path(__file__).parent.parent


def main() -> int:
    print("=" * 72)
    print("  Full e2e suite (phase 1-7)")
    print("=" * 72)

    overall_start = time.perf_counter()
    passed: list[str] = []
    failed: list[tuple[str, str]] = []

    for script in SCRIPTS:
        path = BACKEND_DIR / "scripts" / script
        if not path.exists():
            print(f"\n[SKIP] {script} not found")
            continue

        print(f"\n>>> Running {script}")
        t0 = time.perf_counter()
        try:
            result = subprocess.run(
                [sys.executable, str(path)],
                cwd=str(BACKEND_DIR),
                env={
                    **__import__("os").environ,
                    "LLM_MOCK": "true",
                    "PYTHONIOENCODING": "utf-8",
                },
                capture_output=True,
                text=True,
                timeout=300,
            )
        except subprocess.TimeoutExpired:
            failed.append((script, "TIMEOUT (300s)"))
            print("  [FAIL] TIMEOUT")
            continue
        except Exception as exc:
            failed.append((script, str(exc)))
            print(f"  [FAIL] {exc}")
            continue

        elapsed = int((time.perf_counter() - t0) * 1000)
        if result.returncode == 0:
            passed.append(script)
            print(f"  [OK] {elapsed} ms")
        else:
            stderr_tail = (result.stderr or "")[-500:]
            stdout_tail = (result.stdout or "")[-500:]
            failed.append((script, stderr_tail))
            print(f"  [FAIL] exit={result.returncode}")
            if stdout_tail:
                print("  --- stdout (last 500) ---")
                print(stdout_tail)
            if stderr_tail:
                print("  --- stderr (last 500) ---")
                print(stderr_tail)

    total_elapsed = int((time.perf_counter() - overall_start) * 1000)
    print("\n" + "=" * 72)
    print(f"  Suite complete in {total_elapsed} ms")
    print("=" * 72)
    print(f"  passed: {len(passed)}/{len(SCRIPTS)}")
    for s in passed:
        print(f"    ✓ {s}")
    if failed:
        print(f"  failed: {len(failed)}")
        for s, err in failed:
            print(f"    ✗ {s}: {err}")
        return 1
    print("  ALL PASSED ✓")
    return 0


if __name__ == "__main__":
    sys.exit(main())
