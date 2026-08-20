# DeepMail

> **AI Agent 邮箱助手** —— 多 Agent 协作、四层记忆、人格画像、6 层上下文（按文档）

[![Python](https://img.shields.io/badge/Python-3.12+-blue.svg)]()
[![FastAPI](https://img.shields.io/badge/FastAPI-0.115+-009688.svg)]()
[![LangGraph](https://img.shields.io/badge/LangGraph-0.2+-orange.svg)]()
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-16+-336791.svg)]()
[![pgvector](https://img.shields.io/badge/pgvector-latest-yellow.svg)]()

## 特性

- 🤖 **5 个专业 sub-agent** 自动派发：email / todo / draft / rag / tidy
- 🧠 **4 层记忆体系**：工作 / 短期会话 / 中期话题 / 长期语义 + **衰减**（λ=0.01）
- 👤 **人格画像**（OpenClaw 模式）：LLM 自主决定何时更新，10 字段（name/age/education/profession/personality/communication_style/language_pref/signature/frequent_topics/sample_phrases）
- 🔍 **RAG 知识库**：混合检索（向量 + BM25 + RRF） + Reranker
- 🕐 **当前时间上下文**："2026-08-04 10:30 星期二" 注入所有 skill
- 💬 **多轮摘要**（token 预算触发）+ thinking 单独字段
- 📊 **重点事件看板**（按周/按状态聚合）
- 🔭 **可观测性**：structlog + langsmith trace

## 架构图

```
用户消息
    ↓
┌────────────────────┐
│   FastAPI Server   │
└─────────┬──────────┘
          ↓
┌──────────────────────────────────┐
│   LangGraph 主图                  │
│   ┌─────────────────────────────┐│
│   │  Supervisor (LLM 路由)      ││ ← L1+L2+L4 记忆注入
│   └────────────┬────────────────┘│
│                ↓                 │
│   ┌────────┬────┬────┬────┬────┐ │
│   │ email  │todo│draft│ rag│tidy││ ← 5 ReAct sub-agents (并行)
│   └────┬───┴────┴────┴────┴────┘ │
│        ↓                          │
│   ┌─────────────────────────────┐│
│   │  Aggregator (汇总)           ││
│   └─────────────────────────────┘│
└──────────────────────────────────┘
          ↓
   memory + knowledge + persona
```

## 快速开始

### 1. 前置要求

- Python 3.12+
- Docker Desktop（运行 PostgreSQL + pgvector）
- uv（Python 包管理）
- 可选：真实的 LLM API key（MiniMax-M3 / OpenAI / 其他 OpenAI 兼容）

### 2. 安装

```bash
# 克隆
git clone <repo> deepmail
cd deepmail

# 装依赖
uv sync --extra dev
```

### 3. 配置

```bash
# 复制环境变量模板
cp backend/.env.example backend/.env

# 编辑 backend/.env，至少填：
#   LLM_API_KEY=sk-...              # 你的 LLM key
#   LLM_BASE_URL=https://...         # LLM 服务地址
#   LLM_CHAT_MODEL=...               # 模型名
#   JWT_SECRET=...                   # 随机字符串（首次跑用 uuid 即可）
#   ADMIN_PASSWORD=...               # 首次 seed 用
```

### 4. 启动数据库

```bash
docker compose up -d
docker compose ps   # 确认 deepmail-postgres Up (healthy)
```

### 5. 初始化

```bash
cd backend
uv run python scripts/init_db.py     # 跑所有 alembic 迁移
uv run python scripts/seed_mock_emails.py  # 创建 admin + 30 封 mock 邮件
```

### 6. 启动服务

```bash
# 真实 LLM 模式（需 LLM_API_KEY）
uv run uvicorn app.main:app --host 127.0.0.1 --port 8000

# Mock 模式（无需 LLM key，ReAct 第二次强制终止）
LLM_MOCK=true uv run uvicorn app.main:app --host 127.0.0.1 --port 8000
```

### 7. 体验

```bash
# 浏览器打开 API 文档
http://127.0.0.1:8000/docs

# v2 邮件 UI（推荐）：前端 dev 服务器
cd frontend && npm install && npm run dev
# 浏览器打开 http://127.0.0.1:5173 （自动 proxy /api → 8000）

# 或跑端到端 demo
uv run python scripts/e2e_phase3.py    # 多 Agent 协作
uv run python scripts/demo_retrieve.py # RAG 检索
uv run python scripts/e2e_phase5.py    # 人格画像
```

## 常用命令

```bash
# 测试
uv run python -m pytest -v

# 端到端（每个阶段一个）
ls scripts/e2e_phase*.py
uv run python scripts/e2e_phase1.py

# 一键全量（按顺序跑 phase1-7）
uv run python scripts/run_all_e2e.py

# 跑 ruff lint + format
uv run ruff check backend/
uv run ruff format backend/

# 加新数据库迁移
cd backend
uv run alembic revision --autogenerate -m "add_xxx"
uv run python scripts/init_db.py
```

## 项目结构

```
deepmail/
├── backend/                  # Python FastAPI 后端
│   ├── app/
│   │   ├── main.py          # FastAPI 入口
│   │   ├── core/            # 配置 / 日志 / 追踪
│   │   ├── db/              # ORM 模型
│   │   ├── schemas/         # API DTO
│   │   ├── api/             # 路由（auth/emails/chat/...）
│   │   ├── services/        # 业务逻辑
│   │   ├── agents/          # LangGraph 多 Agent
│   │   │   ├── state.py     # GraphState
│   │   │   ├── supervisor.py
│   │   │   ├── sub_agents.py # 5 ReAct sub-agents
│   │   │   ├── graph.py     # 主图装配
│   │   │   ├── tools/       # LangChain Tools
│   │   │   ├── skills/      # 7 个 AI Skill
│   │   │   ├── aggregator.py
│   │   │   └── context_builder.py
│   │   ├── memory/          # 4 层记忆 + 衰减
│   │   ├── llm/             # LLM 工厂 + Embedding + Reranker
│   │   └── rag/             # 混合检索
│   ├── alembic/             # 数据库迁移
│   ├── scripts/             # e2e + 初始化 + 上传
│   └── tests/               # pytest 单测
├── data/mock_emails/        # 30 封 mock 邮件样本
├── develop_doc/             # 设计文档
├── docker-compose.yml
└── pyproject.toml
```

## 许可证

Internal Project.
