#!/usr/bin/env python3
"""Validate a Naver informational blog draft without external packages."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


FIXED_NOTICE = (
    "본 게시글은 보건복지부 가이드 라인에 따라 의료법 제57조 제3항 각 호의 "
    "사전심의를 받지 아니할 수 있는 항목만으로 이루어진 [일반적인 건강상식, "
    "의학정보를 제공하는 정보 공유 목적]으로 작성되었습니다."
)

HIGHLIGHT_PATTERN = re.compile(
    r"\[HIGHLIGHT_(YELLOW|GREEN|PINK)\](.*?)\[/HIGHLIGHT_\1\]",
    re.DOTALL,
)
QUOTE_PATTERN = re.compile(r"\[QUOTE_HEADING\](.*?)\[/QUOTE_HEADING\]", re.DOTALL)
TITLE_PATTERN = re.compile(r"\[NAVER_TITLE\](.*?)\[/NAVER_TITLE\]", re.DOTALL)
TITLE_BOX_PATTERN = re.compile(
    r"\[TITLE_BOX_LIGHT_GREEN_CENTER\](.*?)\[/TITLE_BOX_LIGHT_GREEN_CENTER\]",
    re.DOTALL,
)
FAQ_PATTERN = re.compile(r"\[FAQ_BOX\](.*?)\[/FAQ_BOX\]", re.DOTALL)
FINAL_PATTERN = re.compile(r"\[FINAL_SUMMARY\](.*?)\[/FINAL_SUMMARY\]", re.DOTALL)
QUESTION_PATTERN = re.compile(r"(?m)^\*\*Q\.\s+.+?\*\*\s*$")


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def visible_character_count(text: str) -> int:
    without_tags = re.sub(r"\[/?[A-Z_]+\]", "", text)
    without_table_rules = re.sub(r"(?m)^\s*\|?\s*:?-{3,}:?.*$", "", without_tags)
    without_markdown = re.sub(r"[*#|`]", "", without_table_rules)
    return len(re.sub(r"\s+", "", without_markdown))


def find_table(text: str) -> tuple[int, list[str]] | None:
    lines = text.splitlines()
    offset = 0
    for index, line in enumerate(lines):
        if line.strip().startswith("|") and line.strip().endswith("|"):
            block = [line]
            next_index = index + 1
            while next_index < len(lines):
                next_line = lines[next_index]
                if not (next_line.strip().startswith("|") and next_line.strip().endswith("|")):
                    break
                block.append(next_line)
                next_index += 1
            return offset, block
        offset += len(line) + 1
    return None


def table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def validate_draft(text: str, expected_title: str) -> tuple[list[str], list[str], int]:
    errors: list[str] = []
    warnings: list[str] = []

    titles = TITLE_PATTERN.findall(text)
    boxes = TITLE_BOX_PATTERN.findall(text)
    quotes = QUOTE_PATTERN.findall(text)
    highlights = list(HIGHLIGHT_PATTERN.finditer(text))
    faqs = FAQ_PATTERN.findall(text)
    finals = FINAL_PATTERN.findall(text)
    questions = list(QUESTION_PATTERN.finditer(text))
    table = find_table(text)

    if len(titles) != 1:
        errors.append(f"[NAVER_TITLE] 블록은 정확히 1개여야 합니다. 현재 {len(titles)}개입니다.")
    elif titles[0] != expected_title:
        errors.append("네이버 상단 제목이 입력 원문과 문자 단위로 일치하지 않습니다.")

    if len(boxes) != 1:
        errors.append(f"연한 녹색 제목 박스는 정확히 1개여야 합니다. 현재 {len(boxes)}개입니다.")
    elif boxes[0] != expected_title:
        errors.append("제목 박스의 제목이 입력 원문과 문자 단위로 일치하지 않습니다.")

    if len(titles) == 1 and len(boxes) == 1 and titles[0] != boxes[0]:
        errors.append("네이버 상단 제목과 제목 박스가 서로 다릅니다.")

    if text.count("[DIVIDER]") != 1:
        errors.append("[DIVIDER]는 정확히 1개여야 합니다.")

    notice_count = text.count(FIXED_NOTICE)
    if notice_count != 1:
        errors.append(f"고정 의료 정보 안내문은 원문 그대로 정확히 1회 필요합니다. 현재 {notice_count}회입니다.")
    divider_index = text.find("[DIVIDER]")
    if divider_index >= 0:
        after_divider = text[divider_index + len("[DIVIDER]"):].lstrip()
        if not after_divider.startswith(FIXED_NOTICE):
            errors.append("고정 안내문은 구분선 바로 다음에 있어야 합니다.")

    if len(quotes) != 3:
        errors.append(f"[QUOTE_HEADING] 소제목은 정확히 3개여야 합니다. 현재 {len(quotes)}개입니다.")
    for index, heading in enumerate(quotes, start=1):
        if not heading.strip():
            errors.append(f"인용구 소제목 {index}이 비어 있습니다.")
        if "\n" in heading.strip():
            warnings.append(f"인용구 소제목 {index}이 여러 줄입니다. 한 줄 사용을 권장합니다.")
        if re.match(r"^(?:\d+[.)]|첫째|둘째|셋째|[\U0001F300-\U0001FAFF])", heading.strip()):
            warnings.append(f"인용구 소제목 {index} 앞에 번호 또는 이모지가 있을 수 있습니다.")

    if len(highlights) < 2:
        errors.append(f"필수 핵심 문장 형광펜은 최소 2개 필요합니다. 현재 {len(highlights)}개입니다.")
    if len(highlights) > 3:
        warnings.append(f"형광펜이 {len(highlights)}개입니다. 지나친 강조인지 확인하세요.")
    colors = {match.group(1) for match in highlights}
    if len(colors) > 3:
        errors.append("한 원고에서 형광펜 색상은 최대 3가지만 사용할 수 있습니다.")
    for index, match in enumerate(highlights, start=1):
        content = match.group(2).strip()
        if not content:
            errors.append(f"형광펜 {index}의 내용이 비어 있습니다.")
        if "**" in content:
            errors.append(f"형광펜 {index} 안에 Markdown 볼드를 중첩하지 마세요.")

    if table is None:
        errors.append("2열 정보표가 없습니다.")
        table_index = -1
    else:
        table_index, rows = table
        if len(rows) < 3:
            errors.append("정보표에는 헤더, 구분 행, 데이터 행이 필요합니다.")
        if len(rows) > 6:
            errors.append("정보표는 헤더와 구분 행을 포함해 최대 6행이어야 합니다.")
        for row_index, row in enumerate(rows, start=1):
            if len(table_cells(row)) != 2:
                errors.append(f"정보표 {row_index}행은 정확히 2열이어야 합니다.")
        if len(rows) >= 2:
            separator_cells = table_cells(rows[1])
            if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator_cells):
                errors.append("정보표 두 번째 행은 두 열짜리 Markdown 구분 행이어야 합니다.")

    if len(faqs) != 1 or (faqs and faqs[0].strip() != "자주 묻는 질문"):
        errors.append("[FAQ_BOX]자주 묻는 질문[/FAQ_BOX]을 정확히 1회 사용해야 합니다.")
    if not 2 <= len(questions) <= 3:
        errors.append(f"볼드 처리된 Q&A 질문은 2~3개여야 합니다. 현재 {len(questions)}개입니다.")

    if len(finals) != 1 or (finals and not finals[0].strip()):
        errors.append("내용이 있는 [FINAL_SUMMARY] 블록이 정확히 1개 필요합니다.")

    positions: list[tuple[str, int]] = []
    if titles:
        positions.append(("네이버 제목", TITLE_PATTERN.search(text).start()))
    if divider_index >= 0:
        positions.append(("구분선", divider_index))
    notice_index = text.find(FIXED_NOTICE)
    if notice_index >= 0:
        positions.append(("고정 안내문", notice_index))
    if boxes:
        positions.append(("제목 박스", TITLE_BOX_PATTERN.search(text).start()))
    if len(highlights) >= 1:
        positions.append(("첫 번째 형광펜", highlights[0].start()))
    quote_matches = list(QUOTE_PATTERN.finditer(text))
    if len(quote_matches) >= 1:
        positions.append(("첫 번째 소제목", quote_matches[0].start()))
    if len(highlights) >= 2:
        positions.append(("두 번째 형광펜", highlights[1].start()))
    if table_index >= 0:
        positions.append(("정보표", table_index))
    if len(quote_matches) >= 2:
        positions.append(("두 번째 소제목", quote_matches[1].start()))
    if len(quote_matches) >= 3:
        positions.append(("세 번째 소제목", quote_matches[2].start()))
    faq_match = FAQ_PATTERN.search(text)
    if faq_match:
        positions.append(("FAQ 박스", faq_match.start()))
    final_match = FINAL_PATTERN.search(text)
    if final_match:
        positions.append(("최종 정리", final_match.start()))

    for (left_name, left_pos), (right_name, right_pos) in zip(positions, positions[1:]):
        if left_pos >= right_pos:
            errors.append(f"필수 순서 오류: {left_name} 다음에 {right_name}이 와야 합니다.")

    if faq_match and final_match:
        qa_between = [question for question in questions if faq_match.end() < question.start() < final_match.start()]
        if len(qa_between) != len(questions):
            errors.append("모든 Q&A 질문은 FAQ 박스와 최종 정리 사이에 있어야 합니다.")

    risky_phrases = (
        "100%",
        "무조건 낫",
        "부작용이 없",
        "반드시 이 질환",
        "완치를 보장",
        "확실한 효과",
    )
    for phrase in risky_phrases:
        if phrase in text:
            warnings.append(f"의료 단정 또는 보장 표현 가능성: '{phrase}'")

    count = visible_character_count(text)
    if not 1200 <= count <= 1500:
        warnings.append(
            f"표시 태그와 공백을 제외한 예상 글자 수가 {count}자입니다. "
            "권장 범위는 약 1,200~1,500자이며 반복으로 늘리지는 마세요."
        )

    return errors, warnings, count


def sample_draft(title: str) -> str:
    return f"""[NAVER_TITLE]{title}[/NAVER_TITLE]

