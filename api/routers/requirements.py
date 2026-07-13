import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from fastapi import APIRouter, HTTPException
from typing import List

from api.schemas import (
    RequirementInput,
    RequirementOutput,
    BatchProcessRequest,
    BatchProcessResponse,
    ProcessResult
)

router = APIRouter()

_pipeline_instance = None


def _get_pipeline():
    global _pipeline_instance
    if _pipeline_instance is None:
        from src.pipeline import DataProcessingPipeline
        from src.llm_client import llm_client
        
        spec_json_path = os.path.join(PROJECT_ROOT, "data", "config", "芯片需求结构化定义规范V4.1.json")
        if not os.path.exists(spec_json_path):
            spec_json_path = os.path.join(PROJECT_ROOT, "data", "config", "芯片需求结构化定义规范V4.0.json")
        
        _pipeline_instance = DataProcessingPipeline(
            category_db_path=os.path.join(PROJECT_ROOT, "data", "config", "categories.dbV4.1.json"),
            templates_path=os.path.join(PROJECT_ROOT, "data", "config", "Master_Requirement_Templates.json"),
            llm_client=llm_client,
            audit_records_dir="Audit_Records",
            output_dir="output",
            template_library_dir="output/library",
            spec_json_path=spec_json_path if os.path.exists(spec_json_path) else None,
            use_spec_provider=os.path.exists(spec_json_path)
        )
    return _pipeline_instance


def _instance_to_output(instance) -> RequirementOutput:
    from src.data_models import RequirementInstance
    
    category_name = None
    if hasattr(_pipeline_instance, 'category_db') and _pipeline_instance.category_db:
        cat = _pipeline_instance.category_db.categories.get(instance.category_uid)
        if cat:
            category_name = cat.get('name')
    
    return RequirementOutput(
        requirement_instance_id=instance.requirement_instance_id,
        requirement_text=instance.requirement_text,
        requirement_type=instance.requirement_type,
        category_uid=instance.category_uid,
        category_name=category_name,
        confidence=getattr(instance, 'confidence', 0.0),
        matched_template_id=getattr(instance, 'matched_template_id', None),
        extracted_variables=getattr(instance, 'extracted_variables', None),
        product_line=getattr(instance, 'product_line', None),
        chip_info=getattr(instance, 'chip_info', None),
        generation_type=getattr(instance, 'generation_type', None),
        review_status=getattr(instance, 'review_status', None)
    )


@router.post("/process", response_model=RequirementOutput, summary="处理单条需求")
async def process_requirement(req: RequirementInput):
    """
    处理单条需求：进行智能分类、模板匹配
    
    - **requirement_text**: 需求文本内容
    - **requirement_id**: 需求ID（可选，自动生成）
    - **product_line**: 产品线（默认MCU）
    - **chip_info**: 芯片信息（可选）
    """
    try:
        pipeline = _get_pipeline()
        
        req_id = req.requirement_id or f"REQ_{hash(req.requirement_text) % 10000:04d}"
        
        instance = pipeline.process_single_requirement(
            requirement_text=req.requirement_text,
            requirement_id=req_id,
            product_line=req.product_line,
            chip_info=req.chip_info
        )
        
        return _instance_to_output(instance)
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理需求失败: {str(e)}")


@router.post("/batch", response_model=BatchProcessResponse, summary="批量处理需求")
async def batch_process_requirements(req: BatchProcessRequest):
    """
    批量处理多条需求
    
    - **requirements**: 需求列表
    - **product_line**: 产品线
    - **chip_info**: 芯片信息
    - **run_template_matching**: 是否运行模板匹配
    """
    try:
        pipeline = _get_pipeline()
        
        requirements_data = [
            {"id": r.requirement_id or f"REQ_{i:04d}", "text": r.requirement_text}
            for i, r in enumerate(req.requirements)
        ]
        
        instances = pipeline.process_batch(
            requirements=requirements_data,
            product_line=req.product_line,
            chip_info=req.chip_info,
            run_template_matching=req.run_template_matching
        )
        
        results = [_instance_to_output(inst) for inst in instances]
        
        return BatchProcessResponse(
            total_count=len(req.requirements),
            success_count=len(results),
            failed_count=len(req.requirements) - len(results),
            results=results
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"批量处理失败: {str(e)}")


@router.get("/trace-chain/{req_id}", response_model=ProcessResult, summary="获取需求追溯链")
async def get_trace_chain(req_id: str):
    """
    获取指定需求的追溯链信息
    
    - **req_id**: 需求实例ID
    """
    try:
        pipeline = _get_pipeline()
        
        cache_dir = os.path.join(pipeline.output_dir, 'classify')
        cache_file = os.path.join(cache_dir, 'classification_cache.json')
        
        if os.path.exists(cache_file):
            import json
            with open(cache_file, 'r', encoding='utf-8') as f:
                cache = json.load(f)
            
            if req_id in cache:
                return ProcessResult(
                    success=True,
                    message="查询成功",
                    data=cache[req_id]
                )
        
        return ProcessResult(
            success=False,
            message=f"未找到需求ID: {req_id}"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"查询追溯链失败: {str(e)}")
