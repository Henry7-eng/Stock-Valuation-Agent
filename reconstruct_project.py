#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
reconstruct_project.py

2.0 机构防御型量化基本面投研中台：像素级无损重构脚本

功能：
1) 建立 2.0 基础工业化目录
2) 按硬编码点对点映射规则执行无损迁移
3) 清理旧虚拟环境和缓存垃圾
4) 初始化 .gitignore 与 config/secrets.py

运行：
    python3 reconstruct_project.py
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path
from typing import List, Tuple


ROOT = Path.cwd()

# 2.0 基础工业化目录
DIR_01 = ROOT / "01_Data_Harvest"
DIR_01_BPC = DIR_01 / "bpc_extension"
DIR_01_TWITTER = DIR_01 / "Twitter_Scrapes"
DIR_01_VIP = DIR_01 / "VIP_Txt_Dumps"

DIR_02 = ROOT / "02_Audit_Prompts"

DIR_03 = ROOT / "03_Quant_Data"
DIR_03_CASES = DIR_03 / "Historical_Cases"

DIR_CONFIG = ROOT / "config"

TARGET_DIRS = [
    DIR_01,
    DIR_01_BPC,
    DIR_01_TWITTER,
    DIR_01_VIP,
    DIR_02,
    DIR_03,
    DIR_03_CASES,
    DIR_CONFIG,
]


def log(msg: str) -> None:
    print(msg)


def ensure_dirs() -> None:
    log("\n=== Step 1/5: 建立 2.0 基础工业化目录 ===")
    for d in TARGET_DIRS:
        try:
            existed = d.exists()
            d.mkdir(parents=True, exist_ok=True)
            if existed:
                log(f"[SKIP] 已存在: {d.relative_to(ROOT)}")
            else:
                log(f"[CREATED] {d.relative_to(ROOT)}")
        except Exception as e:
            log(f"[ERROR] 创建目录失败: {d} | {e}")


def unique_backup_name(dst_path: Path) -> Path:
    """若目标已存在，生成 *_backup_old, *_backup_old_2 ... 名称，绝不覆盖。"""
    parent = dst_path.parent
    stem = dst_path.stem
    suffix = dst_path.suffix

    candidate = parent / f"{stem}_backup_old{suffix}"
    if not candidate.exists():
        return candidate

    idx = 2
    while True:
        candidate = parent / f"{stem}_backup_old_{idx}{suffix}"
        if not candidate.exists():
            return candidate
        idx += 1


def safe_move_path(src: Path, dst_dir: Path) -> bool:
    """安全移动：
    - src 不存在则跳过
    - 目标同名存在时，迁移文件/文件夹自动重命名为 *_backup_old
    - 出错不抛异常，打印错误并返回 False
    """
    try:
        if not src.exists():
            log(f"[SKIP] 源不存在: {src.relative_to(ROOT)}")
            return False

        dst_dir.mkdir(parents=True, exist_ok=True)
        dst = dst_dir / src.name

        # 避免重复移动到同位置
        try:
            if src.resolve() == dst.resolve():
                log(f"[SKIP] 已在目标目录: {src.relative_to(ROOT)}")
                return False
        except Exception:
            # resolve 失败时继续按常规逻辑处理
            pass

        if dst.exists():
            new_dst = unique_backup_name(dst)
            log(
                f"[WARN] 目标已存在同名: {dst.relative_to(ROOT)} | "
                f"改名迁移为: {new_dst.name}"
            )
            dst = new_dst

        shutil.move(str(src), str(dst))
        log(f"[MOVED] {src.relative_to(ROOT)} -> {dst.relative_to(ROOT)}")
        return True
    except Exception as e:
        log(f"[ERROR] 移动失败: {src} -> {dst_dir} | {e}")
        return False


def scan_root_prefix(prefix: str) -> List[Path]:
    """扫描根目录一级条目，返回名称以 prefix 开头的所有路径。"""
    results: List[Path] = []
    try:
        for p in ROOT.iterdir():
            if p.name.startswith(prefix):
                results.append(p)
    except Exception as e:
        log(f"[ERROR] 扫描前缀失败: {prefix} | {e}")
    return sorted(results, key=lambda x: x.name)


def build_precise_migration_list() -> List[Tuple[Path, Path, str]]:
    """构建硬编码迁移清单：[(src, dst_dir, reason), ...]"""
    tasks: List[Tuple[Path, Path, str]] = []

    # A. dataset_twitter-scraper-lite* + scrape_tweets.py -> 01_Data_Harvest/Twitter_Scrapes
    for p in scan_root_prefix("dataset_twitter-scraper-lite"):
        tasks.append((p, DIR_01_TWITTER, "Twitter 数据集资产"))

    tasks.append((ROOT / "scrape_tweets.py", DIR_01_TWITTER, "Twitter 抓取脚本"))

    # B. 核心战略文档 -> 02_Audit_Prompts
    tasks.append((ROOT / "Serenity_Logic_Base.md", DIR_02, "核心战略文档"))
    tasks.append((ROOT / "Serenity_buy_sell_Base.md", DIR_02, "核心战略文档"))

    # C. a_share_fundamental_extraction* -> 03_Quant_Data
    for p in scan_root_prefix("a_share_fundamental_extraction"):
        tasks.append((p, DIR_03, "A股基本面提取资产"))

    # D. akshare_stock_upgrade* （文件夹 + .py）-> 03_Quant_Data
    for p in scan_root_prefix("akshare_stock_upgrade"):
        if p.is_dir() or (p.is_file() and p.suffix.lower() == ".py"):
            tasks.append((p, DIR_03, "AKShare 升级资产"))

    # E. 个股历史案例 -> 03_Quant_Data/Historical_Cases
    tasks.append((ROOT / "003031", DIR_03_CASES, "历史个股案例"))
    tasks.append((ROOT / "case_1", DIR_03_CASES, "历史研究案例"))

    return tasks


