"""
email_learn / demo_email.py
===========================

最小可跑的命令行邮件 demo，覆盖三件事：
    1. 列邮件     python demo_email.py list  --limit 5
    2. 读邮件     python demo_email.py read  --uid 12345
    3. 发邮件     python demo_email.py send  --to foo@bar.com --subject "hi" --body "hello"

技术栈（v2，2026 推荐组合）：
    - imap-tools : 现代化 IMAP 客户端（imaplib 的 Pythonic 封装，活跃维护）
    - 标准库 smtplib + email.message.EmailMessage : 出站 SMTP（无三方依赖）
    - mailparser : MIME 解析（拿到正文、发件人、附件等结构化字段）
                  用于二次解析 imap-tools 的原始字节，拿到 attachments 等细节

依赖安装：
    pip install imap-tools mailparser python-dotenv
"""

from __future__ import annotations

import argparse
import os
import smtplib
import sys
from email.message import EmailMessage
from pathlib import Path
from typing import Any

import mailparser
import imaplib  # 用来给 Commands 字典补 ID 命令定义
from dotenv import load_dotenv
from imap_tools import MailBox  # AND 暂未用到；fetch(uid_list=...) 更高效
from imap_tools.errors import MailboxLoginError, MailboxFolderSelectError


# ─────────────────────────────────────────────────────────────────────────────
# 注册 IMAP ID 命令（RFC 2971）到 imaplib.Commands
#
# 关键坑：Python 3.8 标准库 imaplib 的 Commands 字典里 *没有* ID 命令定义。
# imaplib.IMAP4._command() 第一行是：
#     if self.state not in Commands[name]:
# 直接做字典查找，不存在就抛 KeyError: 'ID'（不是 Imap4Error）。
#
# 因此我们必须在调用 _simple_command('ID', ...) 之前注册 ID。
# ID 命令（RFC 2971）允许在 NONAUTH / AUTH / SELECTED 任意状态下发。
# ─────────────────────────────────────────────────────────────────────────────
if "ID" not in imaplib.Commands:
    imaplib.Commands["ID"] = ("NONAUTH", "AUTH", "SELECTED")

# ─────────────────────────────────────────────────────────────────────────────
# 配置加载：优先用 email_learn/.env，其次仓库其它位置
# ─────────────────────────────────────────────────────────────────────────────
def load_config() -> dict[str, Any]:
    here = Path(__file__).resolve().parent
    for p in (
        here / ".env",
        here.parent / "agent_project_learn" / ".env",
        here.parent / ".env",
    ):
        if p.exists():
            load_dotenv(p)
            print(f"✓ 已加载 .env: {p}")
            break
    else:
        print("⚠ 未找到 .env，请先按 .env.example 填一份")

    return {
        "imap_host": os.getenv("EMAIL_IMAP_HOST", "imap.qq.com"),
        "imap_port": int(os.getenv("EMAIL_IMAP_PORT", "993")),
        "smtp_host": os.getenv("EMAIL_SMTP_HOST", "smtp.qq.com"),
        "smtp_port": int(os.getenv("EMAIL_SMTP_PORT", "465")),
        "user":     os.getenv("EMAIL_USER", ""),
        "password": os.getenv("EMAIL_PASSWORD", ""),  # 授权码，不是登录密码

        # IMAP ID（RFC 2971）—— 网易（163/188）2024 起强制要求
        # 在 IMAP 握手时告诉服务端"我是谁、什么版本、联系邮箱"
        # 不带就报 "Unsafe Login"
        "imap_id_name":         os.getenv("EMAIL_CLIENT_NAME",         "email_learn_demo"),
        "imap_id_version":      os.getenv("EMAIL_CLIENT_VERSION",      "1.0.0"),
        "imap_id_vendor":       os.getenv("EMAIL_CLIENT_VENDOR",       "personal_learning"),
        "imap_id_support_email": os.getenv("EMAIL_CLIENT_SUPPORT_EMAIL", os.getenv("EMAIL_USER", "")),
    }


