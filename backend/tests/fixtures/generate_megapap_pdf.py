"""Regenerate the anonymized audited-layout fixture using reportlab and a Greek TTF."""
import argparse
from pathlib import Path

from reportlab.lib import colors
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas
from reportlab.platypus import Table, TableStyle


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--font", required=True)
    args = parser.parse_args()
    pdfmetrics.registerFont(TTFont("FixtureGreek", args.font))
    path = Path(__file__).with_name("megapap_order.pdf")
    document = canvas.Canvas(str(path), pagesize=(595, 842), invariant=1)
    document.setAuthor("Anonymized acceptance fixture")
    document.setTitle("MEGAPAP audited field structure - test data only")
    document.setFont("FixtureGreek", 11)
    document.drawString(35, 800, "MEGAPAP - B2B")
    document.drawString(35, 775, "Αριθμός παραγγελίας: TEST-ORDER-1")
    document.drawString(35, 750, "Ημερομηνία καταχώρησης: 02/10/2026")
    rows = [["", "Όνομα προϊόντος", "Κωδικός", "Τιμή", "SKU", "Σύνολο"],
            ["", "1 x Test product", "0212605", "8,73€", "GP041-0025,4", "8,73€"],
            ["Μερικό Σύνολο:", "", "", "", "", "8,73€"],
            ["Παραλαβή από πρακτορείο Αθήνας", "", "", "", "", "4,90€"],
            ["ΦΠΑ 24%:", "", "", "", "", "2,10€"],
            ["Γενικό Σύνολο:", "", "", "", "", "15,73€"]]
    table = Table(rows, colWidths=[15, 150, 65, 65, 150, 65], rowHeights=30)
    commands = [("FONTNAME", (0, 0), (-1, -1), "FixtureGreek"), ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black)]
    commands.extend(("SPAN", (0, row), (4, row)) for row in range(2, 6))
    table.setStyle(TableStyle(commands))
    table.wrapOn(document, 510, 400)
    table.drawOn(document, 35, 500)
    document.showPage()
    document.save()
    print(path)


if __name__ == "__main__":
    main()
