#!/usr/bin/env python3
"""인용구 다음 일반 문단 생성 방식을 작은 테스트 본문으로 확인한다."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parent
MAIN_PATH = ROOT / "2026-08-27-naver-blog-auto-draft.py"
SPEC = importlib.util.spec_from_file_location("naver_auto_draft_quote_test", MAIN_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError("자동화 모듈을 불러오지 못했습니다.")
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


async def main() -> None:
    context = await MODULE.launch_context(1)
    try:
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(MODULE.NAVER_BLOG_HOME, wait_until="domcontentloaded")
        print("LOGIN_REQUIRED: 네이버에 직접 로그인해 주세요.", flush=True)
        print('로그인 후 창을 닫지 말고 Codex에 "로그인 완료"라고 알려주세요.', flush=True)
        await asyncio.to_thread(sys.stdin.readline)
        editor_page = await MODULE.open_new_post(page, None)
        await MODULE.dismiss_recovery_prompt(editor_page)
        _, body = await MODULE.ensure_blank_editor(editor_page)
        frame = None
        for candidate in editor_page.frames:
            if await candidate.locator(".se-documentTitle p.se-text-paragraph").count():
                frame = candidate
                break
        if frame is None:
            raise RuntimeError("실제 편집 프레임을 찾지 못했습니다.")

        await body.click()
        await editor_page.keyboard.type("앞 일반문단", delay=10)
        await editor_page.keyboard.press("Enter")
        await editor_page.keyboard.press("Enter")
        quote = frame.locator(
            'button[data-group="documentToolbar"][data-name="quotation"][data-value="default"]'
        ).first
        await quote.click()
        await editor_page.keyboard.type("테스트 소제목", delay=10)
        quotation = frame.locator(".se-component.se-quotation").filter(
            has_text="테스트 소제목"
        ).last
        edge = quotation.locator("button.se-component-edge-button-bottom").first
        await edge.click()
        await editor_page.keyboard.type("뒤 일반문단", delay=10)
        await editor_page.wait_for_timeout(700)

        components = await frame.locator(".se-component").evaluate_all(
            """elements => elements.map(element => ({
                className: element.className,
                text: (element.innerText || '').trim(),
                html: element.outerHTML.slice(0, 1200)
            }))"""
        )
        print(json.dumps(components, ensure_ascii=False, indent=2), flush=True)
        screenshot = ROOT / "History" / f"{datetime.now(ZoneInfo('Asia/Seoul')):%Y-%m-%d-%H%M%S}-quote-exit-diagnostic.png"
        await editor_page.screenshot(path=str(screenshot), full_page=False)
        print(f"SCREENSHOT: {screenshot}", flush=True)
        print("DIAGNOSTIC_DONE: 저장하거나 발행하지 않았습니다.", flush=True)
    finally:
        await MODULE.close_context(context)


if __name__ == "__main__":
    asyncio.run(main())
