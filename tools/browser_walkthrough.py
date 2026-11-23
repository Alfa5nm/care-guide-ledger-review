"""Exercise the live React application and capture walkthrough frames."""
import argparse
import os
import re
from pathlib import Path
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


def verify(page, base, samples, frames, record=False, prefix=""):
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    count = 0

    def chapter(title, subtitle):
        nonlocal count
        count += 1
        if frames is None and not record:
            return
        page.evaluate("""([title, subtitle]) => {
            document.getElementById('qa-caption')?.remove();
            const caption = document.createElement('div');
            caption.id = 'qa-caption';
            caption.style.cssText = 'position:fixed;z-index:9999;left:0;bottom:0;right:0;min-height:64px;padding:10px 24px;background:#162d27;color:#fff;font:15px system-ui;box-shadow:0 -3px 8px #0003';
            const heading = document.createElement('strong');
            heading.textContent = title;
            const line = document.createElement('div');
            line.textContent = subtitle;
            line.style.color = '#d8e9dc';
            caption.append(heading, line);
            (document.querySelector('dialog[open]') || document.body).append(caption);
        }""", [title, subtitle])
        if frames:
            page.screenshot(path=frames / f"{count:02d}.png")
        if record:
            page.wait_for_timeout(4300)
        page.evaluate("document.getElementById('qa-caption').remove()")

    page.goto(base)
    expect(page.get_by_role("heading", name="Documents", exact=True)).to_be_visible()
    page.get_by_role("button", name="Collapse sidebar").click()
    expect(page.get_by_role("button", name="Expand sidebar")).to_have_attribute("aria-expanded", "false")
    if record:
        chapter("Collapsible workspace", "Fold the sidebar into an icon rail to make more room for reviewing files.")
    page.get_by_role("button", name="Expand sidebar").click()
    chapter("Ledger Review", "Upload multiple financial documents in one batch.")
    names = ["01-original-invoice.pdf", "02-conflicting-copy.pdf", "03-scanned-invoice.pdf",
             "10-billing-workbook.xlsx", "12-corrupt.pdf"]
    page.locator('input[type="file"]').set_input_files([
        {"name": prefix + name, "mimeType": "application/octet-stream", "buffer": (samples / name).read_bytes()}
        for name in names
    ])
    expect(page.get_by_role("status")).to_contain_text("5 queued")
    chapter("Batch upload", "The API queues each file independently and the worker reports progress.")
    bad = page.get_by_role("row").filter(has_text=prefix + "12-corrupt.pdf")
    expect(bad).to_contain_text("failed", timeout=60_000)
    expect(page.get_by_role("row").filter(has_text=prefix + "03-scanned-invoice.pdf")).to_contain_text("completed", timeout=60_000)
    chapter("Processing completed", "The scan was read by OCR. The broken PDF failed without stopping the other files.")

    page.get_by_role("button", name=prefix + "03-scanned-invoice.pdf", exact=True).click()
    expect(page.get_by_role("heading", name="CG-2001")).to_be_visible()
    expect(page.get_by_text("Office paper")).to_be_visible()
    source = page.get_by_role("region", name="Source preview")
    expect(source.get_by_role("img", name="Original document, page 1")).to_be_visible()
    source.get_by_role("button", name="Collapse media preview").click()
    expect(source.get_by_role("img")).to_have_count(0)
    source.get_by_role("button", name="Source preview").click()
    expect(source.get_by_role("img", name="Original document, page 1")).to_be_visible()
    page.wait_for_function("document.querySelector('.source-canvas img')?.naturalWidth > 0")
    source.get_by_role("button", name="Zoom").click()
    expect(source.get_by_role("button", name="Fit")).to_have_attribute("aria-pressed", "true")
    source.get_by_role("button", name="Fit").click()
    source.get_by_role("button", name="Expand").click()
    viewer = page.get_by_role("dialog", name="Expanded source viewer")
    expect(viewer).to_be_visible()
    expect(viewer.get_by_role("region", name="Extracted invoice fields")).to_contain_text("Meridian Office")
    with page.expect_response(lambda response: "rotation=90" in response.url and response.ok):
        viewer.get_by_role("button", name="Rotate").click()
    expect(viewer.get_by_role("img", name="Original document, page 1")).to_be_visible()
    if record:
        chapter("Expanded source viewer", "Rotate the scan and inspect the original page beside extracted fields and evidence quotes.")
    page.keyboard.press("Escape")
    expect(viewer).to_have_count(0)
    expect(source.get_by_role("button", name="Expand")).to_be_focused()
    page.get_by_role("button", name="Source & text").click()
    expect(page.get_by_role("heading", name="Extracted text")).to_be_visible()
    expect(page.locator("pre")).to_contain_text("Meridian Office")
    page.get_by_role("button", name="Invoice review").click()
    chapter("OCR and source evidence", "Inspect the invoice fields and line items extracted from a scanned PDF.")
    page.get_by_role("button", name="Documents", exact=True).last.click()
    page.get_by_role("button", name=prefix + "02-conflicting-copy.pdf", exact=True).click()
    expect(page.get_by_text("Subtotal plus tax differs from total.")).to_be_visible()
    chapter("Validation", "This invoice shows an inconsistent total and a duplicate supplier/invoice number.")

    page.get_by_role("button", name="Reconcile").click()
    choices = page.get_by_label("Comparison document")
    for alternative, caption in (
        ("01-original-invoice.pdf", "Compare two PDFs. Their invoice number matches, but the totals differ."),
        ("10-billing-workbook.xlsx", "Compare PDF against Excel. The workbook agrees with this copy's recorded total."),
    ):
        choices.select_option(label=prefix + alternative)
        selector = page.get_by_label("Comparison invoice")
        option = selector.locator("option").filter(has_text=re.compile("CG-1001"))
        expect(option).to_have_count(1)
        selector.select_option(value=option.get_attribute("value"))
        page.get_by_role("button", name="Compare", exact=True).click()
        expect(page.get_by_text("Supplier and invoice number match.")).to_be_visible()
        value = "different" if alternative.endswith(".pdf") else "match"
        table = page.get_by_role("table").last
        expect(table.get_by_role("row").filter(has=page.get_by_role("cell", name="Total", exact=True))).to_contain_text(value)
        page.get_by_role("heading", name="Reconcile invoices", exact=True).evaluate("element => element.scrollIntoView({block: 'start'})")
        chapter("Cross-document reconciliation", caption)
    page.get_by_role("button", name="Close", exact=True).click()

    flag = page.get_by_role("button", name="Subtotal plus tax differs from total.")
    flag.focus()
    page.keyboard.press("Enter")
    expect(page.get_by_role("textbox", name="Total", exact=True)).to_be_focused()
    expect(page.get_by_role("region", name="Guided exception review")).to_contain_text("Total: 115")
    chapter("Guided exception review", "Open the flag to see its evidence and focus the field that needs correction.")
    page.get_by_role("textbox", name="Total", exact=True).fill("110")
    page.get_by_role("button", name="Save correction").click()
    expect(page.get_by_role("status")).to_contain_text("Correction saved")
    expect(flag).to_have_count(0)
    receipt = page.get_by_role("region", name="Correction result")
    expect(receipt).to_contain_text("115 → 110")
    expect(receipt).to_contain_text("Cleared flags: Subtotal plus tax differs from total.")
    chapter("Manual correction", "Saving the corrected total reruns arithmetic validation and records the change.")

    page.get_by_role("button", name="Documents", exact=True).last.click()
    page.get_by_role("button", name=prefix + "12-corrupt.pdf", exact=True).click()
    page.get_by_role("button", name="Retry processing").click()
    page.get_by_role("button", name="Processing history", exact=True).click()
    expect(page.get_by_text("retry requested", exact=False)).to_be_visible()
    chapter("Failed-job reprocessing", "The retry creates a new attempt. A permanently corrupt file fails again.")

    page.get_by_role("navigation").get_by_role("button", name="Search").click()
    page.get_by_role("searchbox").fill("freight")
    page.get_by_label("Search mode").select_option("keyword")
    page.get_by_role("main").get_by_role("button", name="Search", exact=True).click()
    expect(page.get_by_text("No documents match this search.")).to_be_visible()
    page.get_by_label("Search mode").select_option("semantic")
    page.get_by_role("main").get_by_role("button", name="Search", exact=True).click()
    expect(page.get_by_role("button", name=prefix + "01-original-invoice.pdf", exact=True)).to_be_visible()
    chapter("Semantic search", 'Searching for "freight" finds invoices whose text says "Shipping fee".')
    assert not errors, errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    parser.add_argument("--samples", type=Path, default=Path("artifacts/samples"))
    parser.add_argument("--frames", type=Path)
    parser.add_argument("--video", type=Path)
    args = parser.parse_args()
    if args.frames:
        args.frames.mkdir(parents=True, exist_ok=True)
    executable = os.getenv("DOCINTEL_BROWSER_EXECUTABLE") or None
    password = os.getenv("DOCINTEL_SMOKE_PASSWORD")
    with sync_playwright() as runner:
        browser = runner.chromium.launch(executable_path=executable,
                                         slow_mo=120 if args.video else 0)
        viewport = {"width": 1280, "height": 900}
        context_options = {"viewport": viewport}
        if password:
            context_options["http_credentials"] = {"username": "reviewer", "password": password, "origin": args.url}
        if args.video:
            context_options.update(record_video_dir=args.video, record_video_size=viewport)
        context = browser.new_context(**context_options)
        page = context.new_page()
        prefix = f"{uuid4().hex[:6]}-" if password else ""
        verify(page, args.url, args.samples, args.frames, bool(args.video), prefix)
        page.set_viewport_size({"width": 390, "height": 844})
        page.get_by_role("navigation").get_by_role("button", name="Documents").click()
        expect(page.get_by_role("heading", name="Documents", exact=True)).to_be_visible()
        assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
        if args.video:
            page.wait_for_timeout(1800)
        if args.frames:
            page.screenshot(path=args.frames.parent / "mobile.png", full_page=True)
        context.close()
        browser.close()
    print("Browser passed: mixed upload, OCR review, validation, PDF/PDF and PDF/XLSX reconciliation, "
          "correction, failed-job retry, keyword/concept search, and mobile viewport.")


if __name__ == "__main__":
    main()
