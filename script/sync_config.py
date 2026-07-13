# -*- coding: utf-8 -*-
"""
规范配置智能验证与增量同步脚本
=====================================
功能：
  1. 从规范JSON生成 categories.dbV4.1.json → 与现有对比 → 同步
  2. 从规范JSON为【新分类】生成初始模板 → 追加到 Master_Requirement_Templates.json
  3. 检测【孤立模板】（对应分类已从规范中删除）→ 标记但不删除

使用方式：
  # 验证模式：仅检查差异
  python script/sync_config.py --check

  # 同步模式：自动更新
  python script/sync_config.py --sync

  # 强制同步（跳过确认）
  python script/sync_config.py --sync --force
"""
import os
import sys
import io
import json
import re
import hashlib
import argparse
from typing import Dict, List, Any, Optional, Tuple
from datetime import datetime, timezone

# 修复 Windows GBK 编码问题
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC_JSON_PATH = os.path.join(BASE_DIR, "data", "config", "芯片需求结构化定义规范V4.0.json")
CATEGORY_DB_PATH = os.path.join(BASE_DIR, "data", "config", "categories.dbV4.1.json")
TEMPLATES_PATH = os.path.join(BASE_DIR, "data", "config", "Master_Requirement_Templates.json")


# ============================================================================
# UID 工具
# ============================================================================

def generate_uid(key: str) -> str:
    """生成确定性短UID"""
    hash_bytes = hashlib.md5(key.encode('utf-8')).digest()
    chars = "0123456789abcdefghijklmnopqrstuvwxyz"
    return "cat_" + ''.join(chars[hash_bytes[i] % len(chars)] for i in range(6))