def build_imap_id(cfg: dict[str, Any]) -> dict[str, str]:
    """构造 IMAP ID 字典（RFC 2971）"""
    return {
        "name":          cfg["imap_id_name"],
        "version":       cfg["imap_id_version"],
        "vendor":        cfg["imap_id_vendor"],
        "support-email": cfg["imap_id_support_email"],
    }


# ─────────────────────────────────────────────────────────────────────────────
# IMAP ID 命令的"手动实现"
#
# 背景：
#   - 网易（163/188）2024 年下半年起强制要求客户端在 IMAP 握手后、SELECT INBOX 之前
#     发一条 ID 命令（RFC 2971），告诉服务端"我是谁"。否则 SELECT 时报 Unsafe Login。
#   - imap-tools 1.14.0 的 login() 没有 custom_id 参数
#   - Python 3.8 标准库 imaplib 也没有 id_() 方法（3.13 才有）
#   - 所以我们必须手写 _simple_command('ID', '("k" "v") (...)')
#
# ID 命令格式（RFC 2971）：
#     C: a001 ID ("name" "myname") ("version" "1.0.0") ("vendor" "myclient")
#     S: a001 OK ID completed
# ─────────────────────────────────────────────────────────────────────────────
def _send_imap_id(mbox: MailBox, imap_id: dict[str, str]) -> None:
    """在 LOGIN 之后、SELECT 之前，发一条 ID 命令

    ID 命令参数格式（RFC 2971）：
        ID ("key1" "value1" "key2" "value2" ...)
    即**单一外层括号**包住所有键值对，不要每对单独括号。

    错误格式：ID ("name" "x") ("version" "y")        ← 服务端报 BAD
    正确格式：ID ("name" "x" "version" "y")          ← 网易接受
    """
    parts = []
    for k, v in imap_id.items():
        # 转义 value 中的反斜杠和双引号
        escaped = str(v).replace("\\", "\\\\").replace('"', '\\"')
        parts.append(f'"{k}" "{escaped}"')
    # 整个 dict 装在**一对**括号里
    id_args = "(" + " ".join(parts) + ")"

    # 用 imaplib 的内部 _simple_command 直接发原生命令
    typ, data = mbox.client._simple_command("ID", id_args)
    if typ != "OK":
        raise RuntimeError(
            f"IMAP ID 命令被服务端拒绝: {typ} {data!r}\n"
            f"   服务端要求在 SELECT 之前先发 ID 命令；网易等邮箱已强制要求。"
        )


def login_with_imap_id(
    cfg: dict[str, Any],
) -> MailBox:
    """
    imap-tools 的 login() 会在 LOGIN 后立即 SELECT INBOX（initial_folder='INBOX'），
    但网易要求在 SELECT 前先发 ID 命令——顺序错了就 Unsafe Login。

    因此正确流程是：
        1) login(initial_folder=None)   → 只 LOGIN，不 SELECT
        2) 手动发 ID 命令
        3) 手动 folder.set('INBOX')
    """
    mbox = MailBox(host=cfg["imap_host"], port=cfg["imap_port"])
    try:
        mbox.login(cfg["user"], cfg["password"], initial_folder=None)
    except MailboxLoginError as e:
        # 关掉 mbox，避免资源泄漏
        try: mbox.logout()
        except Exception: pass
        raise
    # 发 ID
    _send_imap_id(mbox, build_imap_id(cfg))
    # 现在再 SELECT INBOX
    mbox.folder.set("INBOX")
    return mbox


