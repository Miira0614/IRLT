import sys
import os

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, PROJECT_ROOT)
sys.path.insert(0, os.path.join(PROJECT_ROOT, 'src'))

from fastapi import APIRouter, HTTPException, UploadFile, File
from fastapi.responses import FileResponse
from typing import List
import shutil

from api.schemas import FileUploadResponse, TraceMatrixResponse

router = APIRouter()

UPLOAD_DIR = os.path.join(PROJECT_ROOT, "api", "uploads")
OUTPUT_DIR = os.path.join(PROJECT_ROOT, "api", "output")

os.makedirs(UPLOAD_DIR, exist_ok=True)
os.makedirs(OUTPUT_DIR, exist_ok=True)


@router.post("/upload", response_model=FileUploadResponse, summary="上传Excel文件")
async def upload_file(file: UploadFile = File(...)):
    """
    上传Excel文件
    
    - **file**: Excel文件(.xlsx)
    """
    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="仅支持.xlsx格式的Excel文件")
    
    try:
        file_path = os.path.join(UPLOAD_DIR, file.filename)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        file_size = os.path.getsize(file_path)
        
        return FileUploadResponse(
            filename=file.filename,
            file_path=f"/uploads/{file.filename}",
            file_size=file_size,
            message="文件上传成功"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"文件上传失败: {str(e)}")


@router.post("/upload/batch", response_model=List[FileUploadResponse], summary="批量上传Excel文件")
async def upload_files(files: List[UploadFile] = File(...)):
    """
    批量上传Excel文件
    
    - **files**: Excel文件列表
    """
    results = []
    
    for file in files:
        if not file.filename.endswith('.xlsx'):
            continue
        
        try:
            file_path = os.path.join(UPLOAD_DIR, file.filename)
            
            with open(file_path, "wb") as buffer:
                shutil.copyfileobj(file.file, buffer)
            
            file_size = os.path.getsize(file_path)
            
            results.append(FileUploadResponse(
                filename=file.filename,
                file_path=f"/uploads/{file.filename}",
                file_size=file_size,
                message="文件上传成功"
            ))
        
        except Exception as e:
            results.append(FileUploadResponse(
                filename=file.filename,
                file_path="",
                file_size=0,
                message=f"上传失败: {str(e)}"
            ))
    
    return results


@router.get("/list", summary="列出上传的文件")
async def list_files():
    """
    列出已上传的文件列表
    """
    try:
        files = []
        for filename in os.listdir(UPLOAD_DIR):
            if filename.endswith('.xlsx'):
                file_path = os.path.join(UPLOAD_DIR, filename)
                files.append({
                    "filename": filename,
                    "path": f"/uploads/{filename}",
                    "size": os.path.getsize(file_path),
                    "modified": os.path.getmtime(file_path)
                })
        
        return {"files": files}
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"获取文件列表失败: {str(e)}")


@router.delete("/delete/{filename}", summary="删除上传的文件")
async def delete_file(filename: str):
    """
    删除指定的上传文件
    
    - **filename**: 文件名
    """
    try:
        file_path = os.path.join(UPLOAD_DIR, filename)
        
        if os.path.exists(file_path):
            os.remove(file_path)
            return {"success": True, "message": f"文件 {filename} 已删除"}
        else:
            raise HTTPException(status_code=404, detail=f"文件 {filename} 不存在")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"删除文件失败: {str(e)}")


@router.post("/process-excel", response_model=TraceMatrixResponse, summary="处理Excel文件生成追溯链矩阵")
async def process_excel(file: UploadFile = File(...)):
    """
    处理上传的Excel文件，生成追溯链矩阵
    
    - **file**: Excel文件(.xlsx)
    """
    if not file.filename.endswith('.xlsx'):
        raise HTTPException(status_code=400, detail="仅支持.xlsx格式的Excel文件")
    
    try:
        temp_path = os.path.join(UPLOAD_DIR, file.filename)
        
        with open(temp_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
        
        sys.path.insert(0, os.path.join(PROJECT_ROOT, 'script'))
        from script.需求表格预处理 import process_single_file_standard
        
        result = process_single_file_standard(temp_path, OUTPUT_DIR)
        
        if result and "成功" in result:
            output_files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.xlsx')]
            if output_files:
                latest_file = max(output_files, key=lambda x: os.path.getmtime(os.path.join(OUTPUT_DIR, x)))
                return TraceMatrixResponse(
                    success=True,
                    message="处理成功",
                    output_file=f"/output/{latest_file}"
                )
        
        return TraceMatrixResponse(
            success=False,
            message=result if result else "处理失败"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"处理Excel文件失败: {str(e)}")


@router.get("/download/{filename}", summary="下载处理结果文件")
async def download_file(filename: str):
    """
    下载处理结果文件
    
    - **filename**: 文件名
    """
    try:
        file_path = os.path.join(OUTPUT_DIR, filename)
        
        if os.path.exists(file_path):
            return FileResponse(file_path, filename=filename)
        else:
            raise HTTPException(status_code=404, detail=f"文件 {filename} 不存在")
    
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"下载文件失败: {str(e)}")


@router.post("/generate-trace-matrix", response_model=TraceMatrixResponse, summary="生成追溯链矩阵")
async def generate_trace_matrix():
    """
    从 raw_data 目录读取文件并生成追溯链矩阵
    """
    try:
        sys.path.insert(0, os.path.join(PROJECT_ROOT, 'script'))
        from script.需求表格预处理 import main_orchestrator
        
        import script.需求表格预处理 as preprocessor
        original_input = preprocessor.INPUT_FOLDER
        original_output = preprocessor.OUTPUT_FOLDER
        
        preprocessor.INPUT_FOLDER = os.path.join(PROJECT_ROOT, 'raw_data')
        preprocessor.OUTPUT_FOLDER = OUTPUT_DIR
        
        main_orchestrator()
        
        preprocessor.INPUT_FOLDER = original_input
        preprocessor.OUTPUT_FOLDER = original_output
        
        output_files = [f for f in os.listdir(OUTPUT_DIR) if f.endswith('.xlsx')]
        if output_files:
            latest_file = max(output_files, key=lambda x: os.path.getmtime(os.path.join(OUTPUT_DIR, x)))
            return TraceMatrixResponse(
                success=True,
                message="追溯链矩阵生成成功",
                output_file=f"/output/{latest_file}"
            )
        
        return TraceMatrixResponse(
            success=False,
            message="未生成输出文件"
        )
    
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成追溯链矩阵失败: {str(e)}")
