"""Canvas 提取方案：绕过页面 DRM 防护，直接从 PDF.js 的 <canvas> 元素提取原始图像。

提供两个入口：
  capture_canvas(scale)       — 单篇提取（向后兼容）
  batch_capture.py            — 批量提取该科目所有试卷
"""

import re
import os
import sys
import base64

# 修复 Windows GBK 终端编码问题
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        pass

from playwright.sync_api import sync_playwright

VIEWPORT = {"width": 2560, "height": 1440}
BASE_URL = "https://etd.xjtlu.edu.cn/index.html#/index"


# ═══════════════════════════════════════════════════════════════
# 元数据解析
# ═══════════════════════════════════════════════════════════════

def parse_exam_metadata(page):
    """从 PDF 第一页 textLayer 提取课程代码、年份、考试类型"""
    text = page.evaluate("""() => {
        const layer = document.querySelector('.textLayer');
        return layer ? (layer.textContent || '') : '';
    }""")
    return parse_metadata_from_text(text)


def parse_metadata_from_text(text):
    """从任意文本中提取课程代码、年份、考试类型（降级备用）"""
    code, year, exam_type = "UNKNOWN", "unknown", "F"

    m = re.search(r'\b([A-Z]{3}\d{3})\b', text)
    if m:
        code = m.group(1)

    m = re.search(r'(\d{2,4})\s*/\s*(\d{2})\s*(?:SEMESTER|FINAL|RESIT)', text, re.IGNORECASE)
    if m:
        y1 = m.group(1)
        y2 = m.group(2)
        if len(y1) == 2:
            y1 = "20" + y1
        year = f"{y1}-{y2}"

    if re.search(r'RESIT|RE[- ]?SIT|补考|SUPPLEMENTARY', text, re.IGNORECASE):
        exam_type = "R"
    elif re.search(r'FINAL', text, re.IGNORECASE):
        exam_type = "F"

    return code, year, exam_type


# ═══════════════════════════════════════════════════════════════
# 可复用流程函数
# ═══════════════════════════════════════════════════════════════

def login(page, username=None, password=None):
    """登录 XJTLU 考试系统。凭证优先从参数读取，否则从环境变量 XJTLU_USERNAME / XJTLU_PASSWORD 读取。"""
    if not username:
        username = os.environ.get("XJTLU_USERNAME", "")
    if not password:
        password = os.environ.get("XJTLU_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "未设置登录凭证。请设置环境变量 XJTLU_USERNAME 和 XJTLU_PASSWORD，"
            "或通过 login(page, username, password) 传入。"
        )
    print("打开首页...")
    page.goto(BASE_URL)
    page.wait_for_load_state("networkidle")
    page.wait_for_timeout(500)

    try:
        print("查找登录表单...")
        page.wait_for_selector("input[type='password']", timeout=5000)
        page.fill("input[type='password']", password)

        inputs = page.query_selector_all("input")
        for inp in inputs:
            if inp.get_attribute("type") == "text":
                inp.fill(username)
                break

        print("点击 Sign in 按钮...")
        page.click("button:has-text('Sign in')")
        page.wait_for_timeout(500)

        print("点击 Login 按钮...")
        page.click("button:has-text('Login'), button:has-text('Log in'), button[type='submit']")
        print("已提交登录，等待跳转...")
        page.wait_for_timeout(1000)
    except Exception as e:
        print(f"登录过程: {e}")

    page.wait_for_timeout(1000)


def navigate_to_past_exam_papers(page):
    """点击 Past Exam Papers，返回新标签页。原 page 保留不动。"""
    print("点击 Past Exam Papers...")
    page.click("text=Past Exam Papers")
    page.wait_for_timeout(1000)

    context = page.context
    if len(context.pages) > 1:
        exam_tab = context.pages[-1]
        print(f"已切换到新标签页: {exam_tab.url}")
    else:
        exam_tab = page

    exam_tab.set_viewport_size(VIEWPORT)
    exam_tab.wait_for_load_state("networkidle")
    exam_tab.wait_for_timeout(1000)
    return exam_tab


