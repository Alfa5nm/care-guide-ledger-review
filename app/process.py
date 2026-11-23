import csv
import io
import subprocess
import zipfile
from dataclasses import dataclass
from pathlib import Path

import fitz
import openpyxl
import xlrd
from PIL import Image, ImageOps, ImageSequence

SUFFIXES = {".pdf", ".jpg", ".jpeg", ".png", ".tif", ".tiff", ".xlsx", ".xls", ".csv"}
MAX_UNITS = 2000
MAX_TEXT = 8_000_000
MAX_ROWS = 50_000
MAX_COLS = 150
Image.MAX_IMAGE_PIXELS = 25_000_000


class DocumentError(Exception):
    pass


@dataclass
class Section:
    source: str
    text: str
    rows: list | None = None


def ocr(image, min_width=1300):
    if image.width * image.height > Image.MAX_IMAGE_PIXELS:
        raise DocumentError("Image exceeds the pixel limit.")
    image = ImageOps.autocontrast(ImageOps.grayscale(ImageOps.exif_transpose(image)))
    if image.width < min_width:
        scale = min(2, min_width / image.width)
        size = (round(image.width * scale), round(image.height * scale))
        if size[0] * size[1] <= Image.MAX_IMAGE_PIXELS:
            image = image.resize(size, Image.Resampling.LANCZOS)
    stream = io.BytesIO()
    image.save(stream, format="PNG")
    try:
        result = subprocess.run(
            ["tesseract", "stdin", "stdout", "--psm", "6"],
            input=stream.getvalue(), capture_output=True, timeout=45, check=True,
        )
    except FileNotFoundError:
        raise DocumentError("Tesseract is missing. See the setup instructions.") from None
    except subprocess.TimeoutExpired:
        raise DocumentError("OCR timed out on this page.") from None
    except subprocess.CalledProcessError:
        raise DocumentError("OCR could not read this page.") from None
    return result.stdout.decode("utf-8", errors="replace").strip()


def row_value(value):
    if value is None:
        return ""
    if hasattr(value, "date"):
        return value.date().isoformat()
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def read_pdf_page(page, warnings, source):
    text = page.get_text(sort=True).strip()
    zoom = min(2.5, (12_000_000 / max(1, page.rect.get_area())) ** 0.5)
    matrix = fitz.Matrix(zoom, zoom)

    def read_region(region):
        bitmap = page.get_pixmap(matrix=matrix, clip=region, colorspace=fitz.csGRAY)
        return ocr(Image.frombytes("L", (bitmap.width, bitmap.height), bitmap.samples))

    if not text:
        return read_region(page.rect)

    blocks = [
        (fitz.Rect(block[:4]) * page.rotation_matrix, block[4].strip())
        for block in page.get_text("blocks")
        if block[6] == 0 and block[4].strip()
    ]
    seen_lines = {" ".join(line.casefold().split()) for line in text.splitlines()}
    recovered = []
    seen_regions = set()
    for image in page.get_image_info():
        region = (fitz.Rect(image["bbox"]) * page.rotation_matrix) & page.rect
        bounds = tuple(round(value, 1) for value in region)
        if region.width < 36 or region.height < 12 or bounds in seen_regions:
            continue
        seen_regions.add(bounds)
        try:
            region_text = read_region(region)
        except DocumentError as error:
            warnings.append(f"{source}: image region {bounds}: {error}")
            continue
        lines = [
            line for line in region_text.splitlines()
            if line.strip() and " ".join(line.casefold().split()) not in seen_lines
        ]
        if lines:
            recovered.append((region, "\n".join(lines)))

    if not recovered:
        return text
    return "\n".join(
        content for _, content in sorted(
            blocks + recovered, key=lambda item: (item[0].y0, item[0].x0)
        )
    )


def source_preview(path, suffix, index, rotation=0):
    """Render a bounded still image from a PDF page or an image frame."""
    if suffix == ".pdf":
        with fitz.open(path, filetype="pdf") as document:
            if document.needs_pass:
                raise DocumentError("Password-protected PDFs are unsupported.")
            if index >= len(document):
                raise IndexError(index)
            page = document[index]
            longest = max(page.rect.width, page.rect.height)
            zoom = min(2, 1600 / max(1, longest))
            matrix = fitz.Matrix(zoom, zoom).prerotate(rotation)
            bitmap = page.get_pixmap(matrix=matrix, colorspace=fitz.csRGB)
            return bitmap.tobytes("png"), len(document)

    with Image.open(path) as document:
        count = getattr(document, "n_frames", 1)
        if index >= count:
            raise IndexError(index)
        document.seek(index)
        if document.width * document.height > Image.MAX_IMAGE_PIXELS:
            raise DocumentError("Image exceeds the pixel limit.")
        frame = ImageOps.exif_transpose(document)
        frame.thumbnail((1600, 1600))
        if rotation:
            frame = frame.rotate(-rotation, expand=True)
        output = io.BytesIO()
        frame.convert("RGB").save(output, format="PNG")
        return output.getvalue(), count


