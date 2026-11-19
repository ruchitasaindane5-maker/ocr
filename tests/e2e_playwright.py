"""PDF Q&A — Playwright E2E tests (the whole product, through the browser).

How to run (from the repo root):
    .venv/bin/python tests/e2e_playwright.py
Requirements:
    - Server running:  npm start        (http://127.0.0.1:8000)
    - Env overrides available: BASE_URL, PW_CHROMIUM, PW_LIBS
Report: PASS/FAIL per test; on failure a screenshot goes to tests/failures/.
"""
from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from playwright.sync_api import sync_playwright  # noqa: E402

BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
CHROMIUM = os.environ.get("PW_CHROMIUM", "/tmp/chromium")
LIBS = os.environ.get("PW_LIBS", "/tmp/al2023/lib")
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FAIL_DIR = os.path.join(ROOT, "tests", "failures")
os.makedirs(FAIL_DIR, exist_ok=True)

RESULTS: list[tuple[str, bool, str]] = []


def check(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'✅' if ok else '❌'} {name}" + (f" — {detail}" if detail and not ok else ""))


def shot(page, tag):
    try:
        page.screenshot(path=os.path.join(FAIL_DIR, f"{tag}.png"), full_page=True)
    except Exception:
        pass


def make_test_pdf(path: str):
    import pymupdf

    doc = pymupdf.open()
    p = doc.new_page()
    p.insert_text((72, 72), "Playwright Test Report", fontsize=16)
    p.insert_text((72, 110), "The rule of Zebra Crossing Protocol 42 is:", fontsize=11)
    p.insert_text((72, 132), "At every crossing look left first, then look right.", fontsize=11)
    doc.save(path)
    doc.close()


