"""
批量提取某课程下所有年份的期末/补考试卷。

用法:
  python batch_capture.py EEE112
  python batch_capture.py ACC309 --scale 1.5
  python batch_capture.py MTH101 --headless
"""

import os
import sys
import re
import argparse

# 修复 Windows GBK 终端编码问题
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass
from dataclasses import dataclass, field
from typing import Optional
from playwright.sync_api import sync_playwright

from capture_canvas import (
    VIEWPORT,
    login,
    navigate_to_past_exam_papers,
    agree_and_search,
    collect_search_results,
    parse_exam_metadata,
    parse_metadata_from_text,
    extract_canvas_pages,
    has_next_page,
    go_to_next_page,
)


@dataclass
class PaperLink:
    href: str
    text: str
    index: int
    page_num: int


@dataclass
class ExtractionResult:
    paper: PaperLink
    folder_name: str
    output_dir: str
    page_count: int
    success: bool
    error: Optional[str] = None


# ═══════════════════════════════════════════════════════════════
# 主流程
# ═══════════════════════════════════════════════════════════════

def batch_capture(course_code: str, scale: float = 2.0, headless: bool = False):
    """批量提取 course_code 下所有试卷"""

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context()
        context.set_default_timeout(30000)

        # ═══════════════════ Phase 1: 登录 & 搜索 ═══════════════════
        index_page = context.new_page()
        index_page.set_viewport_size(VIEWPORT)
        login(index_page)

        exam_tab = navigate_to_past_exam_papers(index_page)
        agree_and_search(exam_tab, course_code)

        # ═══════════════════ Phase 2: 收集所有论文链接 ═══════════════════
        all_papers, seen_hrefs = [], set()
        page_num = 1

        while True:
            # 滚动到底部确保懒加载内容可见
            exam_tab.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            exam_tab.wait_for_timeout(500)
            exam_tab.evaluate("window.scrollTo(0, 0)")
            exam_tab.wait_for_timeout(500)

            papers = collect_search_results(exam_tab)
            new_count = 0
            for p in papers:
                if p["href"] not in seen_hrefs:
                    seen_hrefs.add(p["href"])
                    all_papers.append(PaperLink(
                        href=p["href"],
                        text=p["text"],
                        index=p["index"],
                        page_num=page_num,
                    ))
                    new_count += 1

            print(f"  搜索页 {page_num}: +{new_count} 篇 (累计 {len(all_papers)})")

            if not has_next_page(exam_tab):
                break
            go_to_next_page(exam_tab)
            page_num += 1

        if not all_papers:
            print(f"未找到 {course_code} 的试卷。")
            return

        print(f"\n共发现 {len(all_papers)} 篇试卷，开始提取...\n")

        # ═══════════════════ Phase 3: 逐篇提取 ═══════════════════
        results: list[ExtractionResult] = []
        failed: list[tuple[PaperLink, str]] = []

        for idx, paper in enumerate(all_papers):
            print(f"{'='*60}")
            print(f"[{idx+1}/{len(all_papers)}] {paper.text[:100]}")
            print(f"      href: {paper.href[:120]}...")

            try:
                result = extract_one_paper(context, exam_tab, paper, scale, course_code)
                results.append(result)
                if result.success:
                    print(f"  ✓ {result.folder_name} ({result.page_count} 页)")
                else:
                    failed.append((paper, result.error or "unknown"))
                    print(f"  ✗ {result.error}")
            except Exception as e:
                failed.append((paper, str(e)))
                print(f"  ✗ 异常: {e}")
                cleanup_extra_tabs(context, keep=[exam_tab, index_page])

        # ═══════════════════ Phase 4: 汇总 ═══════════════════
        print(f"\n{'='*60}")
        print("批量提取完成")
        print(f"  共发现: {len(all_papers)} 篇")
        print(f"  成功: {sum(1 for r in results if r.success)} 篇")
        print(f"  失败: {len(failed)} 篇")
        for paper, err in failed:
            print(f"    - {paper.text[:60]}: {err}")


# ═══════════════════════════════════════════════════════════════
# 单篇提取（在独立标签页中完成）
# ═══════════════════════════════════════════════════════════════

