# -*- coding: utf-8 -*-
"""
数据模型定义模块
基于 SYSTEM_DESIGN-v2.md 文档第4节的数据模型定义
"""
import json
import logging
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Any, Optional
from datetime import datetime, timezone
import uuid

logger = logging.getLogger(__name__)


def generate_uid(prefix: str = "uid") -> str:
    """生成全局唯一标识符"""
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def get_timestamp() -> str:
    """获取当前UTC时间戳"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


@dataclass
class Variable:
    """变量定义模型"""
    name: str
    type: str  # number, string, enum
    label: str
    unit: str


@dataclass
class CategoryNode:
    """目录分类库模型 (category_db/)"""
    uid: str
    id: str  # 如 "2.1", "3.2.1"
    name: str
    level: int  # 1, 2, 3
    parent_uid: str
    children: List[str]
    description: str = ""
    applicable_lines: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TemplateTraceChain:
    """模板追踪链"""
    parent_template_id: str = ""
    child_template_ids: List[str] = field(default_factory=list)


@dataclass
class RequirementTemplate:
    """静态母版库模型 (Master_Requirement_Templates.json)"""
    template_id: str
    level: str  # L1, L2, L3
    category_uid: str
    templates_text: str
    product_lines: List[str]
    variables: List[Dict[str, Any]] = field(default_factory=list)
    template_trace_chain: Dict[str, Any] = field(default_factory=dict)
    parent_template_id: str = ""
    child_template_ids: List[str] = field(default_factory=list)
    version: str = "V1.0.0"
    created_at: str = ""
    updated_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = get_timestamp()
        if not self.updated_at:
            self.updated_at = get_timestamp()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class InstanceTraceChain:
    """实例追踪链"""
    parent_requirement_id: str = ""
    child_requirement_ids: List[str] = field(default_factory=list)


@dataclass
class RequirementInstance:
    """动态需求实例模型"""
    requirement_instance_id: str
    requirement_text: str
    requirement_type: str  # L1, L2, L3
    category_uid: str
    matched_template_id: str = ""
    extracted_variables: Dict[str, Any] = field(default_factory=dict)
    instance_trace_chain: Dict[str, Any] = field(default_factory=dict)
    generation_type: str = "manual"  # manual, ai_generated
    review_status: str = "pending_review"  # pending_review, approved, rejected
    product_line: str = ""
    chip_info: str = ""
    confidence: float = 0.0  # 分类置信度

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class ChangeDetail:
    """变更明细"""
    before: Dict[str, Any]
    after: Dict[str, Any]


@dataclass
class AuditLogMetadata:
    """审计日志元数据"""
    model_name: str = ""
    prompt_version: str = ""
    tokens_consumed: int = 0


@dataclass
class AuditLog:
    """审计日志数据模型 (Audit_Records/)"""
    audit_log_id: str
    timestamp: str
    operator: str  # AI_ENGINE_V2 / Mo Chen(Human)
    requirement_instance_id: str
    action: str  # HUMAN_OVERRIDE_VARIABLES, AI_GENERATED, etc.
    module: str  # Audit_Review_Module, etc.
    change_detail: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = get_timestamp()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class PendingTemplate:
    """待定新模板（未匹配的全新模板）"""
    template_id: str
    level: str
    category_uid: str
    templates_text: str
    product_lines: List[str]
    variables: List[Dict[str, Any]]
    parent_template_id: Optional[str] = None
    created_at: str = ""

    def __post_init__(self):
        if not self.created_at:
            self.created_at = get_timestamp()

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class CategoryDatabase:
    """分类数据库管理器"""

    def __init__(self, db_path: str):
        self.db_path = db_path
        self.categories: Dict[str, CategoryNode] = {}
        self._load()

    def _load(self):
        """从JSON文件加载分类数据库"""
        try:
            with open(self.db_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                cats = data.get('categories', data)
                for uid, cat_data in cats.items():
                    self.categories[uid] = CategoryNode(**cat_data)
        except Exception as e:
            logger.error(f"Failed to load category database: {e}")

    def get_category(self, uid: str) -> Optional[CategoryNode]:
        """获取指定UID的分类节点"""
        return self.categories.get(uid)

    def get_children(self, uid: str) -> List[CategoryNode]:
        """获取指定分类的所有子分类"""
        cat = self.get_category(uid)
        if not cat:
            return []
        return [self.get_category(child_uid) for child_uid in cat.children
                if self.get_category(child_uid)]

    def get_level3_categories(self) -> List[CategoryNode]:
        """获取所有3级分类节点"""
        return [cat for cat in self.categories.values() if cat.level == 3]

    def get_category_by_id(self, category_id: str) -> Optional[CategoryNode]:
        """根据分类编号（如3.2.1）查找分类节点"""
        for cat in self.categories.values():
            if cat.id == category_id:
                return cat
        return None

    def get_category_path(self, uid: str) -> str:
        """获取分类的完整路径（如 '2.1.4 芯片级可测试性'）"""
        cat = self.get_category(uid)
        if not cat:
            return ""

        path_parts = [cat.id, cat.name]
        parent = self.get_category(cat.parent_uid)
        while parent:
            path_parts.insert(0, parent.name)
            parent = self.get_category(parent.parent_uid)
        return " - ".join(path_parts)

    def build_category_tree_string(self) -> str:
        """构建用于LLM上下文的三级目录树字符串"""
        lines = []
        for cat in self.categories.values():
            if cat.level == 1:
                lines.append(f"# {cat.id} {cat.name}")
            elif cat.level == 2:
                lines.append(f"## {cat.id} {cat.name}")
            elif cat.level == 3:
                lines.append(f"### {cat.id} {cat.name}")
        return "\n".join(lines)


class MasterTemplateLibrary:
    """静态母版库管理器"""

    def __init__(self, templates_path: str):
        self.templates_path = templates_path
        self.templates: Dict[str, RequirementTemplate] = {}
        self._load()

    def _load(self):
        """从JSON文件加载母版库"""
        try:
            with open(self.templates_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
                for tid, tpl_data in data.items():
                    self.templates[tid] = RequirementTemplate(**tpl_data)
        except Exception as e:
            logger.error(f"Failed to load template library: {e}")

    def save(self):
        """保存母版库到JSON文件"""
        import json
        data = {tid: tpl.to_dict() for tid, tpl in self.templates.items()}
        with open(self.templates_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def add_template(self, template: RequirementTemplate):
        """添加新模板"""
        self.templates[template.template_id] = template

    def get_template(self, template_id: str) -> Optional[RequirementTemplate]:
        """获取指定模板"""
        return self.templates.get(template_id)

    def get_templates_by_category(self, category_uid: str) -> List[RequirementTemplate]:
        """获取指定分类下的所有模板"""
        return [tpl for tpl in self.templates.values() if tpl.category_uid == category_uid]

    def get_templates_by_level(self, level: str) -> List[RequirementTemplate]:
        """获取指定层级的所有模板"""
        return [tpl for tpl in self.templates.values() if tpl.level == level]

    def get_templates_by_product_line(self, product_line: str) -> List[RequirementTemplate]:
        """获取适用于指定产品线的所有模板"""
        return [tpl for tpl in self.templates.values()
                if product_line in tpl.product_lines or "ALL" in tpl.product_lines]
