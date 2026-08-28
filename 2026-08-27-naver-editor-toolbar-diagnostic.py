#!/usr/bin/env python3
"""네이버 편집기의 인용구·볼드·표 도구 요소를 읽기만 하는 진단 도구."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / "2026-08-27-blog-sessions" / "blog-01"


async def main() -> None:
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="chrome", headless=False,
            viewport=None, args=["--start-maximized"],
        )
        try:
            home = context.pages[0] if context.pages else await context.new_page()
            await home.goto("https://blog.naver.com/", wait_until="domcontentloaded")
            before = list(context.pages)
            write = home.locator('a[href="https://blog.naver.com/GoBlogWrite.naver"]').first
            await write.click(force=True)
            await home.wait_for_timeout(1800)
            new_pages = [page for page in context.pages if page not in before]
            if not new_pages:
                print(json.dumps({"error": "editor_tab_not_opened"}, ensure_ascii=False))
                return
            editor = new_pages[-1]
            await editor.wait_for_load_state("domcontentloaded")
            await editor.wait_for_timeout(2500)
            if "nidlogin.login" in editor.url:
                print(json.dumps({"error": "login_required"}, ensure_ascii=False))
                return

            for frame in editor.frames:
                popup = frame.locator('[data-name*="se-popup-alert-confirm"]').filter(
                    has_text=re.compile(r"작성 중인 글이 있습니다")
                ).first
                if await popup.count() and await popup.is_visible():
                    await popup.locator("button").filter(
                        has_text=re.compile(r"^\s*취소\s*$")
                    ).first.click()
                    await editor.wait_for_timeout(900)
                    break

            report: list[dict[str, object]] = []
            keywords = ("인용", "굵", "볼드", "표", "quotation", "bold", "table")
            for frame_index, frame in enumerate(editor.frames):
                items: list[str] = []
                locator = frame.locator("button")
                count = await locator.count()
                for index in range(min(count, 500)):
                    item = locator.nth(index)
                    try:
                        text = (await item.inner_text()).strip()
                        title = await item.get_attribute("title") or ""
                        aria = await item.get_attribute("aria-label") or ""
                        data_name = await item.get_attribute("data-name") or ""
                        combined = " ".join((text, title, aria, data_name)).lower()
                        if any(keyword.lower() in combined for keyword in keywords):
                            items.append((await item.evaluate("el => el.outerHTML"))[:1800])
                    except Exception:
                        continue
                report.append({"frame_index": frame_index, "url": frame.url, "toolbar_elements": items})
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
