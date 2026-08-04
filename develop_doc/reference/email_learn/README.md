# 📧 email_learn 学习 Demo

> 本 demo 配合 PRD：先掌握邮件收发的"最基础动作"，为后面做 **email 助手**（邮件分析 / 辅助回复 / 摘要 / 待办提取）打地基。

---

## 0. 一句话总结

| 你想做的事 | 一个命令 |
|---|---|
| 列邮件 | `python demo_email.py list --limit 5` |
| 读邮件 | `python demo_email.py read --uid 12345` |
| 发一句话 | `python demo_email.py send --to foo@bar.com --subject "hi" --body "hello"` |

---

## 1. 先讲邮件的 3 个底层协议

> **不理解这 3 个协议，下面的 `.env` 配置看起来就是一堆魔法数字**。

| 协议 | 作用 | 默认端口（SSL） |
|---|---|---|
| **SMTP** | **发**邮件（出站） | 465 |
| **IMAP** | **收**邮件（远程操作服务器上的文件夹） | 993 |
| **MIME** | 邮件**内容**的格式（multipart、附件、HTML） | — |

> 💡 第三个不是网络协议，是"邮件长什么样的数据格式"。`mailparser` 主要解决的就是 MIME 解析。
> 
> 还有个老的 **POP3**（端口 110），只能把邮件"全下载到本地"，服务器端就删了——基本淘汰，新项目**只推荐 IMAP**。

---

## 2. 关于"授权码"这件事

所有现代邮箱厂商都不允许你**直接用登录密码**连 SMTP/IMAP 了，原因是为了账号安全。

| 邮箱厂商 | 怎么拿到授权码 |
|---|---|
| **QQ 邮箱** | 设置 → 账户 → "POP3/IMAP/SMTP/Exchange/CardDAV/CalDAV服务" → 开启 IMAP/SMTP → 提示"发送短信"后会得到一串 16 位字符 |
| **163 邮箱** | 设置 → POP3/SMTP/IMAP → 开启 → 客户端授权密码 |
| **Gmail** | Google 账户 → 安全性 → 两步验证 → "应用专用密码" → 生成 16 位密码 |

**`.env` 里的 `EMAIL_PASSWORD` 填的是"授权码"，不是你的登录密码。**

---

## 3. 环境准备

### 3.1 安装依赖

```bash
pip install imap-tools mailparser python-dotenv
# 或在项目根目录
uv add imap-tools mailparser python-dotenv
```

### 3.2 拷贝配置模板

```bash
cd email_learn
cp .env.example .env
# 然后编辑 .env，填你的邮箱 + 授权码
```

### 3.3 第一步测试：列邮件

```bash
python demo_email.py list --limit 5
```

预期输出：

```
✓ 已加载 .env: .../email_learn/.env
📬 正在连接 IMAP imap.qq.com:993 ...
收件箱最近 5 封邮件：

────────────────────────────────────────────────────────────────────────
[1] UID: 12345
    From   : "小红" <xiaohong@example.com>
    Subject: 你好
    Date   : 2026-07-20 10:23
────────────────────────────────────────────────────────────────────────
...
```

---

## 4. 三条命令的源码走读

### 4.1 `list` —— 收件箱巡检（imap-tools）

```python
from imap_tools import MailBox

with MailBox(host=..., port=...).login(user, password) as mbox:
    mbox.folder.set("INBOX")                            # ← 切到 INBOX
    for em in mbox.fetch(limit=N, reverse=True):         # ← fetch 没有 folder 参数
        print(em.uid, em.subject, em.from_, em.date)
```

* `MailBox` 是 **`imap-tools` 对 `imaplib.IMAP4_SSL` 的现代封装**（PEP 343 上下文管理器 API）
* **`fetch()` 不接 `folder` 参数**——必须先用 `mbox.folder.set("INBOX")` 切到对应邮箱（底层发 `SELECT INBOX`）
* `mbox.fetch(criteria, ...)` 支持 IMAP 搜索条件：
  * `criteria='ALL'` —— 全部（默认）
  * `criteria=AND(uid='12345', seen=False)` —— 用 SEARCH 命令按条件过滤
  * `uid_list=['1', '2', '3']` —— **跳过 SEARCH**，直接按 UID 取（更高效）
  * `limit=int` / `slice` —— 限制数量
  * `reverse=True` —— 按日期倒序（最近优先）
  * `mark_seen=False` —— 不标记已读
