# Emotional Robot 心伴

面向华为手机的鸿蒙原生 AI 陪伴应用。目标系统已确定为 **HarmonyOS 7.0.0**，模型服务采用 **DeepSeek**。

当前已实现可运行的 Python 后端，以及待 DevEco Studio 编译验证的 ArkTS 客户端源码。后端支持文字流式对话、会话持久化、记忆管理、来源与版本记录、用户与角色隔离、持久化抽取和删除任务。

## 按步骤实施

逐步操作、验收条件和当前状态见[实施清单](docs/implementation-plan.md)。前端尚未真机验证；DeepSeek 适配器已通过模拟接口测试，真实调用需要在本机配置 API Key。

记忆检索已支持中文关键词与语义混合检索：本地中文模型无需收费接口，也可单独配置兼容的 embedding 服务。SQLite 使用精确余弦相似度，PostgreSQL 使用 pgvector。完整时间推理、语音、动画及 Mem0 对照实验仍在后续清单中。

## 启动后端

在仓库根目录使用 Python 3.12：

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.lock
.\.venv\Scripts\python.exe -m pip install -e . --no-deps
Copy-Item .env.example .env
.\.venv\Scripts\python.exe -m emotional_robot.cli serve
```

已有 `.env` 时保留原配置，不重复复制。当前工作区已创建 `.venv` 并安装依赖，也已准备忽略入库的 `.env`；可以直接运行最后一行。

接口文档：<http://127.0.0.1:8000/docs>。默认演示口令为 `local-demo-change-me`，在 Swagger 的 Authorize 中输入口令。演示模式无需模型 Key，主要用于检验对话和记忆流程。

## 使用 DeepSeek

编辑本机 `.env`，保留未涉及的配置：

```dotenv
ROBOT_PROVIDER=compatible
ROBOT_MODEL_BASE_URL=https://api.deepseek.com
ROBOT_MODEL_NAME=deepseek-flash
ROBOT_MODEL_API_KEY=在本机填写你的密钥
```

然后重启后端。模型名称可根据自己的 DeepSeek 账号调整，当前默认依据[官方 Chat Completions 文档](https://api-docs.deepseek.com/api/create-chat-completion/)。配置无效或服务失败会返回错误事件，不会自动切回演示回复。API Key 不进入客户端和 Git 仓库。

DeepSeek 产生的记忆候选需在管理页确认后才参与长期召回。演示模式只对称呼、居住地和喜恶做保守规则抽取；冲突事实也会进入待确认。

## 本地中文语义检索

当前工作区已下载并启用 `BAAI/bge-small-zh-v1.5` 中文模型，使用 CPU 生成 512 维向量。新环境按以下步骤准备：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-semantic.lock
.\.venv\Scripts\python.exe -m emotional_robot.cli prepare-model
# 在 .env 中设置 ROBOT_EMBEDDING_PROVIDER=local，重启后端
.\.venv\Scripts\python.exe -m emotional_robot.cli reindex
```

`reindex` 为已有记忆创建后台索引任务，后端运行时会处理。模型不可用时查询会明确返回 `keyword_fallback`，不会把关键词匹配计作语义检索。DeepSeek 对话接口与 embedding 服务分开配置。

本地合成开发集包含 20 条事实、100 个检索问题：混合检索首条命中 96 题，前五条命中 99 题；关键词方案分别为 51 和 60 题。这是开发调参与回归结果，不能代替真实长期对话的独立评测。复现命令为 `.\.venv\Scripts\python.exe scripts/evaluate_retrieval.py`，摘要见 [评测记录](evals/baseline-summary.json)。

## 鸿蒙客户端

用支持 HarmonyOS 7 SDK 的 DevEco Studio 打开 [apps/harmony](apps/harmony)。操作说明见[客户端运行指引](apps/harmony/README.md)。页面包括聊天、历史会话、记忆管理和服务连接设置。

本机暂未找到鸿蒙 SDK 或构建工具，当前不能声称已生成 HAP 或完成真机适配。

## 检查与测试

```powershell
npm.cmd ci --ignore-scripts --no-audit --no-fund
powershell -ExecutionPolicy Bypass -File scripts/test.ps1
.\.venv\Scripts\python.exe scripts/smoke.py
```

测试覆盖用户隔离、角色隔离、跨会话召回、暂停记忆、纠错冲突、来源追溯、删除后重放、生成中删除、后台任务恢复、DeepSeek 接口行为和流式事件分包。`smoke.py` 会临时启动本机 HTTP 服务，完成检查后退出，不调用外部模型。

## 数据与用户

开发数据库保存在忽略入库的 `data/private/robot.db`。演示模式只用于本地验证。多人使用时关闭演示账号，并为用户分别签发连接口令：

```powershell
# 在 .env 中设置 ROBOT_DEMO_MODE=false 后执行
.\.venv\Scripts\python.exe -m emotional_robot.cli create-user --name 你的名字
```

命令只在创建时显示新口令，数据库保存其哈希。手机端目前只在内存中保留口令，重启后需重新输入。

删除会立即阻止召回，并异步清除在线数据库中的记忆正文、版本、关联来源和缓存回复。为防止助手回声再次带出已删除内容，当前会清除该用户已有助手回复。同源记忆可能一起清除。独立删除日志会在恢复旧备份时重放，防止已删内容复活；该流程不代表备份或 SQLite WAL 的安全擦除。

数据库已采用 Alembic 迁移，支持保留基线版本数据升级。SQLite 快照、恢复命令和删除日志的操作说明见[数据运维指引](docs/operations.md)。恢复要求原始删除日志与备份清单匹配，输出到新文件，不覆盖现有数据库。

PostgreSQL 部署准备见 [infra/compose.yaml](infra/compose.yaml)。在安装 Docker 后设置 `ROBOT_POSTGRES_PASSWORD`，再执行 `docker compose -f infra/compose.yaml up -d`；连接串使用 `postgresql+psycopg://robot:密码@127.0.0.1:5432/emotional_robot`。切换数据库不会自动迁移 SQLite 数据。本机尚未验证该部署。

## 项目文档

| 文档 | 内容 |
| --- | --- |
| [实施清单](docs/implementation-plan.md) | 每步要做什么、验收什么、完成到哪里 |
| [GitHub 项目预研](docs/research/github-landscape-2026-11-01.md) | 15 个仓库的维护状态、许可证与选型依据 |
| [记忆管理设计](docs/architecture/memory-management.md) | 完整目标架构及当前实现差异 |
| [首版验证计划](docs/research/poc-plan.md) | 中文评测、性能与成本测量 |
| [仓库状态快照](docs/research/github-snapshot-2026-11-01.json) | 预研所用提交与许可证识别结果 |
| [API 契约](packages/contracts/openapi.json) | 从当前后端生成的 OpenAPI 定义 |
| [数据运维指引](docs/operations.md) | 数据库升级、索引重建、快照与删除日志恢复 |
| [中文检索样例](evals/chinese-retrieval.json) | 100 道人工合成的开发检索题 |

远程 `origin` 已关联 [djw0514/emotional-robot](https://github.com/djw0514/emotional-robot)。已启用本地 Git 管理，按实施阶段保存独立提交；尚未推送到 GitHub。
