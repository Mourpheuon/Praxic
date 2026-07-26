# 思悟 Agent（Siwu Agent）

> **以辩证唯物主义方法论为认知内核的 AI 智能体**
>
> 「思」以析理，「悟」以通变。六阶段认知循环——调查、矛盾、理性、决策、实践、反思。

---

## 认知循环

```
用户输入
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
④ 决策输出   —— 战略上藐视，战术上重视（行动项 + 可行性预判）
   │
   ▼
⑤ 实践检验   —— 多轮递进实验，自动写代码运行、分析、修复
   │
   ▼
⑥ 反思复盘   —— 实践是检验真理的唯一标准（收敛判定 + 证据管线）
   │
   ▼
判断是否收敛 → 未收敛则重新调查（带上反思提示）
```

---

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
export SIWU_API_KEY="sk-xxx"
export SIWU_BASE_URL="https://api.deepseek.com"

# Anthropic Claude
export ANTHROPIC_API_KEY="sk-ant-xxx"

# 或者写入 .env 文件（不会被 Git 追踪）
cp .env.example .env
# 编辑 .env 填入你的真实 key
```

### 3. 运行

**命令行（CLI）：**

```bash
python -m siwu run "为什么我的开源项目难以吸引贡献者？"
python -m siwu run "考虑一群个体进行博弈..." --mode deep
python -m siwu run --help   # 查看全部选项
```

**Web UI（浏览器）：**

```bash
python -m siwu
# 自动打开 http://localhost:8000
```

**Electron 桌面应用（Windows）：**

```powershell
.\scripts\build-electron.ps1
# 构建后运行 dist-electron/win-unpacked/思悟 Agent.exe
```

**Python SDK：**

```python
import asyncio
from siwu.core.cognitive_loop import CognitiveLoop

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
| `fast` | 跳过矛盾分析/实践/反思，单轮 | 简单问答、信息查询 |
| `standard` | 完整六阶段循环，多轮实践 | 大多数场景 |
| `deep` | 多轮迭代 + 多视角审查 | 复杂分析、决策推演 |
| `custom` | 可跳过指定阶段（如 `skip=contradiction,practice`） | 灵活控制 |

---

## 功能特性

| 特性 | 说明 |
|------|------|
| **联网搜索** | Tavily + 网页抓取，支持多结果并行 |
| **文件读取** | TXT、代码、PDF（多级回退 + OCR）、DOCX、XLSX、PPTX、IPYNB |
| **多 LLM 后端** | DeepSeek、OpenAI、Anthropic、Ollama、自定义中转站 |
| **实践引擎** | 自动写代码、运行、分析结果、修复错误，多轮递进 |
| **技能系统** | 可扩展的 skill 注册表，批量导入（94+ 技能） |
| **项目系统** | 对话按项目组织，内存跨会话共享 |
| **对话管理** | 历史记录、SSE 流式响应、用户引导/打断/终止 |
| **终止证据管线** | 子问题覆盖 + 决策验证 + 矛盾状态——结构化收敛判断 |
| **设置持久化** | UI 设置存 `config.toml`，账户配置写入 `.env` |
| **Electron 壳** | Windows 安装程序，自动启动 Python 后端 |

---

## 项目结构

```
siwu-agent/
├── siwu/                          # 核心包
│   ├── core/                      # 认知引擎
│   │   ├── cognitive_loop.py      # 认知循环控制器（主入口）
│   │   ├── investigation.py       # 调查研究
│   │   ├── contradiction.py       # 矛盾分析
│   │   ├── rational.py            # 理性认识
│   │   ├── decision.py            # 决策引擎
│   │   ├── practice.py            # 实践检验（多轮实验 + 自动修复）
│   │   ├── practice_harness.py    # 实践执行提示词（迭代高频，独立存放）
│   │   ├── practice_classifier.py # 实践可行性分类
│   │   ├── perspectives.py        # 多视角审查
│   │   ├── reflection.py          # 反思引擎（收敛判定 + 证据管线）
│   │   ├── question_preprocessing.py  # 五步预处理管线
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
│   │   ├── filesystem.py          # 文件读写
│   │   ├── file_loader.py         # 多格式文件读取
│   │   ├── pdf_converter.py       # PDF 多级回退转换 + OCR
│   │   ├── web_search.py          # Tavily 联网搜索
│   │   ├── web_fetch.py           # 网页内容抓取
│   │   ├── search.py              # 搜索工具基类
│   │   ├── local_retriever.py     # 本地知识检索
│   │   └── base.py                # 工具抽象
│   ├── memory/                    # 记忆系统
│   │   ├── working_memory.py      # 跨轮次上下文传递
│   │   ├── episodic_memory.py     # 情景记忆（SQLite）
│   │   └── semantic_memory.py     # 语义记忆
│   ├── api/                       # REST API（FastAPI）
│   │   ├── server.py
│   │   ├── routes/
│   │   │   ├── agent.py           # 认知循环 SSE 流式端点
│   │   │   ├── setup.py           # 设置 / 配置 / 构建路由
│   │   │   └── conversations.py   # 对话 + 项目管理
│   │   └── schemas/models.py      # Pydantic 数据模型
│   ├── cli.py                     # 命令行接口
│   ├── config.py                  # 配置管理（TOML + 环境变量）
│   ├── web/                       # 前端（React + Vite + Tailwind）
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
└── Dockerfile                     # Docker 镜像
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
autonomy_level = "standard"      # standard | high | low
max_iterations = 5
web_search_enabled = true
```

### 环境变量（优先级高于 config.toml）

| 变量 | 说明 |
|------|------|
| `SIWU_API_KEY` | OpenAI 兼容 API Key |
| `SIWU_BASE_URL` | 兼容端点地址 |
| `SIWU_MODEL` | 默认模型 |
| `SIWU_LLM_PROVIDER` | `openai_compatible` 或 `anthropic` |
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
cd D:\Files\2026\07\Siwu
npm install
cd siwu/web; npx vite build; cd ..\..
npx electron-builder
# 产物：dist-electron/思悟 Agent Setup *.exe
```

### Docker 镜像

```bash
docker build -t siwu-agent .
docker run -p 8000:8000 -v $(pwd)/data:/app/data siwu-agent
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
