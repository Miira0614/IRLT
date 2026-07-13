FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt -i https://mirrors.aliyun.com/pypi/simple/

COPY . .

RUN mkdir -p /app/Audit_Records \
    && mkdir -p /app/api/uploads \
    && mkdir -p /app/api/output \
    && mkdir -p /app/data/config \
    && mkdir -p /app/raw_data \
    && mkdir -p /app/raw_out \
    && mkdir -p /app/output/classify \
    && mkdir -p /app/output/library \
    && mkdir -p /app/output/历史文件 \
    && mkdir -p /app/complete_data \
    && mkdir -p /app/conplete_out \
    && mkdir -p /app/data/已处理数据集

ENV MODEL_CHOICE=siliconflow
ENV PYTHONPATH=/app:/app/src

EXPOSE 8000
EXPOSE 8501

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]
