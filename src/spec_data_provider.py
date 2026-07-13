# -*- coding: utf-8 -*-
"""
规范数据提供者 (Spec Data Provider)
====================================
从 芯片需求结构化定义规范 JSON 中自动派生：
  1. 分类目录树 (替代 categories.dbV4.1.json)
  2. 为缺失模板的分类生成初始模板

设计原则：
  - 规范JSON 是"目录结构"的唯一数据源（compact, 不发送给LLM的需求文本）
  - 模板库作为独立文件保留（人工维护的3163个模板不受影响）
  - 仅新分类自动获得初始模板
  - UID 保持稳定（确定性生成或从已有配置继承）
"""
import os
import json
import hashlib
import re
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src.data_models import (
    CategoryNode, RequirementTemplate, CategoryDatabase,
    MasterTemplateLibrary
)


# ============================================================================
# UID 工具
# ============================================================================

def generate_uid(key: str) -> str:
    """确定性短UID生成"""
    h = hashlib.md5(key.encode('utf-8')).digest()
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "cat_" + ''.join(chars[h[i] % len(chars)] for i in range(6))


# ============================================================================
# Category 派生
# ============================================================================

def derive_categories_from_spec(
    spec_items: List[Dict],
    existing_uid_map: Optional[Dict[Tuple[str, int], str]] = None
) -> Dict[str, CategoryNode]:
    """
    从规范JSON items 派生 CategoryNode 字典

    规范JSON结构示例:
    {
      "uid": "cat_de343t",
      "维度序号": "1",
      "维度": "核心功能",
      "能力域序号": "1.1",
      "能力域": "CPU",
      "需求项序号": "1.1.1",
      "需求项": "CPU规范定义",
      ...
    }

    构建 L1(维度) → L2(能力域) → L3(需求项) 三级树

    UID策略:
      1. L3: 使用 spec item 中的 uid（已存在则保留）
      2. L2: 已有配置中的uid > 确定性生成
      3. L1: 已有配置中的uid > 确定性生成
    """
    if existing_uid_map is None:
        existing_uid_map = {}

    categories: Dict[str, CategoryNode] = {}

    # 跟踪 L1/L2 映射
    dim_uid_map: Dict[str, str] = {}   # 维度序号 → uid
    cap_uid_map: Dict[str, str] = {}   # 能力域序号 → uid

    for item in spec_items:
        dim_id = str(item.get("维度序号", "")).strip()
        dim_name = str(item.get("维度", "")).strip()
        cap_id = str(item.get("能力域序号", "")).strip()
        cap_name = str(item.get("能力域", "")).strip()
        req_id = str(item.get("需求项序号", "")).strip()
        req_name = str(item.get("需求项", "")).strip()
        item_uid = str(item.get("uid", "")).strip()

        if not all([dim_id, cap_id, req_id]):
            continue

        # --- L1: 维度 ---
        if dim_id not in dim_uid_map:
            dim_uid = existing_uid_map.get((dim_id, 1)) or generate_uid(f"dim_l1_{dim_id}")
            dim_uid_map[dim_id] = dim_uid
            categories[dim_uid] = CategoryNode(
                uid=dim_uid, id=dim_id, name=dim_name,
                level=1, parent_uid="", children=[], description=""
            )

        # --- L2: 能力域 ---
        if cap_id not in cap_uid_map:
            cap_uid = existing_uid_map.get((cap_id, 2)) or generate_uid(f"cap_l2_{cap_id}")
            cap_uid_map[cap_id] = cap_uid
            dim_uid = dim_uid_map[dim_id]
            categories[cap_uid] = CategoryNode(
                uid=cap_uid, id=cap_id, name=cap_name,
                level=2, parent_uid=dim_uid, children=[], description=""
            )
            # 注册到父维度
            if cap_uid not in categories[dim_uid].children:
                categories[dim_uid].children.append(cap_uid)

        # --- L3: 需求项 ---
        if item_uid:
            req_uid = item_uid
        else:
            req_uid = existing_uid_map.get((req_id, 3)) or generate_uid(f"req_l3_{req_id}")

        cap_uid = cap_uid_map[cap_id]
        categories[req_uid] = CategoryNode(
            uid=req_uid, id=req_id, name=req_name,
            level=3, parent_uid=cap_uid, children=[], description=""
        )
        if req_uid not in categories[cap_uid].children:
            categories[cap_uid].children.append(req_uid)

    return categories


# ============================================================================
# Template 派生
# ============================================================================