def agree_and_search(page, course_code):
    """点击 Agree 按钮，输入课程代码并搜索"""
    print("查找 Agree 按钮...")
    page.evaluate("""() => {
        const all = document.querySelectorAll('*');
        for (const el of all) {
            if (el.childNodes.length === 1 && el.textContent.trim() === 'Agree') {
                el.click();
                break;
            }
        }
    }""")
    page.wait_for_timeout(1000)

    print(f"查找搜索框，输入 {course_code}...")
    inputs = page.query_selector_all("input")
    for inp in inputs:
        inp_type = inp.get_attribute("type")
        if inp_type and inp_type not in ["hidden", "submit", "button"]:
            inp.fill(course_code)
            break

    page.keyboard.press("Enter")
    print("已按 Enter，等待搜索结果...")
    try:
        page.wait_for_selector("a[href*='PaperDetail']", timeout=10000)
    except Exception:
        print("未检测到搜索结果（可能无匹配试卷）")
    page.wait_for_timeout(1000)


def detect_total_pages(page):
    """检测 PDF 总页数，三级降级"""
    total = page.evaluate("""() => {
        const app = PDFViewerApplication;
        return app ? app.pagesCount : 0;
    }""")

    if not total:
        total_text = page.evaluate("""() => {
            const el = document.querySelector('#numPages');
            return el ? el.textContent : '';
        }""")
        match = re.search(r'(\d+)', total_text)
        total = int(match.group(1)) if match else 0

    if not total:
        print("无法检测页数，使用默认值 50")
        total = 50

    return total


def preload_pages(page, total):
    """快速遍历每一页触发渲染，再回到第一页"""
    print(f"预加载 {total} 页...")
    for i in range(1, total + 1):
        page.evaluate("(n) => { PDFViewerApplication.page = n; }", i)
        page.wait_for_timeout(200)
    page.evaluate("() => { PDFViewerApplication.page = 1; }")
    page.wait_for_timeout(800)
    print("预加载完成")


def extract_canvas_pages(page, output_dir, scale=2.0):
    """
    逐页提取 Canvas 为 PNG，保存到 output_dir。
    返回成功提取的页数。
    """
    total = detect_total_pages(page)
    preload_pages(page, total)

    os.makedirs(output_dir, exist_ok=True)
    print(f"缩放 {scale}x，开始提取 {total} 页...")

    success = 0
    for i in range(1, total + 1):
        result = page.evaluate(
            """async ({pageNum, scale}) => {
                const app = PDFViewerApplication;
                if (!app) return {ok: false, reason: 'PDFViewerApplication 未初始化'};

                app.pdfViewer.currentScale = scale;
                app.page = pageNum;
                await new Promise(r => setTimeout(r, 600));

                const canvas = await new Promise(resolve => {
                    const deadline = Date.now() + 15000;
                    const check = () => {
                        const el = document.querySelector(
                            '.page[data-page-number="' + pageNum + '"] canvas'
                        );
                        if (el && el.width > 0 && el.height > 0) {
                            resolve(el);
                        } else if (Date.now() < deadline) {
                            setTimeout(check, 200);
                        } else {
                            resolve(null);
                        }
                    };
                    check();
                });

                if (!canvas) return {ok: false, reason: 'canvas 渲染超时'};

                return {
                    ok: true,
                    dataURL: canvas.toDataURL('image/png', 1.0),
                    width: canvas.width,
                    height: canvas.height,
                };
            }""",
            {"pageNum": i, "scale": scale},
        )

        if not result.get("ok"):
            print(f"  第 {i:03d} 页: 失败 ({result.get('reason', 'unknown')})")
            continue

        _, encoded = result["dataURL"].split(",", 1)
        img_data = base64.b64decode(encoded)

        filename = f"pdf_page_{i:03d}.png"
        filepath = os.path.join(output_dir, filename)
        with open(filepath, "wb") as f:
            f.write(img_data)

        success += 1
        print(f"  第 {i:03d} 页 ✓ ({result['width']}×{result['height']}) → {filename}")

    print(f"提取完成，成功 {success}/{total} 页 → {output_dir}/")
    return success


