#!/usr/bin/env python3
"""제목과 기본 본문 문구 주변의 네이버 편집기 구조를 읽는 진단 도구."""

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
            selectors = [
                '.se-documentTitle',
                '[class*="documentTitle"]',
                '.se-main-container',
                '[class*="text-paragraph"]',
                'text="제목"',
                'text=/나를 돌아보는 회고/',
                '[contenteditable="true"]',
            ]
            for frame_index, frame in enumerate(editor.frames):
                matches: dict[str, list[str]] = {}
                for selector in selectors:
                    values: list[str] = []
                    locator = frame.locator(selector)
                    try:
                        count = await locator.count()
                        for index in range(min(count, 5)):
                            html = await locator.nth(index).evaluate("el => el.outerHTML")
                            values.append(html[:1200])
                    except Exception:
                        pass
                    matches[selector] = values
                report.append({"frame_index": frame_index, "url": frame.url, "matches": matches})
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
