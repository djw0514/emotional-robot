# 数据升级与记忆检索运行指引

当前支持单机 SQLite 的迁移、快照及删除日志恢复，支持本地中文 embedding 与 PostgreSQL 的 pgvector 查询。PostgreSQL 容器测试已加入 CI，本机因没有 PostgreSQL 或 Docker 尚未运行该项。

## 数据库迁移

应用启动会在数据库锁保护下执行 Alembic 升级，也可手动执行：

```powershell
.\.venv\Scripts\python.exe -m emotional_robot.cli migrate
```

`0001_baseline` 固定首次提交 `379b075` 的 8 张业务表；`0002_vectors_receipts` 增加向量表和删除重放回执。无版本标记的旧库只有在表、列、类型和空值约束完全匹配基线时才会纳入迁移；未知或不完整的结构会停止升级，不猜测版本。

升级已有数据库前先创建快照；新库可直接迁移。SQLite 使用写事务串行升级，PostgreSQL 使用事务级 advisory lock。PostgreSQL 需要已安装 pgvector 扩展，迁移账号需有创建扩展的权限。

## 本地中文语义检索

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-semantic.lock
.\.venv\Scripts\python.exe -m emotional_robot.cli prepare-model
```

模型下载到 `data/private/models`；`prepare-model` 是显式下载入口。运行时只使用已缓存的模型，不在收到用户消息时自动下载。首次读取模型和 CPU 推理需要额外内存。

在 `.env` 中设置并重启：

```dotenv
ROBOT_EMBEDDING_PROVIDER=local
ROBOT_EMBEDDING_MODEL=BAAI/bge-small-zh-v1.5
ROBOT_EMBEDDING_DIMENSIONS=512
ROBOT_EMBEDDING_VERSION=1
```

已有记忆通过 `robot reindex` 排入后台任务。新增或确认的有效记忆自动排入索引任务，修订时立即去掉旧向量；任务写入前再次核实用户、状态、revision 和模型标识，避免慢任务写回旧内容。

模型标识包含服务类型、模型名、版本、维度与远端地址。更换模型或模型权重时修改 `ROBOT_EMBEDDING_VERSION` 并重新索引，不混用不同向量空间。若接其他 embedding 服务，单独配置 `ROBOT_EMBEDDING_BASE_URL`、`ROBOT_EMBEDDING_API_KEY`、模型名与维度，地址使用 HTTPS；不能把 DeepSeek 的对话地址当作 embedding 地址。

搜索结果中的 `mode` 为 `keyword`、`hybrid` 或 `keyword_fallback`。`/healthz` 中的检索模式只表示已配置的能力；是否成功使用模型以查询结果为准。索引任务失败可从 `/v1/tasks` 查看，并通过 `/v1/tasks/{id}/retry` 重试。

SQLite 在授权范围内计算精确余弦相似度，PostgreSQL 用 pgvector 的余弦距离算子查询。当前未引入 HNSW 近似索引，先保证小规模结果与权限过滤一致。混合排序以语义相似度为主，关键词作为少量加分；阈值默认 0.35，可通过 `ROBOT_SEMANTIC_MIN_SCORE` 调整。

## 快照与恢复

已有 SQLite 数据库可以在运行中创建一致性快照：

```powershell
.\.venv\Scripts\python.exe -m emotional_robot.cli backup --output data/private/backups/before-upgrade.db
```

命令同时生成 `.manifest.json` 清单，记录独立删除日志的身份。备份包含私人数据，应保存在 `data/private` 下，目标文件必须尚不存在。

恢复到新文件：

```powershell
.\.venv\Scripts\python.exe -m emotional_robot.cli restore --backup data/private/backups/before-upgrade.db --output data/private/restored.db
```

恢复会检查快照与清单、升级数据结构，并重放原始删除日志，清除备份之后被要求删除的正文、来源、版本、向量和缓存回复。完成后才将 `.env` 中的数据库地址切换为 `sqlite:///./data/private/restored.db` 并重启。

`ROBOT_DELETION_LEDGER_PATH` 默认指向 `data/private/deletion-ledger.sqlite`。保留该日志，不要用旧备份中的文件替换它；缺失或身份不匹配时，恢复命令会拒绝执行。该日志只记录用户及目标 ID，不存聊天正文。

日志先持久化，业务库再提交；启动时也会重放未应用的记录。重复重放通过回执避免再次清除删除操作之后产生的新回复。源消息和同源派生记忆会一起清理，旧抽取或索引任务不能重建已删内容。

此流程针对单机恢复，不代替操作系统安全擦除，也不能保证手工绕过恢复命令或丢失删除日志后的恢复。多节点部署需要共享的持久删除日志；PostgreSQL 的备份工具链和跨节点恢复演练仍待单独验收。

## 中文检索开发集

运行 `python scripts/evaluate_retrieval.py`，使用合成数据创建临时数据库，对比关键词与本地向量的混合检索。完整逐题记录写入忽略入库的 `evals/results`，公开摘要位于 `evals/baseline-summary.json`。

该集有 20 条人工事实、100 个改写问题，用于开发调参和回归。当前首条命中率为 96%，前五条命中率为 99%；关键词方案分别为 51% 和 60%。测试是本地串行、模型已缓存的检索检查，未调用 DeepSeek，不评估最终回答质量、长期时间推理或未知问题拒答；也不是独立留出集。
