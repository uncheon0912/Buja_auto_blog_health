#!/usr/bin/env python3
"""Preflight a tagged Naver blog draft without modifying the source file."""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path


FIXED_NOTICE = (
    "본 게시글은 보건복지부 가이드 라인에 따라 의료법 제57조 제3항 각 호의 "
    "사전심의를 받지 아니할 수 있는 항목만으로 이루어진 [일반적인 건강상식, "
    "의학정보를 제공하는 정보 공유 목적]으로 작성되었습니다."
)

DISCLAIMER = (
    "이 결과는 자동 콘텐츠 검수이며 법률 자문, 의료 자문 또는 의료광고 "
    "사전심의 결과가 아닙니다. 법적 판단이 필요한 내용은 사용자 또는 "
    "관련 전문가의 확인이 필요합니다."
)

PROHIBITED_PHRASES = (
    "완치",
    "반드시 치료됩니다",
    "100% 효과",
    "즉시 효과",
    "한 번에 해결",
    "부작용 없음",
    "부작용이 없습니다",
    "통증이 전혀 없습니다",
    "누구나 같은 결과를 얻습니다",
    "가장 안전한 치료",
    "최고의 치료",
    "유일한 치료법",
    "국내 최초",
    "업계 1위",
    "무조건 입원해야 합니다",
    "반드시 수술해야 합니다",
    "이 증상이면 해당 질환입니다",
    "치료하지 않으면 큰일 납니다",
    "다른 병원보다 우수합니다",
    "다른 치료는 효과가 없습니다",
)

LEGAL_REVIEW_PATTERNS = (
    "법적으로 문제없",
    "의료광고가 아닙니다",
    "사전심의가 필요 없",
    "심의 대상이 아닙니다",
    "의료법에 위반되지 않",
    "합법입니다",
)

FACT_PATTERNS = (
    re.compile(r"\d+(?:\.\d+)?\s*(?:%|퍼센트|원|만원|억원|명|건|회|개월|주|일|년)"),
    re.compile(r"(?:연구|논문|조사)\s*(?:에 따르면|결과|에서는)"),
    re.compile(r"(?:국내|업계|전국)\s*(?:최초|유일|1위)"),
)

TITLE_RE = re.compile(r"\[NAVER_TITLE\](.*?)\[/NAVER_TITLE\]", re.DOTALL)
BOX_RE = re.compile(
    r"\[TITLE_BOX_LIGHT_GREEN_CENTER\](.*?)\[/TITLE_BOX_LIGHT_GREEN_CENTER\]",
    re.DOTALL,
)
QUOTE_RE = re.compile(r"\[QUOTE_HEADING\](.*?)\[/QUOTE_HEADING\]", re.DOTALL)
HIGHLIGHT_RE = re.compile(
    r"\[HIGHLIGHT_(YELLOW|GREEN|PINK)\](.*?)\[/HIGHLIGHT_\1\]",
    re.DOTALL,
)
FAQ_RE = re.compile(r"\[FAQ_BOX\](.*?)\[/FAQ_BOX\]", re.DOTALL)
FINAL_RE = re.compile(r"\[FINAL_SUMMARY\](.*?)\[/FINAL_SUMMARY\]", re.DOTALL)
QUESTION_RE = re.compile(r"(?m)^\*\*Q\.\s+.+?\*\*\s*$")


@dataclass
class Issue:
    stage: int
    kind: str
    message: str
    excerpt: str = ""
    blocking: bool = True
    safe_auto_fix: bool = False
    suggested_text: str = "자동 수정하지 않음"
    reason: str = ""


@dataclass
class Review:
    title: str
    overall_result: str
    naver_input_allowed: bool
    stages: dict[str, str]
    issues: list[Issue] = field(default_factory=list)
    disclaimer: str = DISCLAIMER


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def table_cells(line: str) -> list[str]:
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def markdown_tables(text: str) -> list[list[str]]:
    tables: list[list[str]] = []
    current: list[str] = []
    for line in text.splitlines() + [""]:
        stripped = line.strip()
        if stripped.startswith("|") and stripped.endswith("|"):
            current.append(line)
        elif current:
            tables.append(current)
            current = []
    return tables


def surrounding_sentence(text: str, index: int) -> str:
    left = max(text.rfind("\n", 0, index), text.rfind(".", 0, index)) + 1
    right_candidates = [pos for pos in (text.find("\n", index), text.find(".", index)) if pos >= 0]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    return text[left:right].strip()[:240]


