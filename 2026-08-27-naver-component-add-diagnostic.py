#!/usr/bin/env python3
"""네이버 에디터의 새 텍스트 컴포넌트 추가 버튼을 읽기 전용으로 진단한다."""

from __future__ import annotations

import asyncio
import importlib.util
import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent
MAIN_PATH = ROOT / "2026-08-27-naver-blog-auto-draft.py"
SPEC = importlib.util.spec_from_file_location("naver_auto_draft", MAIN_PATH)
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
        await MODULE.ensure_blank_editor(editor_page)
        results = []
        for frame_index, frame in enumerate(editor_page.frames):
            elements = await frame.locator(
                '[class*="add"], [data-name*="add"], [aria-label*="추가"]'
            ).evaluate_all(
                """elements => elements.map(element => ({
                    tag: element.tagName,
                    className: element.className,
                    dataName: element.getAttribute('data-name'),
                    ariaLabel: element.getAttribute('aria-label'),
                    text: (element.innerText || '').trim(),
                    visible: !!(element.offsetWidth || element.offsetHeight || element.getClientRects().length),
                    rect: element.getBoundingClientRect().toJSON()
                })).filter(item => item.visible)"""
            )
            if elements:
                results.append({"frame_index": frame_index, "url": frame.url, "elements": elements})
        print(json.dumps(results, ensure_ascii=False, indent=2), flush=True)
        print("DIAGNOSTIC_READY: Chrome과 로그인 세션을 유지합니다.", flush=True)
        print("Codex 확인이 끝날 때까지 Chrome 창을 닫지 마세요.", flush=True)
        await asyncio.to_thread(sys.stdin.readline)
        print("DIAGNOSTIC_DONE: 저장하거나 발행하지 않았습니다.", flush=True)
    finally:
        await MODULE.close_context(context)


if __name__ == "__main__":
    asyncio.run(main())
