# -*- coding: utf-8 -*-
"""
数据加工流水线主模块
基于 SYSTEM_DESIGN-v2.md 文档第3节的整体流程设计
"""
import os
import json
import sys
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone

from src.data_models import (
    RequirementInstance,
    MasterTemplateLibrary,
    CategoryDatabase
)
from src.categorization_module import CategorizationModule
from src.template_matching_module import TemplateMatchingModule
from src.topology_completion_module import TopologyCompletionModule
from src.visualization_module import VisualizationModule
from src.logging_audit_module import LoggingModule, ConsoleLogger
from src.spec_data_provider import SpecDataProvider

# 尝试导入 tqdm 用于进度条
try:
    from tqdm import tqdm
    TQDM_AVAILABLE = True
except ImportError:
    TQDM_AVAILABLE = False


def get_timestamp() -> str:
    """获取当前UTC时间戳"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DataProcessingPipeline:
    """
    数据加工流水线主控模块
    整体流程：
    1. 第一步：智能目录归仓（分类模块）
    2. 第二步：需求模板匹配与变量抽离（清洗匹配模块）
    3. 第三步：LLM拓扑链路检测与智能补全
    4. 第四步：生成内容可视化（导出预览Excel）
    5. 人工统一审核（Human-in-the-Loop）
    6. 双轨数据持久化分账
    """
    def __init__(
        self,
        category_db_path: str = None,
        templates_path: str = None,
        llm_client=None,
        audit_records_dir: str = "Audit_Records",
        output_dir: str = "output",
        template_library_dir: str = "template_library",
        spec_json_path: str = None,
        use_spec_provider: bool = True
    ):
        """
        初始化数据加工流水线

        Args:
            category_db_path: 分类数据库 JSON 文件路径（传统模式）
            templates_path: 模板库 JSON 文件路径
            llm_client: LLM 客户端实例
            audit_records_dir: 审计记录目录
            output_dir: 输出目录
            template_library_dir: 需求实例库目录
            spec_json_path: 规范JSON路径（新模式，自动派生categories）
            use_spec_provider: 是否优先使用SpecDataProvider
        """
        # 单次初始化，保证 batch_id 一致
        self.batch_id = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.audit_logger = LoggingModule(audit_records_dir=audit_records_dir, batch_id=self.batch_id)
        self.logger = ConsoleLogger()

        self.llm_client = llm_client
        self.use_spec_provider = False

        # 确定数据源
        if use_spec_provider and spec_json_path and os.path.exists(spec_json_path):
            # ─── 新模式：从规范JSON自动派生 ───
            self.logger.info("Pipeline", "INIT", f"Using SpecDataProvider from: {spec_json_path}")
            self.spec_provider = SpecDataProvider(
                spec_json_path=spec_json_path,
                templates_json_path=templates_path,
                existing_category_db_path=category_db_path,
                logger=self.logger
            )
            self.use_spec_provider = True

            # 打印统计
            stats = self.spec_provider.get_stats()
            self.logger.info("Pipeline", "INIT",
                f"Categories: {stats['categories_l1']} L1 / {stats['categories_l2']} L2 / {stats['categories_l3']} L3 "
                f"(from {stats['spec_items']} spec items)")
            self.logger.info("Pipeline", "INIT",
                f"Templates: {stats['total_templates']} total "
                f"(existing: {stats.get('existing_templates', 0)}, "
                f"auto-generated: {stats.get('auto_generated_templates', 0)})")

            # 设置 category_db 用于 topology 和 visualization
            self.category_db = CategoryDatabase.__new__(CategoryDatabase)
            self.category_db.categories = self.spec_provider.get_categories()

            # 设置 template_library
            self.template_library = MasterTemplateLibrary.__new__(MasterTemplateLibrary)
            self.template_library.templates = self.spec_provider.get_templates()

            # 初始化各模块
            self.categorization_module = CategorizationModule(
                category_db=self.category_db,
                llm_client=llm_client,
                logger=self.logger
            )

            self.template_matching_module = TemplateMatchingModule(
                templates_path=templates_path or "",
                llm_client=llm_client,
                logger=self.logger,
                output_dir=template_library_dir,
                template_library=self.template_library
            )
        else:
            # ─── 传统模式：从JSON文件加载 ───
            if not category_db_path or not templates_path:
                raise ValueError(
                    "Must provide either spec_json_path or both category_db_path + templates_path"
                )

            self.category_db = CategoryDatabase(category_db_path)
            self.template_library = MasterTemplateLibrary(templates_path)

            self.categorization_module = CategorizationModule(
                category_db_path=category_db_path,
                llm_client=llm_client,
                logger=self.logger
            )

            self.template_matching_module = TemplateMatchingModule(
                templates_path=templates_path,
                llm_client=llm_client,
                logger=self.logger,
                output_dir=template_library_dir
            )

        self.topology_module = TopologyCompletionModule(
            llm_client=llm_client,
            logger=self.logger,
            category_db=self.category_db
        )

        self.visualization_module = VisualizationModule(
            output_dir=output_dir,
            category_db=self.category_db,
            logger=self.logger
        )

        self.output_dir = output_dir
        self.template_library_dir = template_library_dir

        # 分类缓存（一次性加载）
        self._classification_cache = {}

        self._ensure_dirs()

    def _ensure_dirs(self):
        """确保必要的目录存?"""
        for dir_path in [self.output_dir, self.template_library_dir, self.audit_logger.audit_records_dir]:
            if not os.path.exists(dir_path):
                os.makedirs(dir_path)

    def _load_classification_cache(self, product_line: str = ""):
        """一次性加载分类缓存"""
        cache_dir = os.path.join(self.output_dir, 'classify')
        cache_file = os.path.join(cache_dir, f'classification_cache_{product_line}.json') if product_line else os.path.join(cache_dir, 'classification_cache.json')
        
        os.makedirs(cache_dir, exist_ok=True)
        
        if os.path.exists(cache_file):
            try:
                with open(cache_file, 'r', encoding='utf-8') as f:
                    cache_data = json.load(f)
                self._classification_cache = cache_data
                return len(cache_data)
            except Exception as e:
                self.logger.warning("Pipeline", "CACHE", f"读取分类缓存失败: {str(e)}")
        return 0

    def _save_classification_cache(self, product_line: str = ""):
        """批量保存分类缓存到文件"""
        if not self._classification_cache:
            return
        
        cache_dir = os.path.join(self.output_dir, 'classify')
        cache_file = os.path.join(cache_dir, f'classification_cache_{product_line}.json') if product_line else os.path.join(cache_dir, 'classification_cache.json')
        
        os.makedirs(cache_dir, exist_ok=True)
        
        try:
            with open(cache_file, 'w', encoding='utf-8') as f:
                json.dump(self._classification_cache, f, ensure_ascii=False, indent=2)
        except Exception as e:
            self.logger.warning("Pipeline", "CACHE", f"保存分类缓存失败: {str(e)}")

    def process_single_requirement(
        self,
        requirement_text: str,
        requirement_id: str,
        product_line: str = "",
        chip_info: str = ""
    ) -> RequirementInstance:
        """
        处理单条需求
        Args:
            requirement_text: 需求文本
            requirement_id: 需求ID
            product_line: 产品线
            chip_info: 芯片信息

        Returns:
            处理后的需求实例
        """
        instance = RequirementInstance(
            requirement_instance_id=requirement_id,
            requirement_text=requirement_text,
            requirement_type="L3",
            category_uid="",
            product_line=product_line,
            chip_info=chip_info
        )

        self.logger.info(
            "Pipeline",
            requirement_id,
            f"开始处理需求 {requirement_text[:50]}..."
        )

        success, category_uid, category_id, requirement_level, cat_details = self.categorization_module.categorize(
            requirement_text=requirement_text,
            requirement_id=requirement_id,
            product_line=product_line
        )

        if success:
            instance.category_uid = category_uid
            instance.requirement_type = requirement_level or "L3"
            # 保存置信度
            instance.confidence = cat_details.get("confidence", 0.0) if cat_details else 0.0
            
            self.audit_logger.log_categorization(
                requirement_instance_id=requirement_id,
                category_uid=category_uid,
                success=True,
                product_line=product_line
            )
        else:
            instance.category_uid = category_uid or "cat_failed"
            instance.confidence = cat_details.get("confidence", 0.0) if cat_details else 0.0
            
            self.audit_logger.log_categorization(
                requirement_instance_id=requirement_id,
                category_uid=category_uid or "cat_failed",
                success=False,
                product_line=product_line
            )

        if category_uid:
            match_type, template_id, extracted_vars, pending_tpl = \
                self.template_matching_module.match(
                    requirement_text=requirement_text,
                    requirement_id=requirement_id,
                    category_uid=category_uid,
                    product_line=product_line
                )

            instance.matched_template_id = template_id or ""
            instance.extracted_variables = extracted_vars

            self.audit_logger.log_template_match(
                requirement_instance_id=requirement_id,
                matched_template_id=template_id or "",
                extracted_variables=extracted_vars,
                match_type=match_type
            )

        return instance

    def process_batch(
        self,
        requirements: List[Dict[str, Any]],
        product_line: str = "ALL",
        chip_info: str = "",
        run_topology_completion: bool = True,
        run_visualization: bool = True,
        run_template_matching: bool = True
    ) -> List[RequirementInstance]:
        """
        批量处理需求
        流程：
        1. 分类归仓
        2. 模板匹配（对所有实例，包括新生成的）
        3. 基于模板追溯链自动建立需求追溯链
        4. 拓扑链路检测（判断L1/L2/L3层级）
        5. 缺失链路补全（生成缺失的L1/L2/L3需求）
        6. 可视化预览
        Args:
            requirements: 需求列表，每项包含 id 和 text 字段
            product_line: 产品线
            chip_info: 芯片信息
            run_topology_completion: 是否运行拓扑链路补全
            run_visualization: 是否生成可视化预览
            run_template_matching: 是否运行模板匹配
        Returns:
            处理后的需求实例列表
        """
        self.logger.info(
            "Pipeline",
            "BATCH",
            f"开始批量处理{len(requirements)}条需求"
        )

        # 批量加载分类缓存
        cache_count = self._load_classification_cache(product_line)
        if cache_count > 0:
            self.logger.info(
                "Pipeline",
                "CACHE",
                f"已从缓存加载 {cache_count} 条分类结果"
            )

        # 第一步：仅做分类归仓（不进行模板匹配）
        instances = []
        
        # 确定是否使用进度条
        total_reqs = len(requirements)
        use_progress = TQDM_AVAILABLE and total_reqs > 10  # 超过10条才显示进度条
        
        if use_progress:
            # 使用 tqdm 进度条
            iterator = tqdm(requirements, desc="分类归仓", unit="条", file=sys.stdout)
        else:
            iterator = requirements
        
        for req in iterator:
            req_id = req.get("id", f"REQ_{len(instances)}")
            req_text = req.get("text", req.get("requirement_text", ""))

            instance = self._categorize_only(
                requirement_text=req_text,
                requirement_id=req_id,
                product_line=product_line,
                chip_info=chip_info
            )
            instances.append(instance)

        self.logger.info(
            "Pipeline",
            "BATCH",
            f"分类归仓完成，共{len(instances)}条需求"
        )

        # 立即保存分类缓存（确保分类结果被持久化）
        self._save_classification_cache(product_line)

        # 第二步：模板匹配（根据开关控制是否执行）
        if run_template_matching:
            # 加载待定模板缓存（如果存在）
            if hasattr(self.template_matching_module, 'load_pending_templates_by_product'):
                cache_loaded = self.template_matching_module.load_pending_templates_by_product(
                    product_line=product_line,
                    chip_info=chip_info
                )
                if cache_loaded:
                    self.logger.info(
                        "Pipeline",
                        "BATCH",
                        "已加载待定模板缓存"
                    )
            
            # 设置当前产品信息（用于即时保存）
            if hasattr(self.template_matching_module, 'set_current_product_info'):
                self.template_matching_module.set_current_product_info(
                    product_line=product_line,
                    chip_info=chip_info
                )
            
            # 模板匹配（优先匹配，利用模板追溯链）
            instances = self._run_template_matching_batch(instances, product_line)

            self.logger.info(
                "Pipeline",
                "BATCH",
                f"模板匹配完成，共{len(instances)}条需求"
            )

            # 第三步：基于模板追溯链自动建立需求追溯链
            instances = self._build_trace_chain_from_templates(instances)

            self.logger.info(
                "Pipeline",
                "BATCH",
                f"模板追溯链应用完成，共{len(instances)}条需求"
            )
        else:
            self.logger.info(
                "Pipeline",
                "BATCH",
                "模板匹配已跳过（run_template_matching=False）"
            )

        # 第四步：拓扑链路检测和缺失链路补全（仅处理未匹配模板或追溯链不完整的需求）
        if run_topology_completion and instances:
            instances = self._run_topology_completion(instances, product_line)

        self.logger.info(
            "Pipeline",
            "BATCH",
            f"拓扑链路检测完成，共{len(instances)}条需求"
        )

        # 第五步：清理重复的孤立需求
        if instances:
            instances = self._cleanup_duplicate_orphan_instances(instances)

        # 第六步：可视化预览
        if run_visualization and instances:
            self._run_visualization(instances, product_line, chip_info)

        self.logger.info(
            "Pipeline",
            "BATCH",
            f"批量处理完成，共{len(instances)}条需求"
        )

        return instances

    def _run_visualization(
        self,
        instances: List[RequirementInstance],
        product_line: str,
        chip_info: str = ""
    ):
        """
        ✨ 运行可视化预览：生成Excel详情 + 追踪链图 + 统计概览
        """
        try:
            # 文件名：产品线_芯片信息_时间戳.xlsx（过滤非法字符）
            import re
            from datetime import datetime
            safe_chip = re.sub(r'[\\/:*?"<>|\s]', '_', str(chip_info)) if chip_info else "default"
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_filename = f"{product_line}_{safe_chip}_preview_{timestamp}.xlsx"

            # 1) 渲染 Excel 预览
            excel_path = self.visualization_module.render_to_excel(
                instances=instances,
                output_filename=output_filename,
                title=f"{product_line} - {chip_info} 需求预览"
            )
            self.logger.info(
                "Pipeline",
                "BATCH",
                f"Excel 预览已生成: {excel_path}"
            )

            # 2) 渲染追踪链图
            diagram_filename = output_filename.replace(".xlsx", "_trace_chain.txt")
            self.visualization_module.render_trace_chain_diagram(
                instances=instances,
                output_filename=diagram_filename
            )
            self.logger.info(
                "Pipeline",
                "BATCH",
                f"追踪链图已生成: {diagram_filename}"
            )

            # 3) 生成统计概览
            stats = self.visualization_module.generate_summary_stats(instances)
            self.logger.info(
                "Pipeline",
                "BATCH",
                f"统计概览: {stats}"
            )
        except Exception as e:
            self.logger.error(
                "Pipeline",
                "BATCH",
                f"可视化生成失败: {str(e)}"
            )

    def _categorize_only(
        self,
        requirement_text: str,
        requirement_id: str,
        product_line: str,
        chip_info: str
    ) -> RequirementInstance:
        """仅进行分类归仓，不进行模板匹配（支持缓存跳过）"""
        instance = RequirementInstance(
            requirement_instance_id=requirement_id,
            requirement_text=requirement_text,
            requirement_type="L3",  # 默认L3，分类后会更新
            category_uid="",
            product_line=product_line,
            chip_info=chip_info
        )

        # 使用预加载的缓存（如果可用）
        if self._classification_cache and requirement_id in self._classification_cache:
            cached_result = self._classification_cache[requirement_id]
            category_uid = cached_result.get("category_uid", "")
            requirement_level = cached_result.get("requirement_level", "L3")
            
            instance.category_uid = category_uid
            if requirement_level and requirement_level in ["L1", "L2", "L3"]:
                instance.requirement_type = requirement_level
            self.audit_logger.log_categorization(
                requirement_instance_id=requirement_id,
                category_uid=category_uid,
                success=True,
                product_line=product_line
            )
            return instance
        
        # 缓存中不存在，执行分类
        success, category_uid, category_id, requirement_level, cat_details = self.categorization_module.categorize(
            requirement_text=requirement_text,
            requirement_id=requirement_id,
            product_line=product_line
        )

        if success:
            instance.category_uid = category_uid
            # 设置LLM判断的需求层级
            if requirement_level and requirement_level in ["L1", "L2", "L3"]:
                instance.requirement_type = requirement_level
            self.audit_logger.log_categorization(
                requirement_instance_id=requirement_id,
                category_uid=category_uid,
                success=True,
                product_line=product_line
            )
            
            # 将分类结果写入缓存
            self._classification_cache[requirement_id] = {
                "category_uid": category_uid,
                "requirement_level": requirement_level,
                "timestamp": datetime.now().isoformat()
            }
            
            # 即时保存缓存到磁盘（防止中途中断导致数据丢失）
            self._save_classification_cache(product_line)
        else:
            instance.category_uid = category_uid or "cat_failed"
            self.audit_logger.log_categorization(
                requirement_instance_id=requirement_id,
                category_uid=category_uid or "cat_failed",
                success=False,
                product_line=product_line
            )

        return instance

    def _run_template_matching_batch(
        self,
        instances: List[RequirementInstance],
        product_line: str
    ) -> List[RequirementInstance]:
        """批量对所有实例进行模板匹配（包括新生成的需求）"""
        total_count = len(instances)
        processed_count = 0
        
        for idx, instance in enumerate(instances):
            if not instance.category_uid or instance.category_uid == "cat_failed":
                continue
            
            processed_count += 1
            
            match_type, template_id, extracted_vars, pending_tpl = \
                self.template_matching_module.match(
                    requirement_text=instance.requirement_text,
                    requirement_id=instance.requirement_instance_id,
                    category_uid=instance.category_uid,
                    product_line=product_line,
                    progress_info=(processed_count, total_count)
                )

            instance.matched_template_id = template_id or ""
            instance.extracted_variables = extracted_vars

            self.audit_logger.log_template_match(
                requirement_instance_id=instance.requirement_instance_id,
                matched_template_id=template_id or "",
                extracted_variables=extracted_vars,
                match_type=match_type
            )

        return instances

    def _build_trace_chain_from_templates(
        self,
        instances: List[RequirementInstance]
    ) -> List[RequirementInstance]:
        """
        基于模板追溯链自动建立需求追溯链
        
        逻辑：
        1. 如果需求匹配上L3模板，通过parent_template_id找到L2模板，再找到L1模板
        2. 如果需求匹配上L2模板，通过parent_template_id找到L1模板，通过child_template_ids找到L3模板
        3. 如果需求匹配上L1模板，通过child_template_ids找到L2模板，再找到L3模板
        4. 根据模板创建对应的需求实例并建立追溯链
        """
        # 构建实例ID到实例的映射
        id_to_instance = {inst.requirement_instance_id: inst for inst in instances}
        
        # 获取所有模板
        all_templates = self.template_matching_module.get_all_templates()
        template_id_to_template = {tpl.template_id: tpl for tpl in all_templates}
        
        new_instances = []
        
        for instance in instances:
            if not instance.matched_template_id:
                continue
            
            # 获取匹配的模板
            matched_template = template_id_to_template.get(instance.matched_template_id)
            if not matched_template:
                continue
            
            # 根据模板层级和追溯链信息建立需求追溯链
            self._process_template_trace_chain(
                instance, 
                matched_template, 
                template_id_to_template,
                id_to_instance,
                new_instances
            )
        
        # 将新创建的实例添加到列表
        instances.extend(new_instances)
        
        # 更新ID映射
        for inst in new_instances:
            id_to_instance[inst.requirement_instance_id] = inst
        
        # 建立需求之间的追溯链关系
        self._link_requirement_instances(instances, id_to_instance)
        
        return instances

    def _process_template_trace_chain(
        self,
        instance: RequirementInstance,
        template,
        template_id_to_template: Dict[str, Any],
        id_to_instance: Dict[str, RequirementInstance],
        new_instances: List[RequirementInstance]
    ):
        """处理单个模板的追溯链"""
        template_level = template.level
        
        # 设置需求层级为模板层级
        instance.requirement_type = template_level
        
        # 向上查找父级模板
        if template.parent_template_id:
            self._create_parent_requirements(
                instance,
                template.parent_template_id,
                template_id_to_template,
                id_to_instance,
                new_instances
            )
        
        # 向下查找子级模板
        if hasattr(template, 'child_template_ids') and template.child_template_ids:
            for child_tpl_id in template.child_template_ids:
                self._create_child_requirements(
                    instance,
                    child_tpl_id,
                    template_id_to_template,
                    id_to_instance,
                    new_instances
                )

    def _create_parent_requirements(
        self,
        child_instance: RequirementInstance,
        parent_template_id: str,
        template_id_to_template: Dict[str, Any],
        id_to_instance: Dict[str, RequirementInstance],
        new_instances: List[RequirementInstance]
    ):
        """递归创建父级需求"""
        parent_template = template_id_to_template.get(parent_template_id)
        if not parent_template:
            return
        
        # 检查是否已存在对应的需求实例
        parent_instance_id = f"{parent_template.level}_{parent_template_id}"
        if parent_instance_id in id_to_instance:
            # 已存在，建立追溯链
            parent_instance = id_to_instance[parent_instance_id]
            self._link_parent_child(parent_instance, child_instance)
            return
        
        # 创建新的父级需求实例
        parent_instance = RequirementInstance(
            requirement_instance_id=parent_instance_id,
            requirement_text=parent_template.templates_text,
            requirement_type=parent_template.level,
            category_uid=parent_template.category_uid,
            product_line=child_instance.product_line,
            chip_info=child_instance.chip_info,
            generation_type="template_generated",
            matched_template_id=parent_template.template_id
        )
        
        id_to_instance[parent_instance_id] = parent_instance
        new_instances.append(parent_instance)
        
        # 建立追溯链
        self._link_parent_child(parent_instance, child_instance)
        
        # 递归查找更高层级的父级
        if parent_template.parent_template_id:
            self._create_parent_requirements(
                parent_instance,
                parent_template.parent_template_id,
                template_id_to_template,
                id_to_instance,
                new_instances
            )

    def _create_child_requirements(
        self,
        parent_instance: RequirementInstance,
        child_template_id: str,
        template_id_to_template: Dict[str, Any],
        id_to_instance: Dict[str, RequirementInstance],
        new_instances: List[RequirementInstance]
    ):
        """递归创建子级需求"""
        child_template = template_id_to_template.get(child_template_id)
        if not child_template:
            return
        
        # 检查是否已存在对应的需求实例
        child_instance_id = f"{child_template.level}_{child_template_id}"
        if child_instance_id in id_to_instance:
            # 已存在，建立追溯链
            child_instance = id_to_instance[child_instance_id]
            self._link_parent_child(parent_instance, child_instance)
            return
        
        # 创建新的子级需求实例
        child_instance = RequirementInstance(
            requirement_instance_id=child_instance_id,
            requirement_text=child_template.templates_text,
            requirement_type=child_template.level,
            category_uid=child_template.category_uid,
            product_line=parent_instance.product_line,
            chip_info=parent_instance.chip_info,
            generation_type="template_generated",
            matched_template_id=child_template.template_id
        )
        
        id_to_instance[child_instance_id] = child_instance
        new_instances.append(child_instance)
        
        # 建立追溯链
        self._link_parent_child(parent_instance, child_instance)
        
        # 递归查找更低层级的子级
        if hasattr(child_template, 'child_template_ids') and child_template.child_template_ids:
            for grandchild_tpl_id in child_template.child_template_ids:
                self._create_child_requirements(
                    child_instance,
                    grandchild_tpl_id,
                    template_id_to_template,
                    id_to_instance,
                    new_instances
                )

    def _link_parent_child(
        self,
        parent_instance: RequirementInstance,
        child_instance: RequirementInstance
    ):
        """建立父子需求之间的追溯链关系（模板追溯链专用）"""
        # 设置子级的父级ID
        child_instance.instance_trace_chain["parent_requirement_id"] = parent_instance.requirement_instance_id

        # 设置父级的子级ID列表
        if "child_requirement_ids" not in parent_instance.instance_trace_chain:
            parent_instance.instance_trace_chain["child_requirement_ids"] = []
        if child_instance.requirement_instance_id not in parent_instance.instance_trace_chain["child_requirement_ids"]:
            parent_instance.instance_trace_chain["child_requirement_ids"].append(child_instance.requirement_instance_id)

        self.logger.info(
            "Pipeline",
            child_instance.requirement_instance_id,
            f"通过模板追溯链建立关系 {parent_instance.requirement_instance_id} -> {child_instance.requirement_instance_id}"
        )

    def _link_requirement_instances(
        self,
        instances: List[RequirementInstance],
        id_to_instance: Dict[str, RequirementInstance]
    ):
        """建立所有需求实例之间的追溯链关系"""
        for instance in instances:
            parent_id = instance.instance_trace_chain.get("parent_requirement_id")
            if parent_id and parent_id in id_to_instance:
                parent_instance = id_to_instance[parent_id]
                if "child_requirement_ids" not in parent_instance.instance_trace_chain:
                    parent_instance.instance_trace_chain["child_requirement_ids"] = []
                if instance.requirement_instance_id not in parent_instance.instance_trace_chain["child_requirement_ids"]:
                    parent_instance.instance_trace_chain["child_requirement_ids"].append(instance.requirement_instance_id)

    # ──── 阶段二：逐条生成缺失需求文本的提示词 ────
    GENERATE_REQUIREMENT_PROMPT = """## 当前芯片的需求上下文（同分类下的已有需求）

