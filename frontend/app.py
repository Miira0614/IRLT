import streamlit as st
import requests
import json
import os

API_BASE_URL = "http://localhost:8000"

st.set_page_config(
    page_title="需求追溯链系统",
    page_icon="📋",
    layout="wide",
    initial_sidebar_state="expanded"
)

PAGES = {
    "首页": "home",
    "需求处理": "requirements",
    "文件管理": "files",
    "统计信息": "stats"
}


def api_get(endpoint, params=None):
    try:
        response = requests.get(f"{API_BASE_URL}{endpoint}", params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        st.error(f"API请求失败: {e}")
        return None


def api_post(endpoint, data=None, files=None):
    try:
        if files:
            response = requests.post(f"{API_BASE_URL}{endpoint}", files=files)
        else:
            response = requests.post(f"{API_BASE_URL}{endpoint}", json=data)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        try:
            error_detail = response.json()
            st.error(f"API请求失败: {error_detail.get('detail', str(e))}")
        except:
            st.error(f"API请求失败: {e}")
        return None


def page_home():
    st.title("📋 需求追溯链管理系统")
    st.markdown("---")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.info("**需求处理**")
        st.write("智能分类、模板匹配、拓扑补全")
        if st.button("开始处理需求", key="req_btn"):
            st.session_state["page"] = "requirements"
            st.rerun()
    
    with col2:
        st.info("**文件管理**")
        st.write("上传Excel、生成追溯链矩阵")
        if st.button("管理文件", key="file_btn"):
            st.session_state["page"] = "files"
            st.rerun()
    
    with col3:
        st.info("**统计信息**")
        st.write("查看分类、模板、审计记录")
        if st.button("查看统计", key="stats_btn"):
            st.session_state["page"] = "stats"
            st.rerun()
    
    st.markdown("---")
    
    st.subheader("📊 系统概览")
    stats_data = api_get("/api/stats/")
    if stats_data:
        col1, col2, col3, col4 = st.columns(4)
        col1.metric("分类总数", stats_data.get("category_count", 0))
        col2.metric("模板总数", stats_data.get("total_templates", 0))
        col3.metric("L1分类", stats_data.get("categories_l1", 0))
        col4.metric("L3分类", stats_data.get("categories_l3", 0))
    
    st.subheader("🔧 系统状态")
    health_data = api_get("/api/config/health")
    if health_data:
        status = health_data.get("status", "unknown")
        if status == "healthy":
            st.success("✅ 系统运行正常")
        elif status == "degraded":
            st.warning("⚠️ 系统部分组件异常")
        else:
            st.error("❌ 系统异常")
        
        checks = health_data.get("checks", [])
        for check in checks:
            if check["status"] == "ok":
                st.write(f"✅ {check['name']}")
            else:
                st.write(f"❌ {check['name']}")


def page_requirements():
    st.title("🔍 需求处理")
    st.markdown("---")
    
    st.subheader("处理单条需求")
    with st.form("process_form"):
        req_text = st.text_area("需求文本", height=100)
        req_id = st.text_input("需求ID（可选）")
        product_line = st.selectbox("产品线", ["MCU", "EC", "BMS", "Motor", "PD", "信号链"])
        chip_info = st.text_input("芯片信息（可选）")
        submit = st.form_submit_button("处理需求")
        
        if submit and req_text:
            with st.spinner("正在处理..."):
                data = {
                    "requirement_text": req_text,
                    "requirement_id": req_id or None,
                    "product_line": product_line,
                    "chip_info": chip_info
                }
                result = api_post("/api/requirements/process", data=data)
                
                if result:
                    st.success("处理成功！")
                    col1, col2 = st.columns(2)
                    with col1:
                        st.write(f"**需求ID**: {result.get('requirement_instance_id')}")
                        st.write(f"**需求层级**: {result.get('requirement_type')}")
                        st.write(f"**分类UID**: {result.get('category_uid')}")
                        st.write(f"**分类名称**: {result.get('category_name', '-')}")
                    with col2:
                        st.write(f"**置信度**: {result.get('confidence', 0):.2f}")
                        st.write(f"**匹配模板**: {result.get('matched_template_id', '-')}")
                        vars = result.get('extracted_variables', {})
                        if vars:
                            st.write("**提取变量**:")
                            for k, v in vars.items():
                                st.write(f"  - {k}: {v}")
    
    st.markdown("---")
    
    st.subheader("批量处理需求")
    st.write("请在下方输入多条需求，每条一行")
    batch_text = st.text_area("批量需求（每行一条）", height=150)
    
    if st.button("批量处理"):
        if batch_text.strip():
            requirements = []
            for i, line in enumerate(batch_text.strip().split('\n')):
                if line.strip():
                    requirements.append({
                        "requirement_text": line.strip(),
                        "requirement_id": f"REQ_{i+1:04d}"
                    })
            
            with st.spinner("正在批量处理..."):
                data = {
                    "requirements": requirements,
                    "product_line": product_line,
                    "run_template_matching": True
                }
                result = api_post("/api/requirements/batch", data=data)
                
                if result:
                    st.success(f"处理完成！成功: {result['success_count']} / 总数: {result['total_count']}")
                    
                    if result['results']:
                        st.write("处理结果：")
                        for res in result['results'][:5]:
                            st.write(f"• **{res['requirement_instance_id']}** - {res['category_name']} ({res['requirement_type']})")
                        if len(result['results']) > 5:
                            st.write(f"... 还有 {len(result['results']) - 5} 条结果")


def page_files():
    st.title("📁 文件管理")
    st.markdown("---")
    
    st.subheader("上传Excel文件")
    uploaded_files = st.file_uploader("选择Excel文件", type="xlsx", accept_multiple_files=True)
    
    if uploaded_files:
        if st.button("上传文件"):
            for file in uploaded_files:
                with st.spinner(f"上传 {file.name}..."):
                    files = {"file": (file.name, file, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
                    result = api_post("/api/files/upload", files=files)
                    if result:
                        st.success(f"✅ {result['filename']} 上传成功")
    
    st.markdown("---")
    
    st.subheader("已上传文件")
    files_data = api_get("/api/files/list")
    if files_data:
        files = files_data.get("files", [])
        if files:
            for file in files:
                col1, col2, col3 = st.columns([3, 2, 1])
                col1.write(file["filename"])
                col2.write(f"{file['size']} bytes")
                if col3.button("删除", key=f"del_{file['filename']}"):
                    result = api_post(f"/api/files/delete/{file['filename']}")
                    if result and result.get("success"):
                        st.success(f"删除成功")
                        st.rerun()
        else:
            st.info("暂无上传文件")
    
    st.markdown("---")
    
    st.subheader("生成追溯链矩阵")
    st.write("从 raw_data 目录读取需求文件并生成聚合链矩阵")
    
    if st.button("生成追溯链矩阵"):
        with st.spinner("正在生成..."):
            result = api_post("/api/files/generate-trace-matrix")
            if result and result.get("success"):
                st.success(f"✅ 生成成功！")
                if result.get("output_file"):
                    st.write(f"输出文件: {result['output_file']}")
                    st.markdown(f"[下载文件](http://localhost:8000{result['output_file']})")


def page_stats():
    st.title("📊 统计信息")
    st.markdown("---")
    
    st.subheader("系统统计")
    stats_data = api_get("/api/stats/")
    if stats_data:
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("分类总数", stats_data.get("category_count", 0))
        col2.metric("L1分类", stats_data.get("categories_l1", 0))
        col3.metric("L2分类", stats_data.get("categories_l2", 0))
        col4.metric("L3分类", stats_data.get("categories_l3", 0))
        col5.metric("模板总数", stats_data.get("total_templates", 0))
        
        col1, col2 = st.columns(2)
        col1.metric("现有模板", stats_data.get("existing_templates", 0))
        col2.metric("自动生成模板", stats_data.get("auto_generated_templates", 0))
    
    st.markdown("---")
    
    st.subheader("分类列表")
    level_filter = st.selectbox("筛选层级", [None, 1, 2, 3])
    categories = api_get("/api/stats/categories", params={"level": level_filter} if level_filter else None)
    
    if categories:
        st.write(f"共 {len(categories)} 个分类")
        for cat in categories[:20]:
            st.write(f"**{cat['id']}** - {cat['name']} (层级: {cat['level']})")
        if len(categories) > 20:
            st.write(f"... 还有 {len(categories) - 20} 个分类")
    
    st.markdown("---")
    
    st.subheader("审计记录")
    records = api_get("/api/stats/audit-records")
    if records:
        for record in records.get("records", [])[:10]:
            st.write(f"• {record['filename']}")


def main():
    if "page" not in st.session_state:
        st.session_state["page"] = "home"
    
    with st.sidebar:
        st.title("📋 需求追溯链")
        st.markdown("---")
        for page_name, page_key in PAGES.items():
            if st.button(page_name, key=f"nav_{page_key}"):
                st.session_state["page"] = page_key
                st.rerun()
        st.markdown("---")
        st.info("API服务: http://localhost:8000")
    
    current_page = st.session_state["page"]
    
    if current_page == "home":
        page_home()
    elif current_page == "requirements":
        page_requirements()
    elif current_page == "files":
        page_files()
    elif current_page == "stats":
        page_stats()


if __name__ == "__main__":
    main()