* 每个 `em` 是 `MailMessage` 对象，常用字段：
  | 字段 | 含义 |
  |---|---|
  | `em.uid` | 邮箱内唯一 ID（跨 session 不变） |
  | `em.subject` | 已解码的 Subject |
  | `em.from_` | 发件人列表 |
  | `em.to` / `em.cc` | 收件人 / 抄送 |
  | `em.date` | datetime 对象 |
  | `em.text` / `em.html` | 纯文本 / HTML 正文（**只取第一个 part**） |
  | `em.flags` | 已读 / 已加星 / 重要 |
  | `em.obj` | **`email.message.Message` 对象**（不是 bytes；要用 `bytes(em.obj)` 转） |

> 💡 **为什么 list 不直接用 `em.text`**：list 只看主题、发件人、日期这些"信封字段"，imap-tools 已经解好码，不需要再过 mailparser。

### 4.2 `read` —— 解 MIME 邮件（imap-tools + mailparser 二次解析）

```python
msgs = list(mbox.fetch(uid_list=[uid], mark_seen=False))  # ← uid_list 跳过 SEARCH
raw_bytes = bytes(msgs[0].obj)                            # ← msg.obj 是 Message 对象
parsed    = mailparser.parse_from_bytes(raw_bytes)
```

为什么读邮件要"二次解析"：
* `imap-tools` 的 `em.text` / `em.html` 只能拿到"第一个 part"
* 如果邮件**带附件 + 嵌套 MIME**，要看附件清单 + 多 part，用 `mailparser` 更稳
* `mailparser` 把整棵树拍平成属性，最关键的是**附件列表**

**MIME 是有"信封 + 信纸 + 附件"的多层结构**，比如：

```
multipart/mixed
├── multipart/alternative
│   ├── text/plain      ← 纯文本正文（要给模型看的）
│   └── text/html       ← HTML 正文（带样式）
├── image/png          ← 附件（Logo）
└── application/pdf    ← 附件（简历）
```

`mailparser` 把这棵树拍平成属性：

| 属性 | 含义 |
|---|---|
| `parsed.subject` | 主题 |
| `parsed.from_` / `.to` / `.cc` | 发件人 / 收件人 / 抄送（list） |
| `parsed.date` | 日期 |
| `parsed.text_plain` | 纯文本正文（**list**） |
| `parsed.text_html`  | HTML 正文（**list**） |
| `parsed.attachments`| 附件列表（list of dict，含 `filename / payload / mail_content_type`） |

> **未来 email 助手最关键的字段是 `parsed.text_plain[0]`**——这是喂给 LLM 的"原料"。

### 4.3 `send` —— 标准库出站（无三方依赖）

```python
import smtplib
from email.message import EmailMessage

em = EmailMessage()
em["Subject"] = subject
em["From"]    = user
em["To"]      = to
em.set_content(body)

with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=30) as s:
    s.login(user, password)
    s.send_message(em)
```

* `EmailMessage` 是 Python 3.6+ 推荐的现代邮件构造 API（比旧的 `MIMEMultipart` 友好）
* `smtplib.SMTP_SSL` 走 SSL（端口 465）；端口 587 改用 `smtplib.SMTP(...) + .starttls()`
* `with` 退出时自动 `quit()`，避免半开连接

---

## 5. 关于技术栈的诚实评估（按 PRD 的"原则"已迭代）

| 你的选择 | 我的看法 | 现状 |
|---|---|---|
| ~~**mailsuite**~~ → **imap-tools** | 上一版用的是 mailsuite（小众、文档稀薄）。已替换为 **`imap-tools`**（活跃维护、Pythonic、API 干净） | ✅ **已采用** |
| ~~**mailsuite 自带 SMTP**~~ → **标准库 smtplib** | Python 标准库的 SMTP 模块够用，**没必要为了 5 行代码引入三方依赖** | ✅ **已采用** |
| **mailparser** | 工业级 MIME 解析器，**强烈保留** | ✅ 保留 |
| **Python 命令行** | 完全够用 | 真要做产品再加 FastAPI / Web UI |