# ═══════════════════════════════════════════════════════════════
# 搜索结果收集（新增）
# ═══════════════════════════════════════════════════════════════

def collect_search_results(page):
    """从当前搜索结果页抓取所有试卷链接"""
    return page.evaluate("""() => {
        const links = document.querySelectorAll("a[href*='PaperDetail']");
        return Array.from(links).map((a, i) => ({
            href: a.href,
            text: (a.textContent || '').trim().substring(0, 300),
            index: i
        }));
    }""")


def has_next_page(page):
    """检测搜索结果是否有下一页"""
    selectors = [
        ".el-pagination button.btn-next:not([disabled])",
        ".el-pager + button:not([disabled])",
        "button:has-text('Next')",
        "a:has-text('Next')",
        "[class*='pagination'] button:last-child:not([disabled])",
        ".el-icon-arrow-right",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_enabled():
                return True
        except Exception:
            pass
    return False


def go_to_next_page(page):
    """点击下一页，等待结果加载。返回是否成功。"""
    selectors = [
        ".el-pagination button.btn-next",
        ".el-pager + button",
        "button:has-text('Next')",
        "a:has-text('Next')",
        "[class*='pagination'] button:last-child",
        ".el-icon-arrow-right",
    ]
    for sel in selectors:
        try:
            el = page.query_selector(sel)
            if el and el.is_enabled():
                url_before = page.url
                el.click()
                page.wait_for_timeout(2000)
                return True
        except Exception:
            pass
    return False


# ═══════════════════════════════════════════════════════════════
# 向后兼容入口
# ═══════════════════════════════════════════════════════════════

def capture_canvas(scale=2.0, course_code=None):
    """单篇提取（兼容旧版调用方式）。course_code 为空则从环境变量 XJTLU_COURSE 读取。"""
    if not course_code:
        course_code = os.environ.get("XJTLU_COURSE", "")
    if not course_code:
        raise RuntimeError("未指定课程代码，请设置环境变量 XJTLU_COURSE 或传入 course_code 参数。")

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()
        page.set_viewport_size(VIEWPORT)

        login(page)
        exam_tab = navigate_to_past_exam_papers(page)
        agree_and_search(exam_tab, course_code)

        # 点击第一篇试卷
        print("点击第一个试卷...")
        exam_tab.click("a[href*='PaperDetail']")
        exam_tab.wait_for_timeout(1000)

        print("点击 View Online 按钮...")
        exam_tab.click("text=View Online")
        exam_tab.wait_for_timeout(3000)

        # 切换到 PDF viewer 标签页
        context = browser.contexts[0]
        if len(context.pages) > 1:
            pdf_viewer = context.pages[-1]
            print(f"已切换到 PDF viewer 标签页: {pdf_viewer.url}")
        else:
            pdf_viewer = exam_tab

        pdf_viewer.set_viewport_size(VIEWPORT)
        pdf_viewer.wait_for_timeout(3000)

        # 元数据 & 输出目录
        print("解析试卷元数据...")
        code, year, exam_type = parse_exam_metadata(pdf_viewer)
        folder_name = f"{code}_{year}_{exam_type}"
        output_dir = os.path.join("exam_pages", folder_name)
        print(f"  课程: {code}  学年: {year}  类型: {'补考' if exam_type == 'R' else '期末'}")
        print(f"  输出目录: {output_dir}/")

        # 提取
        page_count = extract_canvas_pages(pdf_viewer, output_dir, scale)

        if page_count > 1:
            print("提示: 运行 python merge_png_to_pdf.py 可将 PNG 合并为单个 PDF")

        print("完成")


if __name__ == "__main__":
    import sys
    scale = float(sys.argv[1]) if len(sys.argv) > 1 else 2.0
    course_code = sys.argv[2] if len(sys.argv) > 2 else os.environ.get("XJTLU_COURSE", "")
    if not course_code:
        course_code = input("请输入课程代码: ").strip()
    capture_canvas(scale=scale, course_code=course_code)