{context}

## 分类路径

{category_path}

## 产品线

{product_line}

## 需要生成的需求

- ID: {req_id}
- 类型: {req_type}
- 父级: {parent_info}
- 子级: {child_info}

## 任务说明

请根据上下文信息和分类路径，生成这条 {req_type} 需求的具体文本。
生成的需求必须与分类路径中的章节内容相关，符合该章节的主题和范围。

### 核心规则：
1. **反向生成原则**：如果当前需求有子级（例如为L3生成L2），生成的需求必须能合理推导出子级需求。
- 示例：子级是"L3: 测试时间<2.17小时"，则父级L2应该是"支持测试时间优化"或"定义测试时间指标"，而不是无关的"记录交期信息"
2. **层级递进**：L1→L2→L3是抽象到具体的过程：
- L1 (客户需求): 从最终用户或客户角度出发，用业务/商业语言描述"为什么需要这个产品"或"要达到什么商业目标"。通常不涉及技术实现细节。
  示例："设备需要可靠运行"、"数据需要安全存储"、"要延长电池使用寿命"
- L2 (初始需求): 将客户的商业愿望转化为产品经理视角的具体产品特征和目标描述（定性或半定量）。描述"需要什么功能/特性"，但不规定具体实现方案。
  示例："系统应防止无响应"、"应确保数据不丢失"、"需支持低功耗模式"、"提供POR模块设计保障"
