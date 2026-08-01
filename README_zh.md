# 即物穷理（Praxic）

> **以辩证唯物主义方法论为认知内核的 AI 智能体**
>
> "即物"贴近事物，"穷理"穷尽条理。Praxic = Praxis + Dialectic——在实践中穿过矛盾，淬出真知。

---

## 认知循环

```
用户输入
   │
   ▼
⓪ 问题预处理 —— 解析意图、任务性质、复杂度与阶段计划
   │
   ▼
① 调查研究   —— 没有调查就没有发言权（联网搜索 + 文件读取 + 网页抓取）
   │
   ▼
② 矛盾分析   —— 抓主要矛盾，分析矛盾的主要方面，解剖麻雀
   │
   ▼
③ 理性认识   —— 去粗取精、去伪存真、由此及彼、由表及里
   │
   ▼
④ 实践检验   —— 战略上藐视，战术上重视。从前序产出提炼可证伪论断，
                自主编排行动、调用工具、分析结果，验证证据交给反思
   │
   ▼
⑤ 反思复盘   —— 实践是检验真理的唯一标准（收敛判定 + 证据管线）
   │
   ▼
判断是否收敛 → 未收敛则重新调查（带上反思提示，受 max_iterations 约束）
```

## 快速开始

### 1. 环境要求

- Python 3.11+
- API Key（DeepSeek、OpenAI 或 Anthropic）
- （可选）Tavily API Key——联网搜索

### 2. 配置

复制并编辑配置文件：

```bash
cp config.toml.example config.toml
# 或通过 Web UI 设置页面直接配置
```

配置 API Key（三选一）：

```bash
# DeepSeek（默认，推荐）
export PRAXIC_LLM_API_KEY="sk-xxx"
export PRAXIC_LLM_BASE_URL="https://api.deepseek.com"

# Anthropic Claude
export ANTHROPIC_API_KEY="sk-ant-xxx"

# 或者写入 .env 文件（不会被 Git 追踪）
cp .env.example .env
# 编辑 .env 填入你的真实 key
```

### 3. 运行

**命令行（CLI）：**

```bash
python -m praxic run "为什么我的开源项目难以吸引贡献者？"
python -m praxic run "考虑一群个体进行博弈..." --mode deep
python -m praxic run --help   # 查看全部选项
```

**Web UI（浏览器）：**

```bash
python -m praxic
# 自动打开 http://localhost:8000
```

**Electron 桌面应用（Windows）：**

```powershell
npm run electron:build
# 构建后运行 dist-electron/win-unpacked/即物穷理.exe
```

**Python SDK：**

```python
import asyncio
from praxic.core.cognitive_loop import CognitiveLoop

async def main():
    loop = CognitiveLoop()
    response = await loop.run(
        question="为什么我的开源项目难以吸引贡献者？",
        mode="standard",
    )
    print(response.summary)
    for item in response.action_items:
        print(f"- {item}")

asyncio.run(main())
```

---

## 运行模式

| 模式 | 说明 | 适用场景 |
|------|------|----------|
| `fast` | 调查后走快速矛盾分析与理性认识，跳过实践与反思，单轮 | 简单问答、信息查询 |
| `standard` | 完整认知循环（预处理 + 五阶段），多轮实践 | 大多数场景 |
| `deep` | 多轮迭代，迭代上限更高（至少 7 轮），反思驱动重新调查 | 复杂分析、决策推演 |
| `custom` | 通过 `skip` 参数跳过指定阶段（如 `skip=contradiction,practice`） | 灵活控制 |

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **认知循环** | 预处理 → 调查研究 → 矛盾分析 → 理性认识 → 实践检验 → 反思复盘 |
| **联网搜索** | Tavily + 网页抓取，支持多结果并行 |
| **文件读取** | TXT、代码、PDF（多级回退 + OCR）、DOCX、XLSX、PPTX、IPYNB |
| **多 LLM 后端** | DeepSeek、OpenAI、Anthropic、Ollama、自定义兼容端点 |
| **实践引擎** | 从前序阶段提炼可证伪论断，自主编排行动、调用工具、分析结果，多轮递进自动修复 |
| **权限与授权** | 读取默认自动执行；写入、删除、外部副作用经权限门与异步授权，变更记录 + 回读验证 |
| **工具注册表** | 统一工具契约，结构化序列化结果，区分工具失败与世界状态未改变 |
| **可信度溯源** | 按证据强度限制结论可信度上限（V3/V2），避免超出证据范围的断言 |
| **上下文缓存** | 应用层 KV 缓存 + 供应商 prompt cache，按会话/项目/模型/版本隔离，报告命中与 token 统计 |
| **技能系统** | 可扩展 skill 注册表，按认知阶段注入，支持批量导入 |
| **项目系统** | 对话按项目组织，会话置顶，记忆跨会话共享，历史阶段日志回放 |
| **对话管理** | 历史记录、SSE 流式响应、用户引导/打断/终止/恢复 |
| **实时活动流** | 前端实时显示阶段、工具活动、等待授权、验证与失败状态 |
| **设置持久化** | UI 设置存 `config.toml`，账户配置写入 `.env` |
| **Electron 壳** | Windows 安装程序，自动启动 Python 后端 |

---

## 项目结构