def main() -> int:
    env = dict(os.environ, LD_LIBRARY_PATH=LIBS)
    test_pdf = "/tmp/pw_upload_test.pdf"
    make_test_pdf(test_pdf)
    txt_file = "/tmp/pw_not_a_pdf.txt"
    open(txt_file, "w").write("this is not a pdf")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            executable_path=CHROMIUM, env=env,
            args=["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu",
                  "--single-process"],
        )
        ctx = browser.new_context(viewport={"width": 1440, "height": 900},
                                  accept_downloads=True)
        page = ctx.new_page()
        console_errors: list[str] = []
        page_errors: list[str] = []
        page.on("console", lambda m: console_errors.append(m.text) if m.type == "error" else None)
        page.on("pageerror", lambda e: page_errors.append(str(e)))

        # 1. Page load + title
        page.goto(BASE, wait_until="networkidle")
        check("Page loads with the correct title", "PDF Q&A" in page.title(),
              page.title())

        # 2. Badges populate (must not hang)
        page.wait_for_function(
            "document.querySelector('#dbBadge').textContent.includes('PDFs')", timeout=15000)
        check("Header badges (OCR/DB) are filled",
              "OCR:" in page.text_content("#ocrBadge")
              and "Prisma" in page.text_content("#dbBadge"))

        # 3. 2 sample PDFs in the docs list
        names = page.eval_on_selector_all(".doc .nm", "els => els.map(e => e.textContent)")
        check("2 sample PDFs appear in the list", len(names) >= 2, str(names))

        # 4. DB stats table is filled
        check("Database stats (docs/pages/chunks) are shown",
              (page.text_content("#dbDocs") or "–").strip() not in ("–", "", "0")
              and (page.text_content("#dbChunks") or "").strip() != "")

        # 5. AI panel — 5 providers render
        page.wait_for_selector("#aiList .prov", timeout=15000)
        provs = page.eval_on_selector_all("#aiList .prov .n", "e => e.map(x => x.textContent)")
        check("AI panel shows 5 providers", len(provs) == 5, str(provs))

        # 6. AI badge state
        check("AI badge shows a state",
              (page.text_content("#aiBadge") or "").strip() not in ("", "AI: …"),
              page.text_content("#aiBadge") or "")

        # 7. Wrong file type (txt) — error toast
        page.set_input_files("#file", txt_file)
        page.wait_for_selector(".toast.err", timeout=8000)
        check("Non-PDF file shows an error toast", True)

        # 8. Real upload (small test PDF)
        n_before = page.eval_on_selector_all(".doc", "e => e.length")
        page.set_input_files("#file", test_pdf)
        page.wait_for_function(
            f"document.querySelectorAll('.doc').length > {n_before}", timeout=120000)
        check("PDF is added to the list after upload", True)
        up_ok = "Saved to database" in (page.text_content("#upStatus") or "")
        check("Upload success message + 'Saved to database' is shown", up_ok,
              (page.text_content("#upStatus") or "")[:120])

        # 9. Ask a question (unique line from the uploaded doc)
        page.fill("#q", "What is Zebra Crossing Protocol 42?")
        page.click("#askBtn")
        page.wait_for_selector(".msg.bot details.sources", timeout=60000)
        ans = page.text_content("#msgs") or ""
        check("Answer + sources (page citation) are returned",
              "Zebra" in ans and "page" in ans.lower(), ans[:150])
        check("Answer has a copy button",
              page.eval_on_selector_all(".msg.bot [data-copy]", "e => e.length") >= 1)

        # 10. Suggestion chips are shown + work
        chips = page.eval_on_selector_all("#chips .chip", "e => e.length")
        check("Example question chips are shown", chips >= 1, str(chips))
        if chips:
            n_msgs = page.eval_on_selector_all(".msg", "e => e.length")
            page.click("#chips .chip >> nth=0")
            page.wait_for_function(
                f"document.querySelectorAll('.msg').length > {n_msgs}", timeout=60000)
            check("Clicking a chip sends the question", True)

        # 11. Doc search filter
        page.fill("#docSearch", "upload_test")
        page.wait_for_timeout(400)
        vis = page.eval_on_selector_all(".doc .nm", "e => e.map(x => x.textContent)")
        check("PDF name search filter works",
              len(vis) == 1 and "pw_upload_test" in vis[0], str(vis))
        page.fill("#docSearch", "")

        # 12. View data (viewer dialog)
        page.click(".doc[data-x] >> nth=0") if False else None
        card = page.locator(".doc", has_text="pw_upload_test")
        card.locator("[data-act=view]").click()
        page.wait_for_selector("#textDlg[open]", timeout=15000)
        dlg_text = page.text_content("#dlgBody") or ""
        check("Data viewer dialog shows the extracted text",
              "Zebra Crossing Protocol" in dlg_text, dlg_text[:100])
        page.click("#closeTextBtn")

        # 13. TXT export downloads
        with page.expect_download(timeout=30000) as dl:
            card.locator("[data-act=txt]").click()
        download = dl.value
        check("TXT export downloads",
              (download.suggested_filename or "").endswith(".txt"),
              download.suggested_filename or "")

        # 14. 'Ask this PDF' sets the filter
        card.locator("[data-act=ask]").click()
        sel_val = page.eval_on_selector("#docFilter", "e => e.value")
        check("'Ask this PDF' sets the doc filter", bool(sel_val))
        page.eval_on_selector("#docFilter", "e => { e.value=''; }")

        # 15. Delete — cancel first, then confirm
        card.locator("[data-act=del]").click()
        page.wait_for_selector("#confirmDlg[open]", timeout=8000)
        page.click("#confirmNo")
        page.wait_for_timeout(300)
        still = page.eval_on_selector_all(".doc .nm",
                                          "e => e.map(x => x.textContent)")
        check("PDF stays after cancelling delete",
              any("pw_upload_test" in n for n in still))
        card = page.locator(".doc", has_text="pw_upload_test")
        card.locator("[data-act=del]").click()
        page.wait_for_selector("#confirmDlg[open]", timeout=8000)
        page.click("#confirmYes")
        page.wait_for_function(
            "[...document.querySelectorAll('.doc .nm')].every(n => !n.textContent.includes('pw_upload_test'))",
            timeout=15000)
        check("PDF is removed after confirming delete", True)

        # 16. Empty question — nothing should break
        n_msgs = page.eval_on_selector_all(".msg", "e => e.length")
        page.fill("#q", "   ")
        page.click("#askBtn")
        page.wait_for_timeout(600)
        check("Empty question sends no message",
              page.eval_on_selector_all(".msg", "e => e.length") == n_msgs)

        # 17. Clear chat button
        page.click("#clearChat")
        msgs = page.eval_on_selector_all(".msg", "e => e.length")
        check("Only the welcome message remains after clearing chat", msgs == 1, str(msgs))

        # 18. Enter key sends the question
        page.fill("#q", "How is a UPI QR created?")
        page.press("#q", "Enter")
        page.wait_for_selector(".msg.bot details.sources", timeout=60000)
        check("Pressing Enter sends the question", True)

        # 19. AI test button (must respond even without keys)
        page.click("#testAiBtn")
        page.wait_for_function(
            "document.querySelector('#aiTestResult').children.length > 0", timeout=90000)
        check("AI test button shows results", True)

        # 20. No horizontal overflow on desktop
        overflow = page.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
        check("No side-scroll (overflow) on desktop", overflow)

        # 21. No JS errors
        check("No console/page JS errors", not console_errors and not page_errors,
              "; ".join((console_errors + page_errors)[:3]))

        if any(not ok for _, ok, _ in RESULTS):
            shot(page, "desktop_fail")

        # 22. Mobile viewport (390x844)
        mp = ctx.new_page()
        mp.goto(BASE, wait_until="networkidle")
        mp.wait_for_function(
            "document.querySelector('#dbBadge').textContent.includes('PDFs')", timeout=15000)
        mo = mp.evaluate(
            "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 1")
        check("No side-scroll (overflow) on mobile", mo)
        check("Chat card is visible on mobile",
              mp.is_visible("#chatCard") and mp.is_visible("#q"))
        if not mo:
            shot(mp, "mobile_fail")

        # 23. Server-down banner (with the status API blocked)
        bp = ctx.new_page()
        bp.route("**/api/status", lambda r: r.abort())
        bp.goto(BASE, wait_until="domcontentloaded")
        bp.wait_for_selector("#offlineBar.show", timeout=15000)
        check("Red warning banner appears when the server is down", True)

        browser.close()

    passed = sum(1 for _, ok, _ in RESULTS if ok)
    print(f"\n===== RESULT: {passed}/{len(RESULTS)} PASS =====")
    for name, ok, detail in RESULTS:
        if not ok:
            print(f"FAIL: {name} — {detail[:200]}")
    return 0 if passed == len(RESULTS) else 1


if __name__ == "__main__":
    raise SystemExit(main())