- L3 (系统需求): 将产品需求完全量化、技术化，给出明确的、可测试、可验证的技术指标和实现约束。描述"具体如何实现"和"达到什么量化指标"。
  示例："看门狗定时器超时时间为1秒"、"系统响应时间小于100ms"、"待机电流不超过1.9μA"、"数据保持时间大于10年"
3. **内容相关**：生成的需求必须与父级/子级需求主题相关，不能生成无关的内容
4. **分类匹配**：生成的需求必须与分类路径中的章节主题匹配
5. **避免空泛**：文字不要太空泛，比如"以满足业务目标"这种废话

### 输出格式

返回JSON对象：
{{
  "requirement_text": "生成的需求文本"
}}

只返回JSON，不要其他文字。"""

    def _compute_missing_requirements(
        self,
        trace_chains: List[Dict],
        id_to_instance: Dict[str, RequirementInstance],
        identified_levels: Dict[str, List[str]]
    ) -> List[Dict]:
        """
        阶段一b：脚本确定性计算缺失需求

        根据 trace_chains 中每个链路的三元组空位，自动计算需要补全的需求。
        支持同一层级多个ID用逗号分隔的格式（如 "L2-001,L2-002"）

        需求链结构要求：
        - 每一个L1必须对应至少一个L2
        - 每一个L2必须对应至少一个L3
        - 同一链中可以有多个L2共享同一个L1
        - 同一链中可以有多个L3共享同一个L2
        """
        existing_ids = set(id_to_instance.keys())
        l2_ids = set(identified_levels.get("L2_ids", []))
        l3_ids = set(identified_levels.get("L3_ids", []))
        missing = []

        # 辅助函数：解析逗号分隔的ID列表
        def parse_ids(id_str):
            if not id_str:
                return []
            return [s.strip() for s in id_str.split(",") if s.strip()]

        for chain in trace_chains:
            l1_ids = parse_ids(chain.get("L1_id"))
            l2_ids_in_chain = parse_ids(chain.get("L2_id"))
            l3_ids_in_chain = parse_ids(chain.get("L3_id"))

            # ── 处理 L2 需要补 L1 的情况 ──
            if not l1_ids and l2_ids_in_chain:
                # 为第一个L2生成L1
                first_l2 = l2_ids_in_chain[0]
                new_l1_id = f"L1_{first_l2}"
                if new_l1_id not in existing_ids:
                    missing.append({
                        "requirement_id": new_l1_id,
                        "requirement_type": "L1",
                        "parent_id": "",
                        "child_ids": l2_ids_in_chain
                    })
                    existing_ids.add(new_l1_id)

            # ── 处理每个 L2 需要补 L3 的情况 ──
            if l2_ids_in_chain:
                for l2_id in l2_ids_in_chain:
                    # 检查是否已有对应的L3（优先检查当前链，再检查所有已有实例）
                    has_l3 = False
                    
                    if l3_ids_in_chain:
                        for l3_id in l3_ids_in_chain:
                            l3_inst = id_to_instance.get(l3_id)
                            if l3_inst:
                                parent_id = l3_inst.instance_trace_chain.get("parent_requirement_id", "")
                                if parent_id == l2_id:
                                    has_l3 = True
                                    break
                    
                    if not has_l3:
                        for inst in id_to_instance.values():
                            if inst.requirement_type == "L3":
                                parent_id = inst.instance_trace_chain.get("parent_requirement_id", "")
                                if parent_id == l2_id:
                                    has_l3 = True
                                    break
                    
                    if not has_l3:
                        new_l3_id = f"L3_{l2_id}"
                        if new_l3_id not in existing_ids:
                            missing.append({
                                "requirement_id": new_l3_id,
                                "requirement_type": "L3",
                                "parent_id": l2_id,
                                "child_ids": []
                            })
                            existing_ids.add(new_l3_id)

            # ── 处理 L3 需要补 L2 的情况 ──
            if l3_ids_in_chain and not l2_ids_in_chain:
                # 为第一个L3生成L2
                first_l3 = l3_ids_in_chain[0]
                new_l2_id = f"L2_{first_l3}"
                if new_l2_id not in existing_ids:
                    missing.append({
                        "requirement_id": new_l2_id,
                        "requirement_type": "L2",
                        "parent_id": "",
                        "child_ids": l3_ids_in_chain
                    })
                    existing_ids.add(new_l2_id)

        # ── 处理孤立的已有需求（不在任何 trace_chain 中）──
        chained_l2 = set()
        chained_l3 = set()
        for chain in trace_chains:
            l2_list = parse_ids(chain.get("L2_id"))
            l3_list = parse_ids(chain.get("L3_id"))
            chained_l2.update(l2_list)
            chained_l3.update(l3_list)

        # 孤立 L2 → 补 L1 + L3（先检查是否已有对应的L3）
        for l2_id in l2_ids:
            if l2_id not in chained_l2:
                l1_new = f"L1_{l2_id}"
                
                has_existing_l3 = False
                for inst in id_to_instance.values():
                    if inst.requirement_type == "L3":
                        parent_id = inst.instance_trace_chain.get("parent_requirement_id", "")
                        if parent_id == l2_id:
                            has_existing_l3 = True
                            break
                
                if l1_new not in existing_ids:
                    missing.append({
                        "requirement_id": l1_new,
                        "requirement_type": "L1",
                        "parent_id": "",
                        "child_ids": [l2_id]
                    })
                    existing_ids.add(l1_new)
                
                if not has_existing_l3:
                    l3_new = f"L3_{l2_id}"
                    if l3_new not in existing_ids:
                        missing.append({
                            "requirement_id": l3_new,
                            "requirement_type": "L3",
                            "parent_id": l2_id,
                            "child_ids": []
                        })
                        existing_ids.add(l3_new)

        # 孤立 L3 → 补 L1 + L2
        for l3_id in l3_ids:
            if l3_id not in chained_l3:
                l2_new = f"L2_{l3_id}"
                l1_new = f"L1_{l3_id}"
                if l2_new not in existing_ids:
                    missing.append({
                        "requirement_id": l2_new,
                        "requirement_type": "L2",
                        "parent_id": "",
                        "child_ids": [l3_id]
                    })
                    existing_ids.add(l2_new)
                if l1_new not in existing_ids:
                    missing.append({
                        "requirement_id": l1_new,
                        "requirement_type": "L1",
                        "parent_id": "",
                        "child_ids": [l2_new]
                    })
                    existing_ids.add(l1_new)

        return missing

    def _run_topology_completion(self, instances, product_line):
        """
        运行需求追溯拓扑补全（两阶段架构）

        阶段一：LLM 分析识别 → trace_chains + missing_requirements 清单
        阶段二：逐条调用 LLM 生成缺失需求的文本
        阶段三：脚本组装完整 L1→L2→L3 链路（纯代码）
        """
        # 按分类分组，每组独立处理
        category_groups: Dict[str, List[RequirementInstance]] = {}
        for inst in instances:
            cat_uid = inst.category_uid
            if cat_uid not in category_groups:
                category_groups[cat_uid] = []
            category_groups[cat_uid].append(inst)

        all_instances = []

        total_uids = len(category_groups)
        uid_index = 0

        for category_uid, cat_instances in category_groups.items():
            uid_index += 1
            if not category_uid or category_uid == "cat_failed":
                all_instances.extend(cat_instances)
                continue

            id_to_instance = {inst.requirement_instance_id: inst for inst in cat_instances}

            # ════════════════════════════════
            # 阶段一：LLM 识别已有需求之间的关联（含动态层级调整）
            # ════════════════════════════════
            identified_levels, trace_chains_raw, level_adjustments = \
                self.topology_module.analyze(
                    instances=cat_instances,
                    category_uid=category_uid,
                    product_line=product_line,
                    uid_index=uid_index,
                    total_uids=total_uids
                )

            # ════════════════════════════════
            # 阶段一b：脚本确定性计算缺失需求（100% 确定，不依赖 LLM）
            # ════════════════════════════════
            missing_requirements = self._compute_missing_requirements(
                trace_chains_raw, id_to_instance, identified_levels
            )

            self.logger.info(
                "TopologyCompletion", "BATCH",
                f"计算得出缺失需求（共{len(missing_requirements)}条，待生成文本）："
            )
            for req in missing_requirements:
                rid = req["requirement_id"]
                rtype = req["requirement_type"]
                pid = req["parent_id"]
                cids = req["child_ids"]
                self.logger.info(
                    "TopologyCompletion", rid,
                    f"[{rtype}] {rid} (父级={pid}, 子级={cids})"
                )
            if not missing_requirements:
                self.logger.info("TopologyCompletion", "BATCH", "  (无需补全)")

            # ════════════════════════════════
            # 阶段二：逐条调用 LLM 生成文本
            # ════════════════════════════════
            generated_texts = {}  # req_id -> text
            for req in missing_requirements:
                req_id = req.get("requirement_id", "")
                req_type = req.get("requirement_type", "")

                text = self._generate_single_requirement(
                    req=req,
                    context=self._build_topology_context(cat_instances),
                    category_uid=category_uid,
                    product_line=product_line,
                    id_to_instance=id_to_instance
                )
                if text:
                    generated_texts[req_id] = text

            # ════════════════════════════════
            # 阶段三：脚本组装链路（纯代码）
            # ════════════════════════════════

            # 3a. 创建新实例
            for req in missing_requirements:
                req_id = req.get("requirement_id", "")
                req_type = req.get("requirement_type", "")
                parent_id = req.get("parent_id", "")
                child_ids = req.get("child_ids") or []
                text = generated_texts.get(req_id, "")

                if not req_id or not req_type or not text:
                    continue

                new_inst = RequirementInstance(
                    requirement_instance_id=req_id,
                    requirement_text=text,
                    requirement_type=req_type,
                    category_uid=category_uid,
                    generation_type="ai_generated",
                    review_status="pending_review",
                    product_line=product_line,
                    instance_trace_chain={
                        "parent_requirement_id": parent_id,
                        "child_requirement_ids": list(child_ids)
                    }
                )
                cat_instances.append(new_inst)
                id_to_instance[req_id] = new_inst

                self.logger.info(
                    "TopologyCompletion", req_id,
                    f"补全生成{req_type}: {text[:50]}..."
                )

            # 3b. 从 trace_chains 三元组提取所有 parent→child 对
            chain_pairs = []
            for chain in trace_chains_raw:
                l1_id = chain.get("L1_id", "") or ""
                l2_id = chain.get("L2_id", "") or ""
                l3_id = chain.get("L3_id", "") or ""

                if l1_id and l2_id:
                    chain_pairs.append({"parent_requirement_id": l1_id, "child_requirement_id": l2_id})
                if l2_id and l3_id:
                    chain_pairs.append({"parent_requirement_id": l2_id, "child_requirement_id": l3_id})

            # 3c. 从 missing_requirements 补充链路对（含被拦截的引用修正）
            for req in missing_requirements:
                req_id = req.get("requirement_id", "")
                pid = req.get("parent_id", "")
                cids = list(req.get("child_ids") or [])

                if pid and req_id and pid in id_to_instance:
                    pair = {"parent_requirement_id": pid, "child_requirement_id": req_id}
                    if pair not in chain_pairs:
                        chain_pairs.append(pair)

                for cid in cids:
                    if not cid:
                        continue
                    effective_cid = cid
                    if cid not in id_to_instance:
                        for prefix in ("L1_", "L2_", "L3_"):
                            if cid.startswith(prefix):
                                candidate = cid[len(prefix):]
                                if candidate in id_to_instance:
                                    effective_cid = candidate
                                    break
                    if effective_cid and effective_cid in id_to_instance:
                        pair = {"parent_requirement_id": req_id, "child_requirement_id": effective_cid}
                        if pair not in chain_pairs:
                            chain_pairs.append(pair)

                if req_id in id_to_instance:
                    inst = id_to_instance[req_id]
                    fixed_child_ids = []
                    for cid in cids:
                        if not cid:
                            continue
                        if cid in id_to_instance:
                            fixed_child_ids.append(cid)
                        else:
                            for prefix in ("L1_", "L2_", "L3_"):
                                if cid.startswith(prefix):
                                    candidate = cid[len(prefix):]
                                    if candidate in id_to_instance:
                                        fixed_child_ids.append(candidate)
                                        break
                    inst.instance_trace_chain["child_requirement_ids"] = fixed_child_ids

            # 3d. 应用链路（统一写入所有实例的父子关系）
            validated = self._validate_trace_chains(cat_instances, chain_pairs)
            self._apply_trace_chains(cat_instances, validated)

            # 3f. 检查孤立需求：如果仍有实例无父级也无子级关联，递归补全
            max_retry = 1
            for retry in range(max_retry):
                orphans = self._find_orphan_instances(cat_instances, id_to_instance)
                if not orphans:
                    break
                self.logger.info(
                    "TopologyCompletion", "BATCH",
                    f"发现{len(orphans)}个孤立需求，进行第{retry+1}轮补全..."
                )
                # 用孤立需求重新分析（含动态层级调整）
                orphan_levels, extra_chains, _ = \
                    self.topology_module.analyze(
                        instances=orphans,
                        category_uid=category_uid,
                        product_line=product_line
                    )
                # 确定性计算缺失
                extra_filtered = self._compute_missing_requirements(
                    extra_chains,
                    id_to_instance,
                    orphan_levels
                )
                # 生成文本
                for req in extra_filtered:
                    rid = req.get("requirement_id", "")
                    rtype = req.get("requirement_type", "")
                    text = self._generate_single_requirement(
                        req=req,
                        context=self._build_topology_context(cat_instances),
                        category_uid=category_uid,
                        product_line=product_line,
                        id_to_instance=id_to_instance
                    )
                    if text and rid not in id_to_instance:
                        new_inst = RequirementInstance(
                            requirement_instance_id=rid,
                            requirement_text=text,
                            requirement_type=rtype,
                            category_uid=category_uid,
                            generation_type="ai_generated",
                            review_status="pending_review",
                            product_line=product_line,
                            instance_trace_chain={
                                "parent_requirement_id": req.get("parent_id", ""),
                                "child_requirement_ids": list(req.get("child_ids") or [])
                            }
                        )
                        cat_instances.append(new_inst)
                        id_to_instance[rid] = new_inst
                        self.logger.info("TopologyCompletion", rid, f"补全生成{rtype}: {text[:50]}...")
                # 补充链路对并应用
                for chain in extra_chains:
                    l1_id = chain.get("L1_id", "") or ""
                    l2_id = chain.get("L2_id", "") or ""
                    l3_id = chain.get("L3_id", "") or ""
                    if l1_id and l2_id:
                        p = {"parent_requirement_id": l1_id, "child_requirement_id": l2_id}
                        if p not in chain_pairs:
                            chain_pairs.append(p)
                    if l2_id and l3_id:
                        p = {"parent_requirement_id": l2_id, "child_requirement_id": l3_id}
                        if p not in chain_pairs:
                            chain_pairs.append(p)
                for req in extra_filtered:
                    rid = req.get("requirement_id", "")
                    pid = req.get("parent_id", "")
                    cids = req.get("child_ids") or []
                    if pid and rid and pid in id_to_instance:
                        p = {"parent_requirement_id": pid, "child_requirement_id": rid}
                        if p not in chain_pairs:
                            chain_pairs.append(p)
                    for cid in cids:
                        if cid:
                            ecid = cid
                            if cid not in id_to_instance:
                                for prefix in ("L1_", "L2_", "L3_"):
                                    if cid.startswith(prefix):
                                        c = cid[len(prefix):]
                                        if c in id_to_instance:
                                            ecid = c
                                            break
                            if ecid in id_to_instance:
                                p = {"parent_requirement_id": rid, "child_requirement_id": ecid}
                                if p not in chain_pairs:
                                    chain_pairs.append(p)

                validated = self._validate_trace_chains(cat_instances, chain_pairs)
                self._apply_trace_chains(cat_instances, validated)

            # 3e. 完整性检查：确保所有需求都形成完整的三层链路
            self._ensure_full_hierarchy(cat_instances, id_to_instance, category_uid, product_line)

            # 3f. 最终日志（完整三层链路）
            self._log_final_trace_chains(cat_instances)

            all_instances.extend(cat_instances)

        # 去重
        all_instances = self._deduplicate_instances(all_instances)
        return all_instances

    def _ensure_full_hierarchy(
        self,
        cat_instances: List[RequirementInstance],
        id_to_instance: Dict[str, RequirementInstance],
        category_uid: str,
        product_line: str
    ):
        """
        完整性检查：确保所有需求都形成完整的三层链路

        检查规则：
        1. L1 必须有子级（L2），没有则补上 L2 + L3
        2. L2 必须有父级（L1）和子级（L3），缺什么补什么
        3. L3 必须有父级（L2），没有则补上 L2 + L1
        """
        context = self._build_topology_context(cat_instances)
        modified = True
        max_iterations = 3

        for iteration in range(max_iterations):
            if not modified:
                break
            modified = False

            # 收集当前状态
            l1_list = [inst for inst in cat_instances if inst.requirement_type == "L1"]
            l2_list = [inst for inst in cat_instances if inst.requirement_type == "L2"]
            l3_list = [inst for inst in cat_instances if inst.requirement_type == "L3"]

            # 检查 L1：必须有子级
            for l1 in l1_list:
                chain = l1.instance_trace_chain or {}
                cids = chain.get("child_requirement_ids") or []
                has_valid_child = any(cid in id_to_instance for cid in cids)
                if not has_valid_child:
                    self.logger.info(
                        "TopologyCompletion", l1.requirement_instance_id,
                        "L1无有效子级，补全 L2 + L3"
                    )
                    l1_id = l1.requirement_instance_id
                    l2_new_id = f"L2_{l1_id}"
                    l3_new_id = f"L3_{l1_id}"

                    if l2_new_id not in id_to_instance:
                        l2_text = self._generate_single_requirement(
                            req={"requirement_id": l2_new_id, "requirement_type": "L2", "parent_id": l1_id, "child_ids": [l3_new_id]},
                            context=context,
                            category_uid=category_uid,
                            product_line=product_line,
                            id_to_instance=id_to_instance
                        )
                        if l2_text:
                            l2_inst = RequirementInstance(
                                requirement_instance_id=l2_new_id,
                                requirement_text=l2_text,
                                requirement_type="L2",
                                category_uid=category_uid,
                                generation_type="ai_generated",
                                review_status="pending_review",
                                product_line=product_line,
                                instance_trace_chain={
                                    "parent_requirement_id": l1_id,
                                    "child_requirement_ids": [l3_new_id]
                                }
                            )
                            cat_instances.append(l2_inst)
                            id_to_instance[l2_new_id] = l2_inst
                            self.logger.info("TopologyCompletion", l2_new_id, f"补全生成L2: {l2_text[:50]}...")
                            modified = True

                    if l3_new_id not in id_to_instance:
                        parent_for_l3 = l2_new_id if l2_new_id in id_to_instance else l1_id
                        l3_text = self._generate_single_requirement(
                            req={"requirement_id": l3_new_id, "requirement_type": "L3", "parent_id": parent_for_l3, "child_ids": []},
                            context=context,
                            category_uid=category_uid,
                            product_line=product_line,
                            id_to_instance=id_to_instance
                        )
                        if l3_text:
                            l3_inst = RequirementInstance(
                                requirement_instance_id=l3_new_id,
                                requirement_text=l3_text,
                                requirement_type="L3",
                                category_uid=category_uid,
                                generation_type="ai_generated",
                                review_status="pending_review",
                                product_line=product_line,
                                instance_trace_chain={
                                    "parent_requirement_id": parent_for_l3,
                                    "child_requirement_ids": []
                                }
                            )
                            cat_instances.append(l3_inst)
                            id_to_instance[l3_new_id] = l3_inst
                            self.logger.info("TopologyCompletion", l3_new_id, f"补全生成L3: {l3_text[:50]}...")
                            modified = True

            # 检查 L2：必须有父级和子级
            for l2 in l2_list:
                chain = l2.instance_trace_chain or {}
                pid = chain.get("parent_requirement_id", "")
                cids = chain.get("child_requirement_ids") or []
                has_parent = pid and pid in id_to_instance
                has_child = any(cid in id_to_instance for cid in cids)

                # 缺父级（L1）
                if not has_parent:
                    self.logger.info(
                        "TopologyCompletion", l2.requirement_instance_id,
                        "L2无有效父级，补全 L1"
                    )
                    l2_id = l2.requirement_instance_id
                    l1_new_id = f"L1_{l2_id}"
                    if l1_new_id not in id_to_instance:
                        l1_text = self._generate_single_requirement(
                            req={"requirement_id": l1_new_id, "requirement_type": "L1", "parent_id": "", "child_ids": [l2_id]},
                            context=context,
                            category_uid=category_uid,
                            product_line=product_line,
                            id_to_instance=id_to_instance
                        )
                        if l1_text:
                            l1_inst = RequirementInstance(
                                requirement_instance_id=l1_new_id,
                                requirement_text=l1_text,
                                requirement_type="L1",
                                category_uid=category_uid,
                                generation_type="ai_generated",
                                review_status="pending_review",
                                product_line=product_line,
                                instance_trace_chain={
                                    "parent_requirement_id": "",
                                    "child_requirement_ids": [l2_id]
                                }
                            )
                            cat_instances.append(l1_inst)
                            id_to_instance[l1_new_id] = l1_inst
                            self.logger.info("TopologyCompletion", l1_new_id, f"补全生成L1: {l1_text[:50]}...")
                            modified = True

                # 缺子级（L3）
                if not has_child:
                    self.logger.info(
                        "TopologyCompletion", l2.requirement_instance_id,
                        "L2无有效子级，补全 L3"
                    )
                    l2_id = l2.requirement_instance_id
                    l3_new_id = f"L3_{l2_id}"
                    if l3_new_id not in id_to_instance:
                        l3_text = self._generate_single_requirement(
                            req={"requirement_id": l3_new_id, "requirement_type": "L3", "parent_id": l2_id, "child_ids": []},
                            context=context,
                            category_uid=category_uid,
                            product_line=product_line,
                            id_to_instance=id_to_instance
                        )
                        if l3_text:
                            l3_inst = RequirementInstance(
                                requirement_instance_id=l3_new_id,
                                requirement_text=l3_text,
                                requirement_type="L3",
                                category_uid=category_uid,
                                generation_type="ai_generated",
                                review_status="pending_review",
                                product_line=product_line,
                                instance_trace_chain={
                                    "parent_requirement_id": l2_id,
                                    "child_requirement_ids": []
                                }
                            )
                            cat_instances.append(l3_inst)
                            id_to_instance[l3_new_id] = l3_inst
                            self.logger.info("TopologyCompletion", l3_new_id, f"补全生成L3: {l3_text[:50]}...")
                            modified = True

            # 检查 L3：必须有父级
            for l3 in l3_list:
                chain = l3.instance_trace_chain or {}
                pid = chain.get("parent_requirement_id", "")
                has_parent = pid and pid in id_to_instance
                if not has_parent:
                    self.logger.info(
                        "TopologyCompletion", l3.requirement_instance_id,
                        "L3无有效父级，补全 L2 + L1"
                    )
                    l3_id = l3.requirement_instance_id
                    l2_new_id = f"L2_{l3_id}"
                    l1_new_id = f"L1_{l3_id}"

                    if l2_new_id not in id_to_instance:
                        l2_text = self._generate_single_requirement(
                            req={"requirement_id": l2_new_id, "requirement_type": "L2", "parent_id": l1_new_id, "child_ids": [l3_id]},
                            context=context,
                            category_uid=category_uid,
                            product_line=product_line,
                            id_to_instance=id_to_instance
                        )
                        if l2_text:
                            l2_inst = RequirementInstance(
                                requirement_instance_id=l2_new_id,
                                requirement_text=l2_text,
                                requirement_type="L2",
                                category_uid=category_uid,
                                generation_type="ai_generated",
                                review_status="pending_review",
                                product_line=product_line,
                                instance_trace_chain={
                                    "parent_requirement_id": l1_new_id,
                                    "child_requirement_ids": [l3_id]
                                }
                            )
                            cat_instances.append(l2_inst)
                            id_to_instance[l2_new_id] = l2_inst
                            self.logger.info("TopologyCompletion", l2_new_id, f"补全生成L2: {l2_text[:50]}...")
                            modified = True

                    if l1_new_id not in id_to_instance:
                        l1_text = self._generate_single_requirement(
                            req={"requirement_id": l1_new_id, "requirement_type": "L1", "parent_id": "", "child_ids": [l2_new_id]},
                            context=context,
                            category_uid=category_uid,
                            product_line=product_line,
                            id_to_instance=id_to_instance
                        )
                        if l1_text:
                            l1_inst = RequirementInstance(
                                requirement_instance_id=l1_new_id,
                                requirement_text=l1_text,
                                requirement_type="L1",
                                category_uid=category_uid,
                                generation_type="ai_generated",
                                review_status="pending_review",
                                product_line=product_line,
                                instance_trace_chain={
                                    "parent_requirement_id": "",
                                    "child_requirement_ids": [l2_new_id]
                                }
                            )
                            cat_instances.append(l1_inst)
                            id_to_instance[l1_new_id] = l1_inst
                            self.logger.info("TopologyCompletion", l1_new_id, f"补全生成L1: {l1_text[:50]}...")
                            modified = True

            # 更新链路关系
            if modified:
                chain_pairs = []
                for inst in cat_instances:
                    chain = inst.instance_trace_chain or {}
                    pid = chain.get("parent_requirement_id", "")
                    cids = chain.get("child_requirement_ids") or []
                    if pid and pid in id_to_instance:
                        chain_pairs.append({"parent_requirement_id": pid, "child_requirement_id": inst.requirement_instance_id})
                    for cid in cids:
                        if cid in id_to_instance:
                            chain_pairs.append({"parent_requirement_id": inst.requirement_instance_id, "child_requirement_id": cid})
                validated = self._validate_trace_chains(cat_instances, chain_pairs)
                self._apply_trace_chains(cat_instances, validated)

    def _find_orphan_instances(
        self,
        instances: List[RequirementInstance],
        id_to_instance: Dict[str, RequirementInstance]
    ) -> List[RequirementInstance]:
        """
        找出孤立需求：既没有父级也没有子级关联的实例

        孤立定义：
        - L1 实例：无 child_requirement_ids（没有子级）
        - L2 实例：无 parent_requirement_id 且无 child_requirement_ids
        - L3 实例：无 parent_requirement_id（没有父级）
        """
        orphans = []
        for inst in instances:
            chain = inst.instance_trace_chain or {}
            pid = chain.get("parent_requirement_id", "")
            cids = chain.get("child_requirement_ids") or []

            has_parent = bool(pid and pid in id_to_instance)
            has_children = any(cid in id_to_instance for cid in cids)

            if inst.requirement_type == "L1":
                if not has_children:
                    orphans.append(inst)
            elif inst.requirement_type == "L2":
                if not has_parent and not has_children:
                    orphans.append(inst)
            elif inst.requirement_type == "L3":
                if not has_parent:
                    orphans.append(inst)

        return orphans

    def _cleanup_duplicate_orphan_instances(
        self,
        instances: List[RequirementInstance]
    ) -> List[RequirementInstance]:
        """
        清理重复的孤立需求：
        1. 检查孤立需求是否已存在于某个完整的追溯链中
        2. 如果已存在，只删除LLM生成的重复需求，保留原始需求
        3. 如果需求链不完整且只差这一个需求，则连接需求链

        Args:
            instances: 需求实例列表

        Returns:
            清理后的需求实例列表
        """
        id_to_instance = {inst.requirement_instance_id: inst for inst in instances}
        
        # 找出所有孤立需求
        orphans = self._find_orphan_instances(instances, id_to_instance)
        
        if not orphans:
            return instances
        
        # 收集所有已形成链的需求及其信息
        chained_info = {}  # base_id -> {id, generation_type}
        for inst in instances:
            chain = inst.instance_trace_chain or {}
            if chain:
                base_id = inst.requirement_instance_id.replace("L1_", "").replace("L2_", "").replace("L3_", "")
                if base_id not in chained_info:
                    chained_info[base_id] = {
                        "id": inst.requirement_instance_id,
                        "generation_type": inst.generation_type
                    }
                # 检查子级
                cids = chain.get("child_requirement_ids", [])
                for cid in cids:
                    c_base_id = cid.replace("L1_", "").replace("L2_", "").replace("L3_", "")
                    if c_base_id not in chained_info:
                        if cid in id_to_instance:
                            chained_info[c_base_id] = {
                                "id": cid,
                                "generation_type": id_to_instance[cid].generation_type
                            }
                # 检查父级
                pid = chain.get("parent_requirement_id")
                if pid:
                    p_base_id = pid.replace("L1_", "").replace("L2_", "").replace("L3_", "")
                    if p_base_id not in chained_info:
                        if pid in id_to_instance:
                            chained_info[p_base_id] = {
                                "id": pid,
                                "generation_type": id_to_instance[pid].generation_type
                            }
        
        # 找出需要删除的重复需求（只删除AI生成的版本）
        to_remove = []
        for orphan in orphans:
            # 检查是否已有相同基础ID在链中
            base_id = orphan.requirement_instance_id.replace("L1_", "").replace("L2_", "").replace("L3_", "")
            
            if base_id in chained_info:
                chained_info_item = chained_info[base_id]
                chained_type = chained_info_item["generation_type"]
                orphan_type = orphan.generation_type
                
                # 决策逻辑：
                # 1. 如果孤立需求是AI生成的，而链中是原始需求 → 删除AI生成的孤立需求
                # 2. 如果孤立需求是原始需求，而链中是AI生成的 → 删除链中的AI生成需求，保留原始需求
                # 3. 如果两者都是AI生成或都是原始需求 → 删除孤立版本
                
                should_remove_orphan = True
                remove_reason = ""
                
                if orphan_type == "ai_generated" and chained_type != "ai_generated":
                    should_remove_orphan = True
                    remove_reason = "（AI生成的重复需求）"
                elif orphan_type != "ai_generated" and chained_type == "ai_generated":
                    should_remove_orphan = False
                    # 删除链中的AI生成版本
                    to_remove.append(chained_info_item["id"])
                    self.logger.info(
                        "Pipeline",
                        "BATCH",
                        f"发现重复需求 {chained_info_item['id']}，保留原始需求 {orphan.requirement_instance_id}，删除AI生成版本"
                    )
                else:
                    should_remove_orphan = True
                    remove_reason = "（重复的孤立版本）"
                
                if should_remove_orphan:
                    to_remove.append(orphan.requirement_instance_id)
                    self.logger.info(
                        "Pipeline",
                        "BATCH",
                        f"发现重复需求 {orphan.requirement_instance_id}，已存在于追溯链中，将删除{remove_reason}"
                    )
        
        # 删除重复的需求
        if to_remove:
            instances = [inst for inst in instances if inst.requirement_instance_id not in to_remove]
            self.logger.info(
                "Pipeline",
                "BATCH",
                f"共清理 {len(to_remove)} 个重复需求"
            )
        
        # 更新 id_to_instance
        id_to_instance = {inst.requirement_instance_id: inst for inst in instances}
        
        # 第二部分：检查是否有需求链可以通过孤立需求补全
        remaining_orphans = self._find_orphan_instances(instances, id_to_instance)
        for orphan in remaining_orphans:
            self._try_connect_incomplete_chain(orphan, instances, id_to_instance)
        
        return instances

    def _try_connect_incomplete_chain(
        self,
        orphan: RequirementInstance,
        instances: List[RequirementInstance],
        id_to_instance: Dict[str, RequirementInstance]
    ):
        """
        尝试将孤立需求连接到不完整的需求链
        
        Args:
            orphan: 孤立需求实例
            instances: 所有需求实例列表
            id_to_instance: ID到实例的映射
        """
        orphan_base_id = orphan.requirement_instance_id.replace("L1_", "").replace("L2_", "").replace("L3_", "")
        
        # 查找是否有不完整的链缺少这个需求
        for inst in instances:
            if inst.requirement_instance_id == orphan.requirement_instance_id:
                continue
            
            chain = inst.instance_trace_chain or {}
            if not chain:
                continue
            
            # 获取该链的所有相关ID
            chain_ids = set()
            chain_ids.add(inst.requirement_instance_id)
            
            pid = chain.get("parent_requirement_id")
            if pid:
                chain_ids.add(pid)
            
            cids = chain.get("child_requirement_ids", [])
            chain_ids.update(cids)
            
            # 检查是否可以连接
            for cid in chain_ids:
                base_id = cid.replace("L1_", "").replace("L2_", "").replace("L3_", "")
                if base_id == orphan_base_id:
                    # 找到相同基础ID的需求在链中
                    # 检查是否可以补充连接
                    self._connect_chain_with_orphan(inst, orphan, chain_ids)
                    return

    def _connect_chain_with_orphan(
        self,
        chain_inst: RequirementInstance,
        orphan: RequirementInstance,
        chain_ids: set
    ):
        """
        将孤立需求连接到需求链
        
        Args:
            chain_inst: 链中的需求实例
            orphan: 孤立需求实例
            chain_ids: 链中所有ID的集合
        """
        orphan_id = orphan.requirement_instance_id
        orphan_level = orphan.requirement_type
        
        # 根据层级决定如何连接
        if orphan_level == "L1":
            # L1 可以作为链的根节点
            for inst_id in chain_ids:
                if inst_id.startswith("L2_"):
                    self.logger.info(
                        "Pipeline",
                        "BATCH",
                        f"将孤立需求 {orphan_id} 连接到需求链，作为 L2({inst_id}) 的父级"
                    )
                    return
        elif orphan_level == "L2":
            # L2 可以连接到 L1 或 L3
            for inst_id in chain_ids:
                if inst_id.startswith("L1_"):
                    self.logger.info(
                        "Pipeline",
                        "BATCH",
                        f"将孤立需求 {orphan_id} 连接到需求链，作为 L1({inst_id}) 的子级"
                    )
                    return
                elif inst_id.startswith("L3_"):
                    self.logger.info(
                        "Pipeline",
                        "BATCH",
                        f"将孤立需求 {orphan_id} 连接到需求链，作为 L3({inst_id}) 的父级"
                    )
                    return
        elif orphan_level == "L3":
            # L3 可以作为链的叶子节点
            for inst_id in chain_ids:
                if inst_id.startswith("L2_"):
                    self.logger.info(
                        "Pipeline",
                        "BATCH",
                        f"将孤立需求 {orphan_id} 连接到需求链，作为 L2({inst_id}) 的子级"
                    )
                    return

    def _build_topology_context(self, instances):
        """构建供阶段二使用的上下文"""
        lines = []
        for inst in instances:
            lines.append(f"[{inst.requirement_type}] {inst.requirement_instance_id}: {inst.requirement_text}")
        return "\n".join(lines)

    def _generate_single_requirement(
        self,
        req: Dict,
        context: str,
        category_uid: str,
        product_line: str,
        id_to_instance: Dict[str, RequirementInstance]
    ) -> str:
        """
        阶段二：对单条缺失需求调用 LLM 生成文本

        Returns:
            生成的需求文本，失败返回空字符串
        """
        req_id = req.get("requirement_id", "")
        req_type = req.get("requirement_type", "")
        parent_id = req.get("parent_id", "")
        child_ids = req.get("child_ids") or []

        # 构造父级信息
        parent_info = "无（L1 无父级）"
        if parent_id and parent_id in id_to_instance:
            p = id_to_instance[parent_id]
            parent_info = f"{p.requirement_type}({parent_id}) - {p.requirement_text[:80]}"

        # 构造子级信息
        child_info = "无"
        if child_ids:
            parts = []
            for cid in child_ids:
                if cid in id_to_instance:
                    c = id_to_instance[cid]
                    parts.append(f"{c.requirement_type}({cid}) - {c.requirement_text[:60]}")
                else:
                    parts.append(f"待生成({cid})")
            child_info = "; ".join(parts) if parts else "无"

        # 获取完整的分类路径
        category_path = ""
        if self.categorization_module and hasattr(self.categorization_module, 'category_db'):
            category_path = self.categorization_module.category_db.get_category_path(category_uid)
            if not category_path:
                category_path = f"未知分类({category_uid})"

        prompt = self.GENERATE_REQUIREMENT_PROMPT.format(
            context=context,
            category_path=category_path,
            product_line=product_line,
            req_id=req_id,
            req_type=req_type,
            parent_info=parent_info,
            child_info=child_info
        )

        try:
            result = self.llm_client.request_json_output(prompt=prompt)
            if result:
                text = result.get("requirement_text", "")
                if text:
                    return text

            self.logger.warning("TopologyCompletion", req_id, "LLM 未返回有效文本")
            return ""

        except Exception as e:
            self.logger.error("TopologyCompletion", req_id, f"生成文本异常: {str(e)}")
            return ""

    def _validate_and_fix_hierarchy(
        self,
        instances: List[RequirementInstance]
    ) -> List[RequirementInstance]:
        """
        统一校验层：确保 L1→L2→L3 层级关系
        
        检查所有需求实例的层级关系，确保：
        1. L3 需求的父级必须是 L2
        2. L2 需求的父级必须是 L1
        3. 修复不符合规则的层级关系（找不到匹配父级时生成新的）
        """
        id_to_instance = {inst.requirement_instance_id: inst for inst in instances}
        new_instances = []
        
        for inst in instances:
            if inst.requirement_type == "L3":
                # L3 需求的父级必须是 L2
                parent_id = inst.instance_trace_chain.get("parent_requirement_id")
                if parent_id:
                    parent_inst = id_to_instance.get(parent_id)
                    if parent_inst and parent_inst.requirement_type != "L2":
                        # 父级不是 L2，需要修复
                        new_parent = self._find_and_set_correct_parent(inst, id_to_instance, "L2")
                        if new_parent:
                            new_instances.append(new_parent)
                            id_to_instance[new_parent.requirement_instance_id] = new_parent
                else:
                    # 没有父级，查找合适的 L2 父级
                    new_parent = self._find_and_set_correct_parent(inst, id_to_instance, "L2")
                    if new_parent:
                        new_instances.append(new_parent)
                        id_to_instance[new_parent.requirement_instance_id] = new_parent
            
            elif inst.requirement_type == "L2":
                # L2 需求的父级必须是 L1
                parent_id = inst.instance_trace_chain.get("parent_requirement_id")
                if parent_id:
                    parent_inst = id_to_instance.get(parent_id)
                    if parent_inst and parent_inst.requirement_type != "L1":
                        # 父级不是 L1，需要修复
                        new_parent = self._find_and_set_correct_parent(inst, id_to_instance, "L1")
                        if new_parent:
                            new_instances.append(new_parent)
                            id_to_instance[new_parent.requirement_instance_id] = new_parent
                else:
                    # 没有父级，查找合适的 L1 父级
                    new_parent = self._find_and_set_correct_parent(inst, id_to_instance, "L1")
                    if new_parent:
                        new_instances.append(new_parent)
                        id_to_instance[new_parent.requirement_instance_id] = new_parent
        
        # 添加新生成的父级实例
        instances.extend(new_instances)
        
        return instances

    def _find_and_set_correct_parent(
        self,
        child_inst: RequirementInstance,
        id_to_instance: Dict[str, RequirementInstance],
        target_type: str
    ) -> Optional[RequirementInstance]:
        """查找并设置正确的父级需求（带防覆盖保护）        
        策略：
        1. 优先寻找编码一致的父级（如 L3_209448-4_0 对应 L2_209448-4）
        2. 如果找不到编码一致的，生成新的父级需求
        3. 确保同分类关联，不随意关联到其他需求        
        返回：新生成的父级实例（如果有的话），供调用方添加到实例列表
        """
        # 🔒【防覆盖保护】如果已经有有效的父级关系，不进行修改
        existing_parent_id = child_inst.instance_trace_chain.get("parent_requirement_id")
        if existing_parent_id:
            existing_parent = id_to_instance.get(existing_parent_id)
            if existing_parent and existing_parent.requirement_type == target_type:
                # 已有正确的父级，无需修改
                return None
        
        # 获取子需求的基础ID（用于匹配父级）
        # 例如：L3_209448-4_0 对应 209448-4
        child_base_id = child_inst.requirement_instance_id.split("_")[0]
        if "_" in child_inst.requirement_instance_id:
            # 处理 L3_209448-4_0 这种格式
            parts = child_inst.requirement_instance_id.split("_")
            if len(parts) >= 2:
                child_base_id = parts[1]
        
        # 查找同一分类下的目标类型需求
        candidates = [
            inst for inst in id_to_instance.values()
            if inst.requirement_type == target_type and 
               inst.category_uid == child_inst.category_uid
        ]
        
        if candidates:
            # 优先选择编码一致的父级
            best_candidate = None
            for candidate in candidates:
                # 检查是否编码一致（如 L3_209448-4_0 对应 L2_209448-4）
                if child_base_id in candidate.requirement_instance_id:
                    best_candidate = candidate
                    break
            
            if best_candidate:
                # ✅找到编码一致的父级
                self._link_parent_child(best_candidate, child_inst)
                self.logger.info(
                    "Topology",
                    child_inst.requirement_instance_id,
                    f"层级关系修复：{child_inst.requirement_type}({child_inst.requirement_instance_id})关联到同编码{target_type}父级({best_candidate.requirement_instance_id})"
                )
                return None
            else:
                # 找不到编码一致的父级，生成新的父级需求
                return self._generate_new_parent(child_inst, target_type, child_base_id)
        
        else:
            # 同一分类下没有目标类型的需求，生成新的父级需求
            return self._generate_new_parent(child_inst, target_type, child_base_id)

    def _generate_new_parent(self, child_inst: RequirementInstance, target_type: str, child_base_id: str) -> RequirementInstance:
        """生成新的父级需求"""
        # 生成父级ID（保持编码一致）
        parent_id = f"{target_type}_{child_base_id}"

        # 生成父级需求文本（基于子级需求）
        parent_text = f"基于{child_inst.requirement_type}需求({child_inst.requirement_instance_id})推导的{target_type}需求：{child_inst.requirement_text[:50]}..."

        # 创建父级实例
        parent_instance = RequirementInstance(
            requirement_instance_id=parent_id,
            requirement_text=parent_text,
            requirement_type=target_type,
            category_uid=child_inst.category_uid,
            generation_type="ai_generated",
            review_status="pending_review",
            product_line=child_inst.product_line,
            instance_trace_chain={"parent_requirement_id": "", "child_requirement_ids": [child_inst.requirement_instance_id]}
        )

        # 设置子级的父级ID
        child_inst.instance_trace_chain["parent_requirement_id"] = parent_id

        self.logger.warning(
            "Topology",
            child_inst.requirement_instance_id,
            f"层级关系修复：为{child_inst.requirement_type}({child_inst.requirement_instance_id})生成新的{target_type}父级({parent_id})"
        )

        return parent_instance

    def _deduplicate_instances(
        self,
        instances: List[RequirementInstance]
    ) -> List[RequirementInstance]:
        """去重需求实例，保留第一个出现的实例"""
        seen_ids = set()
        result = []
        for inst in instances:
            if inst.requirement_instance_id not in seen_ids:
                seen_ids.add(inst.requirement_instance_id)
                result.append(inst)
        return result

    def _validate_trace_chains(
        self,
        instances: List[RequirementInstance],
        trace_chains: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        ✨【强校验】过滤并修复不符合L1→L2→L3规则的追踪链
        """
        id_to_instance = {inst.requirement_instance_id: inst for inst in instances}
        valid_chains = []
        
        for chain in trace_chains:
            parent_id = chain.get("parent_requirement_id")
            child_id = chain.get("child_requirement_id")
            
            if parent_id not in id_to_instance or child_id not in id_to_instance:
                continue
            
            parent_inst = id_to_instance[parent_id]
            child_inst = id_to_instance[child_id]
            
            # 强校验：只有L1→L2 或 L2→L3 是合法的
            if (parent_inst.requirement_type == "L1" and child_inst.requirement_type == "L2") or \
               (parent_inst.requirement_type == "L2" and child_inst.requirement_type == "L3"):
                valid_chains.append(chain)
            else:
                self.logger.warning(
                    "Topology",
                    child_id,
                    f"拒绝非法追踪链 {parent_inst.requirement_type}({parent_id}) → {child_inst.requirement_type}({child_id})"
                )

        return valid_chains

    def _apply_trace_chains(
        self,
        instances: List[RequirementInstance],
        trace_chains: List[Dict[str, Any]]
    ):
        """
        ✨应用追溯链：将通过校验的 L1→L2→L3 关系写入实例
        ✨【单父子级约束】每个 L3 只能有 1 个 L2 父级，每个 L2 只能有 1 个 L1 父级
        """
        id_to_instance = {inst.requirement_instance_id: inst for inst in instances}

        for chain in trace_chains:
            parent_id = chain.get("parent_requirement_id")
            child_id = chain.get("child_requirement_id")

            if parent_id not in id_to_instance or child_id not in id_to_instance:
                continue

            parent_inst = id_to_instance[parent_id]
            child_inst = id_to_instance[child_id]

            # ✨【单父子级约束】如果子级已经有同类型父级，则不再覆盖
            existing_parent_id = child_inst.instance_trace_chain.get("parent_requirement_id")
            if existing_parent_id and existing_parent_id != parent_id:
                # 仅当现有父级不属于合法层级时才覆盖
                existing_parent = id_to_instance.get(existing_parent_id)
                if existing_parent and (
                    (child_inst.requirement_type == "L3" and existing_parent.requirement_type == "L2") or
                    (child_inst.requirement_type == "L2" and existing_parent.requirement_type == "L1")
                ):
                    # 子级已有合法类型的父级，保留现有关系
                    self.logger.warning(
                        "Topology",
                        child_id,
                        f"拒绝重复父级：{child_inst.requirement_type}({child_id}) 已存在合法父级 {existing_parent.requirement_type}({existing_parent_id})，跳过 {parent_inst.requirement_type}({parent_id})"
                    )
                    continue

            # 设置子级的父级ID
            child_inst.instance_trace_chain["parent_requirement_id"] = parent_id

            # 设置父级的子级ID列表
            if "child_requirement_ids" not in parent_inst.instance_trace_chain:
                parent_inst.instance_trace_chain["child_requirement_ids"] = []
            if child_id not in parent_inst.instance_trace_chain["child_requirement_ids"]:
                parent_inst.instance_trace_chain["child_requirement_ids"].append(child_id)

    def _log_final_trace_chains(self, instances: List[RequirementInstance]):
        """打印最终完整追溯链（拼接为 L1→L2→L3 三层链路）
        
        支持一个父节点有多个子节点的情况：
        - L1 可以有多个 L2 子节点
        - L2 可以有多个 L3 子节点
        - 每个完整的 L1→L2→L3 路径都会被单独打印
        """
        id_to_instance = {inst.requirement_instance_id: inst for inst in instances}

        # 找到所有 L1（无父级或父级不在当前组）
        l1_instances = []
        for inst in instances:
            parent_id = inst.instance_trace_chain.get("parent_requirement_id", "")
            if not parent_id or parent_id not in id_to_instance:
                l1_instances.append(inst)

        # 为每个 L1 生成所有可能的完整链路
        full_chains = []
        
        for l1_inst in l1_instances:
            l2_ids = l1_inst.instance_trace_chain.get("child_requirement_ids") or []
            
            if not l2_ids:
                # L1 没有子节点，单独一条链
                full_chains.append(f"L1({l1_inst.requirement_instance_id})")
                continue
            
            # 遍历每个 L2 子节点
            for l2_id in l2_ids:
                if l2_id not in id_to_instance:
                    # L2 不存在，只打印到 L1
                    full_chains.append(f"L1({l1_inst.requirement_instance_id}) → L2({l2_id})")
                    continue
                
                l2_inst = id_to_instance[l2_id]
                l3_ids = l2_inst.instance_trace_chain.get("child_requirement_ids") or []
                
                if not l3_ids:
                    # L2 没有子节点
                    full_chains.append(f"L1({l1_inst.requirement_instance_id}) → L2({l2_id})")
                    continue
                
                # 遍历每个 L3 子节点，生成完整链路
                for l3_id in l3_ids:
                    if l3_id in id_to_instance:
                        full_chains.append(
                            f"L1({l1_inst.requirement_instance_id}) → L2({l2_id}) → L3({l3_id})"
                        )
                    else:
                        full_chains.append(
                            f"L1({l1_inst.requirement_instance_id}) → L2({l2_id}) → L3({l3_id})"
                        )

        # 处理没有 L1 的孤立节点
        visited_ids = set()
        for chain in full_chains:
            # 提取所有 ID（格式：L1(id), L2(id), L3(id)）
            import re
            matches = re.findall(r'L[123]\(([^)]+)\)', chain)
            visited_ids.update(matches)
        
        # 检查是否有孤立的 L2 或 L3
        for inst in instances:
            if inst.requirement_instance_id not in visited_ids:
                parent_id = inst.instance_trace_chain.get("parent_requirement_id", "")
                if parent_id and parent_id not in visited_ids:
                    # 父节点也未被访问，说明是一条独立的链
                    chain_str = f"{inst.requirement_type}({inst.requirement_instance_id})"
                    
                    # 如果有子节点，尝试构建完整链路
                    child_ids = inst.instance_trace_chain.get("child_requirement_ids") or []
                    for child_id in child_ids:
                        if child_id in id_to_instance:
                            child_inst = id_to_instance[child_id]
                            chain_str += f" → {child_inst.requirement_type}({child_id})"
                            
                            # 继续检查孙节点
                            grandchild_ids = child_inst.instance_trace_chain.get("child_requirement_ids") or []
                            for gc_id in grandchild_ids:
                                if gc_id in id_to_instance:
                                    gc_inst = id_to_instance[gc_id]
                                    chain_str += f" → {gc_inst.requirement_type}({gc_id})"
                    
                    full_chains.append(chain_str)
                    visited_ids.add(inst.requirement_instance_id)

        if full_chains:
            self.logger.info("TopologyCompletion", "BATCH", f"最终完整追溯链（共{len(full_chains)}条）：")
            for i, chain in enumerate(full_chains, 1):
                self.logger.info("TopologyCompletion", "BATCH", f"  [{i}] {chain}")
        else:
            self.logger.info("TopologyCompletion", "BATCH", "最终完整追溯链：（无）")


    def save_instances(self, instances: list, chip_info: str = "") -> Optional[str]:
        """
        保存所有需求实例到JSON文件

        Args:
            instances: 需求实例列表
            chip_info: 芯片信息（用于文件名）

        Returns:
            保存的文件路径
        """
        if not instances:
            return None

        import json
        from datetime import datetime

        output_dir = os.path.join(self.output_dir, "library")
        os.makedirs(output_dir, exist_ok=True)

        safe_chip = chip_info.replace("[", "_").replace("]", "_").replace("/", "_").replace("\\", "_") if chip_info else ""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"instances_{safe_chip}_{timestamp}.json" if safe_chip else f"instances_{timestamp}.json"
        filepath = os.path.join(output_dir, filename)

        instances_data = []
        for inst in instances:
            inst_dict = {
                "requirement_instance_id": inst.requirement_instance_id,
                "requirement_text": inst.requirement_text,
                "requirement_type": inst.requirement_type,
                "category_uid": inst.category_uid,
                "generation_type": inst.generation_type,
                "review_status": inst.review_status,
                "product_line": inst.product_line,
                "instance_trace_chain": inst.instance_trace_chain,
                "template_id": getattr(inst, 'template_id', None),
                "extracted_variables": getattr(inst, 'extracted_variables', {}),
                "created_at": datetime.now().isoformat()
            }
            instances_data.append(inst_dict)

        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(instances_data, f, ensure_ascii=False, indent=2)

        self.logger.info(
            "Pipeline",
            "BATCH",
            f"已保存 {len(instances_data)} 条需求实例到: {filepath}"
        )

        return filepath

    def save_audit_logs(self, batch_id: Optional[str] = None):
        """保存审计日志"""
        self.audit_logger.save_audit_logs(batch_id=batch_id)

    def finalize(
        self,
        instances: List[RequirementInstance],
        product_line: str = "",
        chip_info: str = "",
        save_logs: bool = True
    ) -> Dict[str, Any]:
        """
        完成流水线处理，执行持久化
        Args:
            instances: 需求实例列表
            product_line: 产品线名称
            chip_info: 芯片信息
            save_logs: 是否保存审计日志

        Returns:
            处理结果汇总
        """
        results = {
            "total_count": len(instances),
            "approved_count": sum(1 for i in instances if i.review_status == "approved"),
            "pending_count": sum(1 for i in instances if i.review_status == "pending_review"),
            "ai_generated_count": sum(1 for i in instances if i.generation_type == "ai_generated"),
            "statistics": self.visualization_module.generate_summary_stats(instances)
        }

        instances_path = self.save_instances(instances, chip_info=chip_info)
        if instances_path:
            results["instances_file"] = instances_path

        # 按产品线保存待定模板
        if hasattr(self.template_matching_module, 'save_pending_templates_by_product') and product_line:
            pending_templates_path = self.template_matching_module.save_pending_templates_by_product(
                product_line=product_line,
                chip_info=chip_info
            )
        else:
            pending_templates_path = self.save_pending_templates()
        if pending_templates_path:
            results["pending_templates_file"] = pending_templates_path

        if save_logs:
            self.save_audit_logs()
            results["audit_logs_saved"] = True

        # 批量保存分类缓存
        self._save_classification_cache(product_line)

        return results


    def save_pending_templates(self) -> Optional[str]:
        """
        保存待定新模板到文件

        Returns:
            保存的文件路径，如果没有待定模板则返回None
        """
        if not hasattr(self, 'template_matching_module'):
            return None
        
        pending_templates = getattr(self.template_matching_module, 'pending_templates', [])
        if not pending_templates:
            return None
        
        import json
        from datetime import datetime
        
        # 确保输出目录存在
        output_dir = os.path.join(self.output_dir, "library")
        os.makedirs(output_dir, exist_ok=True)
        
        # 生成文件名
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filepath = os.path.join(output_dir, f"pending_templates_{timestamp}.json")
        
        # 转换为字典列表
        templates_data = []
        for tpl in pending_templates:
            tpl_dict = {
                "template_id": tpl.template_id,
                "level": tpl.level,
                "category_uid": tpl.category_uid,
                "templates_text": tpl.templates_text,
                "product_lines": tpl.product_lines,
                "variables": tpl.variables,
                "created_at": datetime.now().isoformat()
            }
            templates_data.append(tpl_dict)
        
        # 保存到文件
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(templates_data, f, ensure_ascii=False, indent=2)
        
        self.logger.info(
            "TemplateMatch",
            "BATCH",
            f"成功保存 {len(pending_templates)} 个待定模板到: {filepath}"
        )
        
        return filepath
