# -*- coding: utf-8 -*-
"""
清洗匹配模块 (Template Matching & Extraction Module)
基于 SYSTEM_DESIGN-v2.md 文档第3.2节的设计
"""
import json
import re
from typing import Dict, Any, Optional, Tuple, List
from src.data_models import MasterTemplateLibrary, RequirementTemplate, PendingTemplate
from src.logging_audit_module import ConsoleLogger


class TemplateMatchingModule:
    """
    清洗匹配模块
    在选定的分类目录下进行高效率的模板对撞与参数提取

    处理逻辑：
    1. 缩小检索域：仅在当前 category_uid 的模板子集里进行匹配
    2. 命中（Match）：提取变量值填入实例
    3. 部分命中（Partial Match）：升级模板为完整匹配
    4. 未命中（Miss）：启动"公式化提炼"，生成待定新模板
    """

    SYSTEM_INSTRUCTION = """你是一个半导体芯片需求工程专家。
你的任务是将输入的需求文本与给定的模板进行匹配，并提取其中的变量参数。

重要规则：
1. 变量名必须采用小写蛇形命名法（snake_case），如 sleep_ua、wakeup_time_us
2. 必须严格分离数值与单位，严禁将单位揉入变量值中
   - 正确：current_mA: "3", 单位由模板定义
   - 错误：current_mA: "3mA"
3. 如果需求文本与模板不完全匹配，请判断是"部分匹配"还是"完全不匹配"
"""

    MATCH_PROMPT_TEMPLATE = """## 待匹配需求文本

{requirement_text}

## 可用模板

{templates}

## 产品线

{product_line}

请分析需求文本与模板的匹配程度，并返回结果：

### 如果完全匹配或部分匹配：
返回JSON对象：
{{
  "match_type": "full_match" 或 "partial_match",
  "matched_template_id": "模板ID",
  "template_text": "匹配到的模板文本",
  "extracted_variables": {{
    "变量名": "提取的数值",
    ...
  }},
  "match_explanation": "匹配说明"
}}

### 如果完全不匹配（是新需求）：
返回JSON对象：
{{
  "match_type": "miss",
  "is_new_template_needed": true,
  "reasoning": "为什么这是一个新需求"
}}
"""

    VARIABLE_EXTRACTION_PROMPT = """## 待提取变量需求文本

{requirement_text}

## 模板变量定义

{variables}

请从需求文本中提取每个变量的具体数值，返回JSON对象：
{{
  "extracted_variables": {{
    "变量名": "提取的数值（只包含数字，不含单位）",
    ...
  }},
  "missing_variables": ["未能提取的变量列表"]
}}

只返回一个JSON对象，不要包含任何其他文字。"""

    NEW_TEMPLATE_PROMPT = """你是一个半导体芯片需求工程专家。
当输入的需求文本无法匹配现有模板时，你需要将其公式化提炼为新的需求模板。

## 原始需求文本

{requirement_text}

## 所属分类UID

{category_uid}

## 产品线

{product_line}

## 已有的同分类模板（供参考）

{existing_templates}

请返回一个JSON对象：
{{
  "templates_text": "公式化提炼后的模板文本，使用 ${{variable_name}} 作为变量占位符",
  "variables": [
    {{
      "name": "变量名（小写下划线蛇形）",
      "type": "number 或 string 或 enum",
      "label": "业务直观标签",
      "unit": "物理单位"
    }}
  ],
  "parent_template_id": "对应的父级模板ID（如果能推断出）",
  "reasoning": "提炼逻辑说明"
}}

只返回一个JSON对象，不要包含任何其他文字。"""

    def __init__(
        self,
        templates_path: str = "",
        llm_client=None,
        logger: Optional[ConsoleLogger] = None,
        output_dir: str = "output/library",
        template_library: MasterTemplateLibrary = None
    ):
        """
        初始化模板匹配模块

        Args:
            templates_path: 模板库JSON文件路径（传统模式）
            llm_client: LLM客户端实例
            logger: 日志记录器实例
            output_dir: 待定模板输出目录
            template_library: 已构建的MasterTemplateLibrary实例（新模式，优先使用）
        """
        if template_library is not None:
            self.template_library = template_library
        elif templates_path:
            self.template_library = MasterTemplateLibrary(templates_path)
        else:
            raise ValueError("Must provide either template_library or templates_path")

        self.llm_client = llm_client
        self.logger = logger or ConsoleLogger()
        self.pending_templates: List[PendingTemplate] = []
        self.output_dir = output_dir
        import os
        os.makedirs(output_dir, exist_ok=True)

    def _build_templates_string(self, templates: List[RequirementTemplate]) -> str:
        """构建模板字符串供LLM使用"""
        lines = []
        for tpl in templates:
            vars_str = ", ".join([
                f"{v['name']} ({v['type']}, 单位: {v['unit']})"
                for v in tpl.variables
            ]) if tpl.variables else "无变量"

            lines.append(f"""
模板ID: {tpl.template_id}
模板文本: {tpl.templates_text}
变量: {vars_str}
层级: {tpl.level}
""")
        return "\n".join(lines)

    def _extract_number_from_text(self, text: str, unit: str) -> Optional[str]:
        """
        从文本中提取数值
        例如：从"运行功耗<3mA"中提取"3"
        """
        patterns = [
            rf'(\d+(?:\.\d+)?)\s*{re.escape(unit)}',
            rf'(\d+(?:\.\d+)?)\s*{re.escape(unit)}/',
            rf'{re.escape(unit)}\s*[=<>]\s*(\d+(?:\.\d+)?)',
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1)

        pattern = r'(\d+(?:\.\d+)?)'
        match = re.search(pattern, text)
        if match:
            return match.group(1)

        return None

    def match(
        self,
        requirement_text: str,
        requirement_id: str,
        category_uid: str,
        product_line: str = "ALL",
        progress_info: Tuple[int, int] = None
    ) -> Tuple[str, Optional[str], Dict[str, Any], Optional[PendingTemplate]]:
        """
        对单条需求进行模板匹配和变量提取

        Args:
            requirement_text: 需求文本
            requirement_id: 需求ID
            category_uid: 分类UID
            product_line: 产品线
            progress_info: 进度信息 (当前处理数, 总数)

        Returns:
            Tuple[匹配类型, matched_template_id, extracted_variables, pending_template]
            匹配类型: "full_match", "partial_match", "miss"
        """
        templates = self.template_library.get_templates_by_category(category_uid)

        if not templates:
            self.logger.warning(
                "TemplateMatch",
                requirement_id,
                f"分类{category_uid}下没有可用模板，尝试跨分类匹配"
            )
            templates = self.template_library.get_templates_by_product_line(product_line)

        if not templates:
            self.logger.info(
                "TemplateMatch",
                requirement_id,
                "没有找到匹配的模板，需要创建新模板"
            )
            return self._create_new_template(
                requirement_text, requirement_id, category_uid, product_line, progress_info
            )

        templates_string = self._build_templates_string(templates)

        prompt = self.MATCH_PROMPT_TEMPLATE.format(
            requirement_text=requirement_text,
            templates=templates_string,
            product_line=product_line
        )

        try:
            result = self.llm_client.request_json_output(
                prompt=prompt,
                system_instruction=self.SYSTEM_INSTRUCTION
            )

            if not result:
                return self._create_new_template(
                    requirement_text, requirement_id, category_uid, product_line, progress_info
                )

            match_type = result.get("match_type", "miss")

            if match_type in ["full_match", "partial_match"]:
                matched_template_id = result.get("matched_template_id")
                extracted_variables = result.get("extracted_variables", {})

                return match_type, matched_template_id, extracted_variables, None

            else:
                return self._create_new_template(
                    requirement_text, requirement_id, category_uid, product_line, progress_info
                )

        except Exception as e:
            self.logger.error(
                "TemplateMatch",
                requirement_id,
                f"模板匹配过程异常: {str(e)}"
            )
            return self._create_new_template(
                requirement_text, requirement_id, category_uid, product_line, progress_info
            )

    def _create_new_template(
        self,
        requirement_text: str,
        requirement_id: str,
        category_uid: str,
        product_line: str,
        progress_info: Tuple[int, int] = None
    ) -> Tuple[str, Optional[str], Dict[str, Any], Optional[PendingTemplate]]:
        """创建新的待定模板"""
        templates = self.template_library.get_templates_by_category(category_uid)
        existing_templates_str = self._build_templates_string(templates) if templates else "无"

        prompt = self.NEW_TEMPLATE_PROMPT.format(
            requirement_text=requirement_text,
            category_uid=category_uid,
            product_line=product_line,
            existing_templates=existing_templates_str
        )

        try:
            result = self.llm_client.request_json_output(
                prompt=prompt,
                system_instruction=self.SYSTEM_INSTRUCTION
            )

            if not result:
                self.logger.warning(
                    "TemplateMatch",
                    requirement_id,
                    "无法从LLM获取新模板定义，使用原始文本作为待定模板"
                )
                pending_tpl = PendingTemplate(
                    template_id=f"PENDING_{requirement_id}",
                    level="L3",
                    category_uid=category_uid,
                    templates_text=requirement_text,
                    product_lines=[product_line],
                    variables=[]
                )
                self.pending_templates.append(pending_tpl)
                if hasattr(self, 'current_product_line') and hasattr(self, 'current_chip_info'):
                    self._save_pending_templates_immediately()
                return "miss", None, {}, pending_tpl

            templates_text = result.get("templates_text", requirement_text)
            variables = result.get("variables", [])
            parent_template_id = result.get("parent_template_id")

            pending_tpl = PendingTemplate(
                template_id=f"PENDING_{requirement_id}",
                level="L3",
                category_uid=category_uid,
                templates_text=templates_text,
                product_lines=[product_line],
                variables=variables,
                parent_template_id=parent_template_id
            )

            self.pending_templates.append(pending_tpl)
            
            if hasattr(self, 'current_product_line') and hasattr(self, 'current_chip_info'):
                self._save_pending_templates_immediately()

            progress_str = ""
            if progress_info:
                progress_str = f"[{progress_info[0]}/{progress_info[1]}] "
            
            self.logger.info(
                "TemplateMatch",
                requirement_id,
                f"{progress_str}创建待定新模板: {pending_tpl.template_id}, 变量: {[v['name'] for v in variables]}"
            )

            extracted_vars = {}
            for var in variables:
                value = self._extract_number_from_text(requirement_text, var.get("unit", ""))
                if value:
                    extracted_vars[var["name"]] = value

            return "miss", None, extracted_vars, pending_tpl

        except Exception as e:
            self.logger.error(
                "TemplateMatch",
                requirement_id,
                f"创建新模板异常: {str(e)}"
            )
            return "miss", None, {}, None

    def match_batch(
        self,
        requirements: list,
        category_uid: str,
        product_line: str = "ALL"
    ) -> Dict[str, Dict[str, Any]]:
        """
        批量进行模板匹配

        Args:
            requirements: 需求列表
            category_uid: 分类UID
            product_line: 产品线

        Returns:
            匹配结果字典
        """
        results = {}

        for req in requirements:
            req_id = req.get("id", f"REQ_{len(results)}")
            req_text = req.get("text", req.get("requirement_text", ""))

            match_type, template_id, variables, pending_tpl = self.match(
                requirement_text=req_text,
                requirement_id=req_id,
                category_uid=category_uid,
                product_line=product_line
            )

            results[req_id] = {
                "match_type": match_type,
                "matched_template_id": template_id,
                "extracted_variables": variables,
                "pending_template": pending_tpl.to_dict() if pending_tpl else None,
                "requirement_text": req_text
            }

        return results

    def get_pending_templates(self) -> List[PendingTemplate]:
        """获取所有待定模板"""
        return self.pending_templates

    def get_all_templates(self) -> List[RequirementTemplate]:
        """获取所有模板"""
        return list(self.template_library.templates.values())

    def clear_pending_templates(self):
        """清空待定模板列表"""
        self.pending_templates = []

    def set_current_product_info(self, product_line: str, chip_info: str = ""):
        """
        设置当前处理的产品线和芯片信息，用于即时保存
        
        Args:
            product_line: 产品线名称
            chip_info: 芯片信息
        """
        self.current_product_line = product_line
        self.current_chip_info = chip_info

    def _save_pending_templates_immediately(self):
        """
        创建模板后立即保存整个缓存文件（所有待定模板）
        """
        if not self.pending_templates:
            return
        
        from datetime import datetime
        import os
        
        safe_chip_info = self.current_chip_info.replace("[", "_").replace("]", "_").replace("/", "_").replace("\\", "_") if self.current_chip_info else ""
        filename = f"{self.current_product_line}_{safe_chip_info}_pending.json" if safe_chip_info else f"{self.current_product_line}_pending.json"
        filepath = os.path.join(self.output_dir, filename)
        
        templates_data = []
        for tpl in self.pending_templates:
            tpl_dict = {
                "template_id": tpl.template_id,
                "level": tpl.level,
                "category_uid": tpl.category_uid,
                "templates_text": tpl.templates_text,
                "product_lines": tpl.product_lines,
                "variables": tpl.variables,
                "parent_template_id": tpl.parent_template_id,
                "created_at": datetime.now().isoformat()
            }
            templates_data.append(tpl_dict)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(templates_data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(
            "TemplateMatch",
            "BATCH",
            f"待定模板已即时保存: {len(templates_data)} 条 -> {filepath}"
        )

    def save_pending_templates_by_product(self, product_line: str, chip_info: str = ""):
        """
        将当前产品线下的所有待定模板保存到一个文件
        
        Args:
            product_line: 产品线名称
            chip_info: 芯片信息
            
        Returns:
            保存的文件路径，如果没有待定模板则返回None
        """
        if not self.pending_templates:
            return None
        
        from datetime import datetime
        import os
        
        # 生成文件名：产品线_芯片名_pending.json
        safe_chip_info = chip_info.replace("[", "_").replace("]", "_").replace("/", "_").replace("\\", "_")
        filename = f"{product_line}_{safe_chip_info}_pending.json" if chip_info else f"{product_line}_pending.json"
        filepath = os.path.join(self.output_dir, filename)
        
        templates_data = []
        for tpl in self.pending_templates:
            tpl_dict = {
                "template_id": tpl.template_id,
                "level": tpl.level,
                "category_uid": tpl.category_uid,
                "templates_text": tpl.templates_text,
                "product_lines": tpl.product_lines,
                "variables": tpl.variables,
                "parent_template_id": tpl.parent_template_id,
                "created_at": datetime.now().isoformat()
            }
            templates_data.append(tpl_dict)
        
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(templates_data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(
            "TemplateMatch",
            "BATCH",
            f"已保存 {len(templates_data)} 个待定模板到: {filepath}"
        )
        
        return filepath

    def load_pending_templates_by_product(self, product_line: str, chip_info: str = "") -> bool:
        """
        从文件加载指定产品线的待定模板，如果存在则跳过模板匹配
        
        Args:
            product_line: 产品线名称
            chip_info: 芯片信息
            
        Returns:
            True: 成功加载缓存，应跳过模板匹配
            False: 缓存不存在或加载失败
        """
        import os
        
        safe_chip_info = chip_info.replace("[", "_").replace("]", "_").replace("/", "_").replace("\\", "_")
        filename = f"{product_line}_{safe_chip_info}_pending.json" if chip_info else f"{product_line}_pending.json"
        filepath = os.path.join(self.output_dir, filename)
        
        if not os.path.exists(filepath):
            return False
        
        try:
            with open(filepath, 'r', encoding='utf-8') as f:
                templates_data = json.load(f)
            
            for tpl_data in templates_data:
                pending_tpl = PendingTemplate(
                    template_id=tpl_data["template_id"],
                    level=tpl_data["level"],
                    category_uid=tpl_data["category_uid"],
                    templates_text=tpl_data["templates_text"],
                    product_lines=tpl_data["product_lines"],
                    variables=tpl_data.get("variables", []),
                    parent_template_id=tpl_data.get("parent_template_id")
                )
                self.pending_templates.append(pending_tpl)
            
            self.logger.info(
                "TemplateMatch",
                "BATCH",
                f"已从缓存加载 {len(templates_data)} 个待定模板: {filepath}"
            )
            return True
        
        except Exception as e:
            self.logger.error(
                "TemplateMatch",
                "BATCH",
                f"加载待定模板缓存失败: {str(e)}"
            )
            return False
