from typing import List, Dict, Any, Tuple, Optional

from src.data_models import RequirementInstance
from src.logging_audit_module import ConsoleLogger


class TopologyCompletionModule:
    """
    需求追溯链补全模块
    
    核心功能：
    1. 分析已有需求之间的追溯关系（L1→L2→L3）
    2. 动态调整需求层级
    3. 识别并补全缺失的需求节点
    """

    ANALYZE_PROMPT = """## 任务：芯片需求跨层级追溯链提取与动态调整

你是一个经验丰富的半导体芯片需求工程专家。请分析当前分类【{category_name}】下的需求语义，识别它们之间的“抽象-具体”或“推导-实现”的追溯关系。

**层级定义**：
- L1 (客户需求): 从最终用户或客户角度出发，用业务/商业语言描述"为什么需要这个产品"或"要达到什么商业目标"。通常不涉及技术实现细节。
  示例："设备需要可靠运行"、"数据需要安全存储"、"要延长电池使用寿命"
- L2 (初始需求): 将客户的商业愿望转化为产品经理视角的具体产品特征和目标描述（定性或半定量）。描述"需要什么功能/特性"，但不规定具体实现方案。
  示例："系统应防止无响应"、"应确保数据不丢失"、"需支持低功耗模式"、"提供POR模块设计保障"
- L3 (系统需求): 将产品需求完全量化、技术化，给出明确的、可测试、可验证的技术指标和实现约束。描述"具体如何实现"和"达到什么量化指标"。
  示例："看门狗定时器超时时间为1秒"、"系统响应时间小于100ms"、"待机电流不超过1.9μA"、"数据保持时间大于10年"

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
核心规则
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1. **层级标签灵活处理**：不要被需求的初始层级标签（L1/L2/L3）死死限制。只要需求语义上存在抽象-具体关系，就应建立追溯链。
2. **跨层级串联**：允许且鼓励将原本错标为同级（例如两个都是L2）但实际有上下级关系的需求、以及原本是L2与L3但存在强关联的需求串联到同一条链中。
3. **跨层级合并**：即使需求标记的层级不同（如一个是L2，一个是L3），如果它们语义上属于同一主题（例如："邻苯二甲酸酯含量<1000ppm"和"PVC含量<900ppm"都属于环保有害物质限制），也应该将它们合并到同一个父级需求下。输出格式如：L1(xxx) → L2(id1,id2,id3)
4. **层级动态纠偏**：如果建立了链接，必须在 `level_adjustments` 中修正它们的逻辑层级。确保在最终的链条里：L1（最宏观/用户级） -> L2（系统功能级） -> L3（芯片物理/寄存器级）。
5. **唯一性约束**：每个子需求只能有一个父需求！一个L2只能属于一个L1，一个L3只能属于一个L2。如果一个需求同时适合多个父级，选择语义最匹配的那个。
6. **严禁幻想**：只能使用输入中实际存在的 ID。每条输出的链必须至少包含两个不同的有效 ID（拒绝单节点链）。
7. **链条拆分原则**：如果多个L2共享一个L1，而这些L2各自有不同的L3子需求，请将它们拆分成多条链，确保每条链的L2和L3是一一对应的。
8. **反向生成原则**：生成的父级需求（如L1）不应是子级需求（如L2）的简单拼接，而应是能覆盖所有子级需求且符合层级抽象特性的独立需求。若无法生成，则说明这些子级需求应分属不同的追溯链。

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
输入上下文
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
【当前分类需求集合】
{context}

【当前初始层级（仅作参考）】
{level_summary}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
输出格式 (请严格返回以下 JSON 对象，不要有任何前言或后记)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{{
  "level_adjustments": [
    {{
      "requirement_id": "需求ID",
      "original_level": "原层级",
      "adjusted_level": "调整后层级",
    }}
  ],
  "trace_chains": [
    {{
      "L1_id": "逻辑L1需求ID（若无填\"\"）",
      "L2_id": "逻辑L2需求ID（多个用逗号分隔，若无填\"\"）",
      "L3_id": "逻辑L3需求ID（多个用逗号分隔，若无填\"\"）"
    }}
  ]
}}

只返回JSON，不要其他文字。"""

    def __init__(
        self,
        llm_client,
        logger: Optional[ConsoleLogger] = None,
        category_db=None
    ):
        self.llm_client = llm_client
        self.logger = logger or ConsoleLogger()
        self.category_db = category_db

    def _build_context_string(self, instances):
        """构建供 LLM 分析的需求数据（包含当前标记的层级）"""
        lines = []
        for inst in instances:
            level_tag = f"[当前标记: {inst.requirement_type}]"
            lines.append(f"{level_tag} {inst.requirement_instance_id}: {inst.requirement_text}")
            if inst.extracted_variables:
                vars_str = ", ".join(f"{k}={v}" for k, v in inst.extracted_variables.items())
                lines.append(f"   变量: {vars_str}")
        return "\n".join(lines)

    def _build_level_summary(self, instances):
        """构造层级摘要（显示当前标记的层级）"""
        l1 = [i.requirement_instance_id for i in instances if i.requirement_type == "L1"]
        l2 = [i.requirement_instance_id for i in instances if i.requirement_type == "L2"]
        l3 = [i.requirement_instance_id for i in instances if i.requirement_type == "L3"]
        return "\n".join([
            f"L1（{len(l1)}条）：{', '.join(l1) or '无'}",
            f"L2（{len(l2)}条）：{', '.join(l2) or '无'}",
            f"L3（{len(l3)}条）：{', '.join(l3) or '无'}",
        ])

    def _collect_levels(self, instances):
        """收集各层级的 ID 列表"""
        return {
            "L1_ids": [i.requirement_instance_id for i in instances if i.requirement_type == "L1"],
            "L2_ids": [i.requirement_instance_id for i in instances if i.requirement_type == "L2"],
            "L3_ids": [i.requirement_instance_id for i in instances if i.requirement_type == "L3"],
        }

    def analyze(
        self,
        instances: List[RequirementInstance],
        category_uid: str,
        product_line: str = "ALL",
        uid_index: int = 0,
        total_uids: int = 0
    ) -> Tuple[Dict[str, Any], List[Dict], List[Dict]]:
        """
        阶段一：LLM 识别关联并动态调整层级

        Args:
            uid_index: 当前 UID 的索引（从1开始）
            total_uids: 总共有多少个 UID

        Returns:
            (层级信息, trace_chains 列表, level_adjustments 列表)
            trace_chains 每项：{L1_id, L2_id, L3_id} — 仅含已有需求 ID，不含新生成 ID
            level_adjustments 每项：{requirement_id, original_level, adjusted_level, reason}
        """
        if not instances:
            return self._collect_levels(instances), [], []

        # 分批处理：如果需求数量超过阈值，分批调用 LLM
        BATCH_SIZE = 40  # 每批最多处理40条需求
        if len(instances) > BATCH_SIZE:
            return self._analyze_in_batches(instances, category_uid, product_line, uid_index, total_uids)

        context = self._build_context_string(instances)
        level_summary = self._build_level_summary(instances)

        # 获取分类名称
        category_name = category_uid
        if self.category_db:
            cat_node = self.category_db.get_category(category_uid)
            if cat_node:
                category_name = f"{cat_node.id} {cat_node.name}"

        prompt = self.ANALYZE_PROMPT.format(
            context=context,
            category_name=category_name,
            product_line=product_line,
            level_summary=level_summary
        )

        try:
            result = self.llm_client.request_json_output(
                prompt=prompt,
                system_instruction=""
            )

            trace_chains = result.get("trace_chains", [])
            level_adjustments = result.get("level_adjustments", [])

            # 根据层级调整更新实例
            for adj in level_adjustments:
                req_id = adj.get("requirement_id")
                new_level = adj.get("adjusted_level")
                if req_id and new_level:
                    for inst in instances:
                        if inst.requirement_instance_id == req_id:
                            old_level = inst.requirement_type
                            if old_level != new_level:
                                inst.requirement_type = new_level
                                self.logger.info(
                                    "TopologyCompletion", req_id,
                                    f"层级调整: {old_level} → {new_level} (原因: {adj.get('reason', '')})"
                                )

            # 过滤无效链：移除只有单一层级的链、空链、重复链
            filtered_chains = self._filter_invalid_chains(trace_chains)
            
            # 日志：已有需求的关联链路（合并相同 L1 的链）
            merged_chains = self._merge_chains_by_l1(filtered_chains)
            self.logger.info("TopologyCompletion", "BATCH", f"识别到的追溯链（共{len(merged_chains)}条）：")
            if merged_chains:
                for i, chain in enumerate(merged_chains, 1):
                    parts = []
                    for lv in ("L1", "L2", "L3"):
                        cid = chain.get(f"{lv}_id", "")
                        if cid:
                            parts.append(f"{lv}({cid})")
                    line = f"  [{i}] {' → '.join(parts)}" if parts else f"  [{i}] (空/单节点已过滤)"
                    self.logger.info("TopologyCompletion", "BATCH", line)
            else:
                self.logger.info("TopologyCompletion", "BATCH", "  (暂无关联关系)")

            identified_levels = self._collect_levels(instances)

            return identified_levels, trace_chains, level_adjustments

        except Exception as e:
            self.logger.error("TopologyCompletion", "BATCH", f"拓扑链路检测异常: {str(e)}")
            return self._collect_levels(instances), [], []

    def _filter_invalid_chains(self, trace_chains: List[Dict]) -> List[Dict]:
        """
        过滤无效的追溯链：
        1. 移除只有单一层级的链（如只有L2没有L3）
        2. 移除空链
        3. 移除重复链
        4. 限制单个链中的ID数量（避免过度合并）
        """
        if not trace_chains:
            return []

        seen = set()
        filtered = []

        for chain in trace_chains:
            levels_present = []
            for lv in ("L1", "L2", "L3"):
                cid = chain.get(f"{lv}_id", "").strip()
                if cid:
                    levels_present.append(lv)
            
            if len(levels_present) < 2:
                continue

            chain_key = tuple(sorted([(k, v) for k, v in chain.items()]))
            if chain_key in seen:
                continue
            seen.add(chain_key)

            max_ids_per_level = 5
            has_too_many_ids = False
            for lv in ("L1", "L2", "L3"):
                cid = chain.get(f"{lv}_id", "").strip()
                if cid:
                    ids = [s.strip() for s in cid.split(",") if s.strip()]
                    if len(ids) > max_ids_per_level:
                        has_too_many_ids = True
                        break
            
            if has_too_many_ids:
                split_chains = self._split_overmerged_chain(chain)
                filtered.extend(split_chains)
            else:
                filtered.append(chain)

        return filtered

    def _split_overmerged_chain(self, chain: Dict) -> List[Dict]:
        """将过度合并的链拆分成多个子链"""
        result = []
        
        def parse_ids(id_str):
            if not id_str:
                return []
            return [s.strip() for s in id_str.split(",") if s.strip()]
        
        l1_ids = parse_ids(chain.get("L1_id", ""))
        l2_ids = parse_ids(chain.get("L2_id", ""))
        l3_ids = parse_ids(chain.get("L3_id", ""))
        
        max_ids_per_level = 5
        
        if l1_ids:
            for i in range(0, len(l1_ids), max_ids_per_level):
                sub_l1 = l1_ids[i:i+max_ids_per_level]
                sub_l2 = l2_ids[i:i+max_ids_per_level]
                sub_l3 = l3_ids[i:i+max_ids_per_level]
                
                sub_chain = {}
                if sub_l1:
                    sub_chain["L1_id"] = ",".join(sub_l1)
                if sub_l2:
                    sub_chain["L2_id"] = ",".join(sub_l2)
                if sub_l3:
                    sub_chain["L3_id"] = ",".join(sub_l3)
                
                if len([k for k in ("L1_id", "L2_id", "L3_id") if sub_chain.get(k)]) >= 2:
                    result.append(sub_chain)
        else:
            for i in range(0, len(l2_ids), max_ids_per_level):
                sub_l2 = l2_ids[i:i+max_ids_per_level]
                sub_l3 = l3_ids[i:i+max_ids_per_level]
                
                sub_chain = {}
                if sub_l2:
                    sub_chain["L2_id"] = ",".join(sub_l2)
                if sub_l3:
                    sub_chain["L3_id"] = ",".join(sub_l3)
                
                if len([k for k in ("L2_id", "L3_id") if sub_chain.get(k)]) >= 2:
                    result.append(sub_chain)
        
        return result

    def _merge_chains_by_l1(self, trace_chains: List[Dict]) -> List[Dict]:
        """
        按层级合并追溯链：
        1. 有L1的链：按L1合并，将相同L1对应的多个L2/L3合并
        2. 无L1但有L2的链：按L2合并，将相同L2对应的多个L3合并
        3. 确保ID去重

        Args:
            trace_chains: 原始追溯链列表

        Returns:
            合并后的追溯链列表
        """
        if not trace_chains:
            return []

        merged = []
        
        # 按 L1 分组（处理有L1的链）
        l1_groups = {}
        l2_only_chains = []
        
        for chain in trace_chains:
            l1_id = chain.get("L1_id", "").strip()
            if l1_id:
                if l1_id not in l1_groups:
                    l1_groups[l1_id] = {"L1_id": l1_id, "L2_ids": set(), "L3_ids": set()}
                
                l2_ids = chain.get("L2_id", "").strip()
                if l2_ids:
                    for id_str in l2_ids.split(","):
                        id_str = id_str.strip()
                        if id_str:
                            l1_groups[l1_id]["L2_ids"].add(id_str)
                
                l3_ids = chain.get("L3_id", "").strip()
                if l3_ids:
                    for id_str in l3_ids.split(","):
                        id_str = id_str.strip()
                        if id_str:
                            l1_groups[l1_id]["L3_ids"].add(id_str)
            else:
                # 没有L1的链，单独处理
                l2_only_chains.append(chain)

        # 转换有L1的链
        for l1_id, group in l1_groups.items():
            merged_chain = {"L1_id": l1_id}
            if group["L2_ids"]:
                merged_chain["L2_id"] = ",".join(sorted(group["L2_ids"]))
            if group["L3_ids"]:
                merged_chain["L3_id"] = ",".join(sorted(group["L3_ids"]))
            merged.append(merged_chain)

        # 按 L2 合并无L1的链
        if l2_only_chains:
            l2_groups = {}
            for chain in l2_only_chains:
                l2_ids = chain.get("L2_id", "").strip()
                if l2_ids:
                    l2_id_list = [s.strip() for s in l2_ids.split(",") if s.strip()]
                    for l2_id in l2_id_list:
                        if l2_id not in l2_groups:
                            l2_groups[l2_id] = {"L2_ids": set(), "L3_ids": set()}
                        l2_groups[l2_id]["L2_ids"].update(l2_id_list)
                
                l3_ids = chain.get("L3_id", "").strip()
                if l3_ids:
                    l3_id_list = [s.strip() for s in l3_ids.split(",") if s.strip()]
                    if l2_id_list:
                        # 找到对应的L2组添加L3
                        for l2_id in l2_id_list[:1]:  # 用第一个L2作为key
                            if l2_id in l2_groups:
                                l2_groups[l2_id]["L3_ids"].update(l3_id_list)
            
            # 转换无L1的链
            for key, group in l2_groups.items():
                merged_chain = {}
                if group["L2_ids"]:
                    merged_chain["L2_id"] = ",".join(sorted(group["L2_ids"]))
                if group["L3_ids"]:
                    merged_chain["L3_id"] = ",".join(sorted(group["L3_ids"]))
                merged.append(merged_chain)

        return merged

    def _analyze_in_batches(
        self,
        instances: List[RequirementInstance],
        category_uid: str,
        product_line: str = "ALL",
        uid_index: int = 0,
        total_uids: int = 0
    ) -> Tuple[Dict[str, Any], List[Dict], List[Dict]]:
        """
        分批分析：将大量需求分成小批次处理，避免超过 LLM 响应长度限制

        Args:
            instances: 需求实例列表
            category_uid: 分类UID
            product_line: 产品线
            uid_index: 当前UID索引
            total_uids: 总UID数

        Returns:
            (层级信息, trace_chains 列表, level_adjustments 列表)
        """
        BATCH_SIZE = 40
        total_instances = len(instances)
        num_batches = (total_instances + BATCH_SIZE - 1) // BATCH_SIZE
        
        self.logger.info(
            "TopologyCompletion", "BATCH",
            f"需求数量({total_instances})超过阈值，将分成{num_batches}批处理"
        )

        all_trace_chains = []
        all_level_adjustments = []

        for batch_idx in range(num_batches):
            start_idx = batch_idx * BATCH_SIZE
            end_idx = min(start_idx + BATCH_SIZE, total_instances)
            batch_instances = instances[start_idx:end_idx]
            
            self.logger.info(
                "TopologyCompletion", "BATCH",
                f"处理批次 {batch_idx + 1}/{num_batches} (需求 {start_idx + 1}-{end_idx})"
            )

            # 递归调用 analyze 方法处理每批
            _, batch_chains, batch_adjustments = self.analyze(
                batch_instances,
                category_uid,
                product_line,
                uid_index,
                total_uids
            )

            all_trace_chains.extend(batch_chains)
            all_level_adjustments.extend(batch_adjustments)

        # 合并后的层级信息
        identified_levels = self._collect_levels(instances)

        self.logger.info(
            "TopologyCompletion", "BATCH",
            f"分批处理完成，共识别{len(all_trace_chains)}条追溯链，{len(all_level_adjustments)}处层级调整"
        )

        return identified_levels, all_trace_chains, all_level_adjustments