"""Verify the interview workflow in the browser and optionally record the walkthrough."""
import argparse
import csv
import io
import json
import re
import time
from pathlib import Path

from playwright.sync_api import expect, sync_playwright


CUES = (
    (0, 8, "Flagged invoice", "The duplicate copy shows a total of USD 115. Subtotal plus tax is USD 110."),
    (8, 22, "Compare the two sources", "The supplier and invoice number agree. The total is the difference to review."),
    (22, 38, "Correct the working record", "Enter USD 110 from the matching original. Validation clears the arithmetic flag."),
    (38, 53, "Choose the canonical invoice", "Keep the original supplier file and document why the other copy is excluded."),
    (53, 68, "Approve and export", "Approve the canonical invoice. The CSV batch contains one invoice."),
    (68, 80, "Re-download the stored CSV", "The same batch downloads again with identical bytes. No second export is ready."),
    (80, 90, "Extraction evaluation", "26 of 28 synthetic holdout documents matched exactly. This run had one incorrect acceptance and one abstention."),
)


def timestamp(seconds):
    return f"00:{seconds // 60:02d}:{seconds % 60:02d},000"


def verify(page, base, samples, output, record, holdout):
    names = ["01-original-invoice.pdf", "02-conflicting-copy.pdf"]
    document_ids = []
    for name in names:
        payload = {"name": name, "mimeType": "application/pdf", "buffer": (samples / name).read_bytes()}
        upload = page.request.post(base + "/api/documents", multipart={"files": payload})
        assert upload.ok, upload.text()
        document_ids.append(upload.json()["files"][0]["id"])
    errors = []
    page.on("pageerror", lambda error: errors.append(str(error)))
    page.goto(base)
    for document_id in document_ids:
        endpoint = base + "/api/documents/" + document_id
        deadline = time.monotonic() + 60
        while time.monotonic() < deadline:
            document = page.request.get(endpoint).json()
            if document["status"] in ("completed", "failed"):
                break
            page.wait_for_timeout(250)
        assert document["status"] == "completed", document

    def file(name):
        page.get_by_role("button", name=name, exact=True).click()

    def button(label):
        return page.get_by_role("button", name=label, exact=True)

    def highlight(target):
        target.evaluate("""element => {
            document.querySelectorAll('[data-walk-highlight]').forEach(old => {
                old.style.outline = ''; old.style.outlineOffset = ''; delete old.dataset.walkHighlight;
            });
            element.dataset.walkHighlight = 'true';
            element.style.outline = '3px solid #247156'; element.style.outlineOffset = '3px';
        }""")
        target.evaluate("el => el.scrollIntoView({block: 'nearest'})")

    def cue(index, target=None):
        if not record:
            return
        if target is not None:
            highlight(target)
        _, _, title, text = CUES[index]
        page.evaluate("""([title, text]) => {
            let card = document.querySelector('#walk-caption');
            if (!card) {
                card = document.createElement('div');
                card.id = 'walk-caption';
                card.style.cssText = 'position:fixed;z-index:9999;bottom:0;left:0;right:0;padding:20px 44px;background:#142d25;color:#fff;font:24px/1.35 system-ui;pointer-events:none;box-shadow:0 -3px 14px #142d2530';
                document.body.append(card);
            }
            const heading = document.createElement('strong');
            heading.textContent = title; heading.style.color = '#b7e7c9';
            const line = document.createElement('div'); line.textContent = text;
            card.replaceChildren(heading, line);
        }""", [title, text])

    def wait_until(end):
        if record:
            page.wait_for_timeout(max(0, (start + end - time.monotonic()) * 1000))

    file(names[1])
    flag = button("Subtotal plus tax differs from total.")
    expect(flag).to_be_visible()
    expect(page.get_by_role("img", name="Original document, page 1")).to_be_visible()
    if record:
        page.evaluate("document.body.style.zoom = '1.23'")
    cue(0, flag)
    start = time.monotonic()
    wait_until(8)

    cue(1, button("Reconcile"))
    button("Reconcile").click()
    page.get_by_label("Comparison document").select_option(label=names[0])
    comparison = page.get_by_label("Comparison invoice")
    candidate = comparison.locator("option").filter(has_text="CG-1001")
    expect(candidate).to_have_count(1)
    comparison.select_option(value=candidate.get_attribute("value"))
    button("Compare").click()
    mismatch = page.get_by_role("row").filter(has=page.get_by_role("cell", name="Total", exact=True))
    expect(mismatch).to_contain_text("different")
    if record:
        highlight(mismatch)
    wait_until(22)

    button("Close").click()
    cue(2, flag)
    flag.click()
    total = page.get_by_role("textbox", name="Total", exact=True)
    expect(total).to_be_focused()
    expect(page.get_by_role("region", name="Guided exception review")).to_contain_text("Total: 115")
    if record:
        highlight(total)
        page.wait_for_timeout(2700)
    total.fill("110")
    button("Save correction").click()
    receipt = page.get_by_role("region", name="Correction result")
    expect(receipt).to_contain_text("115 → 110")
    if record:
        highlight(receipt)
    wait_until(38)

    cue(3, button("Resolve duplicates"))
    button("Resolve duplicates").click()
    page.get_by_role("radio", name=re.compile(re.escape(names[0]))).check()
    page.get_by_role("textbox", name="Decision reason").fill("Original supplier invoice supports USD 110.")
    if record:
        highlight(page.get_by_role("group", name="Choose the invoice to keep"))
        page.wait_for_timeout(2600)
    button("Save duplicate decision").click()
    expect(page.get_by_role("heading", name="Excluded from export")).to_be_visible()
    page.get_by_role("navigation").get_by_role("button", name="Documents").click()
    file(names[0])
    wait_until(53)

    cue(4, button("Approve invoice"))
    button("Approve invoice").click()
    expect(page.get_by_text("Approved and ready for CSV export.")).to_be_visible()
    page.get_by_role("navigation").get_by_role("button", name="Exports").click()
    expect(page.get_by_role("heading", name="Ready to export (1)", exact=True)).to_be_visible()
    if record:
        highlight(button("Create CSV export"))
        page.wait_for_timeout(2400)
    button("Create CSV export").click()
    expect(page.get_by_text("Export created with 1 invoice.")).to_be_visible()
    link = page.get_by_role("link", name="Download CSV", exact=True)
    with page.expect_download() as first:
        link.click()
    content = first.value.path().read_bytes()
    rows = list(csv.DictReader(io.StringIO(content.decode("utf-8"))))
    assert [(row["invoice_number"], row["total"]) for row in rows] == [("CG-1001", "110")], rows
    assert names[0] in rows[0]["source_reference"]
    wait_until(68)

    cue(5, link)
    with page.expect_download() as second:
        link.click()
    assert second.value.path().read_bytes() == content
    expect(button("Create CSV export")).to_be_disabled()
    assert page.request.get(base + link.get_attribute("href")).body() == content
    wait_until(80)

    if record:
        assert holdout["exact"] == 26 and holdout["documents"] == 28, holdout
        cue(6)
        page.evaluate("""() => {
            const summary = document.createElement('section');
            summary.className = 'panel export-panel';
            const title = document.createElement('h2');
            title.textContent = 'Extraction evaluation';
            const score = document.createElement('p');
            score.style.cssText = 'font-size:48px;font-weight:700;margin:12px 0;color:#225943';
            score.textContent = '26 / 28 exact documents';
            const details = document.createElement('p');
            details.textContent = 'Frozen synthetic holdout · 1 incorrect acceptance · 1 abstention';
            summary.append(title, score, details);
            document.querySelector('main').replaceChildren(summary);
            window.scrollTo(0, 0);
        }""")
    wait_until(90)
    assert not errors, errors
    if output:
        (output / "verified-export.csv").write_bytes(content)
        (output / "Al_Faridul_Karim_Interview_Walkthrough.srt").write_text(
            "\n\n".join(f"{i}\n{timestamp(begin)} --> {timestamp(end)}\n{title}\n{text}"
                         for i, (begin, end, title, text) in enumerate(CUES, 1)) + "\n",
            encoding="utf-8",
        )
    print("Browser verified both invoices, one canonical export row, and identical redownload bytes.")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--url", default="http://127.0.0.1:8134")
    parser.add_argument("--samples", type=Path, required=True)
    parser.add_argument("--record", type=Path)
    parser.add_argument("--holdout", type=Path)
    parser.add_argument("--browser-executable")
    args = parser.parse_args()
    if args.record and not args.holdout:
        parser.error("--record requires a fresh --holdout result")
    report = json.loads(args.holdout.read_text(encoding="utf-8"))["summary"] if args.holdout else {}
    if args.record:
        args.record.mkdir(parents=True, exist_ok=True)
    viewport = {"width": 1920, "height": 1080}
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path=args.browser_executable)
        recording = {"record_video_dir": str(args.record), "record_video_size": viewport} if args.record else {}
        context = browser.new_context(viewport=viewport, reduced_motion="reduce", **recording)
        page = context.new_page()
        try:
            verify(page, args.url.rstrip("/"), args.samples, args.record, bool(args.record), report)
        finally:
            context.close()
            if page.video:
                page.video.save_as(str(args.record / "capture.webm"))
            browser.close()


if __name__ == "__main__":
    main()