def add_issue(
    issues: list[Issue],
    stage: int,
    kind: str,
    message: str,
    excerpt: str = "",
    *,
    blocking: bool = True,
    safe_auto_fix: bool = False,
    suggested_text: str = "자동 수정하지 않음",
    reason: str = "",
) -> None:
    issues.append(
        Issue(
            stage=stage,
            kind=kind,
            message=message,
            excerpt=excerpt,
            blocking=blocking,
            safe_auto_fix=safe_auto_fix,
            suggested_text=suggested_text,
            reason=reason,
        )
    )


def review_draft(text: str, expected_title: str) -> Review:
    issues: list[Issue] = []

    titles = TITLE_RE.findall(text)
    boxes = BOX_RE.findall(text)
    quote_matches = list(QUOTE_RE.finditer(text))
    highlight_matches = list(HIGHLIGHT_RE.finditer(text))
    faq_match = FAQ_RE.search(text)
    final_match = FINAL_RE.search(text)
    question_matches = list(QUESTION_RE.finditer(text))

    # Stage 1: fixed elements
    if len(titles) != 1:
        add_issue(issues, 1, "네이버 서식", f"상단 제목 블록은 1개여야 합니다. 현재 {len(titles)}개입니다.")
    elif titles[0] != expected_title:
        add_issue(issues, 1, "제목 원문", "상단 제목이 원본 제목과 문자 단위로 다릅니다.", titles[0])

    if text.count("[DIVIDER]") != 1:
        add_issue(issues, 1, "네이버 서식", "제목 아래 구분선은 정확히 1개여야 합니다.")

    if text.count(FIXED_NOTICE) != 1:
        add_issue(issues, 1, "고정 안내문", "고정 의료 정보 안내문이 원문 그대로 정확히 1회 필요합니다.")

    divider_index = text.find("[DIVIDER]")
    if divider_index >= 0:
        after_divider = text[divider_index + len("[DIVIDER]"):].lstrip()
        if not after_divider.startswith(FIXED_NOTICE):
            add_issue(issues, 1, "고정 안내문 위치", "고정 안내문은 구분선 바로 다음에 있어야 합니다.")

    if len(boxes) != 1:
        add_issue(issues, 1, "제목 박스", f"연한 녹색 중앙 정렬 제목 박스는 1개여야 합니다. 현재 {len(boxes)}개입니다.")
    elif boxes[0] != expected_title:
        add_issue(issues, 1, "제목 원문", "제목 박스가 원본 제목과 문자 단위로 다릅니다.", boxes[0])
    if len(titles) == 1 and len(boxes) == 1 and titles[0] != boxes[0]:
        add_issue(issues, 1, "제목 원문", "상단 제목과 제목 박스가 서로 다릅니다.")

    # Stage 2: quote headings
    if len(quote_matches) != 3:
        add_issue(issues, 2, "인용구", f"주요 인용구 소제목은 3개여야 합니다. 현재 {len(quote_matches)}개입니다.")
    for match_index, match in enumerate(quote_matches, start=1):
        heading = match.group(1).strip()
        if not heading:
            add_issue(issues, 2, "인용구", f"인용구 소제목 {match_index}이 비어 있습니다.")
        if len(heading) > 40:
            add_issue(
                issues,
                2,
                "소제목 길이",
                f"인용구 소제목 {match_index}이 공백 포함 40자를 넘습니다.",
                heading,
                blocking=False,
            )
        cleaned = re.sub(r"^(?:\d+[.)]\s*|[\U0001F300-\U0001FAFF]\s*)", "", heading)
        if cleaned != heading:
            add_issue(
                issues,
                2,
                "불필요한 번호·이모지",
                f"인용구 소제목 {match_index} 앞의 번호 또는 이모지를 제거할 수 있습니다.",
                heading,
                blocking=False,
                safe_auto_fix=True,
                suggested_text=cleaned,
                reason="인용구 소제목 앞의 불필요한 장식을 제거해 형식을 맞춥니다.",
            )

    if faq_match is None or faq_match.group(1).strip() != "자주 묻는 질문":
        add_issue(issues, 2, "FAQ 인용구", "자주 묻는 질문 인용구 박스가 정확하지 않습니다.")

    # Stage 3: bold
    bold_blocks = re.findall(r"\*\*(.+?)\*\*", text, re.DOTALL)
    for block in bold_blocks:
        if "\n\n" in block or len(block.strip()) > 160:
            add_issue(issues, 3, "과도한 볼드", "문단 전체가 볼드 처리됐을 수 있습니다.", block.strip()[:240])
    for match in highlight_matches:
        if "**" in match.group(2):
            add_issue(issues, 3, "서식 중첩", "형광펜 안에 볼드가 중첩됐습니다.", match.group(2).strip()[:240])

    # Stage 4: highlights
    if not highlight_matches:
        add_issue(issues, 4, "형광펜", "근거가 확인된 핵심 문장 형광펜이 없습니다.")
    colors = {match.group(1) for match in highlight_matches}
    if len(colors) > 3:
        add_issue(issues, 4, "형광펜 색상", "한 원고의 형광펜 색상은 최대 3종류입니다.")
    boundaries = [match.end() for match in quote_matches]
    end_boundaries = [match.start() for match in quote_matches[1:]] + [faq_match.start() if faq_match else len(text)]
    for section_index, (start, end) in enumerate(zip(boundaries, end_boundaries), start=1):
        count = sum(start <= match.start() < end for match in highlight_matches)
        if count > 1:
            add_issue(issues, 4, "형광펜 반복", f"소제목 {section_index} 구간에 형광펜이 {count}회 사용됐습니다.")

    # Stage 5: tables
    tables = markdown_tables(text)
    if not tables:
        add_issue(issues, 5, "정보표", "본문 정보표가 없습니다.")
    for table_index, table in enumerate(tables, start=1):
        if len(table) < 3:
            add_issue(issues, 5, "표 구조", f"정보표 {table_index}에 헤더·구분 행·데이터 행이 모두 필요합니다.")
            continue
        if len(table) > 6:
            add_issue(issues, 5, "표 행 수", f"정보표 {table_index}의 데이터 행이 4개를 넘습니다.")
        expected_columns = len(table_cells(table[0]))
        if expected_columns > 2 or expected_columns < 1:
            add_issue(issues, 5, "표 열 수", f"정보표 {table_index}은 2열 이하여야 합니다.")
        for row_index, row in enumerate(table, start=1):
            cells = table_cells(row)
            if len(cells) != expected_columns:
                add_issue(issues, 5, "표 구조", f"정보표 {table_index}의 {row_index}행 열 수가 다릅니다.")
            if row_index != 2:
                for cell in cells:
                    if not cell:
                        add_issue(issues, 5, "빈 셀", f"정보표 {table_index}의 {row_index}행에 빈 셀이 있습니다.")
                    elif len(cell) > 45:
                        add_issue(
                            issues,
                            5,
                            "표 가독성",
                            f"정보표 {table_index}의 셀이 공백 포함 45자를 넘습니다.",
                            cell[:240],
                            blocking=False,
                        )
        separator = table_cells(table[1])
        if not all(re.fullmatch(r":?-{3,}:?", cell) for cell in separator):
            add_issue(issues, 5, "표 구분 행", f"정보표 {table_index}의 Markdown 구분 행이 잘못됐습니다.")

    # Stage 6: facts. Remove the fixed notice so its legal numbering is not flagged.
    fact_text = text.replace(FIXED_NOTICE, "")
    for pattern in FACT_PATTERNS:
        for match in pattern.finditer(fact_text):
            excerpt = surrounding_sentence(fact_text, match.start())
            add_issue(
                issues,
                6,
                "근거 확인",
                "수치·연구·순위 주장이 출처와 직접 연결되는지 확인해야 합니다.",
                excerpt,
                reason="자동 검사는 출처의 존재와 적용 범위를 확인할 수 없습니다.",
            )

    # Stage 7: medical and legal safety
    safety_text = text.replace(FIXED_NOTICE, "")
    for phrase in PROHIBITED_PHRASES:
        start = 0
        while True:
            index = safety_text.find(phrase, start)
            if index < 0:
                break
            add_issue(
                issues,
                7,
                "의료 금칙어",
                f"금지 또는 수정 대상 표현을 발견했습니다: {phrase}",
                surrounding_sentence(safety_text, index),
                reason="문맥과 근거를 확인한 뒤 재작성하거나 삭제해야 합니다.",
            )
            start = index + len(phrase)

    for phrase in LEGAL_REVIEW_PATTERNS:
        index = safety_text.find(phrase)
        if index >= 0:
            add_issue(
                issues,
                7,
                "법적 판단",
                f"자동으로 확정할 수 없는 법적 표현을 발견했습니다: {phrase}",
                surrounding_sentence(safety_text, index),
                reason="최신 공식 자료와 사용자 또는 관련 전문가 확인이 필요합니다.",
            )

    for match in highlight_matches:
        content = match.group(2)
        if any(phrase in content for phrase in PROHIBITED_PHRASES):
            add_issue(issues, 7, "위험 문장 강조", "의료 금칙어가 포함된 문장이 형광펜 처리됐습니다.", content.strip()[:240])

    # Stage 8: Q&A
    if not 2 <= len(question_matches) <= 3:
        add_issue(issues, 8, "Q&A 개수·볼드", f"전체 볼드 Q&A 질문은 2~3개여야 합니다. 현재 {len(question_matches)}개입니다.")
    if faq_match and final_match:
        if faq_match.start() > final_match.start():
            add_issue(issues, 8, "Q&A 위치", "Q&A는 최종 정리 앞에 있어야 합니다.")
        for question in question_matches:
            if not faq_match.end() < question.start() < final_match.start():
                add_issue(issues, 8, "Q&A 위치", "모든 Q&A 질문은 FAQ 박스와 최종 정리 사이에 있어야 합니다.")
    else:
        add_issue(issues, 8, "Q&A 위치", "FAQ 박스와 최종 정리 블록이 모두 필요합니다.")

    stage_names = {
        1: "고정 요소",
        2: "인용구",
        3: "볼드",
        4: "형광펜",
        5: "표",
        6: "일반 사실성",
        7: "의료 안전",
        8: "Q&A",
    }
    stages: dict[str, str] = {}
    for stage, name in stage_names.items():
        stage_issues = [issue for issue in issues if issue.stage == stage]
        if not stage_issues:
            stages[f"{stage}. {name}"] = "통과"
        elif any(issue.kind == "법적 판단" for issue in stage_issues):
            stages[f"{stage}. {name}"] = "사용자 확인 필요"
        elif any(issue.kind == "근거 확인" for issue in stage_issues):
            stages[f"{stage}. {name}"] = "근거 확인 필요"
        elif all(issue.safe_auto_fix or not issue.blocking for issue in stage_issues):
            stages[f"{stage}. {name}"] = "자동 수정 가능"
        else:
            stages[f"{stage}. {name}"] = "오류"

    blocking = [issue for issue in issues if issue.blocking]
    has_legal = any(issue.kind == "법적 판단" for issue in blocking)
    has_evidence = any(issue.kind == "근거 확인" for issue in blocking)
    has_medical = any(issue.stage == 7 and issue.kind != "법적 판단" for issue in blocking)
    has_format = any(issue.stage in {1, 2, 3, 4, 5, 8} for issue in blocking)
    has_autofix = any(issue.safe_auto_fix for issue in issues)

    if has_legal:
        overall = "사용자 확인 필요"
    elif has_evidence:
        overall = "근거 부족"
    elif has_medical:
        overall = "의료 표현 재작성 필요"
    elif has_format:
        overall = "네이버 서식 오류"
    elif has_autofix:
        overall = "자동 수정 후 통과"
    else:
        overall = "통과"

    return Review(
        title=expected_title,
        overall_result=overall,
        naver_input_allowed=overall in {"통과", "자동 수정 후 통과"},
        stages=stages,
        issues=issues,
    )


