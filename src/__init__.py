# -*- coding: utf-8 -*-
"""
需求数据清洗与模板生成系统
基于 SYSTEM_DESIGN-v2.md 文档设计
"""

from .data_models import (
    CategoryDatabase,
    MasterTemplateLibrary,
    RequirementInstance,
    RequirementTemplate,
    PendingTemplate,
    AuditLog,
    Variable
)

from .categorization_module import CategorizationModule
from .template_matching_module import TemplateMatchingModule
from .topology_completion_module import TopologyCompletionModule
from .visualization_module import VisualizationModule
from .logging_audit_module import LoggingModule, ConsoleLogger
from .pipeline import DataProcessingPipeline

__all__ = [
    "CategoryDatabase",
    "MasterTemplateLibrary",
    "RequirementInstance",
    "RequirementTemplate",
    "PendingTemplate",
    "AuditLog",
    "Variable",
    "CategorizationModule",
    "TemplateMatchingModule",
    "TopologyCompletionModule",
    "VisualizationModule",
    "LoggingModule",
    "ConsoleLogger",
    "DataProcessingPipeline"
]