> 📌 这次替换把 3 个三方依赖（mailsuite → imap-tools + stdlib + mailparser）的格局压到 **2 个三方依赖**——更轻、更稳。

---

## 6. 进阶路线：从这个 demo 到 email 助手

| 阶段 | 你需要加什么 |
|---|---|
| **✅ 已完成** | 收发 + 解析 |
| **1. 持久化** | 把邮件存到 SQLite / Postgres，标记已读 |
| **2. 批量处理** | `mbox.fetch(limit=1000)` 后按规则过滤 |
| **3. LLM 摘要** | 把 `parsed.text_plain[0]` 喂给 MiniMax-M3，让它生成摘要 |
| **4. 待办提取** | 同上，prompt："从邮件里提取所有 TODO/截止日期" |
| **5. 辅助回复** | 把来信 + 你的历史邮件喂给 LLM，让它生成 draft，你审完再发 |
| **6. Web UI** | 接 FastAPI + 前端，做成产品形态 |

到阶段 3 时，你只需要把 `demo_email.py` 的 `cmd_read` 改成：

```python
import requests  # 复用 chat.py 的 API 调用
text = parsed.text_plain[0]
resp = requests.post("https://api.minimaxi.com/v1/chat/completions", ...)
print(resp.json()["choices"][0]["message"]["content"])
```

就能拿到一封邮件的 AI 摘要。

---

## 7. 常见坑速查

| 现象 | 原因 / 解法 |
|---|---|
| **`Unsafe Login. Please contact kefu@188.com for help`** | **网易系（163/188）2024 年起强制要求带 IMAP ID（RFC 2971）**。本 demo 已经在 `login_with_imap_id()` 里处理了 |
| **`BaseMailBox.fetch() got an unexpected keyword argument 'folder'`** | `fetch()` 没有 `folder` 参数！必须先用 `mbox.folder.set("INBOX")` 切到对应邮箱（详见 §4.1） |
| `KeyError: 'ID'` | Python 3.8 标准库 `imaplib.Commands` 没有 ID 命令定义，必须先 `imaplib.Commands["ID"] = ("NONAUTH", "AUTH", "SELECTED")` 注入 |
| `ID command error: BAD [b'Request not ending with ...']` | ID 命令格式错。必须是 `("k1" "v1" "k2" "v2")` **单一括号**包住所有键值对，不能每对单独包括号 |
| `TypeError: custom_id` | imap-tools 1.14 没有 `custom_id` 参数（要 2.x+ 才有）。手动发 ID 命令 |
| `Login fail` | 授权码错了，或没开 IMAP/SMTP 服务 |
| `Connection refused` | 端口被防火墙挡；SSL 用 465，STARTTLS 用 587 |
| `SSL: CERTIFICATE_VERIFY_FAILED` | 公司网络有 MITM 代理，加 `smtplib.SMTP_SSL(..., context=ssl.create_default_context())` |
| Gmail 报"Less secure app" | Gmail 已禁用了"低安全应用"；必须用 App Password |
| 163 邮箱发信被退回 | 自从 2023 年起 163 强制要求授权码，且单日有发送配额 |
| 邮件正文是空的 | `mailparser` 取的是 `text_plain`，HTML-only 的邮件要 fallback 到 `text_html` |
| `uid_list=[...]` 拿不到数据 | UID 错了；UID 是邮箱内唯一但会跨 session 变（UIDVALIDITY）—— 每次重新 list 取 UID 更稳 |

> ✅ `demo_email.py` 已经把以上几类典型错误集中处理，下次再遇到"Unsafe Login"等，会直接打印中文排查清单，而不是抛 traceback。

---

## 6. IMAP ID（RFC 2971）——网易系必读

> 网易 163/188 在 **2024 年下半年**起做了一次安全升级：**任何客户端连 IMAP 必须先报上"我是谁"**，否则拒绝连接（现象就是 `Unsafe Login`）。
>
> 这个"我是谁"协议叫 **IMAP ID**（RFC 2971），本质是登录后立刻发一条 `ID` 命令，把客户端名称、版本、厂商、支持邮箱告诉服务端。