# ─────────────────────────────────────────────────────────────────────────────
# 网易系（163 / 188）的"Unsafe Login"是出了名的常见错误
# 集中处理：捕获 + 给出明确的排查指引
# ─────────────────────────────────────────────────────────────────────────────
def diagnose_imap_error(err: Exception) -> str:
    """根据错误信息给出中文排查提示"""
    msg = str(err).lower()
    if "unsafe login" in msg:
        return (
            "🔒 网易系（163/188）报 'Unsafe Login'。常见原因：\n"
            "   1) 你填的是登录密码，不是『授权码』。\n"
            "      → 网页登录邮箱 → 设置 → POP3/SMTP/IMAP → 开启服务 → 生成授权码\n"
            "   2) 这个邮箱从来没在你这台机器 / 这个 IP 用过。\n"
            "      → 先去 https://www.188.com 或 https://email.163.com 网页登一次\n"
            "   3) 网易『安全登录保护』白名单挡了。\n"
            "      → 设置 → 安全设置 → 登录保护 → 关闭 / 加白当前 IP"
        )
    if "authentication failed" in msg or "login fail" in msg:
        return (
            "🔑 认证失败：检查 EMAIL_USER / EMAIL_PASSWORD（应是授权码）。\n"
            "   Gmail 用户注意：必须开两步验证 + 用 16 位 App Password。"
        )
    if "connection" in msg or "timed out" in msg:
        return (
            "🌐 网络/端口问题：检查 EMAIL_IMAP_HOST / EMAIL_IMAP_PORT 是否对得上邮箱厂商；"
            "公司网络可能拦了 993 端口。"
        )
    return f"❌ IMAP 异常: {type(err).__name__}: {err}"


# ─────────────────────────────────────────────────────────────────────────────
# 1. 列出最近 N 封邮件（imap-tools）
#
# imap-tools 的核心是 MailBox 上下文管理器：
#   - .login(user, password)  : 登录
#   - .fetch(criteria, mark_seen=False)  : 拉邮件，返回 EmailMessage 迭代器
#   - EmailMessage 自带 uid / subject / from_ / date / text / html / attachments / obj
# ─────────────────────────────────────────────────────────────────────────────
def cmd_list(cfg: dict[str, Any], limit: int) -> int:
    if not cfg["user"] or not cfg["password"]:
        print("❌ 缺少 EMAIL_USER / EMAIL_PASSWORD")
        return 1

    print(f"📬 正在连接 IMAP {cfg['imap_host']}:{cfg['imap_port']} ...")
    try:
        mbox = login_with_imap_id(cfg)   # 已经做了 LOGIN + ID + SELECT INBOX
        with mbox:
            # fetch() 不接受 folder 参数——已经在 login_with_imap_id 里 SELECT 了 INBOX
            # limit=int / slice; reverse=True 拿到"最新 N 封"
            emails = list(mbox.fetch(limit=limit, reverse=True, mark_seen=False))
    except (MailboxLoginError, MailboxFolderSelectError) as e:
        print(diagnose_imap_error(e))
        return 1
    except Exception as e:
        print(f"❌ IMAP 连接异常: {type(e).__name__}: {e}")
        return 1

    if not emails:
        print("（收件箱为空）")
        return 0

    print(f"\n收件箱最近 {len(emails)} 封邮件：\n")
    print("─" * 72)
    for i, em in enumerate(emails, 1):
        print(f"[{i}] UID     : {em.uid}")
        print(f"    From   : {', '.join(str(a) for a in em.from_)}")
        print(f"    Subject: {em.subject or '(无主题)'}")
        print(f"    Date   : {em.date}")
        print("─" * 72)
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# 2. 读取某封邮件详情（imap-tools + mailparser 二次解析）
#
# imap-tools 已经解了 text/html，但 attachments 的"原始字节+文件名"细节用 mailparser 更顺手。
# 流程：
#   - imap-tools 拉回原始字节 (msg.obj)
#   - mailparser 把整封 MIME 邮件拍平成结构化字段
# ─────────────────────────────────────────────────────────────────────────────
def cmd_read(cfg: dict[str, Any], uid: str) -> int:
    if not cfg["user"] or not cfg["password"]:
        print("❌ 缺少 EMAIL_USER / EMAIL_PASSWORD")
        return 1

    print(f"📨 正在拉取 UID={uid} ...")
    try:
        mbox = login_with_imap_id(cfg)
        with mbox:
            # uid_list= 比 AND(uid=) 更高效——它跳过 SEARCH 命令
            msgs = list(mbox.fetch(uid_list=[uid], mark_seen=False))
    except (MailboxLoginError, MailboxFolderSelectError) as e:
        print(diagnose_imap_error(e))
        return 1
    except Exception as e:
        print(f"❌ IMAP 连接异常: {type(e).__name__}: {e}")
        return 1

    if not msgs:
        print("❌ 没找到对应 UID 的邮件")
        return 1
    msg = msgs[0]
    # msg.obj 是 email.message.Message 对象；mailparser 要 bytes
    raw_bytes = bytes(msg.obj)

    # ── mailparser 把 MIME 拆成结构化字段 ────────────────────────────────
    parsed = mailparser.parse_from_bytes(raw_bytes)
    print("\n" + "═" * 60)
    print(f"  From    : {parsed.from_}")
    print(f"  To      : {parsed.to}")
    print(f"  Cc      : {parsed.cc}")
    print(f"  Subject : {parsed.subject}")
    print(f"  Date    : {parsed.date}")
    print(f"  Attachs : {len(parsed.attachments)} 个")
    print("═" * 60)

    # 正文：优先 text/plain，没有就退回 text/html
    if parsed.text_plain:
        print("\n--- 文本正文 (text/plain) ---\n")
        print(parsed.text_plain[0].strip())
    elif parsed.text_html:
        print("\n--- HTML 正文片段 (前 800 字) ---\n")
        print(parsed.text_html[0][:800].strip())
    else:
        print("\n（无可显示的正文）")

    if parsed.attachments:
        print("\n--- 附件列表 ---")
        for att in parsed.attachments:
            print(f"  • {att['filename']}  ({att['mail_content_type']}, "
                  f"{len(att['payload'])} bytes)")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# 3. 发送一封纯文本邮件（标准库 smtplib + email.message.EmailMessage）
