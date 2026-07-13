import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from fastapi import APIRouter, HTTPException
from typing import Dict, Any

router = APIRouter()


@router.get("/", summary="获取系统配置")
async def get_config():
    """
    获取系统当前配置信息
    """
    try:
        config = {
            "project_root": PROJECT_ROOT,
            "data_dir": os.path.join(PROJECT_ROOT, "data"),
            "raw_data_dir": os.path.join(PROJECT_ROOT, "raw_data"),
            "raw_out_dir": os.path.join(PROJECT_ROOT, "raw_out"),
            "output_dir": os.path.join(PROJECT_ROOT, "output"),
            "audit_dir": os.path.join(PROJECT_ROOT, "Audit_Records"),
            "upload_dir": os.path.join(PROJECT_ROOT, "api", "uploads"),
            "api_output_dir": os.path.join(PROJECT_ROOT, "api", "output"),
            "config_dir": os.path.join(PROJECT_ROOT, "data", "config"),
        }
        
        return config
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取配置失败: {str(e)}")


@router.get("/spec", summary="获取规范文件信息")
async def get_spec_info():
    """
    获取规范文件信息
    """
    try:
        spec_path_v41 = os.path.join(PROJECT_ROOT, "data", "config", "芯片需求结构化定义规范V4.1.json")
        spec_path_v40 = os.path.join(PROJECT_ROOT, "data", "config", "芯片需求结构化定义规范V4.0.json")
        
        spec_path = spec_path_v41 if os.path.exists(spec_path_v41) else spec_path_v40
        
        if not os.path.exists(spec_path):
            return {"exists": False, "message": "规范文件不存在"}
        
        import json
        with open(spec_path, 'r', encoding='utf-8') as f:
            spec_data = json.load(f)
        
        return {
            "exists": True,
            "version": spec_data.get("version", "unknown"),
            "path": spec_path,
            "size": os.path.getsize(spec_path)
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取规范信息失败: {str(e)}")


@router.post("/sync", summary="同步配置")
async def sync_config():
    """
    同步规范配置文件
    """
    try:
        sys.path.insert(0, os.path.join(PROJECT_ROOT, 'script'))
        from script.sync_config import main
        
        result = main()
        
        return {
            "success": True,
            "message": result if result else "同步完成"
        }
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"同步配置失败: {str(e)}")


@router.get("/llm", summary="获取LLM配置")
async def get_llm_config():
    """
    获取LLM客户端配置信息
    """
    try:
        from src.llm_client import llm_client
        
        config = {
            "model_name": llm_client.model_name,
            "api_base": llm_client.api_base,
            "is_demo": llm_client.is_demo
        }
        
        return config
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取LLM配置失败: {str(e)}")


@router.get("/health", summary="健康检查")
async def health_check():
    """
    系统健康检查
    """
    try:
        checks = []
        
        data_dir = os.path.join(PROJECT_ROOT, "data")
        checks.append({"name": "data_dir", "status": "ok" if os.path.exists(data_dir) else "error"})
        
        config_dir = os.path.join(PROJECT_ROOT, "data", "config")
        checks.append({"name": "config_dir", "status": "ok" if os.path.exists(config_dir) else "error"})
        
        category_file = os.path.join(config_dir, "categories.dbV4.1.json")
        checks.append({"name": "category_file", "status": "ok" if os.path.exists(category_file) else "error"})
        
        template_file = os.path.join(config_dir, "Master_Requirement_Templates.json")
        checks.append({"name": "template_file", "status": "ok" if os.path.exists(template_file) else "error"})
        
        spec_file = os.path.join(config_dir, "芯片需求结构化定义规范V4.1.json")
        checks.append({"name": "spec_file", "status": "ok" if os.path.exists(spec_file) else "error"})
        
        raw_data_dir = os.path.join(PROJECT_ROOT, "raw_data")
        checks.append({"name": "raw_data_dir", "status": "ok" if os.path.exists(raw_data_dir) else "error"})
        
        all_ok = all(c['status'] == 'ok' for c in checks)
        
        return {
            "status": "healthy" if all_ok else "degraded",
            "checks": checks
        }
    
    except Exception as e:
        return {
            "status": "error",
            "error": str(e)
        }
