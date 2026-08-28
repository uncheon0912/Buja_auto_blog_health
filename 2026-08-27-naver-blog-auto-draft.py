#!/usr/bin/env python3
"""API 없이 네이버 블로그 새 글을 작성하고 임시저장하는 로컬 도우미.

비밀번호, 인증 코드, 쿠키 값을 읽거나 출력하지 않는다. 각 블로그 번호의
로그인 상태는 Chrome이 프로젝트 내부의 전용 프로필 폴더에서 직접 관리한다.
"""

from __future__ import annotations

import argparse
import asyncio
import html
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import win32clipboard
from playwright.async_api import BrowserContext, Frame, Locator, Page, async_playwright


PROJECT_ROOT = Path(__file__).resolve().parent
SESSION_ROOT = PROJECT_ROOT / "2026-08-27-blog-sessions"
HISTORY_ROOT = PROJECT_ROOT / "History"
NAVER_BLOG_HOME = "https://blog.naver.com/"
TITLE_KEY_DELAY_MS = 12
BODY_KEY_DELAY_MS = 2


@dataclass
class BodyBlock:
    kind: str
    value: str | list[list[str]]


def inside_project(path: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(PROJECT_ROOT)
    except ValueError as exc:
        raise ValueError(f"프로젝트 밖의 파일은 사용할 수 없습니다: {resolved}") from exc
    return resolved


def account_profile(blog_number: int) -> Path:
    if blog_number < 1:
        raise ValueError("블로그 번호는 1 이상이어야 합니다.")
    return SESSION_ROOT / f"blog-{blog_number:02d}"


def safe_slug(text: str, limit: int = 36) -> str:
    value = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", text).strip()
    value = re.sub(r"\s+", "-", value)
    return (value[:limit] or "untitled").rstrip("-.")


def read_utf8(path_text: str) -> tuple[Path, str]:
    path = inside_project(Path(path_text))
    if not path.is_file():
        raise FileNotFoundError(path)
    return path, path.read_text(encoding="utf-8")


async def first_visible(page: Page | Frame, selectors: list[str], timeout_ms: int = 2500) -> Locator | None:
    for selector in selectors:
        locator = page.locator(selector).first
        try:
            await locator.wait_for(state="visible", timeout=timeout_ms)
            return locator
        except Exception:
            continue
    return None


async def launch_context(blog_number: int, headless: bool = False) -> BrowserContext:
    profile = account_profile(blog_number)
    profile.mkdir(parents=True, exist_ok=True)
    playwright = await async_playwright().start()
    context = await playwright.chromium.launch_persistent_context(
        user_data_dir=str(profile),
        channel="chrome",
        headless=headless,
        viewport=None,
        args=["--start-maximized"],
    )
    setattr(context, "_local_playwright", playwright)
    return context


async def close_context(context: BrowserContext) -> None:
    playwright = getattr(context, "_local_playwright", None)
    await context.close()
    if playwright is not None:
        await playwright.stop()


async def setup_login(args: argparse.Namespace) -> int:
    context = await launch_context(args.blog_number)
    try:
        page = context.pages[0] if context.pages else await context.new_page()
        await page.goto(args.blog_url or NAVER_BLOG_HOME, wait_until="domcontentloaded")
        print(f"블로그 {args.blog_number} 전용 Chrome 창을 열었습니다.")
        print('네이버에 직접 로그인한 뒤 창을 닫지 말고 Codex 대화창에 "로그인 완료"라고 알려주세요.')
        print("아이디·비밀번호·인증 코드는 이 프로그램이 읽거나 기록하지 않습니다.")
        await page.wait_for_event("close", timeout=0)
    finally:
        try:
            await close_context(context)
        except Exception:
            pass
    return 0


async def open_new_post(page: Page, blog_url: str | None) -> Page:
    await page.goto(blog_url or NAVER_BLOG_HOME, wait_until="domcontentloaded")
    login_markers = [
        'a[href*="nidlogin.login"]',
        'text="로그인"',
    ]
    if await first_visible(page, login_markers, timeout_ms=1200):
        raise RuntimeError("로그인이 필요합니다. setup 명령으로 사용자가 직접 로그인해야 합니다.")

    write_button = await first_visible(
        page,
        [
            'a:has-text("글쓰기")',
            'button:has-text("글쓰기")',
            'a[href*="PostWriteForm"]',
            'a[href*="postwrite"]',
        ],
        timeout_ms=4000,
    )
    if write_button is None:
        raise RuntimeError("새 글쓰기 버튼을 찾지 못했습니다. 블로그 주소를 확인해 주세요.")
    pages_before = list(page.context.pages)
    await write_button.click()
    await page.wait_for_timeout(1800)
    new_pages = [candidate for candidate in page.context.pages if candidate not in pages_before]
    editor_page = new_pages[-1] if new_pages else page
    await editor_page.wait_for_load_state("domcontentloaded")
    await editor_page.wait_for_timeout(1200)

    if "nidlogin.login" in editor_page.url:
        raise RuntimeError("LOGIN_REQUIRED: 네이버 로그인이 필요합니다.")
    login = await first_visible(
        editor_page,
        ['a[href*="nidlogin.login"]', 'text="로그인"'],
        timeout_ms=1000,
    )
    if login is not None:
        raise RuntimeError("LOGIN_REQUIRED: 네이버 로그인이 필요합니다.")
    return editor_page


async def dismiss_recovery_prompt(page: Page) -> bool:
    for frame in page.frames:
        recovery_message = await first_visible(
            frame,
            ['text=/작성 중인 글이 있습니다/'],
            timeout_ms=1500,
        )
        if recovery_message is None:
            continue

        popup = frame.locator(
            '[data-name*="se-popup-alert-confirm"]'
        ).filter(has_text=re.compile(r"작성 중인 글이 있습니다")).first
        try:
            await popup.wait_for(state="visible", timeout=1800)
            cancel = popup.locator("button").filter(
                has_text=re.compile(r"^\s*취소\s*$")
            ).first
            await cancel.wait_for(state="visible", timeout=1800)
        except Exception:
            raise RuntimeError("작성 중 글 안내는 확인했지만 취소 버튼을 찾지 못했습니다.")
        await cancel.click()
        await page.wait_for_timeout(900)
        for check_frame in page.frames:
            if await first_visible(check_frame, ['text=/작성 중인 글이 있습니다/'], timeout_ms=500):
                raise RuntimeError("작성 중 글 안내가 닫히지 않아 입력을 중단합니다.")
        return True
    return False


async def ensure_blank_editor(page: Page) -> tuple[Locator, Locator]:
    title = None
    body = None
    for frame in page.frames:
        title_candidate = await first_visible(
            frame,
            [
                '.se-documentTitle p.se-text-paragraph',
                '.se-documentTitle .se-text-paragraph',
                '.se-documentTitle [contenteditable="true"]',
                '[aria-label*="제목"][contenteditable="true"]',
                'textarea[placeholder*="제목"]',
                'input[placeholder*="제목"]',
            ],
            timeout_ms=1800,
        )
        body_candidate = await first_visible(
            frame,
            [
                '.se-component:not(.se-documentTitle) p.se-text-paragraph',
                '.se-component:not(.se-documentTitle) .se-text-paragraph',
                '.se-main-container .se-text-paragraph[contenteditable="true"]',
                '.se-main-container [contenteditable="true"]',
                '[aria-label*="본문"][contenteditable="true"]',
            ],
            timeout_ms=1800,
        )
        if title_candidate is not None and body_candidate is not None:
            title = title_candidate
            body = body_candidate
            break
    if title is None or body is None:
        raise RuntimeError("네이버 스마트에디터의 제목 또는 본문 입력 영역을 찾지 못했습니다.")

    title_text = (await title.inner_text()).strip()
    body_text = (await body.inner_text()).strip()
    placeholder_values = {
        "제목",
        "본문을 입력해 주세요.",
        "글을 작성해 주세요.",
        "나를 돌아보는 회고, 뜻밖의 발견을 기다립니다. #모두의회고",
    }
    if title_text and title_text not in placeholder_values:
        raise RuntimeError("제목 영역에 기존 내용이 있어 덮어쓰지 않고 중단합니다.")
    if body_text and body_text not in placeholder_values:
        raise RuntimeError("본문 영역에 기존 내용이 있어 덮어쓰지 않고 중단합니다.")
    return title, body


def parse_markdown_body(body: str) -> list[BodyBlock]:
    """원고 표식은 해석하되 네이버 본문에는 Markdown 문자를 입력하지 않는다."""
    lines = body.replace("\r\n", "\n").split("\n")
    blocks: list[BodyBlock] = []
    index = 0
    while index < len(lines):
        stripped = lines[index].strip()
        if not stripped:
            index += 1
            continue
        if stripped.startswith("## "):
            blocks.append(BodyBlock("quote", stripped[3:].strip()))
            index += 1
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            table_lines: list[str] = []
            while index < len(lines):
                candidate = lines[index].strip()
                if not (candidate.startswith("|") and candidate.endswith("|")):
                    break
                table_lines.append(candidate)
                index += 1
            rows = [
                [cell.strip() for cell in row.strip("|").split("|")]
                for row in table_lines
                if not re.fullmatch(r"\|?[\s:|-]+\|?", row)
            ]
            if rows:
                blocks.append(BodyBlock("table", rows))
            continue
        bold_match = re.fullmatch(r"\*\*(.+?)\*\*", stripped)
        if bold_match:
            blocks.append(BodyBlock("bold", bold_match.group(1).strip()))
        else:
            clean = re.sub(r"\*\*(.+?)\*\*", r"\1", stripped)
            blocks.append(BodyBlock("paragraph", clean))
        index += 1
    return blocks


def table_html(rows: list[list[str]]) -> str:
    rendered: list[str] = ['<table style="border-collapse:collapse;width:100%">']
    for row_index, row in enumerate(rows):
        tag = "th" if row_index == 0 else "td"
        rendered.append("<tr>")
        for cell in row:
            rendered.append(
                f'<{tag} style="border:1px solid #d9d9d9;padding:8px;text-align:left">'
                f"{html.escape(cell)}</{tag}>"
            )
        rendered.append("</tr>")
    rendered.append("</table>")
    return "".join(rendered)


def copy_html_to_clipboard(fragment: str) -> None:
    prefix = "<html><body><!--StartFragment-->"
    suffix = "<!--EndFragment--></body></html>"
    header_template = (
        "Version:0.9\r\n"
        "StartHTML:{start_html:010d}\r\n"
        "EndHTML:{end_html:010d}\r\n"
        "StartFragment:{start_fragment:010d}\r\n"
        "EndFragment:{end_fragment:010d}\r\n"
    )
    empty_header = header_template.format(
        start_html=0, end_html=0, start_fragment=0, end_fragment=0
    )
    start_html = len(empty_header.encode("utf-8"))
    start_fragment = start_html + len(prefix.encode("utf-8"))
    end_fragment = start_fragment + len(fragment.encode("utf-8"))
    end_html = end_fragment + len(suffix.encode("utf-8"))
    header = header_template.format(
        start_html=start_html,
        end_html=end_html,
        start_fragment=start_fragment,
        end_fragment=end_fragment,
    )
    payload = (header + prefix + fragment + suffix).encode("utf-8")
    clipboard_format = win32clipboard.RegisterClipboardFormat("HTML Format")
    win32clipboard.OpenClipboard()
    try:
        win32clipboard.EmptyClipboard()
        win32clipboard.SetClipboardData(clipboard_format, payload)
    finally:
        win32clipboard.CloseClipboard()


async def editor_frame(page: Page) -> Frame:
    for frame in page.frames:
        if await frame.locator(".se-documentTitle p.se-text-paragraph").count():
            return frame
    raise RuntimeError("네이버 스마트에디터 프레임을 찾지 못했습니다.")


async def insert_quote(page: Page, frame: Frame, text: str) -> None:
    button = await first_visible(
        frame,
        ['button[data-group="documentToolbar"][data-name="quotation"][data-value="default"]'],
        timeout_ms=2500,
    )
    if button is None:
        raise RuntimeError("네이버 인용구 추가 버튼을 찾지 못했습니다.")
    await button.click()
    await page.wait_for_timeout(250)
    await page.keyboard.type(text, delay=BODY_KEY_DELAY_MS)
    quotation = frame.locator(".se-component.se-quotation").filter(has_text=text).last
    await quotation.wait_for(state="visible", timeout=3000)
    edge = quotation.locator("button.se-component-edge-button-bottom").first
    await edge.click()
    await page.wait_for_timeout(200)


async def insert_bold_line(page: Page, text: str) -> None:
    await page.keyboard.press("Control+B")
    await page.keyboard.type(text, delay=BODY_KEY_DELAY_MS)
    await page.keyboard.press("Control+B")
    await page.keyboard.press("Enter")
    await page.keyboard.press("Enter")


async def insert_table(page: Page, rows: list[list[str]]) -> None:
    copy_html_to_clipboard(table_html(rows))
    await page.keyboard.press("Control+V")
    await page.wait_for_timeout(900)
    frame = await editor_frame(page)
    table_component = frame.locator(".se-component.se-table").last
    await table_component.wait_for(state="visible", timeout=3000)
    edge = table_component.locator("button.se-component-edge-button-bottom").first
    await edge.click()
    await page.wait_for_timeout(200)


async def select_paragraph_text(frame: Frame, text: str) -> Locator:
    paragraph = frame.locator("p.se-text-paragraph").filter(
        has_text=re.compile(rf"^\s*{re.escape(text)}\s*$")
    ).first
    await paragraph.wait_for(state="visible", timeout=5000)
    await paragraph.scroll_into_view_if_needed()
    await paragraph.evaluate(
        """element => {
            const selection = element.ownerDocument.getSelection();
            const range = element.ownerDocument.createRange();
            range.selectNodeContents(element);
            selection.removeAllRanges();
            selection.addRange(range);
            element.focus();
        }"""
    )
    return paragraph


async def enter_text(title_locator: Locator, body_locator: Locator, title: str, body: str, page: Page) -> None:
    await title_locator.click()
    await title_locator.press_sequentially(title, delay=TITLE_KEY_DELAY_MS)
    blocks = parse_markdown_body(body)
    await body_locator.click()
    frame = await editor_frame(page)
    for block in blocks:
        if block.kind == "quote":
            await insert_quote(page, frame, str(block.value))
        elif block.kind == "bold":
            await insert_bold_line(page, str(block.value))
        elif block.kind == "table":
            await insert_table(page, block.value)  # type: ignore[arg-type]
        else:
            await page.keyboard.type(str(block.value), delay=BODY_KEY_DELAY_MS)
            await page.keyboard.press("Enter")
            await page.keyboard.press("Enter")
        await page.wait_for_timeout(80)


async def verify_native_format(page: Page, body: str) -> str:
    frame = await editor_frame(page)
    body_components = frame.locator(".se-component:not(.se-documentTitle)")
    editor_text = (await body_components.all_inner_texts())
    editor_text = "\n".join(editor_text).strip()
    if "##" in editor_text or "**" in editor_text:
        raise RuntimeError("본문에 Markdown 기호가 남아 있어 임시저장을 중단합니다.")
    if "NAVER_TABLE_POSITION_" in editor_text:
        raise RuntimeError("표 위치 표식이 남아 있어 임시저장을 중단합니다.")
    blocks = parse_markdown_body(body)
    expected_quotes = sum(block.kind == "quote" for block in blocks)
    expected_tables = sum(block.kind == "table" for block in blocks)
    expected_bold = sum(block.kind == "bold" for block in blocks)
    quote_count = await frame.locator(".se-component.se-quotation").count()
    table_count = await frame.locator(".se-component.se-table").count()
    bold_count = await frame.locator(
        ".se-text-format-bold, b, strong, [style*='font-weight: bold'], [style*='font-weight:bold']"
    ).count()
    if quote_count < expected_quotes:
        raise RuntimeError(f"인용구 검증 실패: 예상 {expected_quotes}개, 확인 {quote_count}개")
    if table_count < expected_tables:
        raise RuntimeError(f"표 검증 실패: 예상 {expected_tables}개, 확인 {table_count}개")
    if bold_count < expected_bold:
        raise RuntimeError(f"굵게 검증 실패: 예상 {expected_bold}개, 확인 {bold_count}개")
    for block in [item for item in blocks if item.kind == "quote"]:
        quotation = frame.locator(".se-component.se-quotation").filter(has_text=str(block.value))
        if await quotation.count() < 1 or editor_text.count(str(block.value)) != 1:
            raise RuntimeError(f"인용구 본문 검증 실패: {block.value}")
    return f"인용구 {expected_quotes}개, 표 {expected_tables}개, 굵게 {expected_bold}개"


async def save_draft(page: Page) -> str:
    save = None
    save_frame = None
    count_button = None
    for frame in page.frames:
        candidate = await first_visible(
            frame,
            ['button[data-click-area="tpb.save"]'],
            timeout_ms=1500,
        )
        if candidate is not None:
            save = candidate
            save_frame = frame
            count_button = frame.locator(
                'button[data-click-area="tpb*s.count"]'
            ).first
            break
    if save is None or save_frame is None:
        raise RuntimeError("임시저장 버튼을 명확하게 찾지 못해 저장하지 않았습니다.")

    before_count = ""
    try:
        before_count = await count_button.get_attribute("aria-label") or ""
    except Exception:
        pass
    await save.click()
    await page.wait_for_timeout(1500)

    for frame in page.frames:
        success = await first_visible(
            frame,
            [
                'text=/임시저장.*(완료|되었습니다|저장)/',
                'text=/저장.*(완료|되었습니다)/',
            ],
            timeout_ms=1200,
        )
        if success is not None:
            return (await success.inner_text()).strip()

    after_count = ""
    try:
        after_count = await count_button.get_attribute("aria-label") or ""
    except Exception:
        pass
    if before_count and after_count and before_count != after_count:
        return f"{before_count} → {after_count}"

    save_text = (await save.inner_text()).strip()
    if re.search(r"저장\s*(완료|됨)|임시저장\s*\d", save_text):
        return save_text
    raise RuntimeError("임시저장 성공 상태를 확인하지 못했습니다. 중복 저장하지 않고 중단합니다.")


def write_history(blog_number: int, title: str, status: str, evidence: str, source_paths: list[Path]) -> Path:
    now = datetime.now(ZoneInfo("Asia/Seoul"))
    HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
    stem = f"{now:%Y-%m-%d-%H%M%S}-blog-{blog_number:02d}-{safe_slug(title)}-draft-history"
    path = HISTORY_ROOT / f"{stem}.md"
    suffix = 2
    while path.exists():
        path = HISTORY_ROOT / f"{stem}-{suffix:02d}.md"
        suffix += 1
    lines = [
        "# 네이버 블로그 임시저장 기록",
        "",
        f"- 시각: {now:%Y-%m-%d %H:%M:%S} (Asia/Seoul)",
        f"- 블로그 번호: {blog_number}",
        f"- 제목: {title}",
        f"- 상태: {status}",
        f"- 화면 근거: {evidence}",
        "- 발행 여부: 발행하지 않음",
        "- 로그인 정보 기록: 없음",
        "- 입력 파일:",
    ]
    lines.extend(f"  - {path_item.relative_to(PROJECT_ROOT)}" for path_item in source_paths)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


async def create_draft(args: argparse.Namespace) -> int:
    title_path, title = read_utf8(args.title_file)
    body_path, body = read_utf8(args.body_file)
    title = title.strip()
    body = body.strip()
    if not title or not body:
        raise ValueError("제목과 본문은 비어 있을 수 없습니다.")
    if not args.save_draft:
        raise ValueError("임시저장을 허용하려면 --save-draft 옵션이 필요합니다.")

    context = await launch_context(args.blog_number, headless=args.headless)
    try:
        page = context.pages[0] if context.pages else await context.new_page()
        page = await open_new_post(page, args.blog_url)
        await dismiss_recovery_prompt(page)
        title_locator, body_locator = await ensure_blank_editor(page)
        await enter_text(title_locator, body_locator, title, body, page)
        format_evidence = await verify_native_format(page, body)
        evidence = await save_draft(page)
        history = write_history(
            args.blog_number,
            title,
            "임시저장 완료",
            f"{evidence}; {format_evidence}",
            [title_path, body_path],
        )
        print(json.dumps({"status": "saved", "title": title, "history": str(history)}, ensure_ascii=False))
    except Exception as exc:
        screenshot = HISTORY_ROOT / f"{datetime.now(ZoneInfo('Asia/Seoul')):%Y-%m-%d-%H%M%S}-draft-error.png"
        HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            page = context.pages[-1]
            await page.screenshot(path=str(screenshot), full_page=False)
            print(f"오류 화면: {screenshot}", file=sys.stderr)
        except Exception:
            pass
        raise exc
    finally:
        await close_context(context)
    return 0


def read_batch_manifest(path_text: str) -> tuple[Path, dict]:
    path, raw = read_utf8(path_text)
    data = json.loads(raw)
    if not isinstance(data, dict) or not isinstance(data.get("items"), list):
        raise ValueError("배치 목록에는 items 배열이 필요합니다.")
    return path, data


async def wait_for_user_login(page: Page) -> None:
    print("LOGIN_REQUIRED: 네이버에 직접 로그인해 주세요.", flush=True)
    print('로그인 후 Chrome 창을 닫지 말고 Codex 대화창에 "로그인 완료"라고 알려주세요.', flush=True)
    print("Codex가 확인 신호를 보낼 때까지 같은 Chrome 창을 유지합니다.", flush=True)
    await asyncio.to_thread(sys.stdin.readline)
    await page.reload(wait_until="domcontentloaded")
    if "nidlogin.login" in page.url:
        raise RuntimeError("LOGIN_REQUIRED: 로그인 완료 상태를 확인하지 못했습니다.")


async def create_batch(args: argparse.Namespace) -> int:
    manifest_path, manifest = read_batch_manifest(args.manifest)
    blog_number = int(manifest.get("blog_number", args.blog_number or 1))
    blog_url = manifest.get("blog_url") or args.blog_url
    wait_seconds = int(manifest.get("wait_seconds", 60))
    if wait_seconds < 0:
        raise ValueError("대기 시간은 0초 이상이어야 합니다.")
    if not args.save_draft:
        raise ValueError("임시저장을 허용하려면 --save-draft 옵션이 필요합니다.")

    prepared: list[tuple[Path, str, Path, str]] = []
    for item in manifest["items"]:
        if not isinstance(item, dict):
            raise ValueError("각 items 항목은 객체여야 합니다.")
        title_path, title = read_utf8(str(item["title_file"]))
        body_path, body = read_utf8(str(item["body_file"]))
        if not title.strip() or not body.strip():
            raise ValueError("제목과 본문은 비어 있을 수 없습니다.")
        prepared.append((title_path, title.strip(), body_path, body.strip()))

    context = await launch_context(blog_number, headless=args.headless)
    page = context.pages[0] if context.pages else await context.new_page()
    try:
        await page.goto(blog_url or NAVER_BLOG_HOME, wait_until="domcontentloaded")
        await wait_for_user_login(page)
        results: list[dict] = []
        for index, (title_path, title, body_path, body) in enumerate(prepared):
            editor_page = await open_new_post(page, blog_url)
            cancelled = await dismiss_recovery_prompt(editor_page)
            title_locator, body_locator = await ensure_blank_editor(editor_page)
            await enter_text(title_locator, body_locator, title, body, editor_page)
            format_evidence = await verify_native_format(editor_page, body)
            evidence = await save_draft(editor_page)
            history = write_history(
                blog_number,
                title,
                "임시저장 완료",
                f"{evidence}; {format_evidence}; 작성 중 글 취소={cancelled}",
                [manifest_path, title_path, body_path],
            )
            result = {"status": "saved", "title": title, "history": str(history)}
            results.append(result)
            print(json.dumps(result, ensure_ascii=False), flush=True)
            page = editor_page
            if index < len(prepared) - 1:
                print(f"SESSION_WAIT: 로그인 세션을 유지하며 {wait_seconds}초 동안 브라우저 조작 없이 대기합니다.", flush=True)
                await asyncio.sleep(wait_seconds)
                print("SESSION_WAIT_DONE: 다음 새 글 작성을 시작합니다.", flush=True)
        print(json.dumps({"status": "batch-complete", "results": results}, ensure_ascii=False), flush=True)
    except Exception as exc:
        screenshot = HISTORY_ROOT / f"{datetime.now(ZoneInfo('Asia/Seoul')):%Y-%m-%d-%H%M%S}-batch-error.png"
        HISTORY_ROOT.mkdir(parents=True, exist_ok=True)
        try:
            await context.pages[-1].screenshot(path=str(screenshot), full_page=False)
            print(f"오류 화면: {screenshot}", file=sys.stderr)
        except Exception:
            pass
        raise exc
    finally:
        await close_context(context)
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="API 없는 네이버 블로그 임시저장 자동화")
    sub = parser.add_subparsers(dest="command", required=True)

    setup = sub.add_parser("setup", help="블로그 번호별 로그인 세션 준비")
    setup.add_argument("--blog-number", type=int, required=True)
    setup.add_argument("--blog-url")

    draft = sub.add_parser("draft", help="검수 완료 원고를 새 글로 임시저장")
    draft.add_argument("--blog-number", type=int, required=True)
    draft.add_argument("--blog-url")
    draft.add_argument("--title-file", required=True)
    draft.add_argument("--body-file", required=True)
    draft.add_argument("--save-draft", action="store_true")
    draft.add_argument("--headless", action="store_true")

    batch = sub.add_parser("batch", help="한 로그인 세션에서 여러 글을 60초 간격으로 임시저장")
    batch.add_argument("--manifest", required=True)
    batch.add_argument("--blog-number", type=int)
    batch.add_argument("--blog-url")
    batch.add_argument("--save-draft", action="store_true")
    batch.add_argument("--headless", action="store_true")
    return parser


async def async_main() -> int:
    args = build_parser().parse_args()
    if args.command == "setup":
        return await setup_login(args)
    if args.command == "batch":
        return await create_batch(args)
    return await create_draft(args)


def main() -> int:
    try:
        return asyncio.run(async_main())
    except KeyboardInterrupt:
        print("사용자가 작업을 중단했습니다.", file=sys.stderr)
        return 130
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