def print_review(review: Review) -> None:
    print(f"원본 제목: {review.title}")
    print(f"종합 결과: {review.overall_result}")
    print(f"네이버 입력 가능 여부: {'가능' if review.naver_input_allowed else '불가'}")
    print("\n8단계 결과")
    for stage, result in review.stages.items():
        print(f"- {stage}: {result}")
    if review.issues:
        print("\n문제 및 수정 제안")
        for index, issue in enumerate(review.issues, start=1):
            print(f"{index}. [{issue.kind}] {issue.message}")
            if issue.excerpt:
                print(f"   수정 전 문장: {issue.excerpt}")
            print(f"   수정한 문장: {issue.suggested_text}")
            if issue.reason:
                print(f"   수정 이유: {issue.reason}")
    print(f"\n{review.disclaimer}")


def sample_draft(title: str) -> str:
    return f"""[NAVER_TITLE]{title}[/NAVER_TITLE]

[DIVIDER]

{FIXED_NOTICE}

[TITLE_BOX_LIGHT_GREEN_CENTER]{title}[/TITLE_BOX_LIGHT_GREEN_CENTER]

운동을 마친 뒤 허리가 불편하면 통증이 나타난 동작과 시점을 살펴볼 수 있습니다. 증상만으로 원인을 하나로 단정하기는 어렵습니다.

[HIGHLIGHT_PINK]허리 통증은 여러 원인과 관련될 수 있어 나타나는 조건을 함께 확인해야 합니다.[/HIGHLIGHT_PINK]

[QUOTE_HEADING]운동 중 허리에 부담이 커지는 상황은 무엇일까요?[/QUOTE_HEADING]

평소와 다른 자세나 갑작스러운 강도 변화가 있었는지 확인합니다. 같은 동작에서 불편함이 반복되는지도 살펴봅니다.

[HIGHLIGHT_YELLOW]통증이 나타난 동작과 시점을 기록하면 상황을 정리하는 데 도움이 됩니다.[/HIGHLIGHT_YELLOW]

| 살펴볼 상황 | 확인할 부분 |
|---|---|
| 운동을 시작할 때 | 특정 동작과 관련되는지 |
| 휴식을 취했을 때 | 불편함이 달라지는지 |

[QUOTE_HEADING]불편함이 생기면 운동을 어떻게 조절할까요?[/QUOTE_HEADING]

불편함을 참고 같은 강도를 유지하기보다 부담을 주는 동작을 줄이고 변화를 살펴봅니다.

[QUOTE_HEADING]어떤 내용을 기록하면 도움이 될까요?[/QUOTE_HEADING]

시작 시점, 지속 양상, 불편함이 커지는 동작을 적습니다. 다른 증상이 함께 있는지도 확인합니다.

[FAQ_BOX]자주 묻는 질문[/FAQ_BOX]

**Q. 운동 후 허리가 아프면 특정 질환인가요?**

증상만으로 특정 질환을 단정하기는 어렵습니다.

**Q. 불편해도 같은 운동을 계속해도 될까요?**

부담을 주는 동작과 강도를 조절하고 변화를 살펴보는 것이 좋습니다.

[FINAL_SUMMARY]
불편함이 나타난 시점과 관련 동작을 기록해 현재 상황을 차분히 확인해 보세요.
[/FINAL_SUMMARY]
"""


