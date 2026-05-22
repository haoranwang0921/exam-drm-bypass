# 在线试卷系统 DRM 绕过与批量提取工具

网络攻防实训。针对在线试卷系统的 PDF.js 阅读器，分析其多层前端 DRM 防护机制，设计 Canvas 层提取方案完成绕过，实现批量自动化提取。

## 项目结构

```
exam-drm-bypass/
├── capture_canvas.py      # 核心库：可复用函数 + 单篇提取入口
├── batch_capture.py       # 批量提取主脚本（支持交互询问）
├── merge_png_to_pdf.py    # PNG 合成 PDF 工具
├── capture.py             # 原始截图方案（已弃用，仅作参考）
└── exam_pages/            # 产出目录
    ├── EEE112_2022-23_F/  # 课程代码_学年_类型 (F=期末 R=补考)
    ├── EEE112_2022-23_R/
    └── ...
```

## 靶场分析

### 目标系统

在线考试试卷查看器，基于 Mozilla PDF.js 构建。URL 经安全代理（/sf-webproxy/）转发，页面含用户 ID 水印。

### 防护层级（共五层）

| 层级 | 技术手段 | 防护意图 | 代码位置 |
|------|---------|---------|---------|
| **输入层** | `keydown` 捕获 Ctrl+S/Ctrl+P + `stopImmediatePropagation` | 阻止快捷键保存/打印 | `<head>` 内联脚本 |
| **输入层** | `contextmenu` 事件 `preventDefault` | 禁用右键菜单 | `<head>` 内联脚本 |
| **渲染层** | CSS `!important` 隐藏下载/打印按钮 | 阻止 UI 操作入口 | `<style>` 标签 |
| **渲染层** | `@media print { * { display:none } }` | 打印时全屏遮罩 | `<style>` 标签 |
| **事件层** | `beforeprint`/`afterprint` 动态隐藏 DOM | 打印前替换内容为警告文字 | `<head>` 内联脚本 |
| **API层** | 重写 `window.print`、`PDFViewerApplication.download` | 阻止程序化调用 | JS 运行时覆盖 |
| **网络层** | 劫持 `XMLHttpRequest.prototype` | 拦截 PDF 请求 4xx/5xx，统一弹窗假报错 | `DOMContentLoaded` 内 |

### 防护评估

- **有效**: 对普通用户的心理威慑、防止 Ctrl+P 误操作
- **无效**: 对所有防护层均存在已知绕过手段，且存在——Canvas 这层**根本性无法防护**，因为内容已被浏览器解码渲染到 `<canvas>` 元素，`canvas.toDataURL()` 是浏览器原生 API，页面 JS 无权也无法阻止。

结论：前端 DRM 属于「安全剧场」（Security Theater），其理论局限在于——内容一旦在终端解密渲染，控制权即转移至用户。

## 攻击路径设计

### 主路径: Canvas 层直接提取（成功率 ~100%）

PDF.js 将每页渲染到 `.page[data-page-number="N"] canvas` 元素。Canvas API 是浏览器原生接口，不受页面 JS 层任何防护代码影响。水印位于 DOM 层（`.textLayer`），Canvas 内为纯净页面图像。

```
信息收集 → 定位 canvas 元素
触发渲染 → PDFViewerApplication.page = N
数据提取 → canvas.toDataURL('image/png')
持久化   → base64 解码 → PNG → 合并为 PDF
```

没有任何防护代码触及 Canvas API——该路径从根源上绕过了所有五层防护。

### 备用路径: Network 面板取 PDF 二进制（成功率 ~80%）

DevTools Network 面板记录初始 PDF 请求，直接 Save as。前提：DevTools 在页面加载前已打开。

### 不可靠路径

- 恢复 `display:none` 按钮：按钮已被 `cloneNode` 替换，事件监听已丢失
- 仅解除快捷键拦截：后续还有 DOM + API 层等待
- 删除 `@media print` 样式：`beforeprint` 事件监听同样会拦截

## 使用方式

### 环境

```bash
pip install playwright Pillow
playwright install chromium
```

### 批量提取

```bash
# 命令行传入课程代码
python batch_capture.py EEE112

# 交互询问
python batch_capture.py
# → 请输入课程代码: EEE112

# 可选参数
python batch_capture.py EEE112 --scale 1.5   # 低分辨率提速
python batch_capture.py EEE112 --headless     # 无头模式
```

### 单篇提取

```bash
python capture_canvas.py        # 默认 2x 缩放，搜索 EEE112
python capture_canvas.py 1.5    # 1.5x 缩放
```

### 合并 PNG 为 PDF

```bash
python merge_png_to_pdf.py                      # 自动选最新目录
python merge_png_to_pdf.py exam_pages/EEE112_2022-23_F
```

## 工作流程

```
┌──────────┐   ┌──────────┐   ┌──────────┐   ┌──────────┐
│  登录    │ → │ 导航搜索  │ → │ 收集链接  │ → │ 逐篇提取  │
│ XJTLU   │   │ 课程代码  │   │ 处理分页  │   │ 新标签页  │
│ Portal   │   │ Search   │   │ href去重  │   │ Canvas   │
└──────────┘   └──────────┘   └──────────┘   └──────────┘
                                                  ↓
                                             元数据解析
                                             (textLayer)
                                                  ↓
                                             PNG → PDF
                                                  ↓
                                         exam_pages/{CODE}_{YEAR}_{TYPE}/
```

### 标签页管理策略

每次提取在独立新标签页中进行，搜索结果页全程不受干扰：

1. `context.new_page()` → 打开试卷详情页
2. 点击 "View Online" → PDF viewer 在新标签页打开
3. Canvas 提取完成 → 关闭两个标签页
4. 回到搜索结果页，继续下一篇

### 元数据解析降级链

```
主路径: PDF textLayer 文字 → 正则提取 CODE/YEAR/TYPE
  ↓ 失败
降级1: 搜索结果文字解析
  ↓ 失败
降级2: 课程代码 + 索引编号
```

## 产出示例

提取 4 门课程、28 套试卷：

| 课程 | 学年 | 类型 | 页数 |
|------|------|------|------|
| EEE112 | 2022-25 | 三年全 | 49 |
| CAN102 | 2022-25 | 三年全 | 71 |
| EEE109 | 2022-25 | 三年全 | 42 |
| MTH102 | 2022-25 | 三年全 | 54 |

每套试卷含原始 PNG 分页 + 合并 PDF。

## 关键代码

### Canvas 提取核心（capture_canvas.py）

```python
def extract_canvas_pages(page, output_dir, scale=2.0):
    for i in range(1, total + 1):
        result = page.evaluate("""async ({pageNum, scale}) => {
            app.pdfViewer.currentScale = scale;
            app.page = pageNum;                          // 触发渲染
            // ... 轮询等待 canvas 就绪 ...
            return canvas.toDataURL('image/png', 1.0);  // 提取
        }""", {"pageNum": i, "scale": scale})
        # Python 端 base64 解码 → 写 PNG
```

### 搜索结果批量收集（batch_capture.py）

```python
# 保持搜索结果页不动，每个论文在新标签页中提取
for paper in all_papers:
    detail_page = context.new_page()       # 新标签页
    detail_page.goto(paper.href)           # 打开详情
    detail_page.click("text=View Online")  # 打开 PDF
    pdf_viewer = context.pages[-1]         # 切换到 PDF 标签页
    page_count = extract_canvas_pages(pdf_viewer, output_dir, scale)
    pdf_viewer.close()                     # 清理
    detail_page.close()
```

## 许可证

本工具为网络攻防课程实训作品，仅供教育目的。请遵守目标系统的使用条款。