#
# 为什么要 EmailMessage 而不是 MIMEMultipart：
#   - EmailMessage 是 Python 3.6+ 推荐的现代 API
#   - 配合 set_content() 自动处理字符集/编码
# ─────────────────────────────────────────────────────────────────────────────
def cmd_send(cfg: dict[str, Any], to: str, subject: str, body: str) -> int:
    if not cfg["user"] or not cfg["password"]:
        print("❌ 缺少 EMAIL_USER / EMAIL_PASSWORD")
        return 1

    # 1) 构造邮件
    em = EmailMessage()
    em["Subject"] = subject
    em["From"]    = cfg["user"]
    em["To"]      = to
    em.set_content(body)

    # 2) 走 SMTP_SSL（端口 465）；如果是 STARTTLS 用 smtplib.SMTP(port=587) + .starttls()
    print(f"✉️  正在通过 SMTP {cfg['smtp_host']}:{cfg['smtp_port']} 发送 ...")
    try:
        with smtplib.SMTP_SSL(cfg["smtp_host"], cfg["smtp_port"], timeout=30) as s:
            s.login(cfg["user"], cfg["password"])
            s.send_message(em)
    except smtplib.SMTPAuthenticationError as e:
        print(diagnose_imap_error(e))
        return 1
    except Exception as e:
        print(f"❌ 发送失败: {type(e).__name__}: {e}")
        print("   常见原因：1) 授权码不对  2) 端口被防火墙挡  3) 邮箱没开 SMTP/IMAP 服务")
        return 1

    print(f"✅ 已发送给 {to}")
    print(f"   主题: {subject}")
    print(f"   正文: {body}")
    return 0


# ─────────────────────────────────────────────────────────────────────────────
# CLI 入口
# ─────────────────────────────────────────────────────────────────────────────
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="demo_email",
        description="imap-tools + smtplib + mailparser 的最小邮件 CLI（学习用）",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_list = sub.add_parser("list", help="列出最近 N 封邮件")
    p_list.add_argument("--limit", type=int, default=10)

    p_read = sub.add_parser("read", help="读某封邮件详情（按 UID）")
    p_read.add_argument("--uid", required=True)

    p_send = sub.add_parser("send", help="发一封纯文本邮件")
    p_send.add_argument("--to",      required=True, help="收件人邮箱")
    p_send.add_argument("--subject", required=True, help="主题")
    p_send.add_argument("--body",    required=True, help="正文")

    return p


def main() -> int:
    args = build_parser().parse_args()
    cfg = load_config()

    if args.cmd == "list":
        return cmd_list(cfg, args.limit)
    if args.cmd == "read":
        return cmd_read(cfg, args.uid)
    if args.cmd == "send":
        return cmd_send(cfg, args.to, args.subject, args.body)
    return 1


if __name__ == "__main__":
    sys.exit(main())