def extract_variables_from_text(text: str) -> List[Dict]:
    """从模板文本中提取 [[变量]] 占位符"""
    variables = []
    seen = set()
    for match in re.findall(r'\[\[([^\]]+)\]\]', text):
        name = match.strip()
        if name and name not in seen:
            seen.add(name)
            var_type = "number" if any(kw in name.lower() for kw in [
                "数值", "bit", "hz", "ma", "mv", "us", "ns", "kb", "mb",
                "gb", "v", "a", "℃", "%", "次", "个", "路", "种", "年"
            ]) else "string"
            variables.append({"name": name, "type": var_type, "label": name, "unit": ""})
    return variables


def derive_templates_for_category(
    spec_item: Dict,
    template_counter: List[int]
) -> List[RequirementTemplate]:
    """
    为一个规范需求项生成 L1/L2/L3 初始模板组（含追溯链）
    """
    templates = []
    req_uid = spec_item.get("uid", "")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    l1_text = str(spec_item.get("原始需求", "")).strip()
    l2_text = str(spec_item.get("初始需求", "")).strip()
    l3_text = str(spec_item.get("系统需求", "")).strip()

    skip_marker = "[文档中未明确提及]"
    has_l1 = l1_text and skip_marker not in l1_text
    has_l2 = l2_text and skip_marker not in l2_text
    has_l3 = l3_text and skip_marker not in l3_text

    if not (has_l1 or has_l2 or has_l3):
        return templates

    def next_id(level):
        template_counter[0] += 1
        return f"TPL_{level}_{template_counter[0]:05d}"

    l1_id, l2_id, l3_id = None, None, None

    if has_l1:
        l1_id = next_id("L1")
        templates.append(RequirementTemplate(
            template_id=l1_id, level="L1", category_uid=req_uid,
            templates_text=l1_text, product_lines=["ALL"],
            variables=extract_variables_from_text(l1_text),
            template_trace_chain={"parent_template_id": "", "child_template_ids": []},
            version="V4.1.0", created_at=now, updated_at=now
        ))

    if has_l2:
        l2_id = next_id("L2")
        templates.append(RequirementTemplate(
            template_id=l2_id, level="L2", category_uid=req_uid,
            templates_text=l2_text, product_lines=["ALL"],
            variables=extract_variables_from_text(l2_text),
            template_trace_chain={"parent_template_id": l1_id or "", "child_template_ids": []},
            version="V4.1.0", created_at=now, updated_at=now
        ))
        # 更新 L1 的子模板链
        if l1_id:
            for t in templates:
                if t.template_id == l1_id:
                    t.template_trace_chain["child_template_ids"].append(l2_id)

    if has_l3:
        l3_id = next_id("L3")
        templates.append(RequirementTemplate(
            template_id=l3_id, level="L3", category_uid=req_uid,
            templates_text=l3_text, product_lines=["ALL"],
            variables=extract_variables_from_text(l3_text),
            template_trace_chain={"parent_template_id": l2_id or "", "child_template_ids": []},
            version="V4.1.0", created_at=now, updated_at=now
        ))
        if l2_id:
            for t in templates:
                if t.template_id == l2_id:
                    t.template_trace_chain["child_template_ids"].append(l3_id)

    return templates


# ============================================================================
# 主数据提供者
# ============================================================================

