# -*- coding: utf-8 -*-
"""
智能目录归仓模块 (Categorization Module)
基于 SYSTEM_DESIGN-v2.md 文档第3.1节的设计
"""
import json
import os
from typing import Dict, Any, Optional, Tuple
from src.data_models import CategoryDatabase, CategoryNode
from src.logging_audit_module import ConsoleLogger


class CategorizationModule:
    """
    智能目录归仓模块
    作为流水线的第一步，直接接收输入的需求文本，利用LLM将其快速归入标准的三级目录中

    核心原则：必须使用LLM语义匹配，绝对不能只分到二级（如3.2），必须分到三级标题（如3.2.1）
    """

    SYSTEM_INSTRUCTION = """你是一个半导体芯片需求工程专家。
你的任务是将输入的需求文本分类到精确的三级目录中，并判断需求层级。

分类要求：
1. 必须分到三级标题（如3.2.1），不能只分到二级（如3.2）
2. 仔细对照下面的分类目录树，选择最精确匹配的三级分类
3. 考虑需求语义，而不是关键词匹配

层级定义：
- L1 (客户需求): 从最终用户或客户角度出发，用业务/商业语言描述"为什么需要这个产品"或"要达到什么商业目标"。通常不涉及技术实现细节。
  示例："设备需要可靠运行"、"数据需要安全存储"、"要延长电池使用寿命"
- L2 (初始需求): 将客户的商业愿望转化为产品经理视角的具体产品特征和目标描述（定性或半定量）。描述"需要什么功能/特性"，但不规定具体实现方案。
  示例："系统应防止无响应"、"应确保数据不丢失"、"需支持低功耗模式"、"提供POR模块设计保障"
- L3 (系统需求): 将产品需求完全量化、技术化，给出明确的、可测试、可验证的技术指标和实现约束。描述"具体如何实现"和"达到什么量化指标"。
  示例："看门狗定时器超时时间为1秒"、"系统响应时间小于100ms"、"待机电流不超过1.9μA"、"数据保持时间大于10年"

层级判断规则：
1. 如果只描述目标/方向，没有具体技术指标 → L1或L2
2. 如果描述产品特性但无量化指标 → L2
3. 如果包含可测试的量化技术指标 → L3
4. 默认情况下，如果无法明确区分，优先判断为L2
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


只返回一个JSON对象，不要包含任何其他文字。"""

    def __init__(
        self,
        category_db_path: str = None,
        llm_client=None,
        logger: Optional[ConsoleLogger] = None,
        category_db: CategoryDatabase = None
    ):
        """
        初始化分类模块

        Args:
            category_db_path: 分类数据库JSON文件路径（传统模式）
            llm_client: LLM客户端实例
            logger: 日志记录器实例
            category_db: 已构建的CategoryDatabase实例（新模式，优先使用）
        """
        if category_db is not None:
            self.category_db = category_db
        elif category_db_path:
            self.category_db = CategoryDatabase(category_db_path)
        else:
            raise ValueError("Must provide either category_db or category_db_path")

        self.llm_client = llm_client
        self.logger = logger or ConsoleLogger()

    def _build_category_tree_string(self) -> str:
        """构建用于LLM的分类目录树字符串"""
        lines = []
        categories = self.category_db.categories

        for uid, cat in categories.items():
            if cat.level == 1:
                lines.append(f"# {cat.id} {cat.name}")
                if cat.description:
                    lines.append(f"   描述: {cat.description}")
            elif cat.level == 2:
                lines.append(f"## {cat.id} {cat.name}")
                if cat.description:
                    lines.append(f"   描述: {cat.description}")
            elif cat.level == 3:
                lines.append(f"### {cat.id} {cat.name} [UID: {cat.uid}]")
                if cat.description:
                    lines.append(f"   描述: {cat.description}")

        return "\n".join(lines)

    def _get_category_path(self, category_uid: str) -> str:
        """获取分类的完整路径（L1 > L2 > L3）"""
        path_parts = []
        current_uid = category_uid
        
        while current_uid:
            category = self.category_db.get_category(current_uid)
            if not category:
                break
            path_parts.insert(0, f"{category.id} - {category.name}")
            current_uid = category.parent_uid
        
        return " > ".join(path_parts)

    def categorize(
        self,
        requirement_text: str,
        requirement_id: str,
        product_line: str = "ALL"
    ) -> Tuple[bool, Optional[str], Optional[str], Optional[str], Optional[Dict[str, Any]]]:
        """
        对单条需求文本进行智能分类，并判断需求层级

        Args:
            requirement_text: 需求文本内容
            requirement_id: 需求ID（用于日志记录）
            product_line: 产品线

        Returns:
            Tuple[成功标志, category_uid, category_id, requirement_level, 分类结果详情]
        """
        category_tree = self._build_category_tree_string()

        prompt = self.PROMPT_TEMPLATE.format(
            category_tree=category_tree,
            requirement_text=requirement_text,
            product_line=product_line
        )

        try:
            result = self.llm_client.request_json_output(
                prompt=prompt,
                system_instruction=self.SYSTEM_INSTRUCTION
            )

            if not result:
                self.logger.warning(
                    "Categorization",
                    requirement_id,
                    "LLM返回空结果，标记为分类失败"
                )
                return False, None, None, None, None

            category_uid = result.get("category_uid")
            category_id = result.get("category_id")
            confidence = result.get("confidence", 0)
            reasoning = result.get("reasoning", "")
            requirement_level = result.get("requirement_level", "L3")  # 默认L3

            if not category_uid:
                self.logger.warning(
                    "Categorization",
                    requirement_id,
                    "LLM未返回有效的category_uid，标记为分类失败"
                )
                return False, None, None, None, result

            if confidence < 0.6:
                self.logger.warning(
                    "Categorization",
                    requirement_id,
                    f"分类置信度({confidence})低于阈值，标记为分类失败"
                )
                return False, category_uid, category_id, requirement_level, result

            import re
            parsed_uid = category_uid.strip()
            
            if parsed_uid.startswith('[UID:'):
                match = re.search(r'\[UID:\s*([^\]]+)\]', category_uid)
                if match:
                    parsed_uid = match.group(1).strip()
            elif '[UID:' in parsed_uid:
                match = re.search(r'\[UID:\s*([^\]]+)\]', category_uid)
                if match:
                    parsed_uid = match.group(1).strip()
            elif re.match(r'^\d+\.\d+\.\d+$', parsed_uid):
                pass
            else:
                uid_match = re.search(r'cat_[a-zA-Z0-9]+', category_uid)
                if uid_match:
                    parsed_uid = uid_match.group(0)

            category_node = self.category_db.get_category(parsed_uid)
            if not category_node:
                if re.match(r'^\d+\.\d+\.\d+$', parsed_uid):
                    category_node = self.category_db.get_category_by_id(parsed_uid)
                    if category_node:
                        parsed_uid = category_node.uid
                        self.logger.info(
                            "Categorization",
                            requirement_id,
                            f"通过分类编号({category_uid})找到对应UID: {parsed_uid}"
                        )
                elif re.match(r'^[a-zA-Z0-9]{8}$', parsed_uid) and not parsed_uid.startswith('cat_'):
                    full_uid = f"cat_{parsed_uid}"
                    category_node = self.category_db.get_category(full_uid)
                    if category_node:
                        parsed_uid = full_uid
                        self.logger.info(
                            "Categorization",
                            requirement_id,
                            f"通过补全cat_前缀({category_uid})找到对应UID: {parsed_uid}"
                        )

            if not category_node:
                self.logger.warning(
                    "Categorization",
                    requirement_id,
                    f"分类UID({category_uid})在数据库中不存在"
                )
                return False, None, None, None, result

            if category_node.level != 3:
                self.logger.warning(
                    "Categorization",
                    requirement_id,
                    f"分类结果不是三级分类({category_node.level}级)，将尝试重新匹配"
                )
                return False, None, None, None, result

            # 获取完整的分类路径信息（不打印详细日志，由批量处理统一汇总）
            category_path = self._get_category_path(parsed_uid)

            return True, parsed_uid, category_id, requirement_level, result

        except Exception as e:
            self.logger.error(
                "Categorization",
                requirement_id,
                f"分类过程异常: {str(e)}"
            )
            return False, None, None, None

    def categorize_batch(
        self,
        requirements: list,
        product_line: str = "ALL"
    ) -> Dict[str, Dict[str, Any]]:
        """
        批量对需求进行分类

        Args:
            requirements: 需求列表，每项包含 id 和 text 字段
            product_line: 产品线

        Returns:
            分类结果字典，key为需求ID
        """
        results = {}

        for req in requirements:
            req_id = req.get("id", f"REQ_{len(results)}")
            req_text = req.get("text", req.get("requirement_text", ""))

            success, category_uid, category_id, requirement_level, details = self.categorize(
                requirement_text=req_text,
                requirement_id=req_id,
                product_line=product_line
            )

            results[req_id] = {
                "success": success,
                "category_uid": category_uid,
                "category_id": category_id,
                "requirement_level": requirement_level,
                "requirement_text": req_text,
                "details": details
            }

        return results

    def get_category_info(self, category_uid: str) -> Optional[Dict[str, Any]]:
        """获取指定分类的详细信息"""
        cat = self.category_db.get_category(category_uid)
        if not cat:
            return None

        return {
            "uid": cat.uid,
            "id": cat.id,
            "name": cat.name,
            "level": cat.level,
            "parent_uid": cat.parent_uid,
            "description": cat.description,
            "path": self.category_db.get_category_path(category_uid)
        }

    def get_all_level3_categories(self) -> list:
        """获取所有三级分类列表"""
        cats = self.category_db.get_level3_categories()
        return [
            {
                "uid": cat.uid,
                "id": cat.id,
                "name": cat.name,
                "description": cat.description,
                "path": self.category_db.get_category_path(cat.uid)
            }
            for cat in cats
        ]
