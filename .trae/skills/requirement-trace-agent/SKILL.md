---
name: "requirement-trace-agent"
description: "半导体需求追溯链系统。处理芯片需求Excel，执行智能分类、模板匹配、拓扑补全和可视化。当用户需要处理需求数据、生成追溯链矩阵或运行需求清洗流水线时调用。"
---

# 需求追溯链 Agent

## 功能概述

该 Agent 是一个半导体芯片需求追溯链管理系统，具备以下核心能力：

1. **智能需求分类** - 基于LLM对需求文本进行L1/L2/L3层级分类
2. **模板匹配与变量提取** - 将需求文本与预定义模板匹配，提取关键参数
3. **拓扑链路补全** - 自动检测并补全缺失的需求层级（L1→L2→L3）
4. **追溯链可视化** - 生成Excel预览和追溯链图表
5. **批量数据处理** - 支持从Excel文件批量导入和处理需求

## 触发场景

当用户需要以下操作时调用此技能：

- 处理芯片需求Excel文件
- 生成需求追溯链矩阵
- 运行需求清洗流水线
- 进行需求分类或模板匹配
- 补全缺失的需求层级

## 核心模块

| 模块 | 功能 |
|------|------|
| `CategorizationModule` | 需求智能分类（L1/L2/L3） |
| `TemplateMatchingModule` | 模板匹配与变量提取 |
| `TopologyCompletionModule` | 追溯链拓扑补全 |
| `VisualizationModule` | Excel预览与图表生成 |
| `SpecDataProvider` | 规范JSON数据驱动 |

## 使用方式

### 方式一：处理单条需求

```python
from agent_entry import process_single_requirement

result = process_single_requirement(
    requirement_text="运行功耗<3mA，休眠功耗<10μA",
    requirement_id="REQ_DEMO_001",
    product_line="MCU",
    chip_info="CS8M320"
)
```

### 方式二：批量处理Excel文件

```python
from agent_entry import process_batch

# 处理 data/ 目录中的所有Excel文件
process_batch()

# 或指定数据目录
process_batch(data_dir="raw_data")
```

### 方式三：生成追溯链矩阵

```python
from agent_entry import generate_trace_matrix

# 自动处理 raw_data 中的文件并生成聚合链矩阵
generate_trace_matrix()
```

## 数据流程

```
输入Excel → 需求提取 → 智能分类 → 模板匹配 → 拓扑补全 → 可视化输出
    ↓              ↓           ↓           ↓           ↓
  raw_data     L1/L2/L3     变量提取    补全缺失    output/
```

## 目录结构

```
IRLT_V4/
├── raw_data/          # 原始需求Excel输入
├── raw_out/           # 预处理输出（聚合链矩阵）
├── data/              # 中间数据
├── data/config/       # 配置文件（分类、模板、规范）
├── output/            # 最终输出
├── output/classify/   # 分类缓存
├── output/library/    # 模板库
└── Audit_Records/     # 审计日志
```

## 依赖要求

- Python 3.10+
- pandas
- openpyxl
- openai
- tqdm

## 注意事项

1. 首次运行需要配置 LLM 客户端（见 `src/llm_client.py`）
2. 需要在 `data/config/` 目录放置分类和模板配置文件
3. 输入Excel文件需遵循命名规范：`{产品线}_{芯片名} - {需求类型}.xlsx`

## 输出文件

处理完成后会生成：
- Excel预览文件（需求明细）
- 追溯链文本图（层级关系）
- 分类缓存（JSON格式）
- 审计日志（处理记录）
