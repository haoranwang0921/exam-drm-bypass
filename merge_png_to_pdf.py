import os
import glob
import sys
from PIL import Image


def merge_png_to_pdf(input_dir=None, output_file=None):
    """
    将 PNG 合并为单个 PDF。
    用法: python merge_png_to_pdf.py [exam_pages/ACC309_2022-23_F]
    """
    if input_dir is None:
        # 自动寻找最新的子文件夹
        subdirs = sorted(
            [d for d in glob.glob("exam_pages/*") if os.path.isdir(d)],
            key=os.path.getmtime,
            reverse=True,
        )
        if not subdirs:
            # 兼容旧版：直接在 exam_pages 下找
            input_dir = "exam_pages"
        else:
            input_dir = subdirs[0]
            print(f"自动选择最新目录: {input_dir}/")

    files = sorted(
        glob.glob(os.path.join(input_dir, "pdf_page_*.png")),
        key=lambda x: int(os.path.splitext(os.path.basename(x))[0].split("_")[-1]),
    )

    if not files:
        print(f"未在 {input_dir}/ 下找到 pdf_page_*.png 文件")
        return None

    if output_file is None:
        folder_name = os.path.basename(input_dir.rstrip("/\\"))
        output_file = os.path.join(input_dir, f"{folder_name}.pdf")

    images = []
    try:
        for f in files:
            with Image.open(f) as source:
                img = source.convert("RGB")
            images.append(img)
            print(f"  {os.path.basename(f)} ({img.width}×{img.height})")

        images[0].save(output_file, save_all=True, append_images=images[1:])
    finally:
        for image in images:
            image.close()

    print(f"\n已合并 → {output_file}（共 {len(images)} 页）")
    return output_file


def merge_missing_pdf(input_dir):
    """为已有的 PNG 页面目录生成同名 PDF；已有 PDF 时保持不变。"""
    folder_name = os.path.basename(os.path.normpath(input_dir))
    output_file = os.path.join(input_dir, f"{folder_name}.pdf")
    if os.path.isfile(output_file):
        return output_file
    return merge_png_to_pdf(input_dir=input_dir, output_file=output_file)


if __name__ == "__main__":
    merge_png_to_pdf(
        input_dir=sys.argv[1] if len(sys.argv) > 1 else None,
        output_file=sys.argv[2] if len(sys.argv) > 2 else None,
    )
