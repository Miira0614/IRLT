import os
import json
import time
import random
import logging
from typing import Dict, Any
from openai import OpenAI

logger = logging.getLogger(__name__)

# ==========================================
# 模型选择开关 - 可以在这里手动切换使用哪个模型
# ==========================================
# MODEL_CHOICE 可选值:
#   "local"    - 优先使用本地模型
#   "siliconflow" - 优先使用 SiliconFlow
#   "auto"     - 自动选择（优先本地，失败回退到 SiliconFlow）
MODEL_CHOICE = os.getenv("MODEL_CHOICE", "local")


class SemiReqLLMClient:
    def __init__(self):
        self.siliconflow_api_key = os.getenv(
            "SILICONFLOW_API_KEY",
            ""  # ⚠️ 请设置环境变量 SILICONFLOW_API_KEY
        )
        self.siliconflow_base_url = os.getenv(
            "SILICONFLOW_BASE_URL",
            "https://api.siliconflow.cn/v1"
        )
        self.siliconflow_model_id = os.getenv(
            "SILICONFLOW_MODEL_ID",
            "deepseek-ai/DeepSeek-R1-0528-Qwen3-8B"
        )

        self.local_api_key = os.getenv(
            "SEMIREQ_LLM_KEY",
            ""  # ⚠️ 请设置环境变量 SEMIREQ_LLM_KEY
        )
        self.local_base_url = os.getenv(
            "SEMIREQ_LLM_URL",
            "http://localhost:3000/v1"
        )
        self.local_model_name = os.getenv(
            "SEMIREQ_LLM_MODEL",
            "qwen3.6-flash"
        )
        
        self._initialize_model()
    
    def _initialize_model(self):
        if MODEL_CHOICE == "siliconflow":
            self._use_siliconflow()
        else:
            self._use_local()

        # 验证 API Key 是否已配置
        if not self.api_key:
            logger.warning(
                f"⚠️ API Key 未设置！请在环境变量中配置：\n"
                f"  - SiliconFlow: export SILICONFLOW_API_KEY=your_key\n"
                f"  - 本地模型:   export SEMIREQ_LLM_KEY=your_key"
            )

        self.can_fallback = MODEL_CHOICE == "auto"
        self.has_fallen_back = False
    
    def _use_siliconflow(self):
        self.api_key = self.siliconflow_api_key
        self.base_url = self.siliconflow_base_url
        self.model_name = self.siliconflow_model_id
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        self.use_siliconflow = True
        logger.info(f"Using SiliconFlow: {self.model_name}")
    
    def _use_local(self):
        self.api_key = self.local_api_key
        self.base_url = self.local_base_url
        self.model_name = self.local_model_name
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        self.use_siliconflow = False
        logger.info(f"Using Local Model: {self.model_name}")
    
    def _fallback_to_siliconflow(self):
        if not self.has_fallen_back and self.can_fallback:
            logger.warning("Local model failed, switching to SiliconFlow...")
            self._use_siliconflow()
            self.has_fallen_back = True
            return True
        return False
    
    def _handle_rate_limit(self, error_msg: str, max_retries: int = 5) -> bool:
        if "429" in error_msg or "rate limiting" in error_msg.lower() or "TPM limit" in error_msg:
            for attempt in range(max_retries):
                wait_time = 2 ** attempt + random.uniform(0, 1)
                logger.warning(f"Hit rate limit, waiting {wait_time:.2f} seconds (attempt {attempt+1}/{max_retries})")
                time.sleep(wait_time)
                return True
            logger.error(f"Exhausted all {max_retries} retry attempts")
        return False
    
    def request_json_output(self, prompt: str, system_instruction: str = "你是一个半导体芯片需求工程专家。") -> Dict[str, Any]:
        raw_content = ""
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                response_format={"type": "json_object"},
                temperature=0.1
            )
            
            raw_content = response.choices[0].message.content
            json_str = raw_content
            
            if "```json" in raw_content:
                start = raw_content.find("```json") + 7
                end = raw_content.find("```", start)
                if end > start:
                    json_str = raw_content[start:end].strip()
            elif "```" in raw_content:
                start = raw_content.find("```") + 3
                end = raw_content.find("```", start)
                if end > start:
                    json_str = raw_content[start:end].strip()
            
            if "{" in json_str and "}" in json_str:
                start = json_str.find("{")
                end = json_str.rfind("}") + 1
                json_str = json_str[start:end]
            
                json_str = json_str.replace('\u201C', '"').replace('\u201D', '"')
            
                result = json.loads(json_str)
                if self.use_siliconflow:
                    time.sleep(0.5)
                return result
        except json.JSONDecodeError as e:
            logger.error(f"JSON parse failed: {str(e)}")
            logger.debug(f"Raw content: {raw_content[:500]}...")
            
            if self._fallback_to_siliconflow():
                return self.request_json_output(prompt, system_instruction)
            
            logger.error("Cannot complete LLM call, returning empty result")
            return {}
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Current model call failed: {error_msg}")
            
            if self._handle_rate_limit(error_msg):
                return self.request_json_output(prompt, system_instruction)
            
            if self._fallback_to_siliconflow():
                return self.request_json_output(prompt, system_instruction)
            
            logger.error("Cannot complete LLM call, returning empty result")
            return {}
    
    def generate(self, prompt: str, system_instruction: str = "你是一个半导体芯片需求工程专家。") -> str:
        try:
            response = self.client.chat.completions.create(
                model=self.model_name,
                messages=[
                    {"role": "system", "content": system_instruction},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.1
            )
            
            result = response.choices[0].message.content.strip()
            if self.use_siliconflow:
                time.sleep(0.5)
            return result
        except Exception as e:
            error_msg = str(e)
            logger.error(f"Current model call failed: {error_msg}")
            
            if self._handle_rate_limit(error_msg):
                return self.generate(prompt, system_instruction)
            
            if self._fallback_to_siliconflow():
                return self.generate(prompt, system_instruction)
            
            logger.error("Cannot complete LLM call, returning empty result")
            return ""


llm_client = SemiReqLLMClient()

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
    
    print("[TEST] Starting LLM API connectivity test...")
    print(f"[TEST] Model choice: {MODEL_CHOICE}")
    print(f"[TEST] Current service address: {llm_client.base_url}")
    print(f"[TEST] Current model: {llm_client.model_name}")
    print("-" * 50)
    
    test_instruction = (
        'You are a semiconductor assistant. Please return a standard '
        'JSON object with format: {"status": "ok", "chip_type": "chip type mentioned by user"}'
    )
    test_prompt = "Test API connectivity. I am developing a low-power EC chip."
    
    result = llm_client.request_json_output(prompt=test_prompt, system_instruction=test_instruction)
    
    if result and result.get("status") == "ok":
        print("[SUCCESS] API connectivity test passed!")
        print(f"[INFO] Model used: {llm_client.model_name}")
        print(f"[INFO] Returned data: {json.dumps(result, ensure_ascii=False, indent=2)}")
    else:
        print("[FAILED] Did not receive expected JSON response")