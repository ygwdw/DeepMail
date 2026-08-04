# DEPLOY.md —— 部署 / 运维

## 1. 环境要求

| 组件 | 最低 | 推荐 |
|---|---|---|
| CPU | 2 核 | 4 核 |
| 内存 | 4 GB | 8 GB |
| 磁盘 | 20 GB | 50 GB SSD |
| Python | 3.12+ | 3.12 |
| PostgreSQL | 16 + pgvector | 16 + pgvector |
| Docker | 20+ | 24+ |

## 2. 快速部署（开发环境）

```bash
# 1. 启动数据库
docker compose up -d

# 2. 装依赖
cd backend
uv sync --extra dev

# 3. 配置 .env（参考 README）

# 4. 初始化
uv run python scripts/init_db.py
uv run python scripts/seed_mock_emails.py   # 可选

# 5. 启动
uv run uvicorn app.main:app --host 0.0.0.0 --port 8000
```

## 3. 生产部署（systemd）

### 3.1 服务配置 `/etc/systemd/system/deepmail.service`

```ini
[Unit]
Description=DeepMail API
After=network.target docker.service
Requires=docker.service

[Service]
Type=simple
User=deepmail
WorkingDirectory=/opt/deepmail/backend
Environment="PATH=/opt/deepmail/.venv/bin"
EnvironmentFile=/opt/deepmail/backend/.env
ExecStart=/opt/deepmail/.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 2
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

### 3.2 启动

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now deepmail
sudo systemctl status deepmail
```

## 4. 关键环境变量

```env
# === JWT ===
JWT_SECRET=                # 必须！随机字符串

# === LLM ===
LLM_BASE_URL=              # OpenAI 兼容服务 URL
LLM_API_KEY=               # 你的 LLM key
LLM_CHAT_MODEL=             # 模型名
LLM_EMBED_MODEL=            # Embedding 模型（gitee Qwen3-Embedding-0.6B）
LLM_RERANK_MODEL=           # Reranker 模型（gitee Qwen3-Reranker-0.6B）

# === Embedding（gitee 服务） ===
EMBED_BASE_URL=             # https://ai.gitee.com/v1
EMBED_API_KEY=              # gitee key
RERANK_BASE_URL=            # https://ai.gitee.com/v1

# === 管理员 ===
ADMIN_USERNAME=admin
ADMIN_PASSWORD=            # 首次 seed 用

# === 追踪（可选） ===
LANGSMITH_TRACING=true
LANGSMITH_API_KEY=          # langsmith key
LANGSMITH_PROJECT=deepmail
```

## 5. 前端构建（v2-M5）

### 5.1 开发模式

```bash
cd frontend
npm install
npm run dev
# 监听 http://127.0.0.1:5173，Vite proxy /api → http://127.0.0.1:8000
```

### 5.2 生产构建（前端嵌入 FastAPI）

```bash
cd frontend
npm install
npm run build    # 产物落到 frontend/dist/
```

FastAPI 启动时会自动检测 `frontend/dist/`：

- 存在 → mount `/assets/` + `/` 返回 `index.html` + SPA fallback
- 不存在 → 仅 API（开发模式推荐）

生产部署只需启动 uvicorn；前端与 API 同源部署，**无需 CORS**。

### 5.3 环境变量

前端通过 Vite proxy 访问 `/api`，**无独立环境变量**。
后端 `.env` 的 JWT / LLM 配置对前端透明。

---

## 7. 备份策略

### 7.1 数据库备份

```bash
# 每天凌晨 3 点备份
0 3 * * * pg_dump -U deepmail -h localhost deepmail | gzip > /backup/deepmail-$(date +\%Y\%m\%d).sql.gz
```

### 7.2 恢复

```bash
# 停服务
sudo systemctl stop deepmail

# 恢复
gunzip -c /backup/deepmail-20260801.sql.gz | psql -U deepmail -h localhost deepmail

# 启服务
sudo systemctl start deepmail
```

## 8. 监控

### 8.1 健康检查

```bash
curl http://localhost:8000/health
# {"status":"ok"}
```

### 8.2 日志

```bash
# 实时查看
journalctl -u deepmail -f

# 结构化日志（structlog）
journalctl -u deepmail -o cat | jq '.'
```

### 8.3 关键指标（自建 / langsmith）

- 每次 send_message 的 `tokens_used` / `latency_ms` / `memory_used`
- Langsmith dashboard 查 trace / agent run / tool call

## 9. 性能调优

| 参数 | 默认 | 调优 |
|---|---|---|
| uvicorn workers | 1 | CPU * 2 + 1 |
| pgvector lists | 100 | rows / 1000 |
| HNSW m | 16 | 16-64 |
| HNSW ef_construction | 64 | 64-200 |
| Reranker top_n | 5 | 3-10 |
| Max iterations (ReAct) | 10 | 5-15 |

## 10. 常见问题

**Q: pgvector 报 "could not open extension"？**
A: 镜像用 `pgvector/pgvector:pg16`，已预装。

**Q: 嵌入维度不匹配？**
A: 1024 (Qwen3-Embedding) vs 1536 (OpenAI) 改了需要新建表。当前固定 1024。

**Q: MiniMax rerank 中文返回 400？**
A: 已知 bug。retriever 失败自动降级到 RRF 顺序（不影响主流程）。

## 11. 升级流程

```bash
# 1. 拉新代码
git pull

# 2. 装新依赖
cd backend && uv sync
cd frontend && npm install   # v2-M5+

# 3. 跑迁移
uv run python scripts/init_db.py

# 4. 构建前端（可选；不构建则 API 仍可用）
cd ../frontend && npm run build

# 5. 重启服务
sudo systemctl restart deepmail
```

## 12. 故障恢复 Runbook

| 现象 | 排查 | 解决 |
|---|---|---|
| 服务 502 | DB 是否可达 | `docker compose ps` + `pg_isready` |
| 嵌入 401 | API key 过期 | 更新 `.env` |
| 检索 0 命中 | 索引没建 | `POST /api/knowledge/index/emails` |
| agent 死循环 | mock 模式有 counter 防御；真实模式需调 | 临时切 `LLM_MOCK=true` |
| DB 慢 | 缺索引 | `EXPLAIN ANALYZE` 查慢查询 |