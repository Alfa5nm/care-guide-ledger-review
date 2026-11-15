"""Generate fictional documents with known invoice values."""
import argparse
import csv
import io
import json
from pathlib import Path

import fitz
import openpyxl
from PIL import Image, ImageDraw, ImageFilter, ImageFont

FIELDS = ("invoice_number", "invoice_date", "supplier_name", "customer_name", "subtotal", "tax", "total", "currency")
HEADERS = ["Invoice Number", "Invoice Date", "Supplier Name", "Customer Name", "Subtotal", "Tax", "Total",
           "Currency", "Description", "Quantity", "Unit Price", "Line Amount"]


def sample(number, product="Shipping fee", supplier="Harbor Supply", **overrides):
    invoice = {
        "invoice_number": number, "invoice_date": "2026-11-06", "supplier_name": supplier,
        "customer_name": "Maple Studio", "subtotal": "100", "tax": "10", "total": "110",
        "currency": "USD",
        "line_items": [{"description": product, "quantity": "2", "unit_price": "50", "amount": "100"}],
    }
    return invoice | overrides


def lines(data, include_items=True):
    labels = ["Invoice number", "Invoice date", "Supplier", "Customer", "Subtotal", "Tax", "Total", "Currency"]
    output = [f"{label}: {data[field]}" for label, field in zip(labels, FIELDS) if data[field] is not None]
    if include_items and data["line_items"]:
        output.append("Description | Quantity | Unit Price | Amount")
        for item in data["line_items"]:
            output.append(" | ".join(item.values()))
    return output


def draw_pdf_page(document, values):
    page = document.new_page()
    for index, line in enumerate(values):
        page.insert_text((54, 72 + index * 20), line, fontsize=13)
    return page


def pdf(path, invoices, split=False):
    with fitz.open() as document:
        for data in invoices:
            content = lines(data)
            if split:
                draw_pdf_page(document, content[:4])
                draw_pdf_page(document, content[4:])
            else:
                draw_pdf_page(document, content)
        document.save(path, deflate=True)


def raster(data, poor=False):
    size = (1100, 730)
    image = Image.new("L", size, 217 if poor else 255)
    candidates = ["/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "DejaVuSansMono.ttf", "consola.ttf"]
    font = None
    for candidate in candidates:
        try:
            font = ImageFont.truetype(candidate, 29)
            break
        except OSError:
            continue
    if font is None:
        font = ImageFont.load_default(size=29)
    draw = ImageDraw.Draw(image)
    for index, line in enumerate(lines(data)):
        draw.text((56, 54 + index * 46), line, font=font, fill=115 if poor else 10)
    return image.filter(ImageFilter.GaussianBlur(1.1)) if poor else image


def table_row(data):
    return [data[key] for key in FIELDS] + list(data["line_items"][0].values())


def make(directory, legacy=False):
    directory.mkdir(parents=True, exist_ok=True)
    digital = sample("CG-1001")
    different = sample("CG-1001", total="115")
    scan = sample("CG-2001", "Office paper", "Meridian Office")
    poor = sample("CG-2002", "Courier delivery", "North Dock")
    png = sample("CG-2003", "Laptop", "Cedar Hardware")
    first = sample("CG-2004", "Consulting", "Maple Advisory")
    second = sample("CG-2005", "Software subscription", "Fable Works")
    split = sample("CG-3001", "Equipment repair", "Arbor Repairs")
    partial = sample("CG-4001", "Catering", "Willow Foods", customer_name=None, currency=None)
    csv_invoice = sample("CG-5001", "Laptop", "Cedar Hardware")
    legacy_invoice = sample("CG-6001", "Notebooks", "Meridian Office")

    pdf(directory / "01-original-invoice.pdf", [digital])
    pdf(directory / "02-conflicting-copy.pdf", [different])
    with fitz.open() as document:
        page = document.new_page(width=550, height=365)
        image_path = directory / "_scan.png"
        raster(scan).save(image_path)
        page.insert_image(page.rect, filename=image_path)
        document.save(directory / "03-scanned-invoice.pdf", deflate=True)
        image_path.unlink()
    raster(poor, poor=True).save(directory / "04-low-contrast.jpg", quality=52)
    raster(png).save(directory / "05-invoice-image.png")
    raster(first).save(directory / "06-multi-frame.tiff", save_all=True, append_images=[raster(second)], compression="tiff_deflate")
    pdf(directory / "07-two-page-invoice.pdf", [split], split=True)
    pdf(directory / "08-incomplete-invoice.pdf", [partial])
    with (directory / "09-register.csv").open("w", encoding="utf-8", newline="") as handle:
        csv.writer(handle).writerows([HEADERS, table_row(csv_invoice)])
    workbook = openpyxl.Workbook()
    workbook.active.title = "North branch"
    workbook.active.append(HEADERS)
    workbook.active.append(table_row(different))
    sheet = workbook.create_sheet("South branch")
    sheet.append(HEADERS)
    sheet.append(table_row(csv_invoice))
    workbook.save(directory / "10-billing-workbook.xlsx")
    legacy_path = directory / "11-legacy-ledger.xls"
    if legacy:
        import xlwt
        book = xlwt.Workbook()
        sheet = book.add_sheet("Ledger")
        for r, row in enumerate([HEADERS, table_row(legacy_invoice)]):
            for c, value in enumerate(row):
                sheet.write(r, c, value)
        book.save(str(legacy_path))
    if not legacy_path.exists():
        bundled = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / legacy_path.name
        if bundled.exists():
            legacy_path.write_bytes(bundled.read_bytes())
    (directory / "12-corrupt.pdf").write_bytes(b"%PDF-1.7\nThis document is intentionally corrupt.\n")
    (directory / "13-malformed.csv").write_bytes(b'Invoice Number,Description\nCG-BAD,"unterminated\n')
    evidence = {
        "01-original-invoice.pdf": [digital], "02-conflicting-copy.pdf": [different],
        "03-scanned-invoice.pdf": [scan], "04-low-contrast.jpg": [poor], "05-invoice-image.png": [png],
        "06-multi-frame.tiff": [first, second], "07-two-page-invoice.pdf": [split],
        "08-incomplete-invoice.pdf": [partial], "09-register.csv": [csv_invoice],
        "10-billing-workbook.xlsx": [different, csv_invoice], "12-corrupt.pdf": None, "13-malformed.csv": None,
    }
    if legacy_path.exists():
        evidence[legacy_path.name] = [legacy_invoice]
    (directory / "labels.json").write_text(json.dumps(evidence, indent=2) + "\n")
    return evidence


def benchmark(directory, pages, scanned_every=0):
    directory.mkdir(parents=True, exist_ok=True)
    kind = "mixed" if scanned_every else "digital"
    path = directory / f"benchmark-{pages}-{kind}-pages.pdf"
    with fitz.open() as document:
        for index in range(pages):
            record = sample(f"BENCH-{index+1:04d}")
            if scanned_every and (index + 1) % scanned_every == 0:
                page = document.new_page(width=550, height=365)
                image = io.BytesIO()
                raster(record).save(image, format="PNG")
                page.insert_image(page.rect, stream=image.getvalue())
            else:
                draw_pdf_page(document, lines(record))
        document.save(path, deflate=True)
    return path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=Path("artifacts/samples"))
    parser.add_argument("--benchmark", type=int, default=0)
    parser.add_argument("--generate-legacy", action="store_true")
    args = parser.parse_args()
    make(args.out, args.generate_legacy)
    if args.benchmark:
        print(benchmark(args.out, args.benchmark))
