#!/usr/bin/env python3
"""로그인 창을 유지하며 네이버 네이티브 서식 도구를 확인하는 진단 도구."""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from playwright.async_api import async_playwright


ROOT = Path(__file__).resolve().parent
PROFILE = ROOT / "2026-08-27-blog-sessions" / "blog-01"
LOGIN_URL = "https://nid.naver.com/nidlogin.login?mode=form&url=https://blog.naver.com/"


async def main() -> None:
    async with async_playwright() as playwright:
        context = await playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE), channel="chrome", headless=False,
            viewport=None, args=["--start-maximized"],
        )
        try:
            home = context.pages[0] if context.pages else await context.new_page()
            await home.goto("https://blog.naver.com/", wait_until="domcontentloaded")
            login_link = home.locator('a[href*="nidlogin.login"]').first
            if await login_link.count() and await login_link.is_visible():
                await home.goto(LOGIN_URL, wait_until="domcontentloaded")
                print("LOGIN_REQUIRED: 이 Chrome 창에서 직접 로그인해 주세요.", flush=True)
                for _ in range(300):
                    await asyncio.sleep(2)
                    if "nidlogin.login" not in home.url:
                        break
                else:
                    raise RuntimeError("로그인 대기 시간이 초과됐습니다.")
                await home.goto("https://blog.naver.com/", wait_until="domcontentloaded")

            before = list(context.pages)
            write = home.locator('a[href="https://blog.naver.com/GoBlogWrite.naver"]').first
            await write.evaluate("el => el.click()")
            await home.wait_for_timeout(1800)
            new_pages = [page for page in context.pages if page not in before]
            if not new_pages:
                raise RuntimeError("새 편집기 탭이 열리지 않았습니다.")
            editor = new_pages[-1]
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
            keywords = ("인용", "굵", "볼드", "표", "quotation", "bold", "table")
            for frame_index, frame in enumerate(editor.frames):
                items: list[str] = []
                buttons = frame.locator("button")
                count = await buttons.count()
                for index in range(min(count, 600)):
                    button = buttons.nth(index)
                    try:
                        values = [
                            (await button.inner_text()).strip(),
                            await button.get_attribute("title") or "",
                            await button.get_attribute("aria-label") or "",
                            await button.get_attribute("data-name") or "",
                            await button.get_attribute("class") or "",
                        ]
                        combined = " ".join(values).lower()
                        if any(keyword.lower() in combined for keyword in keywords):
                            items.append((await button.evaluate("el => el.outerHTML"))[:2000])
                    except Exception:
                        continue
                report.append({"frame_index": frame_index, "url": frame.url, "toolbar_elements": items})
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
        finally:
            await context.close()


if __name__ == "__main__":
    asyncio.run(main())