[DIVIDER]

{FIXED_NOTICE}

[TITLE_BOX_LIGHT_GREEN_CENTER]{title}[/TITLE_BOX_LIGHT_GREEN_CENTER]

운동을 마친 뒤 허리가 불편하면 방금 한 동작과 강도를 먼저 떠올려 볼 수 있습니다. 증상만으로 원인을 하나로 단정하기는 어렵습니다.

통증이 시작된 시점과 반복되는 동작을 차분히 살펴보는 것이 첫 단계입니다.

[HIGHLIGHT_PINK]허리 통증은 여러 원인과 관련될 수 있어 나타나는 조건을 함께 확인해야 합니다.[/HIGHLIGHT_PINK]

[QUOTE_HEADING]운동할 때 허리에 부담이 커지는 상황은 무엇일까요?[/QUOTE_HEADING]

자세가 흐트러지거나 평소보다 강도를 갑자기 높이면 허리에 부담이 커질 수 있습니다. 같은 동작에서 반복되는지도 살펴봅니다.

운동 전후의 변화와 쉬었을 때의 차이를 기록하면 현재 상황을 설명하는 데 도움이 됩니다.

[HIGHLIGHT_YELLOW]특정 동작과 통증의 관계를 기록하면 확인해야 할 범위를 정리할 수 있습니다.[/HIGHLIGHT_YELLOW]