def extract_one_paper(context, exam_tab, paper: PaperLink,
                      scale: float, course_code: str) -> ExtractionResult:
    """
    在新标签页中打开试卷详情页 → 点击 View Online → 提取 Canvas → 关闭标签页。
    exam_tab（搜索结果页）始终保持不动。
    """

    # 1. 在新标签页打开详情页
    detail_page = context.new_page()
    detail_page.set_viewport_size(VIEWPORT)
    detail_page.goto(paper.href)
    detail_page.wait_for_load_state("networkidle")
    detail_page.wait_for_timeout(1000)

    # 2. 点击 View Online
    try:
        detail_page.click("text=View Online", timeout=8000)
        detail_page.wait_for_timeout(3000)
    except Exception:
        detail_page.close()
        return ExtractionResult(
            paper=paper, folder_name="", output_dir="",
            page_count=0, success=False,
            error="未找到 View Online 按钮",
        )

    # 3. 切换到 PDF viewer 标签页
    all_pages = context.pages
    pdf_viewer = all_pages[-1]
    if pdf_viewer == detail_page:
        # View Online 未在新标签页打开，尝试在当前页查找 PDF viewer
        pdf_viewer.wait_for_timeout(3000)
        has_viewer = pdf_viewer.evaluate("() => !!window.PDFViewerApplication")
        if not has_viewer:
            detail_page.close()
            return ExtractionResult(
                paper=paper, folder_name="", output_dir="",
                page_count=0, success=False,
                error="PDF viewer 未打开",
            )

    pdf_viewer.set_viewport_size(VIEWPORT)
    pdf_viewer.wait_for_timeout(3000)

    # 4. 解析元数据（多级降级）
    code, year, exam_type = parse_exam_metadata(pdf_viewer)

    if code == "UNKNOWN" or year == "unknown":
        code2, year2, type2 = parse_metadata_from_text(paper.text)
        if code == "UNKNOWN":
            code = code2
        if year == "unknown":
            year = year2
        if exam_type == "F" and type2 != "F":
            exam_type = type2

    # 最后兜底
    if code == "UNKNOWN":
        code = course_code
    if year == "unknown":
        year = f"idx{paper.page_num:02d}_{paper.index:02d}"

    folder_name = f"{code}_{year}_{exam_type}"
    output_dir = os.path.join("exam_pages", folder_name)

    # 去重：已存在则跳过
    if os.path.exists(output_dir) and os.listdir(output_dir):
        n = len(os.listdir(output_dir))
        print(f"  ⏭ 已存在 {n} 个文件，跳过")
        pdf_viewer.close()
        detail_page.close()
        return ExtractionResult(
            paper=paper, folder_name=folder_name,
            output_dir=output_dir, page_count=n, success=True,
        )

    print(f"  {code}  {year}  {'补考' if exam_type == 'R' else '期末'} → {output_dir}/")

    # 5. Canvas 提取
    try:
        page_count = extract_canvas_pages(pdf_viewer, output_dir, scale)
    except Exception as e:
        page_count = 0
        pdf_viewer.close()
        detail_page.close()
        return ExtractionResult(
            paper=paper, folder_name=folder_name,
            output_dir=output_dir, page_count=0, success=False,
            error=f"提取异常: {e}",
        )

    # 6. 清理标签页
    pdf_viewer.close()
    detail_page.close()

    return ExtractionResult(
        paper=paper, folder_name=folder_name,
        output_dir=output_dir, page_count=page_count,
        success=(page_count > 0),
    )


# ═══════════════════════════════════════════════════════════════
# 工具函数
# ═══════════════════════════════════════════════════════════════

def cleanup_extra_tabs(context, keep: list):
    """关闭除 keep 列表外的所有标签页"""
    kept_ids = {id(p) for p in keep}
    for p in context.pages:
        if id(p) not in kept_ids:
            try:
                p.close()
            except Exception:
                pass


# ═══════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="批量提取某课程历年所有试卷"
    )
    parser.add_argument("course_code", nargs="?", default=None,
                        help="课程代码，如 EEE112（不填则交互询问）")
    parser.add_argument("--scale", type=float, default=2.0,
                        help="Canvas 缩放倍数 (默认 2.0)")
    parser.add_argument("--headless", action="store_true",
                        help="无头模式运行")
    args = parser.parse_args()

    course_code = args.course_code
    if not course_code:
        course_code = input("请输入课程代码: ").strip()
        if not course_code:
            print("未输入课程代码，退出。")
            sys.exit(0)

    batch_capture(course_code, scale=args.scale, headless=args.headless)
