"""Exercise the local site on desktop and phone viewports, without external requests."""
from __future__ import annotations
import argparse
from datetime import datetime
from io import BytesIO
import json
import os
import hashlib
import re
from pathlib import Path
import socket
import subprocess
import sys
import time
from uuid import uuid4
import zipfile

import httpx
from PIL import Image, ImageDraw
from pillow_heif import register_heif_opener
from playwright.sync_api import sync_playwright, expect

from check_service import DemoService
ROOT = Path(__file__).resolve().parents[1]
register_heif_opener(thumbnails=False)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--browser-executable", type=Path)
    parser.add_argument("--executable", type=Path, help="Frozen backend to exercise")
    args = parser.parse_args()
    output = ROOT / ".cache/browser-checks" / (datetime.now().strftime("%Y%m%d-%H%M%S") + "-" + uuid4().hex[:6])
    output.mkdir(parents=True)
    service=DemoService(output,args.executable).start()
    base=service.base
    try:
        with sync_playwright() as pw:
            options = {"headless": True}
            if args.browser_executable: options["executable_path"] = str(args.browser_executable.resolve())
            elif Path("C:/Program Files/Google/Chrome/Application/chrome.exe").exists(): options["executable_path"]="C:/Program Files/Google/Chrome/Application/chrome.exe"
            browser = pw.chromium.launch(**options)
            external, errors = [], []
            context = browser.new_context(viewport={"width": 1360, "height": 960}, accept_downloads=True)
            def local_only(route):
                if not route.request.url.startswith(base + "/"):
                    external.append(route.request.url); route.abort()
                else: route.continue_()
            context.route("**/*", local_only)
            page = context.new_page()
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.goto(base+"/#pair="+service.pairing()); expect(page.locator("#connection-label")).to_contain_text("проверка доставки")
            page.screenshot(path=str(output / "desktop.png"), full_page=True)
            page.set_viewport_size({"width": 430, "height": 932})
            page.screenshot(path=str(output / "phone-empty.png"), full_page=True)
            images = []
            for n, color in [(1, "white"), (2, "#f5f9ee")]:
                image = Image.new("RGB", (1200, 1600), color)
                ImageDraw.Draw(image).text((80, 100), f"LOCAL TEST PAGE {n}", fill="black", font_size=60)
                buffer = BytesIO(); image.save(buffer, format="HEIF" if n == 1 else "JPEG", quality=95)
                images.append({"name": f"page-{n}.heic" if n == 1 else f"page-{n}.jpg",
                               "mimeType": "image/heic" if n == 1 else "image/jpeg", "buffer": buffer.getvalue()})
            page.locator("#files-input").set_input_files(images)
            for _ in images: page.locator("#accept-photo").click()
            assert page.locator("#pages .page").count() == 2
            page.get_by_role("button", name="Переместить выше 2", exact=True).click()
            assert "page-2.jpg" in page.locator("#pages .page").first.inner_text()
            page.screenshot(path=str(output / "phone-pages.png"), full_page=True)
            # Lose the first upload acknowledgement after the backend accepted the bytes.
            lost = [False]
            def lose_ack(route):
                if not lost[0]: lost[0] = True; route.fetch(); route.abort()
                else: route.continue_()
            context.route("**/pages/1", lose_ack)
            page.locator("#solve").click(); page.locator("#retry").wait_for(state="visible")
            page.locator("#retry").click(); page.locator("#result").wait_for(state="visible", timeout=30000)
            assert "Проверка доставки" in page.locator("#result-title").inner_text()
            assert page.locator("#answer-cards img").count() > 0
            page.screenshot(path=str(output / "phone-result.png"), full_page=True)
            page.locator("#text-tab").click(); assert "No AI solution" in page.locator("#answer-text").inner_text()
            with page.expect_download() as pending: page.locator("#zip-download").click()
            download = pending.value; target = output / "answer.zip"; download.save_as(target)
            with zipfile.ZipFile(target) as archive:
                manifest = json.loads(archive.read("manifest.json")); identifier = manifest["session_id"]
                assert manifest["demo"] and "No AI solution" in archive.read("answer.txt").decode()
            incoming = output / "sessions" / identifier / "incoming"
            assert hashlib.sha256((incoming / "page_01.jpg").read_bytes()).digest() == hashlib.sha256(images[1]["buffer"]).digest()
            assert (incoming / "page_02.heic").read_bytes() == images[0]["buffer"]
            # The completed task survives a reload with its full answer.
            page.reload(); page.locator("#result").wait_for(state="visible", timeout=30000)
            assert page.locator("#zip-download").get_attribute("href").startswith(f"/v1/sessions/{identifier}/")
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            page.locator("#new-task").click(); page.locator("#empty-state").wait_for(state="visible")
            assert page.locator("#pages .page").count() == 0
            page.locator("#files-input").set_input_files(images[:1]); page.locator("#accept-photo").click()
            # Close/reload the page while polling is disconnected, after submission persisted.
            interrupted = [True]
            def drop_status(route):
                if interrupted[0]: route.abort()
                else: route.continue_()
            context.route(re.compile(re.escape(base) + r"/v1/sessions/[0-9a-f-]+$"), drop_status)
            page.locator("#solve").click(); page.locator("#error").wait_for(state="visible", timeout=30000)
            interrupted[0] = False
            page.reload(); page.locator("#result").wait_for(state="visible", timeout=30000)
            assert identifier not in page.locator("#zip-download").get_attribute("href")
            from browser_recovery import run_recovery
            recovery=run_recovery(page,context,service,images)
            assert not errors, errors
            assert not external, external
            report = {"desktop_and_phone_viewports": True, "external_requests": external, "javascript_errors": errors,
                      "original_upload_and_reorder": True, "lost_upload_ack_retry": True,
                      "zip_download": True, "reload_restore": True, "new_task_isolation": True,
                      "heic_preview_and_original_bytes": True, "restore_after_poll_disconnect": True,
                      "demo": True, "real_iphone_hotspot_tested": False, "recovery":recovery}
            (output / "report.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
            browser.close()
            print(f"Browser flow PASS; demo=True; report={output.relative_to(ROOT) / 'report.json'}")
    finally:
        service.close()


if __name__ == "__main__":
    main()
