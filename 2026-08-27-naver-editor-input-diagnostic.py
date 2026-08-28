#!/usr/bin/env python3
"""네이버 스마트에디터의 입력 가능한 요소를 읽기만 하는 진단 도구."""

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
            editor = new_pages[-1] if new_pages else home
            await editor.wait_for_load_state("domcontentloaded")
            await editor.wait_for_timeout(2500)

            for frame in editor.frames:
                popup = frame.locator('[data-name*="se-popup-alert-confirm"]').filter(
                    has_text=re.compile(r"작성 중인 글이 있습니다")
                ).first
                if await popup.count() and await popup.is_visible():
                    cancel = popup.locator("button").filter(
                        has_text=re.compile(r"^\s*취소\s*$")
                    ).first
                    await cancel.click()
                    await editor.wait_for_timeout(900)
                    break

            report: list[dict[str, object]] = []
            for frame_index, frame in enumerate(editor.frames):
                elements: list[dict[str, str]] = []
                locator = frame.locator('[contenteditable="true"], textarea, input')
                count = await locator.count()
                for index in range(min(count, 40)):
                    item = locator.nth(index)
                    try:
                        elements.append({
                            "tag": await item.evaluate("el => el.tagName"),
                            "class": await item.get_attribute("class") or "",
                            "aria_label": await item.get_attribute("aria-label") or "",
                            "placeholder": await item.get_attribute("placeholder") or "",
                            "text": (await item.inner_text()).strip()[:120],
                        })
                    except Exception:
                        continue
                report.append({"frame_index": frame_index, "url": frame.url, "elements": elements})
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
