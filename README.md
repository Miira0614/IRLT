# SemiReq-Hub: AI-Powered Chip Requirement Lifecycle Manager

> **AI驱动的芯片需求全生命周期管理系统**
>
> 用 LLM 将散乱的芯片需求自动分类、匹配模板、建立追溯链、生成结构化报表。
> 从 0 到 1 独立开发，在真实工业场景中处理了 **40+ 芯片项目、2000+ 条需求**。

[English](#english) | [中文](#chinese)

---

## 🇬🇧 English <a id="english"></a>

### What It Does

SemiReq-Hub (Intelligent Requirement Lifecycle Tracer) leverages Large Language Models to automate the most tedious parts of chip requirement engineering:

1. **Smart Categorization** — Auto-classify requirements into an 8-dimension × 200+ node taxonomy
2. **Template Matching** — Match requirements against a master template library and extract variables
3. **Traceability Completion** — Build L1(Customer)→L2(Initial)→L3(System) trace chains, auto-fill missing levels
4. **Visualization Export** — Generate formatted Excel reports with statistics

### Architecture

```
┌─────────────────────────────────────────────────┐
│                  main.py (Entry)                 │
└──────────────────┬──────────────────────────────┘
                   │
    ┌──────────────┼──────────────────┐
    ↓              ↓                  ↓
┌────────┐  ┌────────────┐  ┌────────────────┐
│ Categorize│  │Template    │  │Topology        │
│ (LLM)    │→ │Match (LLM) │→ │Completion (LLM)│
└────────┘  └────────────┘  └────────────────┘
    │              │                  │
    └──────────────┼──────────────────┘
                   ↓
         ┌────────────────┐
         │  Visualization  │
         │  (Excel Export) │
         └────────────────┘
                   ↑
         ┌────────────────┐
         │ SpecDataProvider│  ← NEW: auto-derive from spec JSON
         │ (Categories +   │
         │  Templates)     │
         └────────────────┘
```

### Tech Stack

| Layer | Technology |
|-------|-----------|
| Language | Python 3.10+ |
| LLM Framework | **LangChain 0.2+** |
| LLM | DeepSeek-R1 / Qwen (OpenAI-compatible API) |
| Data | OpenPyXL (Excel), JSON |
| Concurrency | ThreadPoolExecutor |
| Logging | Custom audit trail system |

### Quick Start

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Configure LLM
#    Set MODEL_CHOICE via environment variable: "local", "siliconflow", or "auto"
#    Set API keys via environment variables

# 3. Test connection
python src/llm_client.py

# 4. Run demo (with auto spec-derived categories)
python main.py --demo

# 5. Check spec consistency
python main.py --check-spec

# 6. Batch process (spec-driven mode, recommended)
python main.py

# 7. Sync configs from spec JSON (standalone)
python script/sync_config.py --check    # check only
python script/sync_config.py --sync     # sync with confirmation

# Legacy: traditional JSON file mode
python main.py --no-spec-provider
```

### Project Structure

```
├── main.py                  # Main entry
├── src/
│   ├── llm_client.py        # LLM client (dual-mode: local + cloud)
│   ├── pipeline.py          # Pipeline orchestrator
│   ├── spec_data_provider.py   # NEW: Auto-derive categories & templates from spec JSON
│   ├── categorization_module.py   # AI categorization
│   ├── template_matching_module.py # Template matching & variable extraction
│   ├── topology_completion_module.py # Trace chain completion
│   ├── visualization_module.py     # Excel export
│   ├── data_models.py             # Data models
│   └── logging_audit_module.py    # Audit logging
├── data/config/
│   ├── 芯片需求结构化定义规范V4.1.json  # Spec JSON (single source of truth)
│   ├── categories.dbV4.1.json           # Category taxonomy (auto-derived from spec)
│   └── Master_Requirement_Templates.json # Master template library
├── script/
│   ├── sync_config.py          # NEW: Validate & sync configs from spec
│   ├── extract_doc_text.py     # NEW: Extract text from .doc spec files
│   ├── 需求表格预处理.py         # Pre-process raw requirement Excel files
│   └── 完整模板补充.py           # Template chain completion
├── api/                      # FastAPI backend
│   ├── main.py               # API entry
│   ├── schemas.py            # Pydantic models
│   └── routers/              # API routes
├── frontend/                 # Streamlit frontend
│   └── app.py                # Web UI
├── output/                   # Generated reports
└── requirements.txt
```

### Spec-Driven Mode (NEW V4.1)

Starting from V4.1, categories are **auto-derived** from `芯片需求结构化定义规范V4.1.json`.
No more manual maintenance of `categories.dbV4.1.json`.

```
芯片需求结构化定义规范书V4.1.doc (Word)
         │
         │  script/extract_doc_text.py  (extract text)
         ▼
    规范书纯文本
         │
         │  LLM parsing (one-time, on major spec updates)
         ▼
芯片需求结构化定义规范V4.1.json  ←── single source of truth
         │
         │  SpecDataProvider (auto-derive at runtime)
         ├──────────────────────────────────
         ▼                                  ▼
  categories (in memory)            templates (existing + auto-gen)
         │                                  │
         └──────────┬───────────────────────┘
                    ▼
              pipeline.py (runs as before)
```

**Token efficiency**: The category tree sent to LLM is only ~7KB (209 lines of compact metadata), NOT the full spec text.

### Key Features

- **Spec-Driven Architecture (NEW V4.1)**: Categories auto-derived from spec JSON; single source of truth eliminates manual sync
- **3-Tier LLM Prompt Architecture**: Dimension → Domain → Item level cascading classification
- **Dual Model Support**: Auto-fallback between local LLM and SiliconFlow cloud API
- **Concurrent Processing**: 6-thread parallel AI calls with exponential backoff retry
- **Checkpoint Recovery**: Classification cache prevents duplicate LLM calls
- **Human-in-the-Loop**: Full audit trail for every AI decision
- **Template Library**: Parameterized requirement templates with variable extraction
- **Smart Sync Tool**: `script/sync_config.py` validates and auto-generates configs from spec

### LangChain Integration (V4.2)

#### Why LangChain?

| Aspect | Before | After (LangChain) |
|--------|--------|-------------------|
| **LLM Client** | Hand-written OpenAI API calls | `ChatOpenAI` with built-in retry |
| **Fallback Mechanism** | Manual fallback logic | `.with_fallbacks([...])` one-liner |
| **Prompt Management** | Hardcoded strings | `ChatPromptTemplate` structured templates |
| **JSON Parsing** | Fragile `find('{') + rfind('}')` | Pydantic models + manual format instructions |
| **Output Validation** | Manual field extraction | Automatic Pydantic validation |

#### Key Changes

**1. LLM Client (`src/llm_client.py`)**

- Replaced manual `OpenAI()` calls with `ChatOpenAI()` from `langchain-openai`
- Added built-in retry (`max_retries=3`) and timeout (`timeout=30`)
- Implemented automatic fallback between local and cloud models using `.with_fallbacks()`
- Separated JSON mode and text mode models for better performance
- Added `_create_chat_openai()` factory method with `response_format` compatibility handling
- Implemented **lazy loading** to avoid LLM connection errors during module import
- Added `_ensure_models_initialized()` guard method for deferred initialization

**2. Pydantic Output Models**

- `CategorizationResult` — Classification output with `category_uid`, `confidence`, `requirement_level`
- `TemplateMatchResult` — Template matching output with `match_type`, `extracted_variables`
- `TemplateVariable` — Variable definition with `name`, `type`, `label`, `unit`
- `NewTemplateResult` — New template generation output
- `TopologyAnalysisResult` — Trace chain analysis with `level_adjustments`, `trace_chains`
- Each model includes a `get_format_instructions()` class method for generating JSON format prompts

**3. Prompt Architecture**

- System instruction + Human message separation using `ChatPromptTemplate.from_messages()`
- **Custom format instructions** instead of `JsonOutputParser.get_format_instructions()` for better compatibility
- Supports template variables with proper escaping

**4. Fixed Issues**

- **ImportError**: Replaced `from langchain.output_parsers import JsonOutputParser` with custom format instructions
- **Double prompt wrapping**: Removed `ChatPromptTemplate` from individual modules, centralized in `llm_client.py`
- **LLM connection on import**: Implemented lazy loading to defer model initialization
- **response_format compatibility**: Added try/except in `_create_chat_openai()` to handle servers that don't support JSON mode
- **AttributeError**: Pre-initialized `model_name` and `base_url` attributes in `__init__`

### Results

| Metric | Value |
|--------|-------|
| Chips Processed | 40+ |
| Requirements Managed | 2000+ |
| Product Lines | 7 (BMS, EC, MCU, PD, PPG, HUB, Signal Chain) |
| Classification Accuracy | 80%+ |
| Efficiency Improvement | 3x (2-3 days → hours per chip) |

---

## 🇨🇳 中文 <a id="chinese"></a>

### 系统简介

SemiReq-Hub（智能需求生命周期追溯系统）利用大语言模型自动化芯片需求工程中最繁琐的工作：

1. **智能分类** — 将需求自动归类到 8 大维度 × 200+ 节点的分类目录
2. **模板匹配** — 将需求与母版模板库匹配，自动提取变量参数
3. **追溯补全** — 建立 L1(客户需求)→L2(初始需求)→L3(系统需求) 三级追溯链
4. **可视化导出** — 生成格式化 Excel 报表，含统计概览

### 技术栈

| 层次 | 技术 |
|------|------|
| 语言 | Python 3.10+ |
| LLM 框架 | **LangChain 0.2+** |
| LLM | DeepSeek-R1 / Qwen（OpenAI 兼容接口） |
| 数据处理 | OpenPyXL (Excel), JSON |
| 并发 | ThreadPoolExecutor |
| 日志 | 自研审计追踪系统 |

### 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置 LLM
#    通过环境变量设置 MODEL_CHOICE: "local", "siliconflow", 或 "auto"
#    通过环境变量设置 API Key

# 3. 测试连接
python src/llm_client.py

# 4. 演示模式
python main.py --demo

# 5. 批量处理（将 Excel 文件放入 data/）
python main.py
```

### 核心亮点

- **三级 LLM 提示词架构**：维度级→能力域级→需求项级的级联分类
- **双模型支持**：本地模型与 SiliconFlow 云 API 自动切换
- **并发处理**：6 线程并发 AI 调用，指数退避重试
- **断点续传**：分类缓存避免重复调用 LLM
- **人机协同**：完整的审计追踪，每次 AI 决策可追溯
- **模板库**：参数化需求模板 + 变量自动提取

### 处理效果

| 指标 | 数值 |
|------|------|
| 处理芯片数 | 40+ |
| 管理需求数 | 2000+ |
| 覆盖产品线 | 7 条 (BMS, EC, MCU, PD, PPG, HUB, 信号链) |
| 分类准确率 | 80%+ |
| 效率提升 | 3倍（单芯片 2-3天 → 数小时） |

### 项目背景

本项目诞生于芯片设计公司的真实痛点：需求文档格式不统一、分类靠人工、追溯链断裂。实习生独立完成从需求分析 → 系统设计 → 编码实现 → 落地推广的全流程。

---

## License

MIT License

## Author

**Chen Mo (陈默)** — *Intern, System Engineering*

- Project Period: 2026.04 - 2026.07# IRLT