def self_test() -> int:
    title = "운동 후 허리가 아픈 이유는 무엇일까요?"
    safe_review = review_draft(sample_draft(title), title)
    if safe_review.overall_result != "통과":
        print(f"SELF-TEST FAILED: 정상 원고가 {safe_review.overall_result}로 분류됐습니다.")
        print_review(safe_review)
        return 1

    prohibited = sample_draft(title).replace(
        "증상만으로 원인을 하나로 단정하기는 어렵습니다.",
        "반드시 치료됩니다.",
    )
    prohibited_review = review_draft(prohibited, title)
    if prohibited_review.overall_result != "의료 표현 재작성 필요":
        print(f"SELF-TEST FAILED: 금칙어 원고가 {prohibited_review.overall_result}로 분류됐습니다.")
        return 1

    malformed = sample_draft(title).replace("[DIVIDER]", "")
    malformed_review = review_draft(malformed, title)
    if malformed_review.overall_result != "네이버 서식 오류":
        print(f"SELF-TEST FAILED: 서식 오류 원고가 {malformed_review.overall_result}로 분류됐습니다.")
        return 1

    mismatch_review = review_draft(sample_draft(title), "다른 제목")
    if mismatch_review.overall_result != "네이버 서식 오류":
        print(f"SELF-TEST FAILED: 제목 불일치가 {mismatch_review.overall_result}로 분류됐습니다.")
        return 1

    print("SELF-TEST PASSED: 정상, 금칙어, 구분선 오류, 제목 불일치 분류를 확인했습니다.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="의료 표현과 네이버 원고 구조를 사전 검수합니다.")
    parser.add_argument("draft", nargs="?", type=Path, help="검수할 Markdown 원고")
    parser.add_argument("--title", help="사용자가 제공한 원본 제목")
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력합니다.")
    parser.add_argument("--self-test", action="store_true", help="내장 예시로 분류 동작을 검사합니다.")
    return parser.parse_args()


def main() -> int:
    configure_output()
    args = parse_args()
    if args.self_test:
        return self_test()
    if args.draft is None or args.title is None:
        print("오류: 원고 경로와 --title 또는 --self-test가 필요합니다.", file=sys.stderr)
        return 2
    try:
        text = args.draft.read_text(encoding="utf-8")
    except OSError as exc:
        print(f"오류: 원고를 읽을 수 없습니다: {exc}", file=sys.stderr)
        return 2

    review = review_draft(text, args.title)
    if args.json:
        print(json.dumps(asdict(review), ensure_ascii=False, indent=2))
    else:
        print_review(review)
    return 0 if review.naver_input_allowed else 1


if __name__ == "__main__":
    raise SystemExit(main())