### 6.1 关键难点：命令顺序

网易要求严格的"三步握手"：

```
C: <tag> LOGIN "user" "authcode"                          ← 第 1 步：登录
S: <tag> OK
C: <tag> ID ("name" "xxx" "version" "1.0.0" ...)         ← 第 2 步：必须立刻发 ID
S: <tag> OK
C: <tag> SELECT "INBOX"                                  ← 第 3 步：选邮箱
S: <tag> OK
```

> ⚠ **ID 命令格式**：**单一外层括号**包住所有键值对——不是每个键值对各自包括号。
> 
> 错误（服务端 BAD）：`ID ("name" "x") ("version" "y")`
> 正确（网易接受）：`ID ("name" "x" "version" "y")`

**坑点 1**：imap-tools 1.14 的 `MailBox.login()` **默认会自动 SELECT INBOX**（`initial_folder='INBOX'`），导致在 ID 之前就触发 `SELECT`——网易立即报 "Unsafe Login"。

**坑点 2**：Python 3.8 的标准库 `imaplib` **完全没有 ID 命令的定义**（imaplib.Commands 字典里没有 `'ID'`）。即使绕过坑点 1，调 `client._simple_command('ID', ...)` 也会抛 `KeyError: 'ID'`。

所以正确做法是：

```python
import imaplib
# 1) 注册 ID 命令定义（Python 3.8 必须手动加；3.13+ 标准库自带）
if "ID" not in imaplib.Commands:
    imaplib.Commands["ID"] = ("NONAUTH", "AUTH", "SELECTED")

mbox = MailBox(host=..., port=...)                                # 2. 实例化
mbox.login(user, password, initial_folder=None)                  # 3. 只 LOGIN，不 SELECT
mbox.client._simple_command("ID", '("name" "x" "version" "y")')  # 4. 手动发 ID（单括号）
mbox.folder.set("INBOX")                                          # 5. 现在才 SELECT
```

`demo_email.py` 把这 5 步封装到 `login_with_imap_id()` 里，你直接用就行。

> 📌 文档里曾提到的 `login(custom_id=...)` 是 `imap-tools` 新版本（2.x+）的能力。**1.14.0 没有这个参数**，所以本 demo 走"手动发 ID"路线。
> 📌 Python 3.13+ 标准库 `imaplib.IMAP4.id_()` 已自带，可以删掉 `imaplib.Commands["ID"] = ...` 那行。

### 6.2 .env 里的 4 个字段

| 字段 | 含义 | 推荐值 |
|---|---|---|
| `EMAIL_CLIENT_NAME` | 你的客户端名称 | `email_learn_demo` |
| `EMAIL_CLIENT_VERSION` | 版本号 | `1.0.0` |
| `EMAIL_CLIENT_VENDOR` | 厂商/作者 | `personal_learning` |
| `EMAIL_CLIENT_SUPPORT_EMAIL` | 联系邮箱（出问题邮箱厂商找你） | 随便一个能收到信的邮箱 |

> 💡 网易只是用 ID 追溯"哪家客户端在出问题"，不强制要求真实。QQ/Gmail 不强制要求，但加上无害。

### 6.3 还报错怎么办？

按顺序排查：

1. ✅ 确认 `EMAIL_CLIENT_*` 4 个字段都在 `.env` 里
2. ✅ 确认 `EMAIL_USER` / `EMAIL_PASSWORD` 是**授权码**（不是登录密码）
3. ✅ 确认 `cmd_list` / `cmd_read` 调用的是 `login_with_imap_id(cfg)` 而不是 `MailBox.login(...)`
4. ✅ 升级 `imap-tools`：`pip install -U imap-tools`（如果到了 2.x，可以删掉手动 ID 代码）

---

## 8. 一句话总结

> **这个 demo 就是 email 世界的"Hello World"**：3 条命令、30 行核心代码、3 个协议、3 个邮箱厂商配置——把这一关走通，后面所有的 email 助手功能都是"在这些原子上叠加业务"。