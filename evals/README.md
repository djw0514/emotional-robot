# 中文记忆检索开发评测

`chinese-retrieval.json` 包含 20 条人工合成事实和 100 个改写问题，覆盖称呼、居住地、饮食偏好、过敏信息、计划、爱好和生活习惯。所有内容均为合成示例。

运行：

```powershell
.\.venv\Scripts\python.exe -m emotional_robot.cli prepare-model
.\.venv\Scripts\python.exe scripts/evaluate_retrieval.py
```

程序创建独立临时数据库，通过真实后台索引和搜索接口对比关键词与混合检索，不读取个人对话，也不调用 DeepSeek。模型使用 FastEmbed 支持的中文 `BAAI/bge-small-zh-v1.5`，512 维，CPU 推理。[模型列表](https://qdrant.github.io/fastembed/examples/Supported_Models/)

当前开发结果见 `baseline-summary.json`：关键词首条命中率 51%，前五条命中率 60%；混合检索分别为 96% 和 99%。该集合用于开发调参和回归，不能作为独立测试集或线上回答正确率。延迟是模型已缓存、20 条事实、本地串行请求的检索耗时，不包含 DeepSeek 生成。

完整逐题结果写入 `results/chinese-retrieval.json`，该目录已忽略入库。新增独立测试集时，应分开记录数据、阈值和模型版本，保留失败案例。
