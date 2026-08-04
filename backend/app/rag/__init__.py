"""RAG 模块。

阶段 2 实现说明（2026-08）：
    架构文档 `技术栈.md` 选 llama-index 作为 RAG 框架；本阶段落地改用
    **原生 SQL**（pgvector + PG tsvector）+ 直连 gitee embedding/rerank API。
    详细偏离原因见 `develop_doc/模块架构设计.md` § 6.1。

本目录三个文件均手写实现：
    - chunker.py     chunk 切分（800/120 滑动窗口）
    - indexer.py     嵌入 + 写库
    - retriever.py   向量 + BM25 + RRF + Reranker 混合检索

第二周期如需附件解析、复杂 query 改写，可迁移到 llama-index。
"""
