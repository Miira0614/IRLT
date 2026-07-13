# 需求数据清洗与模板生成系统 - 设计说明文档 V4.1

## 📋 目录

1. [系统概述](#1-系统概述)
2. [项目结构与文件组织](#2-项目结构与文件组织)
3. [数据加工流水线](#3-数据加工流水线)
4. [核心模块设计](#4-核心模块设计)
5. [数据模型定义](#5-数据模型定义)
6. [处理规则说明](#6-处理规则说明)
7. [输出格式规范](#7-输出格式规范)
8. [日志与审计追踪系统](#8-日志与审计追踪系统)
9. [人工审核功能](#9-人工审核功能)
10. [目录ID管理系统](#10-目录id管理系统)
11. [规范驱动架构](#11-规范驱动架构-v41新增)
12. [API 接口设计](#12-api-接口设计)
13. [前端界面设计](#13-前端界面设计)
14. [Docker 部署设计](#14-docker-部署设计)
15. [扩展与维护](#15-扩展与维护)

***

## 1. 系统概述

### 1.1 核心定位

本系统旨在将 LLM 作为"超级数据清洗工具和提取器"，对多源原始需求数据进行结构化加工，最终构建**产品线标准化需求模板库（母版库）与**芯片级高精细度需求实例库。

### 1.2 输入数据源

系统标准的输入源为 Excel 表格流。其典型数据结构如下：

| ID     | 需求              | 最终优化后的需求描述             | 优化项序号    |
| :----- | :-------------- | :--------------------- | :------- |
| 209685 | 功耗： 运行功耗<3mA... | 运行功耗<3mA，休眠功耗<10μA（系统） | 209685-1 |

- **列过滤规则**：系统完全忽略 `ID` 列和 `系统需求` 列。在某些输入源中，前两列可能完全缺失，系统需直接以 `最终优化后的需求描述` 列和 `优化项序号` 列作为合法输入入口。
- **需求层级结构**：需求划分为 L1（客户需求）、L2（初始需求）、L3（系统需求）三级。在输入数据中，这些层级通常呈扁平化并列排布，系统需利用 LLM 依据语义重建其级联拓扑链，若存在层级缺失，则由 LLM 启动双向推理自动补全。

### 1.3 最终交付物

- **`Master_Requirement_Templates.json`**：标准母版库。包含产品线的参数化需求母版，按目录分类存储，每个目录下包含多个具有变量占位符的通用模板。
- **`output/library/`（待定模板缓存库）**：存储针对具体芯片/项目落地实施后的待定模板快照，记录变量的实际提取值，并维护动态的业务追溯链。

### 1.4 日志与审计控制

系统引入全局日志与审计模块（Log Module），对数据加工流水线中的每一次 LLM 推理、参数抽取、拓扑补全以及人工覆盖（Override）进行全生命周期痕迹保留，确保芯片需求变更的每一项指标均可溯源。

***

## 2. 项目结构与文件组织

```
New_IRLT/
├── Audit_Records/                    # 审计记录目录
├── complete_data/                    # 完整模板补充输入目录
├── conplete_out/                     # 完整模板补充输出目录
├── data/                             # 数据目录（原子需求包数据目录）
│   ├── config/                       # 配置文件目录
│   │   ├── 芯片需求结构化定义规范V4.0.json    # 🆕 规范定义（唯一数据源，categories由此派生）
│   │   ├── categories.dbV4.1.json            # 分类目录（V4.1起由系统自动维护）
│   │   ├── Master_Requirement_Templates.json # 静态母版库
│   │   └── .spec_hash               # 🆕 规范文件哈希（变更检测）
│   └── 已处理数据集/                  # 已处理数据集目录
├── output/                           # 通用输出目录
│   ├── classify/                     # 分类缓存目录
│   ├── library/                      # 待定模板缓存目录
│   └── 历史文件/                     # 历史输出文件目录
├── raw_data/                         # 原始需求包数据目录
├── raw_out/                          # 需求表格预处理输出目录
├── script/                           # 辅助脚本目录
│   ├── sync_config.py               # 🆕 规范配置同步工具
│   ├── extract_doc_text.py          # 🆕 .doc规范书文本提取
│   ├── 完整模板补充.py                # 完整模板补充脚本
│   └── 需求表格预处理.py              # 需求表格预处理脚本
├── src/                              # 核心模块源码目录
│   ├── categorization_module.py      # 智能目录归仓模块
│   ├── data_models.py                # 数据模型定义
│   ├── spec_data_provider.py        # 🆕 规范数据提供者
│   ├── __init__.py                   # 包导出定义
│   ├── logging_audit_module.py       # 日志与审计模块
│   ├── llm_client.py                 # LLM客户端
│   ├── pipeline.py                   # 数据加工流水线主控模块
│   ├── template_matching_module.py   # 模板匹配与变量提取模块
│   ├── topology_completion_module.py # 拓扑链路补全模块
│   └── visualization_module.py       # 可视化预览模块
├── api/                              # 🆕 API 接口目录
│   ├── main.py                       # FastAPI 主入口
│   ├── schemas.py                    # Pydantic 数据模型
│   └── routers/                      # 路由模块
│       ├── requirements.py           # 需求处理路由
│       ├── files.py                  # 文件管理路由
│       ├── stats.py                  # 统计信息路由
│       └── config.py                 # 系统配置路由
├── frontend/                         # 🆕 前端界面目录
│   └── app.py                        # Streamlit 主应用
├── .streamlit/                       # 🆕 Streamlit 配置目录
│   ├── config.toml                   # 配置文件
│   └── credentials.toml              # 凭据配置
├── .trae/                            # 🆕 TRAE 技能目录
│   └── skills/
│       └── requirement-trace-agent/  # 需求追溯链技能
│           ├── SKILL.md              # 技能描述
│           └── agent_entry.py        # 技能入口
├── main.py                           # 统一主入口
├── requirements.txt                  # Python依赖清单
├── Dockerfile                        # 🆕 Docker 镜像构建文件
├── docker-compose.yml                # 🆕 Docker Compose 配置
└── SYSTEM_DESIGN-V4.0.md             # 系统设计文档
```

**主入口命令行参数**：

| 参数 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `--demo` | 运行演示模式（处理单条示例需求） | 否 |
| `--no-template` | 跳过模板匹配（仅执行分类） | 否 |
| `--data-dir` | 指定数据目录 | `data/` |

**使用示例**：
```bash
# 批量处理 data/ 目录下的所有Excel文件
python main.py

# 演示模式（处理单条示例需求）
python main.py --demo

# 跳过模板匹配，仅执行分类
python main.py --no-template

# 指定数据目录
python main.py --data-dir data/已处理数据集
```

***

## 3. 数据加工流水线

### 3.1 整体流程

```
┌─────────────────────────────────────────────────────────────────┐
│                         数据加工流水线                         │
├─────────────────────────────────────────────────────────────────┤
│  需求条目输入 (已具备基本断句的 Excel/数据流)                    │
│       ↓                                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 第一步：智能目录归仓（分类模块）                             │    │
│  │  - 依据 product_line 检索对应 category_db 目录树            │    │
│  │  - LLM 语义识别，直接绑定三级目录的 category_uid            │    │
│  │  - 支持分类缓存，避免重复计算                               │    │
│  └─────────────────────────────────────────────────────────┘    │
│       ↓                                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 第二步：需求模板匹配与变量抽离（清洗匹配模块）              │    │
│  │  - 对所有实例进行模板匹配                                   │    │
│  │  - 命中模板：提取变量值填入实例，绑定 template_id           │    │
│  │  - 未命中：LLM 公式化提炼参数，生成【待定新模板】            │    │
│  │  - 待定模板即时保存到 output/library/                       │    │
│  └─────────────────────────────────────────────────────────┘    │
│       ↓                                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 第三步：基于模板追溯链自动建立需求追溯链                    │    │
│  │  - 通过 parent_template_id 递归向上查找父级模板             │    │
│  │  - 通过 child_template_ids 递归向下查找子级模板            │    │
│  │  - 自动创建对应的需求实例并建立追溯链                        │    │
│  └─────────────────────────────────────────────────────────┘    │
│       ↓                                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 第四步：LLM拓扑链路检测与智能补全（两阶段架构）              │    │
│  │  - 阶段一：LLM分析识别追溯关系与动态层级调整                  │    │
│  │  - 阶段一b：脚本确定性计算缺失需求                          │    │
│  │  - 阶段二：逐条调用LLM生成缺失需求文本                       │    │
│  │  - 阶段三：脚本组装完整L1→L2→L3链路                         │    │
│  └─────────────────────────────────────────────────────────┘    │
│       ↓                                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 第五步：清理重复的孤立需求                                  │    │
│  └─────────────────────────────────────────────────────────┘    │
│       ↓ 【生成内容可视化】                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ ★ 第六步：生成内容可视化（导出预览 Excel）                   │    │
│  │  - 将内存中的结构化数据动态渲染为多维 Excel 表格            │    │
│  │  - 【高亮标记】：用不同底色区分人工输入与 AI 自动补全的数据  │    │
│  │  - 【链路连线】：在 Excel 中直观展示 L1-L2-L3 的层级对齐关系 │    │
│  │  - 生成追踪链关系图和统计概览                              │    │
│  └─────────────────────────────────────────────────────────┘    │
│       ↓                                                         │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 人工统一审核（Human-in-the-Loop）                          │    │
│  │  - 工程师基于导出的预览 Excel 或系统前端界面进行核对与修改   │    │
│  └─────────────────────────────────────────────────────────┘    │
│       ↓                                                         │
│  三轨数据持久化分流（Data Branching）                          │
├─────────────────┬─────────────────┬──────────────────────────────┤
│ 💾 路径 A       │ 💾 路径 B       │ 💾 路径 C                    │
│ 需求实例保存     │ 待定模板缓存     │ 审计日志记录                 │
│ (instances_     │ ({product_line}_│ (pipeline_run_xxx.log)       │
│ xxx.json)       │ {chip}_pending. │                              │
│                 │ json)           │                              │
└─────────────────┴─────────────────┴──────────────────────────────┘
```

### 3.2 流水线主控类

`DataProcessingPipeline` 类是整个流水线的核心，负责协调各模块的执行：

```python
class DataProcessingPipeline:
    def __init__(
        self,
        category_db_path: str,           # 分类数据库路径
        templates_path: str,             # 模板库路径
        llm_client,                      # LLM客户端实例
        audit_records_dir: str = "Audit_Records",
        output_dir: str = "output",
        template_library_dir: str = "output/library"
    )
```

**核心方法**：

- `process_single_requirement()` - 处理单条需求
- `process_batch()` - 批量处理需求（主入口）

**批量处理流程**（`process_batch`）：

1. 加载分类缓存
2. 第一步：分类归仓（`_categorize_only`）
3. 保存分类缓存
4. 第二步：模板匹配（`_run_template_matching_batch`），支持待定模板缓存跳过
5. 第三步：基于模板追溯链建立需求追溯链（`_build_trace_chain_from_templates`）
6. 第四步：拓扑链路检测与补全（`_run_topology_completion`）
7. 第五步：清理重复的孤立需求
8. 第六步：可视化预览（`_run_visualization`）

***

## 4. 核心模块设计

### 4.1 智能目录归仓模块 (CategorizationModule)

- **功能职责**：作为流水线的第一步，直接接收输入的需求文本，利用 LLM 将其快速归入标准的三级目录中，实现“数据定位”。
- **位置**：`src/categorization_module.py`
- **处理逻辑**：
  1. 从 `data/config/categories.dbV4.1.json` 中检索并加载对应的树状目录树。
  2. 配合专有 Prompt 将目录结构作为上下文喂给 LLM。
  3. LLM 进行语义推理，直接匹配到最精确的三级标题（x.x.x），并返回关联的 `category_uid`、`confidence` 和 `requirement_level`。
  4. **置信度阈值**：置信度低于 0.6 标记为分类失败。
  5. **异常处理**：若语义模糊导致无法分类，状态标记为 `"cat_failed"`，直接挂起流转至后续人工审核。

**关键方法**：

- `categorize()` - 单条需求分类
- `categorize_batch()` - 批量分类

**Prompt 设计**：

```python
SYSTEM_INSTRUCTION = """你是一个半导体芯片需求工程专家。
你的任务是将输入的需求文本分类到精确的三级目录中，并判断需求层级。
...
"""

PROMPT_TEMPLATE = """## 可用分类目录
{category_tree}

## 待分类需求文本
{requirement_text}

## 产品线
{product_line}

请返回一个JSON对象，包含以下字段：
- "category_uid": 匹配的三级分类UID
- "confidence": 分类置信度（0-1之间的浮点数）
- "requirement_level": 需求层级（L1、L2或L3）
"""
```

### 4.2 清洗匹配模块 (TemplateMatchingModule)

- **功能职责**：在选定的分类目录下进行高效率的模板对撞与参数提取。
- **位置**：`src/template_matching_module.py`
- **处理逻辑**：
  1. **缩小检索域**：系统仅提取 `data/config/Master_Requirement_Templates.json` 中属于当前 `category_uid` 且适用该产品线的通用模板子集。
  2. **命中（Match）**：LLM 进行语义匹配，若命中已有模板，LLM 提取文本中的具体数值参数，按标准键值对存入 `extracted_variables`，并绑定 `matched_template_id`。
  3. **部分命中（Partial Match）**：LLM 进行语义匹配，若仅匹配到模板的部分内容，LLM 提取文本中的具体数值参数，按标准键值对存入 `extracted_variables`，并绑定 `matched_template_id`。
  4. **未命中（Miss）**：若判定为新需求类型，LLM 启动“公式化提炼”，自动识别数值参数并将其抽象为占位符 `${variable_name}`，定义其类型、单位与 Label，生成一个\*\*【待定新模板】\*\*暂存至内存。

**关键方法**：

- `match()` - 单条需求模板匹配
- `_create_new_template()` - 创建新的待定模板
- `save_pending_templates_by_product()` - 按产品线保存待定模板
- `load_pending_templates_by_product()` - 从缓存加载待定模板（支持跳过匹配）
- `set_current_product_info()` - 设置当前产品信息（用于即时保存）

**变量提取规则**：

- 变量名必须采用小写蛇形命名法（snake\_case），如 `sleep_ua`、`wakeup_time_us`
- 必须严格分离数值与单位，严禁将单位揉入变量值中

### 4.3 基于模板追溯链的需求追溯链建立模块

- **功能职责**：利用模板库中已有的 `parent_template_id` 和 `child_template_ids` 关系，自动为需求实例建立追溯链。
- **位置**：`src/pipeline.py` 中的 `_build_trace_chain_from_templates()` 方法

**处理逻辑**：

1. 获取所有模板，构建模板ID到模板的映射
2. 对每个匹配到模板的需求实例，递归处理其父级和子级模板
3. 通过 `_create_parent_requirements()` 向上递归创建父级需求
4. 通过 `_create_child_requirements()` 向下递归创建子级需求
5. 通过 `_link_parent_child()` 建立父子需求之间的追溯链关系

### 4.4 双向拓扑链路检测与智能补全模块 (TopologyCompletionModule)

- **功能职责**：扫描当前芯片的需求包，检测并修复上下级追踪链（Trace Chain）不全的问题；在没有任何显式 ID 亲缘关联的场景下，通过语义推理进行“拓扑解耦与骨架重组”。
- **位置**：`src/topology_completion_module.py`
- **两阶段架构**：

**阶段一：LLM 分析识别**

- 分析已有需求之间的语义关联
- 动态调整需求层级（`level_adjustments`）
- 识别追溯链（`trace_chains`）

**阶段一b：脚本确定性计算缺失需求**

- 根据 trace\_chains 中的空位，自动计算需要补全的需求
- 支持同一层级多个ID用逗号分隔的格式（如 "L2-001,L2-002"）
- 处理规则：
  - L2 需要补 L1 的情况
  - 每个 L2 需要补 L3 的情况
  - L3 需要补 L2 的情况
  - 孤立的已有需求（不在任何 trace\_chain 中）

**阶段二：逐条调用 LLM 生成缺失需求文本**

- 根据上下文和分类路径，生成缺失需求的具体文本
- 遵循反向生成原则、层级递进原则、内容相关原则

**关键方法**：

- `analyze()` - 阶段一：LLM分析识别
- `_analyze_in_batches()` - 分批分析（超过40条需求自动分批）
- `_filter_invalid_chains()` - 过滤无效追溯链
- `_merge_chains_by_l1()` - 按层级合并追溯链

### 4.5 生成内容可视化模块 (VisualizationModule)

- **功能职责**：在人工审核前，将内存中复杂的拓扑数据结构转换为用户最直观的交互媒介。
- **位置**：`src/visualization_module.py`
- **处理逻辑**：
  1. 读取当前批次处理完成的动态列表。
  2. 调用 Excel 渲染引擎（openpyxl），利用 `instance_trace_chain` 的对应关系，将 L1-L2-L3 需求在表格中按级联顺序、递进缩进排列。
  3. 根据 `generation_type` 属性进行**色彩硬编码**：
     - `#BDD7EE`（浅蓝）：AI 生成的数据行
     - `#FFF2CC`（浅黄）：需求包中提取的真实需求数据行
  4. 将带有变量提取明细、模板绑定状态的预览 Excel 导出供用户下载。
  5. 生成追踪链关系图（文本格式）。
  6. 生成统计概览。

**关键方法**：

- `render_to_excel()` - 渲染需求数据到Excel（包含"需求详情"和"统计概览"两个工作表）
- `render_trace_chain_diagram()` - 生成追踪链关系图
- `generate_summary_stats()` - 生成汇总统计信息

### 4.6 日志与审计追踪模块 (LoggingModule & ConsoleLogger)

- **功能职责**：全局横切模块（AOP 面向切面设计）。负责捕获数据流转全过程中的关键行为，并将其转化为不可篡改的日志审计记录。
- **位置**：`src/logging_audit_module.py`
- **处理逻辑**：
  1. **统一日志输出**：集成标准库 logging，确保本地 `.log` 文件与终端控制台输出完全一致（包含报错堆栈）。
  2. **日志格式**：`[时间戳] [日志等级] [模块] [实体ID] 描述`
  3. **结构化审计记录**：将变更明细、处理耗时、Token 消耗及修改人标识实时写入 `Audit_Records/`。
  4. **持久化**：保存文本日志。

**关键方法**：

- `log_info()` / `log_error()` / `log_warning()` - 日志输出
- `create_audit_log()` - 创建结构化审计记录
- `log_categorization()` - 记录分类操作
- `log_template_match()` - 记录模板匹配操作
- `log_topology_completion()` - 记录拓扑补全操作
- `log_human_override()` - 记录人工覆盖操作

### 4.7 LLM 客户端模块 (SemiReqLLMClient)

- **功能职责**：提供统一的 LLM 调用接口，支持本地模型和云端模型自动切换。
- **位置**：`src/llm_client.py`
- **配置选项**：
  - `MODEL_CHOICE = "siliconflow"` - 优先使用 SiliconFlow
  - `MODEL_CHOICE = "local"` - 优先使用本地模型
  - `MODEL_CHOICE = "auto"` - 自动选择（优先本地，失败回退到 SiliconFlow）

**关键方法**：

- `request_json_output()` - 请求 JSON 格式输出（核心方法）
- `generate()` - 请求文本生成
- `_fallback_to_siliconflow()` - 失败回退到 SiliconFlow
- `_handle_rate_limit()` - 处理限流（指数退避重试）

***

## 5. 数据模型定义

### 5.1 变量定义模型 (Variable)

```python
@dataclass
class Variable:
    name: str       # 变量名（小写下划线蛇形）
    type: str       # number, string, enum
    label: str      # 业务直观标签
    unit: str       # 物理单位
```

### 5.2 目录分类库模型 (CategoryNode)

```python
@dataclass
class CategoryNode:
    uid: str                # 分类UID（如 cat_de332f）
    id: str                 # 分类编号（如 "2.1", "3.2.1"）
    name: str               # 分类名称
    level: int              # 层级（1, 2, 3）
    parent_uid: str         # 父级UID
    children: List[str]     # 子级UID列表
    description: str = ""   # 描述
    applicable_lines: List[str] = field(default_factory=list)  # 适用产品线
```

**分类数据库管理器** (`CategoryDatabase`)：

- `__init__(db_path)` - 加载分类数据库
- `get_category(uid)` - 获取指定UID的分类节点
- `get_level3_categories()` - 获取所有3级分类节点
- `get_category_by_id(category_id)` - 根据分类编号查找分类节点
- `build_category_tree_string()` - 构建用于LLM上下文的三级目录树字符串

### 5.3 静态母版库模型 (RequirementTemplate)

```python
@dataclass
class RequirementTemplate:
    template_id: str                    # 模板ID（如 TPL_L3_00001）
    level: str                          # L1, L2, L3
    category_uid: str                   # 所属分类UID
    templates_text: str                 # 模板文本（含变量占位符）
    product_lines: List[str]            # 适用产品线列表
    variables: List[Dict[str, Any]]     # 变量定义列表
    template_trace_chain: Dict[str, Any] # 模板追溯链
    parent_template_id: str = ""        # 父级模板ID
    child_template_ids: List[str] = field(default_factory=list) # 子级模板ID列表
    version: str = "V1.0.0"             # 版本号
    created_at: str = ""                # 创建时间
    updated_at: str = ""                # 更新时间
```

**母版库管理器** (`MasterTemplateLibrary`)：

- `__init__(templates_path)` - 加载母版库
- `save()` - 保存母版库到JSON文件
- `add_template(template)` - 添加新模板
- `get_templates_by_category(category_uid)` - 获取指定分类下的所有模板
- `get_templates_by_product_line(product_line)` - 获取适用于指定产品线的所有模板

### 5.4 动态需求实例模型 (RequirementInstance)

```python
@dataclass
class RequirementInstance:
    requirement_instance_id: str          # 需求实例ID
    requirement_text: str                 # 需求文本
    requirement_type: str                 # L1, L2, L3
    category_uid: str                     # 分类UID
    matched_template_id: str = ""         # 匹配的模板ID
    extracted_variables: Dict[str, Any] = field(default_factory=dict) # 提取的变量
    instance_trace_chain: Dict[str, Any] = field(default_factory=dict) # 实例追溯链
    generation_type: str = "manual"       # manual, ai_generated, template_generated
    review_status: str = "pending_review" # pending_review, approved, rejected
    product_line: str = ""                # 产品线
    chip_info: str = ""                   # 芯片信息
    confidence: float = 0.0               # 分类置信度
```

### 5.5 待定新模板模型 (PendingTemplate)

```python
@dataclass
class PendingTemplate:
    template_id: str                    # 模板ID（如 PENDING_xxx）
    level: str                          # L1, L2, L3
    category_uid: str                   # 所属分类UID
    templates_text: str                 # 模板文本
    product_lines: List[str]            # 适用产品线列表
    variables: List[Dict[str, Any]]     # 变量定义列表
    parent_template_id: Optional[str] = None # 父级模板ID
    created_at: str = ""                # 创建时间
```

### 5.6 审计日志数据模型 (AuditLog)

```python
@dataclass
class AuditLog:
    audit_log_id: str                  # 审计日志ID
    timestamp: str                     # 时间戳
    operator: str                      # 操作人（AI_ENGINE_V2 / Human）
    requirement_instance_id: str       # 关联的需求实例ID
    action: str                        # 操作类型（CATEGORIZATION_SUCCESS, TEMPLATE_FULL_MATCH等）
    module: str                        # 所属模块
    change_detail: Dict[str, Any]      # 变更明细（before/after）
    metadata: Dict[str, Any] = field(default_factory=dict) # 元数据（模型名称、Token消耗等）
```

***

## 6. 处理规则说明

### 6.1 数据过滤与原子映射规则

规则 6.1.1：完全忽略原始 Excel 输入中的“ID”和“系统需求”两列。唯一合法的文本入口为“最终优化后的需求描述”列，唯一索引依据为“优化项序号”列。

规则 6.1.2：若输入行缺乏“优化项序号”，系统采用 \[文件名简写]-\[自增序号] 规则自动回填，确保需求实例标识符的唯一性。

### 6.2 变量抽离与公式化规则

规则 6.2.1：LLM 提炼变量名必须采用小写蛇形命名法（snake\_case），如 `sleep_ua`、`wakeup_time_us`。

规则 6.2.2：必须严格分离数值与单位，严禁将单位揉入变量值中（例如：禁止出现 `"current_mA": "3mA"`，必须规范为 `"current_mA": "3"`，单位由模板定义）。

### 6.3 双向链路补全规则

系统在完成初步分类与模板匹配后，必须触发拓扑结构完整性检查。AI 的补全策略遵循以下双向规则：

**前向追溯（向上补齐）**：当输入数据仅包含 L3 级具体技术指标，但所属 product\_line 在当前上下文中无法关联到任何 L1 或 L2 节点。LLM 将分析 L3 的技术边界，反推其背后的系统级低功耗控制策略（L2）或最终客户应用场景（L1）。

**后向分解（向下补全）**：当输入数据中包含高层级的 L1 或 L2 描述，但缺乏能够指导设计和验证的 L3 级具体参数。LLM 将检索 category\_db 确定该 L2 所属的三级目录，并根据当前产品限制和工艺基准，向后生成若干条具体的 L3 需求，并自动重新触发模板匹配模块。

规则 6.3.1（独立编号语义织网原则）：即使输入的 L1、L2、L3 需求条目在原始 Excel 中的 ID 编码、序号完全独立、杂乱且在物理行上不相邻，系统亦严禁将其作为孤立长尾数据处理。必须依赖拓扑链路检测的语义推理能力，将扁平条目织成树状拓扑。

规则 6.3.2（模板父子绑定逆向回填规则）：在清洗匹配阶段未命中母版而触发“全新母版提炼”时，临时新母版的 `parent_template_id` 允许暂置为 `null`。当流水线流转至拓扑补全阶段并由 AI 织网引擎成功锁定其实例层面的父子关系后，系统必须逆向追溯，将新提炼的 L3 母版之 `parent_template_id` 强行覆盖回填为关联 L2 母版之 ID。此绑定关系随人工一键通过（Approved）后最终物理持久化至静态母版库。

### 6.4 层级定义规则

**L1 (客户需求)**：从最终用户或客户角度出发，用业务/商业语言描述"为什么需要这个产品"或"要达到什么商业目标"。通常不涉及技术实现细节。
示例："设备需要可靠运行"、"数据需要安全存储"、"要延长电池使用寿命"

**L2 (初始需求)**：将客户的商业愿望转化为产品经理视角的具体产品特征和目标描述（定性或半定量）。描述"需要什么功能/特性"，但不规定具体实现方案。
示例："系统应防止无响应"、"应确保数据不丢失"、"需支持低功耗模式"、"提供POR模块设计保障"

**L3 (系统需求)**：将产品需求完全量化、技术化，给出明确的、可测试、可验证的技术指标和实现约束。描述"具体如何实现"和"达到什么量化指标"。
示例："看门狗定时器超时时间为1秒"、"系统响应时间小于100ms"、"待机电流不超过1.9μA"、"数据保持时间大于10年"

***

## 7. 输出格式规范

### 7.1 数据多轨持久化规范

系统执行三路持久化分流写入：

**路径 A - 需求实例保存**：将所有需求实例保存到 `output/library/instances_{chip_info}_{timestamp}.json`，记录完整的需求文本、分类信息、追溯链和提取变量。

**路径 B - 待定模板缓存**：按产品线保存待定模板到 `output/library/{product_line}_{chip_info}_pending.json`，支持后续加载和审核。

**路径 C - 审计日志记录**：将所有操作记录写入 `Audit_Records/pipeline_run_YYYYMMDD_HHMMSS.log`，包含变更明细、处理耗时和Token消耗。

> **注**：母版库增量合入（将审核通过的新模板写入 `data/config/Master_Requirement_Templates.json`）需在人工审核确认后手动执行。

### 7.2 预览 Excel 格式规范

预览 Excel 包含两个工作表：

**工作表1：需求详情**

| 需求ID   | 层级     | 需求文本   | 分类名称   | 分类UID  | 置信度    | 父级需求   | 子级需求   | 生成类型   | 审核状态   | 产品线    |
| :----- | :----- | :----- | :----- | :----- | :----- | :----- | :----- | :----- | :----- | :----- |
| <br /> | <br /> | <br /> | <br /> | <br /> | <br /> | <br /> | <br /> | <br /> | <br /> | <br /> |

**工作表2：统计概览**（以L3为核心组织，显示完整追溯链）

| 需求维度   | 能力域    | 需求项    | 需求ID   | L1客户需求 | 需求ID   | L2初始需求 | 需求ID   | L3系统需求 | 需求追溯链  |
| :----- | :----- | :----- | :----- | :----- | :----- | :----- | :----- | :----- | :----- |
| <br /> | <br /> | <br /> | <br /> | <br /> | <br /> | <br /> | <br /> | <br /> | <br /> |

**高亮色标管理**：

- `#BDD7EE`（浅蓝）：AI 生成的数据行
- `#FFF2CC`（浅黄）：待审核的数据行

***

## 8. 日志与审计追踪系统

### 8.1 日志分级与控制台输出规范

系统运行日志采用标准时间戳 + 日志等级 + 模块标识 + 实体ID + 描述的形式进行流式输出：

```
[2026-06-01 11:15:51] [INFO] [Categorization] [REQ_L3_209685-1] 智能归仓成功, 分类UID: cat_e2bc87.
[2026-06-01 11:15:52] [INFO] [TemplateMatch] [REQ_L3_209685-1] 成功命中标准模板 TPL_L3_00001, 成功抽离变量: {current_mA: 3}.
[2026-06-01 11:15:53] [WARN] [TopologyCompletion] [REQ_L3_209685-1] 检测到 L3 追踪链断裂！启动前向追溯, AI 自动补全生成 L2 级父需求实例: REQ_L2_AI_GENERATED_9921.
[2026-06-01 11:20:11] [INFO] [HumanReview] [REQ_L3_209685-1] 接收到人工审核后的 Excel 反向导入。
[2026-06-01 11:20:12] [WARN] [HumanReview] [REQ_L3_209685-1] 检测到人工覆盖：将提取变量电流值从 30mA 纠正为 3mA。触发创建审计变更日志 LOG_20260601_00084。
```

### 8.2 审计记录持久化

审计记录以文本日志格式保存：

- **文本日志**：`Audit_Records/pipeline_run_YYYYMMDD_HHMMSS.log` - 实时记录所有操作

***

## 9. 人工审核功能 (Human-in-the-Loop)

### 9.1 交互与反馈闭环

```
 ┌─────────────────┐     导出预览     ┌──────────────────┐
 │ 第六步完毕的内存 │ ─────────────►   │  浅蓝/浅黄高亮    │
 │   结构化数据     │                 │   预览 Excel     │
 └─────────────────┘                 └──────────────────┘
```

**修改接受规则**：工程师可直接在导出的 Excel 中修改需求内容、调整章节分类（手动覆盖三级标题）。

***

## 10. 目录ID管理系统

### 10.1 UID 与 业务ID 解耦机制

核心原则：系统内部所有数据关联（模板引用、实例归仓）必须统一使用 `category_uid`（如 `cat_de332f`），绝对禁止直接绑定业务目录 ID（如 `2.1`、`2.1.3`）。

支撑逻辑：当企业规范变更需要将目录 `2.1` 变更为 `3.4` 时，只需修改 `category_db/` 中对应 UID 下的 `id` 和 `name` 属性。由于母版库和实例数据库均使用 `category_uid` 作为外键指针，整个系统的底层拓扑关系和历史数据无需进行任何迁移或重写，从而保障系统的可维护性。

***

## 11. 规范驱动架构（V4.1新增）

### 11.1 设计动机

V4.0 及之前版本存在以下痛点：
- `categories.dbV4.1.json` 和 `芯片需求结构化定义规范V4.0.json` 需要人工保持同步
- 规范书(.doc)更新后，配置文件的更新完全依赖人工
- 新增需求项分类后，需要手动创建对应的模板

V4.1 引入 **SpecDataProvider**，将规范JSON作为唯一数据源，分类目录自动派生。

### 11.2 数据流

```
芯片需求结构化定义规范书V4.1.doc
         │
         │  extract_doc_text.py (COM/LibreOffice)
         ▼
    规范书纯文本
         │
         │  LLM 解析 (一次性)
         ▼
芯片需求结构化定义规范V4.0.json  ←── 唯一数据源 (156 items)
         │
         │  SpecDataProvider (运行时自动派生)
         ├──────────────────────────────────
         ▼                                  ▼
  categories (内存, 209 nodes)    templates (3211: 3163 existing + 48 auto-gen)
         │                                  │
         │  仅发送紧凑目录树给LLM               │  仅发送当前分类模板给LLM
         │  (~7KB, 209行)                    │
         ▼                                  ▼
  CategorizationModule              TemplateMatchingModule
```

### 11.3 Token 效率分析

| 数据 | 大小 | 何时发送给LLM |
|------|------|--------------|
| 规范JSON完整文本 | ~100KB | **从不**发送给LLM |
| 分类目录树 | ~7KB / 209行 | 每次分类时（仅id+name+UID） |
| 单个分类的模板 | ~5-20条 | 模板匹配时（仅当前category_uid） |

### 11.4 UID 稳定性机制

- L3需求项：优先使用规范JSON中的 `uid` 字段
- L2能力域/L1维度：优先匹配已有 `categories.dbV4.1.json` 中的UID
- 无匹配时：基于 `(id, level)` 确定性生成（MD5 hash → 6字符短UID）
- UID在整个系统生命周期中保持稳定

### 11.5 模板增量策略

- **已有模板（3163个）**：完全不改动，保留人工维护成果
- **新分类（16个）**：从规范JSON的 L1/L2/L3 文本自动生成初始模板（48个）
- **孤立模板（5个）**：规范中已删除分类的模板 → 标记但不删除
- **模板文本变更**：不自动覆盖，需人工确认

### 11.6 规范变更检测

系统通过 `.spec_hash` 文件追踪规范JSON的变更：

```python
provider.check_spec_changed(hash_file_path)
# → (True, "规范文件已变更 (上次同步: 2026-07-03)")
# → (False, "规范文件未变更")
```

变更时：
- `main.py --check-spec` 显示警告
- `main.py --auto-sync` 自动接受变更并更新哈希
- `script/sync_config.py` 独立同步工具可预览差异后确认

***

## 12. API 接口设计

### 12.1 架构概述

系统提供基于 FastAPI 的 RESTful API 接口，支持需求处理、文件管理、统计查询等功能。

**技术栈：**
- FastAPI 0.100+
- Uvicorn ASGI 服务器
- Pydantic 数据验证
- CORS 跨域支持

### 12.2 目录结构

```
api/
├── main.py              # 应用主入口
├── schemas.py           # Pydantic 数据模型
└── routers/
    ├── requirements.py  # 需求处理路由
    ├── files.py         # 文件管理路由
    ├── stats.py         # 统计信息路由
    └── config.py        # 系统配置路由
```

### 12.3 路由设计

#### 需求处理路由 (`/api/requirements`)

| 路径 | 方法 | 功能 | 请求体 | 响应体 |
|------|------|------|--------|--------|
| `/process` | POST | 处理单条需求 | `RequirementInput` | `RequirementOutput` |
| `/batch` | POST | 批量处理需求 | `BatchProcessRequest` | `BatchProcessResponse` |
| `/trace-chain/{req_id}` | GET | 获取追溯链 | - | `ProcessResult` |

#### 文件管理路由 (`/api/files`)

| 路径 | 方法 | 功能 | 请求体 | 响应体 |
|------|------|------|--------|--------|
| `/upload` | POST | 上传Excel文件 | `UploadFile` | `FileUploadResponse` |
| `/list` | GET | 列出上传文件 | - | `{files: []}` |
| `/delete/{filename}` | DELETE | 删除文件 | - | `{success: bool}` |
| `/process-excel` | POST | 处理Excel | `UploadFile` | `TraceMatrixResponse` |
| `/generate-trace-matrix` | POST | 生成追溯链矩阵 | - | `TraceMatrixResponse` |
| `/download/{filename}` | GET | 下载文件 | - | 文件流 |

#### 统计信息路由 (`/api/stats`)

| 路径 | 方法 | 功能 | 参数 | 响应体 |
|------|------|------|------|--------|
| `/` | GET | 获取系统统计 | - | `StatsResponse` |
| `/categories` | GET | 获取分类列表 | `level` | `List[CategoryInfo]` |
| `/categories/{uid}` | GET | 获取分类详情 | `uid` | `CategoryInfo` |
| `/templates` | GET | 获取模板列表 | `level`, `category_uid` | `List[TemplateInfo]` |
| `/audit-records` | GET | 获取审计记录 | - | `{records: []}` |

#### 系统配置路由 (`/api/config`)

| 路径 | 方法 | 功能 | 响应体 |
|------|------|------|--------|
| `/` | GET | 获取系统配置 | `{}` |
| `/spec` | GET | 获取规范信息 | `{}` |
| `/sync` | POST | 同步配置 | `{}` |
| `/llm` | GET | 获取LLM配置 | `{}` |
| `/health` | GET | 详细健康检查 | `{}` |

### 12.4 数据模型

#### RequirementInput

```python
{
    "requirement_text": str,        # 需求文本
    "requirement_id": str | None,   # 需求ID（可选）
    "product_line": str,            # 产品线（默认MCU）
    "chip_info": str | None         # 芯片信息（可选）
}
```

#### RequirementOutput

```python
{
    "requirement_instance_id": str,
    "requirement_text": str,
    "requirement_type": str,        # L1/L2/L3
    "category_uid": str,
    "category_name": str | None,
    "confidence": float,
    "matched_template_id": str | None,
    "extracted_variables": dict | None,
    "product_line": str | None,
    "chip_info": str | None
}
```

### 12.5 API 文档

- **交互式文档**: `/docs` (Swagger UI)
- **Redoc 文档**: `/redoc`

***

## 13. 前端界面设计

### 13.1 技术栈

- **框架**: Streamlit 1.50+
- **样式**: Streamlit 原生组件
- **数据交互**: RESTful API (requests)
- **布局**: 侧边栏导航 + 主内容区

### 13.2 页面结构

```
frontend/
└── app.py              # Streamlit 主应用
```

### 13.3 页面功能

#### 首页

- 系统概览（分类数、模板数统计）
- 系统健康检查状态
- 快捷入口按钮

#### 需求处理页面

- 单条需求处理（输入需求文本、产品线、芯片信息）
- 批量需求处理（多行输入）
- 处理结果展示（分类、匹配模板、提取变量）

#### 文件管理页面

- Excel文件上传（支持多文件）
- 文件列表展示与删除
- 一键生成追溯链矩阵

#### 统计信息页面

- 系统统计指标展示
- 分类列表（支持层级筛选）
- 审计记录查看

### 13.4 启动方式

```bash
streamlit run frontend/app.py
```

**访问地址**: http://localhost:8501

***

## 14. Docker 部署设计

### 14.1 架构设计

```
┌──────────────────────────────────────────┐
│           Docker Compose                 │
├──────────────────┬───────────────────────┤
│    irlt-api      │    irlt-frontend      │
│  (FastAPI:8000)  │   (Streamlit:8501)   │
├──────────────────┼───────────────────────┤
│  src/            │  frontend/            │
│  api/            │  .streamlit/          │
│  script/         │                       │
├──────────────────┴───────────────────────┤
│              数据卷映射                   │
│  data/          → /app/data              │
│  raw_data/      → /app/raw_data          │
│  output/        → /app/output            │
│  Audit_Records/ → /app/Audit_Records     │
└──────────────────────────────────────────┘
```

### 14.2 Dockerfile

**基础镜像**: `python:3.12-slim`

**构建步骤**:
1. 安装系统依赖（gcc, g++）
2. 安装 Python 依赖
3. 复制项目文件
4. 创建必要目录
5. 设置环境变量
6. 暴露端口（8000, 8501）

### 14.3 docker-compose.yml

**服务定义**:

| 服务 | 端口 | 命令 |
|------|------|------|
| `api` | 8000 | `uvicorn api.main:app --host 0.0.0.0 --port 8000` |
| `frontend` | 8501 | `streamlit run frontend/app.py` |

**环境变量**:

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `MODEL_CHOICE` | `siliconflow` | LLM 模型选择 |
| `SILICONFLOW_API_KEY` | - | SiliconFlow API Key |
| `API_BASE_URL` | `http://api:8000` | 前端调用的 API 地址 |

**数据卷映射**:

| 本地目录 | 容器目录 | 用途 |
|---------|---------|------|
| `data/` | `/app/data` | 输入数据 |
| `raw_data/` | `/app/raw_data` | 原始需求包 |
| `raw_out/` | `/app/raw_out` | 预处理输出 |
| `output/` | `/app/output` | 处理结果 |
| `Audit_Records/` | `/app/Audit_Records` | 审计日志 |
| `complete_data/` | `/app/complete_data` | 完整模板输入 |
| `conplete_out/` | `/app/conplete_out` | 完整模板输出 |
| `api/uploads/` | `/app/api/uploads` | 上传文件 |
| `api/output/` | `/app/api/output` | API 输出 |

### 14.4 启动命令

```bash
# 构建镜像
docker-compose build

# 启动服务（后台运行）
docker-compose up -d

# 查看日志
docker-compose logs -f

# 停止服务
docker-compose down
```

***

## 15. 扩展与维护

### 12.1 缓存机制

**分类缓存**：分类结果缓存在 `output/classify/classification_cache_{product_line}.json`，避免重复调用 LLM。

**待定模板缓存**：待定模板按产品线保存到 `output/library/{product_line}_{chip_info}_pending.json`，支持后续加载跳过模板匹配流程。

### 12.2 容错与回退机制

**LLM 客户端容错**：

- 支持本地模型和 SiliconFlow 云端模型自动切换
- 限流处理：指数退避重试（最多5次）
- JSON 解析失败自动回退

**流水线容错**：

- 分类失败标记为 `cat_failed`，不中断后续流程
- 模板匹配失败自动创建待定模板
- 拓扑补全支持分批处理（超过40条自动分批）

***

## 📖 附录：辅助脚本说明

### script/完整模板补充.py

**功能**：将 `data/config/芯片需求结构化定义规范V4.0.json` 中的标准需求项与 Excel 预览文件进行对比，补充缺失的需求项。

**处理流程**：

1. 读取 `complete_data/` 目录下的 Excel 文件
2. 读取 `data/config/芯片需求结构化定义规范V4.0.json` 获取标准需求项
3. 按需求项序号进行版本排序合并
4. 将规范中存在但 Excel 中缺失的需求项添加到 Excel
5. 输出到 `conplete_out/` 目录

**路径配置**（使用相对路径）：

```python
script_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(script_dir)

data_dir = os.path.join(project_root, 'complete_data')
json_path = os.path.join(project_root, 'data', 'config', '芯片需求结构化定义规范V4.0.json')
out_dir = os.path.join(project_root, 'conplete_out')
```

### script/需求表格预处理.py

**功能**：对原始需求 Excel 表格进行标准化预处理，支持一体化大宽表解析和跨层级拓扑聚合。

**输入输出**：
- **输入目录**：`raw_data/` - 存放所有原始需求包 Excel 文件
- **输出目录**：`raw_out/` - 处理后的统一格式 Excel 输出，得到待原子化需求包 Excel 文件

**核心功能**：

1. **双轨血缘穿透**：支持 L1/L2/L3 三层需求的柔性对齐
2. **智能防文件占用**：自动检测文件占用并生成新文件名
3. **状态智能打标**：自动标记追溯链完整性状态
4. **两种处理模式**：
   - 一体化大宽表模式：直接解析包含所有层级的单文件
   - 分立子表模式：自动匹配客户需求/初始需求/系统需求文件并聚合

