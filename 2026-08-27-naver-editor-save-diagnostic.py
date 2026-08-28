#!/usr/bin/env python3
"""네이버 스마트에디터의 저장 관련 요소만 읽는 진단 도구."""

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
            await home.locator('a[href="https://blog.naver.com/GoBlogWrite.naver"]').first.click(force=True)
            await home.wait_for_timeout(1800)
            editor = [page for page in context.pages if page not in before][-1]
            await editor.wait_for_load_state("domcontentloaded")
            await editor.wait_for_timeout(2500)

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
            for frame_index, frame in enumerate(editor.frames):
                items: list[str] = []
                locator = frame.locator('button, a, [role="button"]')
                count = await locator.count()
                for index in range(min(count, 400)):
                    item = locator.nth(index)
                    try:
                        text = (await item.inner_text()).strip()
                        title = await item.get_attribute("title") or ""
                        aria = await item.get_attribute("aria-label") or ""
                        if "저장" in text or "저장" in title or "저장" in aria:
                            items.append((await item.evaluate("el => el.outerHTML"))[:1600])
                    except Exception:
                        continue
                report.append({"frame_index": frame_index, "url": frame.url, "save_elements": items})
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