```
Praxic/
├── praxic/                          # 核心包
│   ├── core/                      # 认知引擎
│   │   ├── cognitive_loop.py      # 认知循环控制器（主入口）
│   │   ├── question_preprocessing.py  # 问题预处理（意图/任务性质/阶段计划）
│   │   ├── investigation.py       # 调查研究
│   │   ├── contradiction.py       # 矛盾分析
│   │   ├── rational.py            # 理性认识
│   │   ├── practice.py            # 实践检验（多轮实验 + 自动修复）
│   │   ├── practice_harness.py    # 实践执行提示词（迭代高频，独立存放）
│   │   ├── reflection.py          # 反思引擎（收敛判定 + 证据管线）
│   │   ├── loop_controller.py     # 终止/引导/打断控制
│   │   ├── skill_manager.py       # 技能加载与管理
│   │   ├── skill_importer.py      # 技能批量导入
│   │   ├── autonomy.py            # 自主度控制
│   │   ├── credibility_chain.py   # 可信度溯源
│   │   └── dev_tracer.py          # 开发追踪
│   ├── llm/                       # LLM 后端
│   │   ├── base.py                # 抽象基类
│   │   ├── claude.py              # Anthropic Claude
│   │   └── openai_compatible.py   # OpenAI / DeepSeek / Ollama
│   ├── tools/                     # 工具系统
│   │   ├── base.py                # 工具抽象
│   │   ├── registry.py            # 工具注册表
│   │   ├── permissions.py         # 权限/授权门控
│   │   ├── filesystem.py          # 文件读写
│   │   ├── file_loader.py         # 多格式文件读取
│   │   ├── pdf_converter.py       # PDF 多级回退转换 + OCR
│   │   ├── web_search.py          # Tavily 联网搜索
│   │   ├── web_fetch.py           # 网页内容抓取
│   │   ├── shell.py / python_exec.py  # 命令执行
│   │   ├── user_context.py        # 用户上下文
│   │   └── local_retriever.py     # 本地知识检索
│   ├── memory/                    # 记忆系统
│   │   ├── working_memory.py      # 跨轮次上下文传递
│   │   ├── episodic_memory.py     # 情景记忆（SQLite）
│   │   ├── semantic_memory.py     # 语义记忆
│   │   └── context_cache.py       # 上下文编译与缓存
│   ├── api/                       # REST API（FastAPI）
│   │   ├── server.py
│   │   ├── routes/
│   │   │   ├── agent.py           # 认知循环 SSE 流式端点
│   │   │   ├── setup.py           # 设置 / 配置 / 构建路由
│   │   │   └── conversations.py   # 对话 + 项目管理
│   │   └── schemas/models.py      # Pydantic 数据模型
│   ├── skills/                    # 技能包与注册表
│   ├── cli.py                     # 命令行接口
│   ├── config.py                  # 配置管理（TOML + 环境变量）
│   ├── web/                       # 前端（实际入口为 index.html；src/ 为待收口的 TypeScript 树）
│   └── __main__.py                # 桌面入口（uvicorn 子进程 + 热重启）
├── electron/                      # Electron 壳
│   ├── main.js                    # 主进程（Python 子进程管理）
│   └── preload.js                 # 安全桥接（文件选择等原生 API）
├── scripts/
│   ├── push.sh                    # GitHub token 推送
│   ├── release.sh                 # 版本发布
│   ├── import_skills.py           # 技能批量导入
│   ├── build-electron.ps1         # Windows Electron 构建
│   └── build-electron.sh          # Linux Electron 构建
├── tests/                         # 测试
│   ├── test_cognitive_loop.py
│   ├── test_contradiction.py
│   ├── test_full_loop_integration.py
│   ├── test_steering.py           # 引导/打断/终止控制
│   ├── test_clarification.py      # 主动澄清
│   ├── test_practice_integration.py
│   ├── test_skill_manager.py
│   └── ...
├── config.toml.example            # 配置模板
├── pyproject.toml
├── package.json                   # Electron 依赖
├── electron-builder.yml           # Electron 打包配置
├── Dockerfile / docker-compose.yml
└── PROJECT_HANDOFF.md             # 内部交接文档（不入库）
```

---

## 配置

### 基础配置

编辑 `config.toml`（参考 `config.toml.example`）：

```toml
[llm]
provider = "openai_compatible"   # openai_compatible | anthropic
base_url = "https://api.deepseek.com"
model = "deepseek-v4-pro"

[runtime]
autonomy_level = "standard"      # 行为自主：read_only | sandboxed | standard | elevated
permission_mode = "ask"           # 权限模式：read_only | ask | auto_review | full
max_iterations = 5
web_search_enabled = true
```

### 环境变量（优先级高于 config.toml）

| 变量 | 说明 |
|------|------|
| `PRAXIC_LLM_API_KEY` | OpenAI 兼容 API Key |
| `PRAXIC_LLM_BASE_URL` | 兼容端点地址 |
| `PRAXIC_LLM_MODEL` | 默认模型 |
| `PRAXIC_LLM_PROVIDER` | `openai_compatible` 或 `anthropic` |
| `ANTHROPIC_API_KEY` | Anthropic API Key |
| `TAVILY_API_KEY` | Tavily 搜索 API Key |

### Web UI 账户标签页

Web UI 的设置对话框支持：
- 选择服务商（DeepSeek / OpenAI / Anthropic / Ollama / 自定义）
- 自动加载模型列表
- **连接测试**——保存前先验证 API Key 有效性
- **保存配置**——同时写入 `config.toml` 和 `.env`

---

## 构建 & 发布

### Electron 桌面应用（Windows）

```powershell
npm install
npm run electron:build
# 产物：dist-electron/即物穷理 Setup *.exe
```

### Docker 镜像

```bash
docker build -t praxic .
docker run -p 8000:8000 -v $(pwd)/data:/app/data praxic
```

### 版本发布

```bash
bash scripts/release.sh 0.2.0
# 更新 pyproject.toml → 创建 release commit → 打标签 → 推送
```

---

## License

MIT

---

*本项目旨在探索将辩证唯物主义方法论内化为 AI 推理流程的可能性。*
