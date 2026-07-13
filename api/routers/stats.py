import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from fastapi import APIRouter, HTTPException
from typing import List

from api.schemas import StatsResponse, CategoryInfo, TemplateInfo

router = APIRouter()


@router.get("/", response_model=StatsResponse, summary="获取系统统计信息")
async def get_stats():
    """
    获取系统统计信息：分类数、模板数等
    """
    try:
        from src.spec_data_provider import SpecDataProvider
        
        spec_json_path = os.path.join(PROJECT_ROOT, "data", "config", "芯片需求结构化定义规范V4.1.json")
        if not os.path.exists(spec_json_path):
            spec_json_path = os.path.join(PROJECT_ROOT, "data", "config", "芯片需求结构化定义规范V4.0.json")
        
        if not os.path.exists(spec_json_path):
            raise HTTPException(status_code=404, detail="规范文件不存在")
        
        provider = SpecDataProvider(
            spec_json_path=spec_json_path,
            templates_json_path=os.path.join(PROJECT_ROOT, "data", "config", "Master_Requirement_Templates.json"),
            existing_category_db_path=os.path.join(PROJECT_ROOT, "data", "config", "categories.dbV4.1.json")
        )
        
        stats = provider.get_stats()
        
        return StatsResponse(
            category_count=stats.get('category_count', 0),
            categories_l1=stats.get('categories_l1', 0),
            categories_l2=stats.get('categories_l2', 0),
            categories_l3=stats.get('categories_l3', 0),
            total_templates=stats.get('total_templates', 0),
            existing_templates=stats.get('existing_templates', 0),
            auto_generated_templates=stats.get('auto_generated_templates', 0),
            categories_with_templates=stats.get('categories_with_templates', 0),
            missing_template_categories=stats.get('missing_template_categories', 0)
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取统计信息失败: {str(e)}")


@router.get("/categories", response_model=List[CategoryInfo], summary="获取所有分类信息")
async def get_categories(level: int = None):
    """
    获取所有分类信息
    
    - **level**: 可选，筛选指定层级的分类（1/2/3）
    """
    try:
        import json
        
        category_path = os.path.join(PROJECT_ROOT, "data", "config", "categories.dbV4.1.json")
        if not os.path.exists(category_path):
            category_path = os.path.join(PROJECT_ROOT, "data", "config", "categories.dbV4.0.json")
        
        if not os.path.exists(category_path):
            raise HTTPException(status_code=404, detail="分类数据库文件不存在")
        
        with open(category_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        categories = data.get('categories', {})
        results = []
        
        for uid, cat in categories.items():
            if level is not None and cat.get('level') != level:
                continue
            
            results.append(CategoryInfo(
                uid=cat.get('uid', ''),
                id=cat.get('id', ''),
                name=cat.get('name', ''),
                level=cat.get('level', 0),
                parent_uid=cat.get('parent_uid', ''),
                children=cat.get('children', []),
                description=cat.get('description'),
                applicable_lines=cat.get('applicable_lines')
            ))
        
        return results
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取分类信息失败: {str(e)}")


@router.get("/categories/{uid}", response_model=CategoryInfo, summary="获取指定分类详情")
async def get_category(uid: str):
    """
    获取指定分类的详细信息
    
    - **uid**: 分类UID
    """
    try:
        import json
        
        category_path = os.path.join(PROJECT_ROOT, "data", "config", "categories.dbV4.1.json")
        if not os.path.exists(category_path):
            category_path = os.path.join(PROJECT_ROOT, "data", "config", "categories.dbV4.0.json")
        
        if not os.path.exists(category_path):
            raise HTTPException(status_code=404, detail="分类数据库文件不存在")
        
        with open(category_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        categories = data.get('categories', {})
        
        if uid not in categories:
            raise HTTPException(status_code=404, detail=f"分类UID不存在: {uid}")
        
        cat = categories[uid]
        
        return CategoryInfo(
            uid=cat.get('uid', ''),
            id=cat.get('id', ''),
            name=cat.get('name', ''),
            level=cat.get('level', 0),
            parent_uid=cat.get('parent_uid', ''),
            children=cat.get('children', []),
            description=cat.get('description'),
            applicable_lines=cat.get('applicable_lines')
        )
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取分类详情失败: {str(e)}")


@router.get("/templates", response_model=List[TemplateInfo], summary="获取所有模板信息")
async def get_templates(level: str = None, category_uid: str = None):
    """
    获取所有模板信息
    
    - **level**: 可选，筛选指定层级的模板（L1/L2/L3）
    - **category_uid**: 可选，筛选指定分类的模板
    """
    try:
        import json
        
        template_path = os.path.join(PROJECT_ROOT, "data", "config", "Master_Requirement_Templates.json")
        
        if not os.path.exists(template_path):
            raise HTTPException(status_code=404, detail="模板文件不存在")
        
        with open(template_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        
        templates = data.get('templates', {})
        results = []
        
        for tid, tpl in templates.items():
            if level is not None and tpl.get('level') != level:
                continue
            
            if category_uid is not None and tpl.get('category_uid') != category_uid:
                continue
            
            results.append(TemplateInfo(
                template_id=tpl.get('template_id', ''),
                level=tpl.get('level', ''),
                category_uid=tpl.get('category_uid', ''),
                templates_text=tpl.get('templates_text', ''),
                product_lines=tpl.get('product_lines', []),
                variables=tpl.get('variables', []),
                parent_template_id=tpl.get('parent_template_id')
            ))
        
        return results
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取模板信息失败: {str(e)}")


@router.get("/audit-records", summary="获取审计记录")
async def get_audit_records():
    """
    获取最近的审计记录列表
    """
    try:
        audit_dir = os.path.join(PROJECT_ROOT, "Audit_Records")
        
        if not os.path.exists(audit_dir):
            return {"records": []}
        
        records = []
        for filename in os.listdir(audit_dir):
            if filename.endswith('.log'):
                file_path = os.path.join(audit_dir, filename)
                records.append({
                    "filename": filename,
                    "path": file_path,
                    "size": os.path.getsize(file_path),
                    "modified": os.path.getmtime(file_path)
                })
        
        records.sort(key=lambda x: x['modified'], reverse=True)
        
        return {"records": records[:20]}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取审计记录失败: {str(e)}")