def execute_precise_migration() -> None:
    log("\n=== Step 2/5: 点对点·无损搬家映射 ===")
    tasks = build_precise_migration_list()

    moved_count = 0
    skipped_count = 0

    for src, dst, reason in tasks:
        log(f"\n[PLAN] {reason}: {src.name} -> {dst.relative_to(ROOT)}")
        ok = safe_move_path(src, dst)
        if ok:
            moved_count += 1
        else:
            skipped_count += 1

    log("\n--- 迁移汇总 ---")
    log(f"[SUMMARY] 成功迁移: {moved_count}")
    log(f"[SUMMARY] 跳过/失败: {skipped_count}")


def safe_delete(path: Path) -> bool:
    try:
        if not path.exists() and not path.is_symlink():
            return False

        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)

        log(f"[DELETED] {path.relative_to(ROOT)}")
        return True
    except Exception as e:
        log(f"[ERROR] 删除失败: {path} | {e}")
        return False


def cleanup_junk() -> None:
    log("\n=== Step 3/5: 冷酷清理电子垃圾 ===")

    # 只要求删除根目录 /.venv
    safe_delete(ROOT / ".venv")

    # 递归清理 __pycache__ 和 .pytest_cache
    for p in ROOT.rglob("*"):
        try:
            if any(part == ".git" for part in p.parts):
                continue
            if p.is_dir() and p.name in {"__pycache__", ".pytest_cache"}:
                safe_delete(p)
        except Exception as e:
            log(f"[ERROR] 清理扫描异常: {p} | {e}")


def write_secrets_template() -> None:
    secrets = DIR_CONFIG / "secrets.py"
    template = (
        "# 2.0 Quantamental Secrets Template\n"
        "TUSHARE_TOKEN = \"YOUR_TUSHARE_TOKEN_HERE\"\n"
        "GEMINI_API_KEY = \"YOUR_GEMINI_API_KEY_HERE\"\n"
    )

    try:
        if secrets.exists():
            log(f"[SKIP] 已存在: {secrets.relative_to(ROOT)}")
            return
        secrets.write_text(template, encoding="utf-8")
        log(f"[CREATED] {secrets.relative_to(ROOT)}")
    except Exception as e:
        log(f"[ERROR] 写入 secrets.py 失败: {secrets} | {e}")


def write_gitignore() -> None:
    gitignore = ROOT / ".gitignore"

    required_rules = [
        "# ===== Quantamental 2.0 Privacy & Cache Rules =====",
        "/config/secrets.py",
        ".venv/",
        "*.venv/",
        "__pycache__/",
        ".pytest_cache/",
        "*.pyc",
        "*.pyo",
        "*.pyd",
    ]

    try:
        existing_text = ""
        existing_lines: List[str] = []

        if gitignore.exists():
            existing_text = gitignore.read_text(encoding="utf-8", errors="ignore")
            existing_lines = existing_text.splitlines()

        changed = False
        final_lines = existing_lines.copy()
        for rule in required_rules:
            if rule not in final_lines:
                final_lines.append(rule)
                changed = True

        if not gitignore.exists():
            gitignore.write_text("\n".join(required_rules) + "\n", encoding="utf-8")
            log(f"[CREATED] {gitignore.relative_to(ROOT)}")
        elif changed:
            gitignore.write_text("\n".join(final_lines).rstrip() + "\n", encoding="utf-8")
            log(f"[UPDATED] {gitignore.relative_to(ROOT)}")
        else:
            log(f"[SKIP] {gitignore.relative_to(ROOT)} 已包含所需规则")
    except Exception as e:
        log(f"[ERROR] 写入 .gitignore 失败: {gitignore} | {e}")


def init_security() -> None:
    log("\n=== Step 4/5: 防漏网与隐私初始化 ===")
    write_secrets_template()
    write_gitignore()


def print_final_hint() -> None:
    log("\n=== Step 5/5: 完成状态 ===")
    log("[DONE] 重构执行完成。请检查以上日志确认每个核心资产的迁移结果。")
    log("[TIP] 若需二次复核，可重新运行脚本；它具备存在即跳过与冲突改名保护。")


def main() -> int:
    log("\n===== Reconstruct Project: Quantamental 2.0 =====")
    log(f"[ROOT] {ROOT}")

    try:
        ensure_dirs()
        execute_precise_migration()
        cleanup_junk()
        init_security()
        print_final_hint()
        return 0
    except KeyboardInterrupt:
        log("\n[INTERRUPTED] 用户主动中断。")
        return 130
    except Exception as e:
        log(f"\n[FATAL] 未捕获异常: {e}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
