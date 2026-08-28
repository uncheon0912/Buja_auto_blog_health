#!/usr/bin/env python3
"""네이버 스마트에디터 안내창의 접근 가능한 요소만 읽는 진단 도구."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / "2026-08-27-blog-sessions" / "blog-01"


async def main() -> None:
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE),
            channel="chrome",
            headless=False,
            viewport=None,
            args=["--start-maximized"],
        )
        try:
            page = context.pages[0] if context.pages else await context.new_page()
            await page.goto("https://blog.naver.com/", wait_until="domcontentloaded")
            write = page.locator('a:has-text("글쓰기"), button:has-text("글쓰기"), a[href*="PostWriteForm"], a[href*="postwrite"]').first
            await write.wait_for(state="visible", timeout=8000)
            await write.click()
            await page.wait_for_load_state("domcontentloaded")
            await page.wait_for_timeout(4000)

            report: list[dict[str, object]] = []
            for index, frame in enumerate(page.frames):
                try:
                    body_text = await frame.locator("body").inner_text(timeout=2000)
                except Exception:
                    body_text = ""
                related = [
                    line.strip()
                    for line in body_text.splitlines()
                    if any(token in line for token in ("작성 중인 글", "취소", "확인"))
                ]
                buttons: list[str] = []
                try:
                    count = await frame.locator("button, [role=button], a").count()
                    for button_index in range(min(count, 300)):
                        text = (await frame.locator("button, [role=button], a").nth(button_index).inner_text()).strip()
                        if text in {"취소", "확인"}:
                            buttons.append(text)
                except Exception:
                    pass
                report.append(
                    {
                        "frame_index": index,
                        "url": frame.url,
                        "related_text": related[:20],
                        "matching_buttons": buttons,
                    }
                )
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
