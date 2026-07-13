from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any


class RequirementInput(BaseModel):
    requirement_text: str = Field(..., description="需求文本")
    requirement_id: Optional[str] = Field(None, description="需求ID")
    product_line: Optional[str] = Field("MCU", description="产品线")
    chip_info: Optional[str] = Field("", description="芯片信息")


class RequirementOutput(BaseModel):
    requirement_instance_id: str
    requirement_text: str
    requirement_type: str
    category_uid: str
    category_name: Optional[str] = None
    confidence: float = 0.0
    matched_template_id: Optional[str] = None
    extracted_variables: Optional[Dict[str, Any]] = None
    product_line: Optional[str] = None
    chip_info: Optional[str] = None
    generation_type: Optional[str] = None
    review_status: Optional[str] = None


class BatchProcessRequest(BaseModel):
    requirements: List[RequirementInput] = Field(..., description="需求列表")
    product_line: Optional[str] = Field("MCU", description="产品线")
    chip_info: Optional[str] = Field("", description="芯片信息")
    run_template_matching: Optional[bool] = Field(True, description="是否运行模板匹配")


class BatchProcessResponse(BaseModel):
    total_count: int
    success_count: int
    failed_count: int
    results: List[RequirementOutput]


class StatsResponse(BaseModel):
    category_count: int
    categories_l1: int
    categories_l2: int
    categories_l3: int
    total_templates: int
    existing_templates: int
    auto_generated_templates: int
    categories_with_templates: int
    missing_template_categories: int


class CategoryInfo(BaseModel):
    uid: str
    id: str
    name: str
    level: int
    parent_uid: str
    children: List[str]
    description: Optional[str] = None
    applicable_lines: Optional[List[str]] = None


class TemplateInfo(BaseModel):
    template_id: str
    level: str
    category_uid: str
    templates_text: str
    product_lines: List[str]
    variables: List[Dict[str, Any]]
    parent_template_id: Optional[str] = None


class FileUploadResponse(BaseModel):
    filename: str
    file_path: str
    file_size: int
    message: str


class TraceMatrixResponse(BaseModel):
    success: bool
    message: str
    output_file: Optional[str] = None
    record_count: Optional[int] = None


class ProcessResult(BaseModel):
    success: bool
    message: str
    data: Optional[Dict[str, Any]] = None