def table_section(name, rows, budget):
    table = []
    lines = []
    for row in rows:
        budget[0] -= 1
        if budget[0] < 0 or len(row) > MAX_COLS:
            raise DocumentError("Spreadsheet exceeds the row or column limit.")
        if not any(value is not None and value != "" for value in row):
            continue
        values = [row_value(value) for value in row]
        line = " | ".join(values)
        budget[1] -= len(line)
        if budget[1] < 0:
            raise DocumentError("Spreadsheet exceeds the extracted text limit.")
        table.append(values)
        lines.append(line)
    return Section(name, "\n".join(lines), table)


def spreadsheet(path, suffix):
    budget = [MAX_ROWS, MAX_TEXT]
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            sample = handle.read(4096)
            handle.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
            except csv.Error:
                dialect = "excel"
            yield table_section("CSV", csv.reader(handle, dialect, strict=True), budget)
    elif suffix == ".xlsx":
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if len(entries) > 3000 or sum(item.file_size for item in entries) > 96 * 1024 * 1024:
                raise DocumentError("XLSX archive exceeds the expanded size limit.")
        workbook = openpyxl.load_workbook(path, read_only=True, data_only=True)
        try:
            for sheet in workbook:
                if (sheet.max_column or 0) > MAX_COLS:
                    raise DocumentError("Spreadsheet exceeds the column limit.")
                yield table_section(f"Sheet {sheet.title}", sheet.values, budget)
        finally:
            workbook.close()
    else:
        workbook = xlrd.open_workbook(path, on_demand=True)
        try:
            for sheet in workbook.sheets():
                def values():
                    for index in range(sheet.nrows):
                        yield [
                            xlrd.xldate_as_datetime(cell.value, workbook.datemode)
                            if cell.ctype == xlrd.XL_CELL_DATE else cell.value
                            for cell in sheet.row(index)
                        ]
                yield table_section(f"Sheet {sheet.name}", values(), budget)
        finally:
            workbook.release_resources()


def extract(path: Path, suffix, progress):
    sections = []
    warnings = []
    size = 0

    def add(source, get_text):
        nonlocal size
        try:
            content = get_text()
        except DocumentError as error:
            warnings.append(f"{source}: {error}")
            content = ""
        size += len(content)
        if size > MAX_TEXT:
            raise DocumentError("Document exceeds the extracted text limit.")
        if not content.strip() and not any(warning.startswith(f"{source}:") for warning in warnings):
            warnings.append(f"{source}: no readable text.")
        sections.append(Section(source, content))

    try:
        if suffix == ".pdf":
            with fitz.open(path, filetype="pdf") as document:
                if document.needs_pass:
                    raise DocumentError("Password-protected PDFs are unsupported.")
                if not 0 < len(document) <= MAX_UNITS:
                    raise DocumentError("PDF page count is outside the supported range.")
                for n, page in enumerate(document, 1):
                    source = f"Page {n}"
                    add(source, lambda: read_pdf_page(page, warnings, source))
                    progress(5 + n * 55 // len(document), f"Reading page {n} of {len(document)}")
        elif suffix in {".xlsx", ".xls", ".csv"}:
            for index, section in enumerate(spreadsheet(path, suffix), 1):
                if index > 100:
                    raise DocumentError("Workbook exceeds the sheet limit.")
                sections.append(section)
                if not section.text:
                    warnings.append(f"{section.source}: no populated cells.")
                progress(min(60, 12 + index * 2), f"Reading {section.source}")
        else:
            with Image.open(path) as document:
                total = getattr(document, "n_frames", 1)
                if total > MAX_UNITS:
                    raise DocumentError("Image exceeds the frame limit.")
                for index, frame in enumerate(ImageSequence.Iterator(document), 1):
                    add(f"Image {index}", lambda: ocr(frame, min_width=1500))
                    progress(5 + index * 55 // total, f"Reading image {index} of {total}")
    except DocumentError:
        raise
    except Exception as error:
        raise DocumentError("The file is corrupt, unsupported, or cannot be decoded.") from error
    if not any(section.text.strip() for section in sections):
        raise DocumentError(warnings[0] if warnings else "No readable text or spreadsheet data was found.")
    return sections, warnings
