import re
import os
from playwright.sync_api import sync_playwright

def capture_pdf():
    output_dir = "exam_pages"
    os.makedirs(output_dir, exist_ok=True)

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        page = browser.new_page()

        # 全屏模式 (2K屏幕)
        page.set_viewport_size({"width": 2560, "height": 1440})
        page.evaluate("window.moveTo(0, 0); window.resizeTo(screen.width, screen.height);")

        print("打开首页...")
        page.goto("https://etd.xjtlu.edu.cn/index.html#/index")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(500)

        # 登录
        try:
            print("查找登录表单...")
            page.wait_for_selector("input[type='password']", timeout=1000)
            import os as _os
            page.fill("input[type='password']", _os.environ.get("XJTLU_PASSWORD", ""))

            inputs = page.query_selector_all("input")
            for inp in inputs:
                inp_type = inp.get_attribute("type")
                if inp_type == "text":
                    inp.fill(_os.environ.get("XJTLU_USERNAME", ""))
                    break

            print("点击 Sign in 按钮...")
            page.click("button:has-text('Sign in')")
            page.wait_for_timeout(500)

            print("点击 Log in 按钮...")
            page.click("button:has-text('Login'), button:has-text('Log in'), button[type='submit']")
            print("已提交登录，等待跳转...")
            page.wait_for_timeout(1000)
        except Exception as e:
            print(f"登录过程: {e}")

        page.wait_for_timeout(1000)

        try:
            # 点击 Past Exam Papers
            print("点击 Past Exam Papers...")
            page.click("text=Past Exam Papers")

            # 等待新标签页打开
            print("等待新标签页...")
            page.wait_for_timeout(1000)

            # 切换到新打开的标签页
            context = browser.contexts[0]
            if len(context.pages) > 1:
                page = context.pages[-1]
                print(f"已切换到新标签页: {page.url}")
                # 新标签页强制全屏
                page.set_viewport_size({"width": 2560, "height": 1440})
                page.evaluate("window.moveTo(0, 0); window.resizeTo(screen.width, screen.height);")

            # 等待新页面加载
            print("等待新页面加载...")
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(1000)

            # 使用 evaluate 查找 Agree 按钮
            print("查找 Agree 按钮...")
            page.evaluate("""() => {
                const allElements = document.querySelectorAll('*');
                for (const el of allElements) {
                    if (el.childNodes.length === 1 && el.textContent.trim() === 'Agree') {
                        el.click();
                        break;
                    }
                }
            }""")
            page.wait_for_timeout(1000)

            # 查找搜索框并输入 EEE112
            print("查找搜索框...")
            inputs = page.query_selector_all("input")
            for inp in inputs:
                inp_type = inp.get_attribute("type")
                if inp_type and inp_type not in ["hidden", "submit", "button"]:
                    inp.fill("EEE112")
                    print(f"已输入 EEE112")
                    break

            page.keyboard.press("Enter")
            print("已按 Enter 键")
            page.wait_for_timeout(3000)

            # 点击第一个试卷链接
            print("点击第一个试卷...")
            page.click("a[href*='PaperDetail']")
            page.wait_for_timeout(1000)

            # 点击 View Online 按钮
            print("点击 View Online 按钮...")
            page.click("text=View Online")
            page.wait_for_timeout(3000)

            # 切换到 View Online 打开的新标签页（PDF viewer）
            context = browser.contexts[0]
            if len(context.pages) > 1:
                page = context.pages[-1]
                print(f"已切换到 PDF viewer 标签页: {page.url}")
                # PDF viewer 标签页强制全屏
                page.set_viewport_size({"width": 2560, "height": 1440})
                page.evaluate("window.moveTo(0, 0); window.resizeTo(screen.width, screen.height);")
            else:
                print("未发现新标签页")

            page.wait_for_timeout(3000)

            # 设置 PDF viewer 为 Fit Page 缩放
            print("点击缩放按钮...")
            page.click("body", position={"x": 1269, "y": 11})  # 缩放按钮位置
            page.wait_for_timeout(500)

            # 按两下方向键选择 Fit Page
            print("选择 Fit Page...")
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(300)
            page.keyboard.press("ArrowDown")
            page.wait_for_timeout(300)

            # 按回车确认
            page.keyboard.press("Enter")
            page.wait_for_timeout(1000)

            # 刷新页面
            print("刷新页面...")
            page.reload()
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(3000)

            # 读取 PDF 总页数
            total_pages = 50  # 默认值
            try:
                # 方法1：从 pageNumber 输入框的 max 属性获取
                page_number_input = page.query_selector("#pageNumber")
                if page_number_input:
                    max_attr = page_number_input.get_attribute("max")
                    if max_attr:
                        total_pages = int(max_attr)
                        print(f"检测到 PDF 共 {total_pages} 页 (from max attribute)")
                # 方法2：从 numPages 文本获取
                if total_pages == 50:
                    num_pages = page.query_selector("#numPages")
                    if num_pages:
                        text = num_pages.text_content()
                        print(f"numPages 文本: {text}")
                        match = re.search(r'of\s*(\d+)', text)
                        if match:
                            total_pages = int(match.group(1))
                            print(f"检测到 PDF 共 {total_pages} 页 (from text)")
            except Exception as e:
                print(f"读取页数异常: {e}")

            # 循环翻页截图
            print("开始截图 PDF...")
            page_num = 1
            page.screenshot(path=f"{output_dir}/pdf_page_{page_num:03d}.png", clip={"x": 630, "y": 0, "width": 800, "height": 1440})
            print(f"已截图第 {page_num}/{total_pages} 页")

            while page_num < total_pages:
                page.keyboard.press("ArrowRight")
                page.wait_for_timeout(1500)
                page_num += 1

                page.evaluate("document.body.offsetHeight")
                page.screenshot(path=f"{output_dir}/pdf_page_{page_num:03d}.png", clip={"x": 630, "y": 0, "width": 800, "height": 1440})
                print(f"已截图第 {page_num}/{total_pages} 页")

            print(f"完成，共截取 {page_num} 页")

        except Exception as e:
            print(f"流程异常: {e}")

        print("完成")

capture_pdf()