def build_existing_uid_map(category_db_path: str) -> Dict[Tuple[str, int], str]:
    """从已有 categories.db 构建 (id, level) → uid 映射"""
    uid_map = {}
    if not os.path.exists(category_db_path):
        return uid_map
    try:
        with open(category_db_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
        cats = data.get('categories', data)
        for uid, node in cats.items():
            node_id = node.get('id', '')
            level = node.get('level', 0)
            if node_id and level:
                uid_map[(node_id, level)] = uid
    except Exception:
        pass
    return uid_map


# ============================================================================
# Category DB 同步
# ============================================================================

def generate_categories(spec_items: List[Dict], existing_uid_map: Dict) -> Dict:
    """
    从规范JSON生成 categories 结构，保留已有UID
    """
    categories = {}
    dim_uids: Dict[str, str] = {}
    cap_uids: Dict[str, str] = {}

    for item in spec_items:
        dim_id = item.get("维度序号", "")
        dim_name = item.get("维度", "")
        cap_id = item.get("能力域序号", "")
        cap_name = item.get("能力域", "")
        req_id = item.get("需求项序号", "")
        req_name = item.get("需求项", "")
        item_uid = item.get("uid", "")

        if not all([dim_id, cap_id, req_id]):
            continue

        # L1 维度
        if dim_id not in dim_uids:
            dim_uid = existing_uid_map.get((dim_id, 1)) or generate_uid(f"dim_{dim_id}")
            dim_uids[dim_id] = dim_uid
            categories[dim_uid] = {
                "uid": dim_uid,
                "id": dim_id,
                "name": dim_name,
                "level": 1,
                "parent_uid": "",
                "children": [],
                "description": ""
            }

        # L2 能力域
        if cap_id not in cap_uids:
            cap_uid = existing_uid_map.get((cap_id, 2)) or generate_uid(f"cap_{cap_id}")
            cap_uids[cap_id] = cap_uid
            categories[cap_uid] = {
                "uid": cap_uid,
                "id": cap_id,
                "name": cap_name,
                "level": 2,
                "parent_uid": dim_uids[dim_id],
                "children": [],
                "description": ""
            }
            dim_uid = dim_uids[dim_id]
            if cap_uid not in categories[dim_uid]["children"]:
                categories[dim_uid]["children"].append(cap_uid)

        # L3 需求项
        req_uid = item_uid or existing_uid_map.get((req_id, 3)) or generate_uid(f"req_{req_id}")
        cap_uid = cap_uids[cap_id]
        categories[req_uid] = {
            "uid": req_uid,
            "id": req_id,
            "name": req_name,
            "level": 3,
            "parent_uid": cap_uid,
            "children": [],
            "description": item.get("description", "")
        }
        if req_uid not in categories[cap_uid]["children"]:
            categories[cap_uid]["children"].append(req_uid)

    return {"categories": categories}


def compare_categories(existing: Dict, generated: Dict) -> Dict:
    """
    智能对比 categories：
    - 忽略 children 数组顺序
    - 仅比较结构字段（新增/删除/名称/父节点变更）
    - 忽略元数据字段（description, applicable_lines 等人工维护的富化信息）
    """
    existing_cats = existing.get("categories", {})
    generated_cats = generated.get("categories", {})

    report = {
        "added": [],
        "removed": [],
        "name_changed": [],
        "parent_changed": [],
        "children_changed": [],
    }

    existing_ids = set(existing_cats.keys())
    generated_ids = set(generated_cats.keys())

    for uid in generated_ids - existing_ids:
        node = generated_cats[uid]
        report["added"].append(
            f"[L{node.get('level','?')}] {node.get('id','?')} {node.get('name','?')} [uid={uid}]"
        )

    for uid in existing_ids - generated_ids:
        node = existing_cats[uid]
        report["removed"].append(
            f"[L{node.get('level','?')}] {node.get('id','?')} {node.get('name','?')} [uid={uid}]"
        )

    for uid in existing_ids & generated_ids:
        e = existing_cats[uid]
        g = generated_cats[uid]
        node_label = f"[L{g.get('level','?')}] {g.get('id','?')} {g.get('name','?')}"

        if e.get("name", "") != g.get("name", ""):
            report["name_changed"].append(
                f"{node_label}: '{e.get('name','')}' -> '{g.get('name','')}'"
            )
        if e.get("parent_uid", "") != g.get("parent_uid", ""):
            report["parent_changed"].append(
                f"{node_label}: parent '{e.get('parent_uid','')}' -> '{g.get('parent_uid','')}'"
            )
        if sorted(e.get("children", [])) != sorted(g.get("children", [])):
            e_set = set(e.get("children", []))
            g_set = set(g.get("children", []))
            added = g_set - e_set
            removed = e_set - g_set
            detail = ""
            if added:
                detail += f" +{len(added)}"
            if removed:
                detail += f" -{len(removed)}"
            report["children_changed"].append(f"{node_label}: children changed{detail}")

    return report


def sync_categories(generated: Dict, target_path: str, force: bool = False):
    """同步 categories.db，保留已有的元数据字段"""
    if not os.path.exists(target_path):
        print(f"[INFO] {target_path} 不存在，将创建新文件")
        os.makedirs(os.path.dirname(target_path), exist_ok=True)
        with open(target_path, 'w', encoding='utf-8') as f:
            json.dump(generated, f, ensure_ascii=False, indent=2)
        print(f"[OK] 已创建: {target_path}")
        return

    with open(target_path, 'r', encoding='utf-8') as f:
        existing = json.load(f)

    report = compare_categories(existing, generated)

    total_changes = sum(len(v) for v in report.values())
    print(f"\n{'='*60}")
    print(f"Categories DB 变更报告")
    print(f"{'='*60}")

    if total_changes == 0:
        print("OK - Categories DB 与规范书完全一致，无需更新")
        return

    for change_type, items in report.items():
        if items:
            label = {
                "added": "[ADDED] 新增节点",
                "removed": "[REMOVED] 删除节点",
                "name_changed": "[RENAMED] 名称变更",
                "parent_changed": "[REPARENTED] 父节点变更",
                "children_changed": "[CHILDREN] 子节点列表变更",
            }.get(change_type, change_type)
            print(f"\n{label} ({len(items)}):")
            for item in items[:15]:
                print(f"  {item}")
            if len(items) > 15:
                print(f"  ... 共 {len(items)} 条")

    print(f"\nTotal: {total_changes} changes")

    if not force:
        confirm = input(f"\nWrite changes to {target_path}? (type 'yes' to confirm): ")
        if confirm.lower() != "yes":
            print("[CANCEL] User cancelled")
            return

    # Backup
    backup_path = target_path + ".backup." + datetime.now().strftime("%Y%m%d_%H%M%S")
    import shutil
    shutil.copy2(target_path, backup_path)
    print(f"[BACKUP] {backup_path}")

    # Merge: use generated as base, preserve existing metadata
    existing_cats = existing.get("categories", {})
    generated_cats = generated.get("categories", {})

    # Metadata fields to preserve from existing
    preserve_fields = ["description", "applicable_lines"]

    merged_cats = {}
    for uid, gen_node in generated_cats.items():
        merged_node = dict(gen_node)
        if uid in existing_cats:
            for field in preserve_fields:
                if field in existing_cats[uid] and existing_cats[uid][field]:
                    merged_node[field] = existing_cats[uid][field]
        merged_cats[uid] = merged_node

    merged = {"categories": merged_cats}
    with open(target_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)
    print(f"[OK] Categories DB updated ({len(merged_cats)} nodes)")


# ============================================================================
# Templates 增量同步
# ============================================================================

def extract_variables(text: str) -> List[Dict]:
    """从模板文本中提取 [[变量]] 占位符"""
    variables = []
    seen = set()
    for match in re.findall(r'\[\[([^\]]+)\]\]', text):
        name = match.strip()
        if name and name not in seen:
            seen.add(name)
            var_type = "number" if any(kw in name.lower() for kw in [
                "数值", "bit", "hz", "ma", "mv", "us", "ns", "kb", "mb",
                "gb", "v", "a", "℃", "%", "次", "个", "路", "种", "年"
            ]) else "string"
            variables.append({"name": name, "type": var_type, "label": name, "unit": ""})
    return variables


def generate_new_templates(spec_item: Dict, template_counter: List[int]) -> List[Dict]:
    """
    为一个需求项生成 L1/L2/L3 模板组（含追溯链）
    """
    templates = []
    req_uid = spec_item.get("uid", "")
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    l1_text = spec_item.get("原始需求", "").strip()
    l2_text = spec_item.get("初始需求", "").strip()
    l3_text = spec_item.get("系统需求", "").strip()

    skip_marker = "[文档中未明确提及]"
    has_l1 = l1_text and skip_marker not in l1_text
    has_l2 = l2_text and skip_marker not in l2_text
    has_l3 = l3_text and skip_marker not in l3_text

    if not (has_l1 or has_l2 or has_l3):
        return templates

    def next_id(level):
        template_counter[0] += 1
        return f"TPL_{level}_{template_counter[0]:05d}"

    l1_id, l2_id, l3_id = None, None, None

    if has_l1:
        l1_id = next_id("L1")
        templates.append({
            "template_id": l1_id, "level": "L1",
            "category_uid": req_uid,
            "templates_text": l1_text,
            "product_lines": ["ALL"],
            "variables": extract_variables(l1_text),
            "template_trace_chain": {
                "parent_template_id": "",
                "child_template_ids": []
            },
            "version": "V4.1.0", "created_at": now, "updated_at": now
        })

    if has_l2:
        l2_id = next_id("L2")
        templates.append({
            "template_id": l2_id, "level": "L2",
            "category_uid": req_uid,
            "templates_text": l2_text,
            "product_lines": ["ALL"],
            "variables": extract_variables(l2_text),
            "template_trace_chain": {
                "parent_template_id": l1_id or "",
                "child_template_ids": []
            },
            "version": "V4.1.0", "created_at": now, "updated_at": now
        })
        if l1_id:
            # 更新 L1 的 child ids
            for t in templates:
                if t["template_id"] == l1_id:
                    t["template_trace_chain"]["child_template_ids"].append(l2_id)

    if has_l3:
        l3_id = next_id("L3")
        templates.append({
            "template_id": l3_id, "level": "L3",
            "category_uid": req_uid,
            "templates_text": l3_text,
            "product_lines": ["ALL"],
            "variables": extract_variables(l3_text),
            "template_trace_chain": {
                "parent_template_id": l2_id or "",
                "child_template_ids": []
            },
            "version": "V4.1.0", "created_at": now, "updated_at": now
        })
        if l2_id:
            for t in templates:
                if t["template_id"] == l2_id:
                    t["template_trace_chain"]["child_template_ids"].append(l3_id)

    return templates


def analyze_templates(spec_items: List[Dict], templates_path: str) -> Dict:
    """
    分析模板库：
    - 哪些分类缺少模板 → 生成
    - 哪些分类在模板中存在但规范中已删除 → 标记
    """
    # 加载已有模板
    existing_tpls = {}
    if os.path.exists(templates_path):
        with open(templates_path, 'r', encoding='utf-8') as f:
            existing_tpls = json.load(f)

    # 分类 → 是否已有模板
    categories_with_templates = set()
    for tid, tpl in existing_tpls.items():
        categories_with_templates.add(tpl.get("category_uid", ""))

    # 规范中的分类
    spec_category_uids = {item.get("uid", "") for item in spec_items if item.get("uid")}

    # 分析
    missing_templates = spec_category_uids - categories_with_templates
    orphan_templates = categories_with_templates - spec_category_uids - {"", "cat_failed"}

    # 获取已有模板的最大序号
    max_num = 0
    for tid in existing_tpls:
        match = re.search(r'TPL_[A-Z]\d_(\d+)', tid)
        if match:
            max_num = max(max_num, int(match.group(1)))

    return {
        "total_existing": len(existing_tpls),
        "spec_categories": len(spec_category_uids),
        "categories_with_templates": len(categories_with_templates & spec_category_uids),
        "missing_templates": missing_templates,
        "orphan_templates": orphan_templates,
        "last_template_num": max_num,
    }


def sync_templates(
    spec_items: List[Dict],
    templates_path: str,
    force: bool = False
):
    """
    增量同步模板：仅为缺失模板的分类生成初始模板
    """
    analysis = analyze_templates(spec_items, templates_path)

    print(f"\n{'='*60}")
    print(f"Templates 变更报告")
    print(f"{'='*60}")
    print(f"  已有模板数: {analysis['total_existing']}")
    print(f"  规范分类数: {analysis['spec_categories']}")
    print(f"  已有模板覆盖: {analysis['categories_with_templates']}/{analysis['spec_categories']}")
    print(f"  缺失模板的分类: {len(analysis['missing_templates'])}")
    print(f"  孤立模板（分类已删除）: {len(analysis['orphan_templates'])}")

    if analysis["orphan_templates"]:
        print(f"\n  ⚠️  孤立模板分类 (在模板库中存在但规范中已删除):")
        for uid in sorted(analysis["orphan_templates"])[:10]:
            print(f"    - {uid}")
        if len(analysis["orphan_templates"]) > 10:
            print(f"    ... 共 {len(analysis['orphan_templates'])} 个")

    if not analysis["missing_templates"]:
        print("\n✅ 所有规范分类都已有模板，无需生成")
        return

    # 为缺失的分类生成模板
    print(f"\n📝 为 {len(analysis['missing_templates'])} 个新分类生成初始模板...")

    # 构建 uid → item 映射
    uid_to_item = {item.get("uid", ""): item for item in spec_items}

    counter = [analysis["last_template_num"]]
    new_templates = {}

    for uid in sorted(analysis["missing_templates"]):
        item = uid_to_item.get(uid)
        if not item:
            continue
        tpls = generate_new_templates(item, counter)
        for tpl in tpls:
            new_templates[tpl["template_id"]] = tpl
            print(f"  + {tpl['template_id']} ({tpl['level']}) → {tpl['templates_text'][:50]}...")

    if not new_templates:
        print("  (无有效需求文本可生成模板)")
        return

    print(f"\n  共生成 {len(new_templates)} 个新模板")

    if not force:
        confirm = input(f"\n⚠️  是否将 {len(new_templates)} 个新模板追加到 {templates_path}？(输入 yes 确认): ")
        if confirm.lower() != "yes":
            print("[CANCEL] 用户取消")
            return

    # 备份
    if os.path.exists(templates_path):
        backup_path = templates_path + ".backup." + datetime.now().strftime("%Y%m%d_%H%M%S")
        import shutil
        shutil.copy2(templates_path, backup_path)
        print(f"[BACKUP] {backup_path}")

    # 合并：已有模板 + 新模板
    existing_tpls = {}
    if os.path.exists(templates_path):
        with open(templates_path, 'r', encoding='utf-8') as f:
            existing_tpls = json.load(f)

    merged = {**existing_tpls, **new_templates}
    with open(templates_path, 'w', encoding='utf-8') as f:
        json.dump(merged, f, ensure_ascii=False, indent=2)

    print(f"[OK] Templates 已更新 ({len(merged)} 个模板)")


# ============================================================================
# CLI
# ============================================================================

def main():
    parser = argparse.ArgumentParser(
        description="规范配置验证与增量同步",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python script/sync_config.py --check          # 仅检查差异
  python script/sync_config.py --sync            # 同步配置
  python script/sync_config.py --sync --force    # 强制同步（跳过确认）
  python script/sync_config.py --categories-only # 仅同步目录
  python script/sync_config.py --templates-only  # 仅同步模板
        """
    )

    parser.add_argument("--spec-json", type=str, default=SPEC_JSON_PATH,
                         help="规范JSON文件路径")
    parser.add_argument("--category-db", type=str, default=CATEGORY_DB_PATH,
                         help="categories DB JSON路径")
    parser.add_argument("--templates", type=str, default=TEMPLATES_PATH,
                         help="Templates JSON路径")

    parser.add_argument("--check", action="store_true",
                         help="仅检查差异（默认行为）")
    parser.add_argument("--sync", action="store_true",
                         help="执行同步")
    parser.add_argument("--force", action="store_true",
                         help="跳过确认提示")
    parser.add_argument("--categories-only", action="store_true",
                         help="仅同步 categories")
    parser.add_argument("--templates-only", action="store_true",
                         help="仅同步 templates")

    args = parser.parse_args()

    # 默认行为：check
    if not args.sync and not args.check:
        args.check = True

    # 加载规范JSON
    if not os.path.exists(args.spec_json):
        print(f"[ERROR] 规范JSON不存在: {args.spec_json}")
        sys.exit(1)

    with open(args.spec_json, 'r', encoding='utf-8') as f:
        data = json.load(f)
    spec_items = data if isinstance(data, list) else data.get("items", [])

    if not spec_items:
        print("[ERROR] 规范JSON为空")
        sys.exit(1)

    print(f"[OK] 已加载规范JSON: {len(spec_items)} 个需求项")

    # Categories
    if not args.templates_only:
        existing_uid_map = build_existing_uid_map(args.category_db)
        generated_cats = generate_categories(spec_items, existing_uid_map)

        if args.check:
            existing_cats = {}
            if os.path.exists(args.category_db):
                with open(args.category_db, 'r', encoding='utf-8') as f:
                    existing_cats = json.load(f)
            report = compare_categories(existing_cats, generated_cats)
            total = sum(len(v) for v in report.values())
            if total == 0:
                print("\n✅ Categories DB 与规范书完全一致！")
            else:
                print(f"\n⚠️  Categories DB 有 {total} 处差异，使用 --sync 执行同步")
        else:
            sync_categories(generated_cats, args.category_db, force=args.force)

    # Templates
    if not args.categories_only:
        if args.check:
            analysis = analyze_templates(spec_items, args.templates)
            print(f"\n{'='*60}")
            print(f"Templates 状态报告")
            print(f"{'='*60}")
            print(f"  已有模板: {analysis['total_existing']}")
            print(f"  规范分类: {analysis['spec_categories']}")
            print(f"  已覆盖: {analysis['categories_with_templates']}")
            print(f"  缺失: {len(analysis['missing_templates'])}")
            print(f"  孤立: {len(analysis['orphan_templates'])}")

            if analysis["missing_templates"]:
                print(f"\n  缺失模板的分类:")
                for uid in sorted(analysis["missing_templates"])[:15]:
                    item = next((i for i in spec_items if i.get("uid") == uid), None)
                    if item:
                        print(f"    - [{uid}] {item.get('需求项序号','?')} {item.get('需求项','?')[:30]}")
                if len(analysis["missing_templates"]) > 15:
                    print(f"    ... 共 {len(analysis['missing_templates'])} 个")
                print(f"\n💡 使用 --sync 自动为缺失分类生成初始模板")

            if analysis["orphan_templates"]:
                print(f"\n  ⚠️  孤立模板（规范中已删除的分类）:")
                for uid in sorted(analysis["orphan_templates"])[:10]:
                    print(f"    - {uid}")

            if not analysis["missing_templates"] and not analysis["orphan_templates"]:
                print("\n✅ Templates 与规范书完全一致！")
        else:
            sync_templates(spec_items, args.templates, force=args.force)


if __name__ == "__main__":
    main()
