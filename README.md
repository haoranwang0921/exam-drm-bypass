# XJTLU Past Exam Papers 批量整理工具

登录学校试卷库后，按课程代码查找试卷，将可在线查看的页面保存为 PNG，并在每套试卷目录中自动合并为 PDF。登录必须由用户在 Chrome 中手动完成；程序不会代填账号密码。

仅用于你有权访问和保存的试卷。请遵守学校网站的使用条款，不要公开分享下载内容或浏览器登录资料。

## 快速开始（Windows）

需要 Python 3.10+、Google Chrome，以及能够访问学校试卷库的网络。以下命令在 PowerShell 中运行。

```powershell
git clone https://github.com/haoranwang0921/exam-drm-bypass.git
cd exam-drm-bypass
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install playwright Pillow python-dotenv rapidocr onnxruntime
```

如果已经有项目目录和 `.venv`，直接在项目目录运行后面的命令即可，不需要重复克隆或安装。

### 1. 手动登录

```powershell
.\.venv\Scripts\python.exe login.py
```

程序会打开专用 Chrome。请在窗口中手动登录学校网站，等待终端显示“登录完成”。**不要关闭这个 Chrome 窗口**；后续抓取会复用同一登录会话。无需配置 `.env` 中的用户名或密码，脚本不会使用它们自动登录。

### 2. 抓取课程试卷

```powershell
.\.venv\Scripts\python.exe batch_capture.py CAN209
```

将 `CAN209` 换成实际课程代码。例如，学校试卷库中 *Advanced Electrical Circuits and Electromagnetics* 对应 `CAN209`，*Continuous and Discrete Time Signals and Systems* 对应 `CAN207`。请以试卷库搜索结果中的完整标题核对课程，不能仅凭相似名称猜代码。

脚本会列出找到、成功和失败的篇数。抓取结束后，PDF 和分页图片位于 `exam_pages/`：

```text
exam_pages/
  CAN209_2024-25_F/
    CAN209_2024-25_F.pdf
    pdf_page_001.png
    pdf_page_002.png
    ...
  CAN209_2024-25_R/
    CAN209_2024-25_R.pdf
    ...
```

`F` 表示期末，`R` 表示补考。学年优先取自网站搜索结果或详情页；网站缺少信息时才读取 PDF 首页文字或使用本地 OCR。仍无法确认学年时，目录名会包含 `idx`，避免把不确定的信息当成年份。

### 3. 结束使用

```powershell
.\.venv\Scripts\python.exe login.py --status
.\.venv\Scripts\python.exe login.py --close
```

`--status` 只检查常驻浏览器是否还在运行，不验证学校登录是否仍有效。`--close` 会关闭专用 Chrome；下次抓取通常需要重新手动登录。

## 常用操作

| 需求 | 命令 |
| --- | --- |
| 不记得课程代码，运行时输入 | `.\.venv\Scripts\python.exe batch_capture.py` |
| 用较低分辨率加快抓取 | `.\.venv\Scripts\python.exe batch_capture.py CAN209 --scale 1.5` |
| 只抓搜索结果中的第一套（仅保存 PNG） | `.\.venv\Scripts\python.exe capture_canvas.py 2 CAN209` |
| 为现有分页图片手动合并 PDF | `.\.venv\Scripts\python.exe merge_png_to_pdf.py exam_pages\CAN209_2024-25_F` |

批量模式会自动合并 PDF，不需要再运行合并命令。若同名目录已有文件，批量模式会跳过重新抓取，并在缺少 PDF 时尝试补生成。它**不会检查已有 PNG 是否缺页**；若怀疑旧目录不完整，请先核对图片数量和 PDF 页数，再决定是否重新抓取。已存在的文件不会被自动改名。

不先运行 `login.py` 也可以直接启动批量模式，此时程序会自行打开浏览器等待手动登录，并在本次运行结束后关闭浏览器。推荐使用两步法，便于连续抓取多门课程。`--headless` 不适合首次登录。

## 常见问题

**学校网站在开启代理后空白或无法登录**

程序启动的 Chrome 已设置为不使用系统代理，但虚拟网卡（TUN）仍可能接管流量和 DNS。在 FlClash 中可以先保持“系统代理”和“规则”模式开启，仅关闭“虚拟网卡 / TUN”，再重新打开登录窗口。处于校内网络时，可用 `Resolve-DnsName etd.xjtlu.edu.cn` 检查是否得到校内地址；不要把一次查到的 IP 永久写死到配置中。若关闭 TUN 后仍有学校子域名走代理，检查系统代理的绕过列表是否包含 `*.xjtlu.edu.cn`。网络或代理设置由用户自行调整，脚本不会修改它们。

**搜索结果为 0**

搜索框按 **Paper Code** 查找，不是按课程英文标题查找。先核对课程代码，并留意网站当前可搜索的学年范围；旧代码或较早学年的试卷可能不在本次结果中。不要把 0 篇直接当作登录失败。

**目录名出现 `idx`**

网站和 PDF 首页都未提供可确认的学年。该标记表示信息待核对，不代表抓取失败。可打开 PDF 与网站详情页比对；程序不会自动更改已有目录名。

**已有 PNG，但没有 PDF**

对该目录运行上面的 `merge_png_to_pdf.py` 命令，或重新运行同一课程的批量命令。若合并失败，原始 PNG 会保留。

**登录会话失效**

保持专用 Chrome 打开；如果网站要求重新登录，请在窗口中手动完成。关闭专用 Chrome 后可重新运行 `login.py`。不要将浏览器资料目录复制或提交到 Git。

## 工作原理与文件

`login.py` 启动常驻 Chrome；`browser_session.py` 管理浏览器连接。`batch_capture.py` 复用登录会话，按课程代码搜索并逐篇打开详情页。`capture_canvas.py` 从 PDF.js 已渲染的 Canvas 保存页面图片，`merge_png_to_pdf.py` 将图片按页码合并。网站元数据优先用于命名，PDF 首页文字和 OCR 只用于补缺。

`exam_pages/`、`.env`、`.browser_session.json`、浏览器资料目录、虚拟环境和整理出的 `unused_files/` 均不应上传到 GitHub。`capture.py` 是旧版参考实现，不是推荐入口。

## 许可证

代码采用 [MIT License](LICENSE)。此许可证不授予对学校试卷内容的再分发权。
