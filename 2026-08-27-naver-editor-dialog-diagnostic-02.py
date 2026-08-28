#!/usr/bin/env python3
"""네이버 새 글 화면의 안내창 요소를 읽기만 하는 두 번째 진단 도구."""

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
            await page.goto("https://blog.naver.com/GoBlogWrite.naver", wait_until="domcontentloaded")
            await page.wait_for_timeout(5000)

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
                selectors: dict[str, int] = {}
                for selector in (
                    'text=/작성 중인 글이 있습니다/',
                    'text="취소"',
                    'button:has-text("취소")',
                    '[role="button"]:has-text("취소")',
                ):
                    try:
                        selectors[selector] = await frame.locator(selector).count()
                    except Exception:
                        selectors[selector] = -1
                report.append(
                    {
                        "frame_index": index,
                        "url": frame.url,
                        "related_text": related[:20],
                        "selector_counts": selectors,
                    }
                )
            print(json.dumps(report, ensure_ascii=False, indent=2))
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