| 살펴볼 상황 | 확인할 부분 |
|---|---|
| 운동을 시작할 때 | 특정 동작에서 나타나는지 |
| 강도를 높였을 때 | 불편함이 커지는지 |

[QUOTE_HEADING]통증이 나타나면 운동을 어떻게 조절할까요?[/QUOTE_HEADING]

불편함을 참고 같은 강도를 유지하기보다 부담을 주는 동작을 줄이고 변화를 살펴봅니다. 무리한 동작은 피하는 편이 안전합니다.

증상이 계속되면 개인 상태에 맞는 확인이 필요할 수 있습니다.

[QUOTE_HEADING]어떤 변화를 기록하면 도움이 될까요?[/QUOTE_HEADING]

통증이 시작된 시점, 지속 시간, 악화되는 동작을 적어 둡니다. 휴식 뒤 어떻게 달라지는지도 함께 기록합니다.

다리 감각 변화처럼 다른 증상이 함께 있는지도 살펴볼 수 있습니다.

[FAQ_BOX]자주 묻는 질문[/FAQ_BOX]

**Q. 운동 후 허리가 아프면 특정 질환인가요?**

증상만으로 특정 질환을 단정하기는 어렵습니다. 나타나는 조건을 함께 살펴보는 것이 좋습니다.

**Q. 불편해도 같은 운동을 계속해도 될까요?**

부담을 주는 동작과 강도를 조절하고 변화를 확인하는 편이 좋습니다.

[FINAL_SUMMARY]
허리 불편함은 한 가지 정보만으로 판단하기 어렵습니다. 오늘부터 시작 시점과 관련 동작, 휴식 뒤 변화를 기록해 보세요.
[/FINAL_SUMMARY]
"""


def self_test() -> int:
    title = "운동 후 허리가 아픈 이유는 무엇일까요?"
    errors, warnings, count = validate_draft(sample_draft(title), title)
    if errors:
        print("SELF-TEST FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"SELF-TEST PASSED: 필수 제목, 안내문, 순서, 표, Q&A 구조를 확인했습니다. ({count}자)")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="네이버 정보성 블로그 초안 구조를 검증합니다.")
    parser.add_argument("draft", nargs="?", type=Path, help="검증할 Markdown 초안")
    parser.add_argument("--title", help="사용자가 입력한 제목 원문")
    parser.add_argument("--self-test", action="store_true", help="내장 예시로 구조를 검증합니다.")
    return parser.parse_args()


def main() -> int:
    configure_output()
    args = parse_args()
    if args.self_test:
        return self_test()
    if args.draft is None or args.title is None:
        print("오류: 초안 경로와 --title 또는 --self-test가 필요합니다.", file=sys.stderr)
        return 2
    try:
        text = args.draft.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"오류: 초안을 읽을 수 없습니다: {exc}", file=sys.stderr)
        return 2

    errors, warnings, count = validate_draft(text, args.title)
    if errors:
        print(f"검증 실패: {len(errors)}개 문제를 발견했습니다. 예상 글자 수: {count}자")
        for error in errors:
            print(f"ERROR: {error}")
        for warning in warnings:
            print(f"WARNING: {warning}")
        return 1

    print(f"검증 통과: 필수 구조를 확인했습니다. 예상 글자 수: {count}자")
    for warning in warnings:
        print(f"WARNING: {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

