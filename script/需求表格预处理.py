# -*- coding: utf-8 -*-
# ===================== 【导入依赖库】 =====================
import os          # 文件路径操作
import re          # 正则表达式匹配
import numpy as np # 数值处理
import pandas as pd # 数据处理核心库
from openpyxl.styles import Alignment # Excel单元格格式设置
import sys         # 系统相关功能
import io          # 输入输出流

# 设置控制台输出编码为UTF-8，避免emoji字符显示问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
# ===========================================================

# ===================== 【全局配置区域】 =====================
INPUT_FOLDER = "raw_data"    # 存放所有原始需求Excel的文件夹（输入目录）
OUTPUT_FOLDER = "raw_out"   # 处理后的统一格式Excel输出文件夹（输出目录）
# ===========================================================

# ===================== 【核心工具函数】 =====================

def combine_name_desc_util(df, id_col, name_col, desc_col, new_col, extra_cols=None):
    """
    【全面穿透合并版】单表数据清洗与合并工具函数
    【改进点】不再单一依靠 ID 分组，而是将相同的【需求名称】强行聚拢，并将其对应的多个 ID 用逗号合并。
    """
    df = df.copy()
    
    # 1. 强制对名称列和描述列进行空值填充与基础清洗（抹除名称内换行防止打架）
    df[name_col] = df[name_col].fillna("未命名需求").astype(str)\
        .str.replace(r'[\r\n\t]+', '', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()
    df[desc_col] = df[desc_col].fillna("").astype(str).str.strip()
    
    # 2. 强力清洗 ID 列，确保 ID 的文本一致性
    df[id_col] = df[id_col].fillna("").astype(str).str.strip()
    
    # 3. 构建聚合规则：描述进行去重罗列，ID 进行逗号拼接，其它列保留
    agg_dict = {
        id_col: lambda x: ",".join(list(dict.fromkeys([str(i).strip() for i in x if str(i).strip() and str(i).strip().lower() != 'nan']))),
        desc_col: lambda x: "\n".join([f"• {str(i).strip()}" if str(i).strip() else "" for i in x if str(i).strip()]),
    }
    
    if extra_cols:
        for col in extra_cols:
            if col in df.columns and col not in agg_dict and col != name_col:
                agg_dict[col] = "first"

    # 🔥 改用【需求名称】作为 groupby 的第一主轴，把相同名字的行强行焊死在一起！
    grouped = df.groupby(name_col).agg(agg_dict).reset_index()
    
    # 4. 组装输出文本，防止名称在描述里套娃
    def finalize_content(row):
        name = row[name_col]
        desc = row[desc_col]
        desc = re.sub(rf"^{re.escape(name)}[：:]\s*", "", desc)
        
        lines = []
        for line in desc.split('\n'):
            line_clean = line.strip().lstrip("• ").strip()
            if line_clean and line_clean != name and line_clean not in lines:
                lines.append(line_clean)
                
        if name and lines:
            return f"{name}：\n" + "\n".join([f"• {l}" for l in lines])
        return name

    grouped[new_col] = grouped.apply(finalize_content, axis=1)
    return grouped

def clean_id_series(df, cols):
    """ID列数据清洗工具函数"""
    for col in cols:
        if col in df.columns:
            df[col] = df[col].fillna(np.nan).apply(
                lambda x: str(int(float(x))) if pd.notna(x) and (isinstance(x, (float, int)) or str(x).endswith('.0')) else str(x)
            ).str.strip()
            df.loc[df[col].isin(["nan", "None", ""]), col] = np.nan
    return df

def extract_issue_id_from_desc(desc):
    """从描述中提取ISSUE ID（增强容错版）"""
    if pd.isna(desc) or not isinstance(desc, str):
        return None
    match_issue = re.search(r'\[ISSUE:(\d+)\]', desc)
    if match_issue:
        return match_issue.group(1)
    match_l2 = re.search(r'(?:L[123]_)?(\d+)', desc)
    if match_l2:
        return match_l2.group(1)
    return None

def process_available_sheets_chain(cust_p, init_p, syst_p, output_dir, prefix=""):
    """【带柔性血缘追溯合并版】跨层级全弹性拓扑算法"""
    print(f"\n[🚀 LOG][{prefix}] 进入拓扑对齐核心链...")
    
    try:
        customer_req = None
        initial_req = None
        system_req = None
        
        # 1. 动态自适应加载
        if cust_p and os.path.exists(cust_p):
            customer_df = pd.read_excel(cust_p)
            customer_df.columns = customer_df.columns.astype(str).str.strip()
            print(f"[🚀 LOG][{prefix}] L1表加载成功, 尺寸: {customer_df.shape}")
            
            customer_desc_col = next((c for c in customer_df.columns if any(kw in c for kw in ["需求内容", "需求描述", "描述"])), customer_df.columns[-1] if len(customer_df.columns) > 1 else "名称")
            customer_df["_orig_name"] = customer_df["名称"].fillna("未命名客户需求").astype(str)\
                .str.replace(r'[\r\n\t]+', '', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()
            
            customer_req = combine_name_desc_util(customer_df, "ID", "名称", customer_desc_col, "客户需求(名称：内容)", extra_cols=["_orig_name"])
            customer_req = customer_req.rename(columns={"ID": "客户需求ID"})
            customer_req = clean_id_series(customer_req, ["客户需求ID"])
        
        if init_p and os.path.exists(init_p):
            initial_df = pd.read_excel(init_p)
            initial_df.columns = initial_df.columns.astype(str).str.strip()
            print(f"[🚀 LOG][{prefix}] L2表加载成功, 尺寸: {initial_df.shape}")
            
            initial_df["_orig_name"] = initial_df["名称"].fillna("未命名初始需求").astype(str)\
                .str.replace(r'[\r\n\t]+', '', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()
            
            initial_req = combine_name_desc_util(initial_df, "ID", "名称", "需求描述", "初始需求(名称：内容)", extra_cols=["上游需求", "_orig_name"])
            initial_req = initial_req.rename(columns={"ID": "初始需求ID", "上游需求": "上游客户需求ID"})
            initial_req = clean_id_series(initial_req, ["初始需求ID", "上游客户需求ID"])
            
        if syst_p and os.path.exists(syst_p):
            system_df = pd.read_excel(syst_p)
            system_df.columns = system_df.columns.astype(str).str.strip()
            print(f"[🚀 LOG][{prefix}] L3表加载成功, 尺寸: {system_df.shape}")
            
            syst_name_col = next((c for c in system_df.columns if any(kw in c for kw in ["名称", "需求概述", "需求名称"])), system_df.columns[0])
            syst_desc_col = next((c for c in system_df.columns if any(kw in c for kw in ["需求概述", "需求描述", "描述"])), syst_name_col)

            if "上游需求" in system_df.columns:
                system_df["_extracted_issue_id"] = system_df["上游需求"].apply(extract_issue_id_from_desc)
                system_df["上游需求"] = system_df["_extracted_issue_id"].fillna(system_df.get("上游需求", ""))
            
            system_df["_orig_name"] = system_df[syst_name_col].fillna("未命名系统需求").astype(str)\
                .str.replace(r'[\r\n\t]+', '', regex=True).str.replace(r'\s+', ' ', regex=True).str.strip()
            
            system_req = combine_name_desc_util(system_df, "ID", syst_name_col, syst_desc_col, "系统需求(名称：内容)", extra_cols=["上游需求", "_orig_name"])
            system_req = system_req.rename(columns={"ID": "系统需求ID", "上游需求": "上游初始需求ID"})
            system_req = clean_id_series(system_req, ["系统需求ID", "上游初始需求ID"])

        # =================================================================
        # 🔥【柔性追溯核心】初始化空表占位，构建双轨制血缘对齐
        # =================================================================
        if customer_req is None: customer_req = pd.DataFrame(columns=["客户需求ID", "客户需求(名称：内容)", "_orig_name"])
        if initial_req is None: initial_req = pd.DataFrame(columns=["初始需求ID", "上游客户需求ID", "初始需求(名称：内容)", "_orig_name"])
        if system_req is None: system_req = pd.DataFrame(columns=["系统需求ID", "上游初始需求ID", "系统需求(名称：内容)", "_orig_name"])

        # ---- 【步骤A：L1 和 L2 双轨融合】 ----
        # 修正：将 how="full" 改为 how="outer"
        l1_l2_res = pd.merge(customer_req, initial_req, left_on="客户需求ID", right_on="上游客户需求ID", how="outer")
        
        # 补链尝试：没有上游ID但名称相同的 L2 看板认亲
        for idx, row in l1_l2_res.iterrows():
            if pd.isna(row["客户需求ID"]) and pd.notna(row["_orig_name_y"]):
                matched_l1 = customer_req[customer_req["_orig_name"] == row["_orig_name_y"]]
                if not matched_l1.empty:
                    target_l1_id = matched_l1.iloc[0]["客户需求ID"]
                    tgt_mask = (l1_l2_res["客户需求ID"] == target_l1_id) & (l1_l2_res["初始需求ID"].isna())
                    if tgt_mask.any():
                        tgt_idx = l1_l2_res[tgt_mask].index[0]
                        l1_l2_res.at[tgt_idx, "初始需求ID"] = row["初始需求ID"]
                        l1_l2_res.at[tgt_idx, "上游客户需求ID"] = target_l1_id
                        l1_l2_res.at[tgt_idx, "初始需求(名称：内容)"] = row["初始需求(名称：内容)"]
                        l1_l2_res.at[tgt_idx, "_orig_name_y"] = row["_orig_name_y"]
                        l1_l2_res.at[idx, "初始需求ID"] = np.nan 

        l1_l2_res = l1_l2_res[~(l1_l2_res["客户需求ID"].isna() & l1_l2_res["初始需求ID"].isna())]
        l1_l2_res["_combined_name_l12"] = l1_l2_res["_orig_name_x"].fillna(l1_l2_res["_orig_name_y"])

        # ---- 【步骤B：L1+L2 基础看板与 L3 柔性融合】 ----
        # 修正：将 how="full" 改为 how="outer"
        final_res = pd.merge(l1_l2_res, system_req, left_on="初始需求ID", right_on="上游初始需求ID", how="outer")
        
        # 补链尝试：上游ID为空但名称相同的 L3 系统需求到主板里认亲
        for idx, row in final_res.iterrows():
            if pd.isna(row["初始需求ID"]) and pd.notna(row["_orig_name"]):
                matched_base = l1_l2_res[l1_l2_res["_combined_name_l12"] == row["_orig_name"]]
                if not matched_base.empty:
                    target_init_id = matched_base.iloc[0]["初始需求ID"]
                    tgt_mask = (final_res["初始需求ID"] == target_init_id) & (final_res["系统需求ID"].isna())
                    if tgt_mask.any():
                        tgt_idx = final_res[tgt_mask].index[0]
                        final_res.at[tgt_idx, "系统需求ID"] = row["系统需求ID"]
                        final_res.at[tgt_idx, "上游初始需求ID"] = target_init_id
                        final_res.at[tgt_idx, "系统需求(名称：内容)"] = row["系统需求(名称：内容)"]
                        final_res.at[tgt_idx, "_orig_name"] = row["_orig_name"]
                        final_res.at[idx, "系统需求ID"] = np.nan

        final_res = final_res[~(final_res["初始需求ID"].isna() & final_res["系统需求ID"].isna() & final_res["客户需求ID"].isna())]

        # 清除清洗的过程冗余字段
        if "_combined_name_l12" in final_res.columns: final_res = final_res.drop(columns=["_combined_name_l12"])
        for c in ["_orig_name_x", "_orig_name_y", "_orig_name"]:
            if c in final_res.columns: final_res = final_res.drop(columns=[c])

        # =================================================================
        # 📊【状态智能打标】与汇总
        # =================================================================
        def join_ids(series):
            vals = []
            for v in series.dropna().unique():
                for sub_v in str(v).replace('\n', ',').split(','):
                    sub_v = sub_v.strip()
                    if sub_v and sub_v not in ["nan", "未追溯L1", "未追溯L2", "未追溯L3"]:
                        vals.append(sub_v)
            return ",".join(list(dict.fromkeys(vals))) if vals else np.nan

        def join_descs(series):
            vals = [str(v).strip() for v in series.dropna().unique() if str(v).strip() and str(v).strip() != "nan"]
            return "\n----\n".join(vals) if vals else np.nan

        # 最终安全重分组
        final_res["Final_Anchor"] = final_res["初始需求ID"].fillna(final_res["系统需求ID"].fillna(final_res["客户需求ID"]))
        aggregated_df = final_res.groupby("Final_Anchor").agg({
            "客户需求ID": join_ids, "客户需求(名称：内容)": join_descs,
            "初始需求ID": join_ids, "初始需求(名称：内容)": join_descs,
            "系统需求ID": join_ids, "系统需求(名称：内容)": join_descs
        }).reset_index(drop=True)

        def get_status(row):
            has_l1 = pd.notna(row["客户需求(名称：内容)"]) and str(row["客户需求(名称：内容)"]).strip() != ""
            has_l2 = pd.notna(row["初始需求(名称：内容)"]) and str(row["初始需求(名称：内容)"]).strip() != ""
            has_l3 = pd.notna(row["系统需求(名称：内容)"]) and str(row["系统需求(名称：内容)"]).strip() != ""
            if has_l1 and has_l2 and has_l3: return "完整全链追溯 (L1->L2->L3)"
            elif has_l1 and has_l2: return "局部链路追溯 (L1->L2 断L3)"
            elif has_l2 and has_l3: return "分层链追溯成功 (L2->L3 无L1)"
            elif has_l1 and has_l3: return "异常穿透链路 (L1->L3 缺失L2)"
            elif has_l1: return "独立客户需求 (仅L1)"
            elif has_l2: return "独立初始需求 (仅L2)"
            else: return "独立系统需求 (仅L3)"

        aggregated_df["追溯状态"] = aggregated_df.apply(get_status, axis=1)
        
        def make_full_trace_summary(row):
            blocks = []
            c_val = str(row["客户需求(名称：内容)"]).strip()
            i_val = str(row["初始需求(名称：内容)"]).strip()
            s_val = str(row["系统需求(名称：内容)"]).strip()
            if c_val and c_val != "nan": blocks.append(f"客户需求-----\n{c_val}")
            if i_val and i_val != "nan": blocks.append(f"初始需求-----\n{i_val}")
            if s_val and s_val != "nan": blocks.append(f"系统需求-----\n{s_val}")
            return "\n\n".join(blocks) if blocks else np.nan

        aggregated_df["全链路需求描述汇总"] = aggregated_df.apply(make_full_trace_summary, axis=1)

        final_cols = ["客户需求ID", "客户需求(名称：内容)", "初始需求ID", "初始需求(名称：内容)", "系统需求ID", "系统需求(名称：内容)", "全链路需求描述汇总", "追溯状态"]
        sort_col = "系统需求ID" if syst_p else ("初始需求ID" if init_p else "客户需求ID")
        aggregated_df = aggregated_df[final_cols].sort_values(by=["追溯状态", sort_col], na_position="last")

        out_name = f"{prefix if prefix else '分层需求'}[聚合链矩阵].xlsx"
        out_path = os.path.join(output_dir, out_name)
        
        # 智能防 Excel 软件打开占用避让机制
        counter = 1
        base_name, ext = os.path.splitext(out_name)
        while True:
            try:
                f = open(out_path, 'a')
                f.close()
                break
            except IOError:
                out_name = f"{base_name}_{counter}{ext}"
                out_path = os.path.join(output_dir, out_name)
                counter += 1
        
        with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
            aggregated_df.to_excel(writer, sheet_name="完整链路矩阵", index=False)
            workbook = writer.book
            worksheet = writer.sheets["完整链路矩阵"]
            for row in worksheet.iter_rows(min_row=2, max_row=worksheet.max_row):
                for cell in row:
                    cell.alignment = Alignment(wrap_text=True, vertical="top")
        return f"✅ 成功完成项目 [{prefix}] 的处理 -> 生成文件: {out_name} (共{len(aggregated_df)}条记录)"
    except Exception as e:
        import traceback
        return f"❌ 拓扑链路核心段遭遇崩溃性失败，原因: {str(e)}\n详细堆栈:\n{traceback.format_exc()}"

def process_single_file_standard(input_path, output_dir):
    """单文件一对一标准化大宽表集成解析"""
    try:
        df = pd.read_excel(input_path, sheet_name=0)
        df.columns = df.columns.astype(str).str.strip()
        col_text = "|".join(df.columns).lower()
        filename = os.path.basename(input_path)

        if "系统需求id" in col_text and "初始需求" in col_text and "客户需求" in col_text:
            sys_id = next((c for c in df.columns if "系统需求id" in c.lower()), None)
            init_id = next((c for c in df.columns if "初始需求id" in c.lower()), None)
            cust_id = next((c for c in df.columns if "客户需求id" in c.lower()), None)
            
            sys_name = next((c for c in df.columns if "系统需求名称" in c), None)
            sys_desc = next((c for c in df.columns if "系统需求概述" in c or "系统需求描述" in c), None)
            init_name = next((c for c in df.columns if "初始需求名称" in c), None)
            init_desc = next((c for c in df.columns if "初始需求描述" in c), None)
            cust_name = next((c for c in df.columns if "客户需求名称" in c), None)
            cust_desc = next((c for c in df.columns if "客户需求描述" in c), None)

            result = []
            for _, row in df.iterrows():
                rid = None
                for id_col_name in [sys_id, init_id, cust_id]:
                    if id_col_name and pd.notna(row[id_col_name]) and str(row[id_col_name]).strip() != "":
                        rid = str(row[id_col_name]).strip()
                        break
                if not rid: continue

                s_n = str(row[sys_name]).strip() if sys_name and pd.notna(row[sys_name]) else ""
                s_d = str(row[sys_desc]).strip() if sys_desc and pd.notna(row[sys_desc]) else ""
                i_n = str(row[init_name]).strip() if init_name and pd.notna(row[init_name]) else ""
                i_d = str(row[init_desc]).strip() if init_desc and pd.notna(row[init_desc]) else ""
                c_n = str(row[cust_name]).strip() if cust_name and pd.notna(row[cust_name]) else ""
                c_d = str(row[cust_desc]).strip() if cust_desc and pd.notna(row[cust_desc]) else ""

                parts = []
                if s_n or s_d: parts.append(f"{s_n}：{s_d}".strip("："))
                if i_n or i_d: parts.append(f"{i_n}：{i_d}".strip("："))
                if c_n or c_d: parts.append(f"{c_n}：{c_d}".strip("："))

                full = "\n----\n".join(parts) if parts else ""
                if full: result.append([rid, full])

            output_df = pd.DataFrame(result, columns=["ID", "需求"])
            return save_excel_util(output_df, filename, output_dir, "大宽表集成格式")

        elif "id" in col_text and "名称" in col_text and ("概述" in col_text or "需求概述" in col_text) and "上游需求" not in col_text:
            id_col = next((c for c in df.columns if "id" in c.lower()), None)
            name_col = next((c for c in df.columns if "名称" in c), None)
            desc_col = next((c for c in df.columns if "概述" in c or "需求概述" in c), None)

            result = []
            for _, row in df.iterrows():
                rid = row[id_col]
                if pd.isna(rid) or str(rid).strip() == "": continue
                name = str(row[name_col]).strip() if pd.notna(row[name_col]) else ""
                desc = str(row[desc_col]).strip() if pd.notna(row[desc_col]) else ""
                
                content = f"{name}：{desc}".strip("：")
                if content: result.append([rid, content])

            output_df = pd.DataFrame(result, columns=["ID", "系统需求"])
            return save_excel_util(output_df, filename, output_dir, "单表标准格式")
        else:
            return None 
            
    except Exception as e:
        return f"❌ {os.path.basename(input_path)} | 大宽表解析失败: {str(e)[:50]}"

def save_excel_util(df, filename, out_dir, flag):
    os.makedirs(out_dir, exist_ok=True)
    out_name = f"[标准化]{filename}"
    out_path = os.path.join(out_dir, out_name)
    with pd.ExcelWriter(out_path, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="需求表")
    return f"✅ {filename} | {flag} | 转化完成 {len(df)} 条"

def main_orchestrator():
    print("=" * 70)
    print("      需求全能管家：已部署【双轨血缘穿透与智能防文件占用系统】")
    print("=" * 70)

    if not os.path.exists(INPUT_FOLDER):
        os.makedirs(INPUT_FOLDER)
        print(f"\n📂 已创建输入夹：{INPUT_FOLDER}，请把需要处理的Excel表格放入其中。")
        return

    os.makedirs(OUTPUT_FOLDER, exist_ok=True)
    all_files = [f for f in os.listdir(INPUT_FOLDER) if f.endswith((".xlsx", ".xls"))]
    if not all_files:
        print("\n❌ 提示：在输入文件夹内未找到有效的Excel表格文件。")
        return

    print(f"\n[1/2] 阶段一：扫描并优先处理一体化集成大宽表...")
    remained_files = []
    for f in all_files:
        full_p = os.path.join(INPUT_FOLDER, f)
        res = process_single_file_standard(full_p, OUTPUT_FOLDER)
        if res:
            print(res)
        else:
            remained_files.append(f)

    if remained_files:
        print(f"\n[2/2] 阶段二：对分立的需求子表进行项目匹配与跨层聚合...")
        
        project_groups = {}
        for f in remained_files:
            match = re.match(r"^([A-Za-z0-9]+)\s*-\s*", f)
            proj_key = match.group(1) if match else "未分类项目"
            if proj_key not in project_groups:
                project_groups[proj_key] = []
            project_groups[proj_key].append(f)

        for proj, f_list in project_groups.items():
            cust_f = next((f for f in f_list if "客户需求" in f), None)
            init_f = next((f for f in f_list if "初始需求" in f), None)
            syst_f = next((f for f in f_list if "系统需求" in f), None)

            if cust_f or init_f or syst_f:
                print(f" -> 正在自动分析项目 [{proj}] 的可用层级，执行自适应看板聚合...")
                cust_full_path = os.path.join(INPUT_FOLDER, cust_f) if cust_f else None
                init_full_path = os.path.join(INPUT_FOLDER, init_f) if init_f else None
                syst_full_path = os.path.join(INPUT_FOLDER, syst_f) if syst_f else None
                
                report = process_available_sheets_chain(
                    cust_full_path, init_full_path, syst_full_path,
                    OUTPUT_FOLDER, prefix=proj
                )
                print(report)
            else:
                for single_f in f_list:
                    print(f"⚠️ 无法为文件 {single_f} 自动匹配追溯流，已跳过。")
                    
    print(f"\n🏁 全部操作已安全执行完毕！请前往输出目录查看结果：{OUTPUT_FOLDER}")

if __name__ == "__main__":
    main_orchestrator()