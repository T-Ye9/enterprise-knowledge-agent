"""生成公开虚构的 Web 上传验收 PDF，无真实企业信息。"""
from pathlib import Path
import argparse
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont

parser = argparse.ArgumentParser()
parser.add_argument("--output", type=Path, default=Path(__file__).with_name("web-demo-policy.pdf"))
parser.add_argument("--project", default="Project Cedar")
args = parser.parse_args()
path = args.output
path.parent.mkdir(parents=True, exist_ok=True)
pdf = canvas.Canvas(str(path))
pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
pdf.setFont("STSong-Light", 12)
pdf.setTitle("Fictional Project Cedar Policy")
for line_number, line in enumerate([
    "公开虚构测试制度，不包含真实企业信息。",
    f"{args.project} 健康补贴：每位员工每月 731 元。",
    "员工需在次月 5 日前向人力资源部门提交发票作为补贴材料。",
    "第 1 页 / 共 1 页。",
]):
    pdf.drawString(45, 780 - 28 * line_number, line)
pdf.save()
print("Created public fixture:", path.name)