class SpecDataProvider:
    """
    统一数据提供者

    数据来源优先级：
      1. 规范JSON (芯片需求结构化定义规范V4.0.json) → 派生 categories
      2. 模板库JSON (Master_Requirement_Templates.json) → 加载已有模板
      3. 规范JSON的L1/L2/L3文本 → 为缺失模板的分类生成初始模板

    使用方式:
      provider = SpecDataProvider(spec_json_path, templates_json_path)
      categories = provider.get_categories()  # Dict[str, CategoryNode]
      templates = provider.get_templates()    # Dict[str, RequirementTemplate]
    """

    def __init__(
        self,
        spec_json_path: str,
        templates_json_path: Optional[str] = None,
        existing_category_db_path: Optional[str] = None,
        logger=None
    ):
        self.spec_json_path = spec_json_path
        self.templates_json_path = templates_json_path
        self.logger = logger
        self.stats = {}  # 收集统计信息

        # 加载规范JSON
        if not os.path.exists(spec_json_path):
            raise FileNotFoundError(f"规范JSON不存在: {spec_json_path}")

        with open(spec_json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        self.spec_items = data if isinstance(data, list) else data.get("items", [])

        # 从已有category db构建UID映射（保持UID稳定）
        existing_uid_map = {}
        if existing_category_db_path and os.path.exists(existing_category_db_path):
            try:
                with open(existing_category_db_path, 'r', encoding='utf-8') as f:
                    existing_data = json.load(f)
                existing_cats = existing_data.get("categories", existing_data)
                for uid, node in existing_cats.items():
                    nid = node.get("id", "")
                    level = node.get("level", 0)
                    if nid and level:
                        existing_uid_map[(nid, level)] = uid
            except Exception:
                pass

        # 派生 categories
        self._categories = derive_categories_from_spec(self.spec_items, existing_uid_map)
        self.stats["category_count"] = len(self._categories)

        # 加载/构建 templates
        self._templates: Dict[str, RequirementTemplate] = {}
        self._load_templates()

    def _load_templates(self):
        """加载模板：已有模板库 + 为缺失分类自动生成"""
        # 1. 加载已有模板库
        existing_count = 0
        if self.templates_json_path and os.path.exists(self.templates_json_path):
            try:
                with open(self.templates_json_path, 'r', encoding='utf-8') as f:
                    tpl_data = json.load(f)
                for tid, tpl in tpl_data.items():
                    try:
                        self._templates[tid] = RequirementTemplate(**tpl)
                        existing_count += 1
                    except Exception:
                        pass
            except Exception as e:
                if self.logger:
                    self.logger.warning("SpecData", "LOAD",
                                        f"Failed to load templates: {e}")

        self.stats["existing_templates"] = existing_count

        # 2. 找出缺失模板的分类
        categories_with_templates = set()
        for tpl in self._templates.values():
            categories_with_templates.add(tpl.category_uid)

        spec_category_uids = {item.get("uid", "") for item in self.spec_items if item.get("uid")}
        missing = spec_category_uids - categories_with_templates

        self.stats["categories_with_templates"] = len(categories_with_templates & spec_category_uids)
        self.stats["missing_template_categories"] = len(missing)

        # 3. 为缺失的分类自动生成初始模板
        if missing:
            # 确定起始序号
            max_num = 0
            for tid in self._templates:
                match = re.search(r'TPL_[A-Z]\d_(\d+)', tid)
                if match:
                    max_num = max(max_num, int(match.group(1)))

            counter = [max_num]
            uid_to_item = {item.get("uid", ""): item for item in self.spec_items}
            generated_count = 0

            for uid in sorted(missing):
                item = uid_to_item.get(uid)
                if not item:
                    continue
                new_tpls = derive_templates_for_category(item, counter)
                for tpl in new_tpls:
                    self._templates[tpl.template_id] = tpl
                    generated_count += 1

            self.stats["auto_generated_templates"] = generated_count

            if generated_count > 0 and self.logger:
                self.logger.info("SpecData", "INIT",
                    f"Auto-generated {generated_count} templates for {len(missing)} new categories")

    def get_categories(self) -> Dict[str, CategoryNode]:
        """获取派生自规范JSON的分类目录"""
        return self._categories

    def get_templates(self) -> Dict[str, RequirementTemplate]:
        """获取模板库（已有 + 自动生成）"""
        return self._templates

    def get_category_tree_string(self) -> str:
        """构建紧凑的分类目录树字符串（用于LLM prompt）"""
        lines = []
        for uid, cat in sorted(self._categories.items(), key=lambda x: (x[1].level, x[1].id)):
            prefix = "#" * cat.level
            line = f"{prefix} {cat.id} {cat.name} [UID: {cat.uid}]"
            lines.append(line)
        return "\n".join(lines)

    def get_spec_hash(self) -> str:
        """获取规范文件的MD5哈希（用于变更检测）"""
        if not os.path.exists(self.spec_json_path):
            return ""
        with open(self.spec_json_path, 'rb') as f:
            return hashlib.md5(f.read()).hexdigest()

    def save_spec_hash(self, hash_file_path: str):
        """保存当前规范哈希到文件"""
        h = self.get_spec_hash()
        os.makedirs(os.path.dirname(hash_file_path), exist_ok=True)
        with open(hash_file_path, 'w') as f:
            f.write(h + "\n")
            f.write(datetime.now().isoformat() + "\n")

    def check_spec_changed(self, hash_file_path: str) -> Tuple[bool, str]:
        """
        检查规范文件是否自上次同步后发生了变化
        Returns:
            (changed, message)
        """
        current_hash = self.get_spec_hash()
        if not os.path.exists(hash_file_path):
            return True, "首次运行，未记录规范哈希"

        with open(hash_file_path, 'r') as f:
            lines = f.readlines()
            saved_hash = lines[0].strip() if lines else ""
            saved_time = lines[1].strip() if len(lines) > 1 else "unknown"

        if current_hash != saved_hash:
            return True, f"规范文件已变更 (上次同步: {saved_time})"

        return False, f"规范文件未变更 (上次同步: {saved_time})"

    def get_stats(self) -> Dict:
        """获取统计信息"""
        level1 = sum(1 for c in self._categories.values() if c.level == 1)
        level2 = sum(1 for c in self._categories.values() if c.level == 2)
        level3 = sum(1 for c in self._categories.values() if c.level == 3)
        return {
            **self.stats,
            "spec_items": len(self.spec_items),
            "categories_l1": level1,
            "categories_l2": level2,
            "categories_l3": level3,
            "total_templates": len(self._templates),
        }
