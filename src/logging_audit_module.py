# -*- coding: utf-8 -*-
"""
日志与审计追踪模块 - 优化版
集成标准库 logging，确保本地 .log 文件与终端控制台输出完完全全一致（包含报错堆栈）
"""
import os
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

def get_timestamp() -> str:
    """获取当前UTC时间戳"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class LoggingModule:
    """
    全局日志与审计模块
    """

    def __init__(self, audit_records_dir: str = "Audit_Records", batch_id: Optional[str] = None):
        self.audit_records_dir = audit_records_dir
        self.audit_logs: List[Dict[str, Any]] = []
        self._ensure_dir()
        
        # 初始化统一的文本日志生成
        if batch_id is None:
            batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.log_file_path = os.path.join(self.audit_records_dir, f"pipeline_run_{batch_id}.log")
        self._setup_unified_logger()

    def _ensure_dir(self):
        """确保审计记录目录存在"""
        if not os.path.exists(self.audit_records_dir):
            os.makedirs(self.audit_records_dir)

    def _setup_unified_logger(self):
        """核心重构：配置底层的标准日志器，实现终端与文件百分百同步"""
        self.root_logger = logging.getLogger("SemiReqHub")
        self.root_logger.setLevel(logging.INFO)
        self.root_logger.handlers.clear()  # 防止重复添加 Handler

        # 定义与你控制台完全一致的纯文本格式
        # 格式示例: [2026-06-01 11:15:51] [INFO] [Module] [ID] Message
        log_format = "[%(asctime)s] [%(levelname)s] %(message)s"
        date_format = "%Y-%m-%d %H:%M:%S"
        formatter = logging.Formatter(log_format, datefmt=date_format)

        # 1. 终端处理器 (控制台输出)
        console_handler = logging.StreamHandler()
        console_handler.setFormatter(formatter)
        self.root_logger.addHandler(console_handler)

        # 2. 文件处理器 (完完全全同步落盘，包括报错)
        file_handler = logging.FileHandler(self.log_file_path, encoding='utf-8')
        file_handler.setFormatter(formatter)
        self.root_logger.addHandler(file_handler)

    def _get_log_id(self) -> str:
        """生成日志ID"""
        date_str = datetime.now().strftime("%Y%m%d")
        count = len(self.audit_logs) + 1
        return f"LOG_{date_str}_{count:05d}"

    def log_info(self, module: str, entity_id: str, message: str):
        """统一通过标准日志器输出，自动实现双写"""
        self.root_logger.info(f"[{module}] [{entity_id}] {message}")

    def log_error(self, module: str, entity_id: str, message: str, exc_info: bool = False):
        """
        统一通过标准日志器输出错误
        Args:
            exc_info: 如果在 except 块中调用，设为 True 会自动捕获并打印完整的代码报错堆栈！
        """
        self.root_logger.error(f"[{module}] [{entity_id}] {message}", exc_info=exc_info)

    def log_warning(self, module: str, entity_id: str, message: str):
        """统一通过标准日志器输出警告"""
        self.root_logger.warning(f"[{module}] [{entity_id}] {message}")

    def create_audit_log(
        self,
        requirement_instance_id: str,
        action: str,
        module: str,
        operator: str = "AI_ENGINE_V2",
        before: Optional[Dict[str, Any]] = None,
        after: Optional[Dict[str, Any]] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """创建结构化审计数据记录（原逻辑保留，用于业务对齐）"""
        audit_log = {
            "audit_log_id": self._get_log_id(),
            "timestamp": get_timestamp(),
            "operator": operator,
            "requirement_instance_id": requirement_instance_id,
            "action": action,
            "module": module,
            "change_detail": {"before": before or {}, "after": after or {}},
            "metadata": metadata or {}
        }
        self.audit_logs.append(audit_log)
        return audit_log

    def log_categorization(self, requirement_instance_id: str, category_uid: str, success: bool, product_line: str = ""):
        action = "CATEGORIZATION_SUCCESS" if success else "CATEGORIZATION_FAILED"
        # 不输出逐条日志，只保留审计记录
        return self.create_audit_log(requirement_instance_id=requirement_instance_id, action=action, module="Categorization", before={"category_uid": ""}, after={"category_uid": category_uid, "product_line": product_line})

    def log_template_match(self, requirement_instance_id: str, matched_template_id: str, extracted_variables: Dict[str, Any], match_type: str = "full_match"):
        action = f"TEMPLATE_{match_type.upper()}"
        message = f"成功命中标准模板 {matched_template_id}, 成功抽离变量: {extracted_variables}" if matched_template_id else f"未命中标准模板, 已创建待定新模板, 成功抽离变量: {extracted_variables}"
        self.log_info("TemplateMatch", requirement_instance_id, message)
        return self.create_audit_log(requirement_instance_id=requirement_instance_id, action=action, module="TemplateMatch", before={"matched_template_id": ""}, after={"matched_template_id": matched_template_id, "extracted_variables": extracted_variables, "match_type": match_type})

    def log_topology_completion(self, requirement_instance_id: str, parent_requirement_id: str, child_requirement_ids: List[str], completion_type: str, generated_content: Optional[str] = None):
        action = f"TOPOLOGY_{completion_type.upper()}"
        self.log_info("TopologyCompletion", requirement_instance_id, f"拓扑链路{completion_type}补全完成, 父级: {parent_requirement_id}, 子级: {child_requirement_ids}")
        return self.create_audit_log(requirement_instance_id=requirement_instance_id, action=action, module="TopologyCompletion", operator="AI_ENGINE_V2", before={"parent_requirement_id": "", "child_requirement_ids": []}, after={"parent_requirement_id": parent_requirement_id, "child_requirement_ids": child_requirement_ids, "generated_content": generated_content})

    def log_human_override(self, requirement_instance_id: str, before_variables: Dict[str, Any], after_variables: Dict[str, Any], operator: str = "Mo Chen(Human)"):
        self.log_info("HumanReview", requirement_instance_id, f"人工覆盖变量: {before_variables} -> {after_variables}")
        return self.create_audit_log(requirement_instance_id=requirement_instance_id, action="HUMAN_OVERRIDE_VARIABLES", module="Audit_Review_Module", operator=operator, before={"extracted_variables": before_variables, "review_status": "pending_review"}, after={"extracted_variables": after_variables, "review_status": "approved"})

    def save_audit_logs(self, batch_id: Optional[str] = None):
        """保存传统的结构化JSON审计数据（独立留存，互不干扰）"""
        if not self.audit_logs:
            return
        if batch_id is None:
            batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        json_filename = os.path.join(self.audit_records_dir, f"audit_data_snapshot_{batch_id}.json")
        with open(json_filename, 'w', encoding='utf-8') as f:
            json.dump(self.audit_logs, f, ensure_ascii=False, indent=2)
        
        # 顺便在文本日志里记录一句持久化成功的INFO
        self.root_logger.info(f"[AUDIT] 完美的物理文本运行日志已实时保存至: {self.log_file_path}")
        self.root_logger.info(f"[AUDIT] 结构化业务变更JSON快照已保存至: {json_filename}")

    def clear_logs(self):
        self.audit_logs = []


class ConsoleLogger:
    """
    重构桥接类：让原有代码中调用的 self.logger.info / error 
    直接透明地路由到统一的 Root Logger 中，不破坏外部 pipeline 结构
    """
    def __init__(self):
        self.logger = logging.getLogger("SemiReqHub")

    def info(self, module: str, entity_id: str, message: str):
        self.logger.info(f"[{module}] [{entity_id}] {message}")

    def error(self, module: str, entity_id: str, message: str, exc_info: bool = False):
        # ✨ 关键：增加 exc_info 参数，当底层 LLM 连接中断崩溃时，传入 exc_info=True 即可抓取全部 traceback 报错！
        self.logger.error(f"[{module}] [{entity_id}] {message}", exc_info=exc_info)

    def warning(self, module: str, entity_id: str, message: str):
        self.logger.warning(f"[{module}] [{entity_id}] {message}")

    def success(self, module: str, entity_id: str, message: str):
        self.logger.info(f"[{module}] [{entity_id}] [SUCCESS] {message}")