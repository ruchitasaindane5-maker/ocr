"""Capture real screenshots of the running PDF Q&A app with the installed Chrome.
shots.py <out_dir>   (server must be running on http://localhost:8000)
Never deletes anything: the delete dialog is opened and then cancelled."""
import os, sys, time
from playwright.sync_api import sync_playwright

OUT = sys.argv[1]
os.makedirs(OUT, exist_ok=True)
BASE = "http://localhost:8000"
QUESTION = "What safety precautions does the manual give for cleanliness in the engine room?"


def save(page, name, **kw):
    path = os.path.join(OUT, name)
    page.screenshot(path=path, **kw)
    print("saved", name, flush=True)


with sync_playwright() as pw:
    b = pw.chromium.launch(channel="chrome", headless=True)
    ctx = b.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1.5, color_scheme="dark")
    page = ctx.new_page()
    page.goto(BASE, wait_until="networkidle")
    page.wait_for_function("document.querySelector('#dbBadge').textContent.includes('PDFs')", timeout=20000)
    page.wait_for_selector("#aiList .prov", timeout=20000)
    # background job banner (2-2 manual is processing) — appears after first poll
    try:
        page.wait_for_selector("#upLive b", timeout=10000)
    except Exception:
        pass
    time.sleep(1)
    save(page, "01_home.png")
    # crops below: stop the sticky header from covering the cropped card
    page.add_style_tag(content="header{position:static !important}")
    page.locator("#side section.card").nth(0).screenshot(path=os.path.join(OUT, "02_upload_progress.png")); print("saved", "02_upload_progress.png", flush=True)

    # Database panel
    page.locator("#side section.card").nth(1).screenshot(path=os.path.join(OUT, "03_database_panel.png")); print("saved", "03_database_panel.png", flush=True)

    # AI panel: run the live key test
    page.click("#testAiBtn")
    page.wait_for_function("document.querySelector('#aiTestResult').children.length > 0 && !document.querySelector('#testAiBtn').disabled", timeout=300000)
    card = page.locator("#side section.card").nth(2)
    card.scroll_into_view_if_needed()
    time.sleep(0.5)
    card.screenshot(path=os.path.join(OUT, "04_ai_panel_test.png")); print("saved", "04_ai_panel_test.png", flush=True)

    # PDF list card
    docs = page.locator("#side section.card").nth(3)
    docs.scroll_into_view_if_needed()
    time.sleep(0.3)
    docs.screenshot(path=os.path.join(OUT, "05_pdf_list.png")); print("saved", "05_pdf_list.png", flush=True)

    # Ask a question
    page.evaluate("window.scrollTo(0,0)")
    page.fill("#q", QUESTION)
    page.click("#askBtn")
    time.sleep(1.2)
    page.locator("#chatCard").screenshot(path=os.path.join(OUT, "06_thinking.png")); print("saved", "06_thinking.png", flush=True)
    page.wait_for_selector(".msg.bot .foot", timeout=600000)
    page.locator(".msg.bot details.sources").last.evaluate("d => d.open = true")
    time.sleep(0.6)
    page.evaluate("document.querySelector('#msgs').scrollTop = 0")
    page.add_style_tag(content="header{position:sticky !important}")
    save(page, "07_answer.png")
    page.add_style_tag(content="header{position:static !important}")
    page.locator("#chatCard").screenshot(path=os.path.join(OUT, "08_answer_chat.png")); print("saved", "08_answer_chat.png", flush=True)
    msgs = page.locator("#msgs")
    msgs.evaluate("m => m.scrollTop = m.scrollHeight")
    time.sleep(0.4)
    page.locator("#chatCard").screenshot(path=os.path.join(OUT, "09_sources.png")); print("saved", "09_sources.png", flush=True)

    # View extracted data
    first = page.locator(".doc").first
    first.locator("[data-act=view]").click()
    page.wait_for_selector("#textDlg[open]", timeout=60000)
    time.sleep(0.8)
    save(page, "10_view_data.png")
    page.click("#closeTextBtn")

    # Delete confirmation — then CANCEL
    first.locator("[data-act=del]").click()
    page.wait_for_selector("#confirmDlg[open]", timeout=10000)
    time.sleep(0.4)
    save(page, "11_delete_confirm.png")
    page.click("#confirmNo")
    time.sleep(0.3)
    assert page.locator(".doc").count() >= 1, "doc unexpectedly missing"

    # Mobile
    m = b.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=2, color_scheme="dark", is_mobile=True)
    mp = m.new_page()
    mp.goto(BASE, wait_until="networkidle")
    mp.wait_for_function("document.querySelector('#dbBadge').textContent.includes('PDFs')", timeout=20000)
    time.sleep(1.5)
    save(mp, "12_mobile.png")
    b.close()

    with open(os.path.join(OUT, "answer.txt"), "w", encoding="utf-8") as f:
        f.write(QUESTION + "\n---\n")
print("done")
