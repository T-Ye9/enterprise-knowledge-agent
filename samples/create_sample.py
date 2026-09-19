"""生成完全虚构的公开 PDF 测试样本，生产解析无需执行此脚本。"""

from pathlib import Path

from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.pdfgen import canvas


def main():
    destination = Path(__file__).with_name("demo-company-policy.pdf")
    pdfmetrics.registerFont(UnicodeCIDFont("STSong-Light"))
    pdf = canvas.Canvas(str(destination), pagesize=(595, 842))
    pdf.setTitle("Fictional Company Policy")
    pdf.setAuthor("Enterprise Knowledge Agent Demo")
    sections = [
        ("虚构企业制度：工作与休假", [
            "此文件仅用于测试，不包含真实企业信息。",
            "工作时间：周一至周五，上午九点至下午六点。",
            "休假申请：请提前三个工作日向主管提交申请。",
        ]),
        ("虚构企业制度：差旅报销", [
            "差旅需要事先获得主管批准。",
            "报销规则：员工需提交发票及费用说明。",
            "报销期限：返回后十个工作日内提交。",
        ]),
    ]
    for number, (heading, lines) in enumerate(sections, start=1):
        pdf.setFont("STSong-Light", 20)
        pdf.drawString(60, 760, heading)
        pdf.setFont("STSong-Light", 12)
        for index, line in enumerate(lines):
            pdf.drawString(60, 710 - index * 30, line)
        pdf.drawString(60, 60, f"第 {number} 页 / 共 2 页")
        pdf.showPage()
    pdf.save()
    print("Created synthetic PDF:", destination.name)


if __name__ == "__main__":
    main()
