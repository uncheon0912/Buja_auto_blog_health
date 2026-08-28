#!/usr/bin/env python3
"""Validate a research ledger without network access or third-party packages."""

from __future__ import annotations

import argparse
import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any


ALLOWED_CATEGORIES = {
    "일반 생활정보",
    "금융·보험 정보",
    "법률·세무 정보",
    "병원·건강·의료 정보",
    "기타 전문정보",
}

ALLOWED_STATUSES = {
    "입력 완료",
    "주제 분석",
    "자료 확인",
    "원고 작성",
    "의료·표현 검수",
    "네이버 입력",
    "임시저장 완료",
    "실패 또는 사용자 확인 필요",
}

MEDICAL_TERMS = (
    "병원",
    "건강",
    "증상",
    "통증",
    "질환",
    "치료",
    "시술",
    "수술",
    "진단",
    "의약품",
    "회복",
    "재활",
    "허리",
)

REQUIRED_TITLE_FIELDS = {
    "number",
    "original_title",
    "category",
    "medical_safety_mode",
    "core_question",
    "required_materials",
    "verified_sources",
    "unverified_items",
    "writing_cautions",
    "similar_to",
    "status",
}

REQUIRED_SOURCE_FIELDS = {
    "source_id",
    "verified_fact",
    "organization",
    "document_title",
    "published_or_revised_date",
    "checked_date",
    "url",
    "scope_or_caution",
}


def normalized_title(value: str) -> str:
    return re.sub(r"[^0-9A-Za-z가-힣]", "", value).lower()


def similarity(left: str, right: str) -> float:
    return SequenceMatcher(None, normalized_title(left), normalized_title(right)).ratio()


def require_nonempty_string(item: dict[str, Any], field: str, label: str, errors: list[str]) -> None:
    value = item.get(field)
    if not isinstance(value, str) or not value.strip():
        errors.append(f"{label}: '{field}' 값이 비어 있거나 문자열이 아닙니다.")


def require_list(item: dict[str, Any], field: str, label: str, errors: list[str]) -> None:
    if not isinstance(item.get(field), list):
        errors.append(f"{label}: '{field}' 값은 배열이어야 합니다.")


def validate_ledger(data: Any, expected_titles: list[str] | None = None) -> list[str]:
    errors: list[str] = []
    if not isinstance(data, dict):
        return ["최상위 JSON 값은 객체여야 합니다."]

    titles = data.get("titles")
    if not isinstance(titles, list) or not titles:
        return ["'titles'는 하나 이상의 제목 객체를 가진 배열이어야 합니다."]

    if expected_titles is not None and len(titles) != len(expected_titles):
        errors.append(
            f"제목 수가 다릅니다: 입력 {len(expected_titles)}개, 결과 {len(titles)}개."
        )

    seen_numbers: set[int] = set()
    actual_titles: list[str] = []

    for index, item in enumerate(titles, start=1):
        label = f"제목 {index:02d}"
        if not isinstance(item, dict):
            errors.append(f"{label}: 객체가 아닙니다.")
            continue

        missing = sorted(REQUIRED_TITLE_FIELDS - set(item))
        if missing:
            errors.append(f"{label}: 필수 필드 누락: {', '.join(missing)}")

        number = item.get("number")
        if number != index:
            errors.append(f"{label}: number는 입력 순서와 같은 {index}이어야 합니다.")
        if isinstance(number, int):
            if number in seen_numbers:
                errors.append(f"{label}: 제목 번호 {number}가 중복되었습니다.")
            seen_numbers.add(number)

        require_nonempty_string(item, "original_title", label, errors)
        require_nonempty_string(item, "core_question", label, errors)
        for field in (
            "required_materials",
            "verified_sources",
            "unverified_items",
            "writing_cautions",
            "similar_to",
        ):
            require_list(item, field, label, errors)

        original_title = item.get("original_title")
        if isinstance(original_title, str):
            actual_titles.append(original_title)
            if expected_titles is not None and index <= len(expected_titles):
                if original_title != expected_titles[index - 1]:
                    errors.append(
                        f"{label}: 원본 제목이 문자 단위로 일치하지 않습니다."
                    )

            if any(term in original_title for term in MEDICAL_TERMS):
                if item.get("medical_safety_mode") is not True:
                    errors.append(f"{label}: 의료 관련 표현이 있으므로 의료 안전 모드가 필요합니다.")

        if not isinstance(item.get("medical_safety_mode"), bool):
            errors.append(f"{label}: medical_safety_mode는 true 또는 false여야 합니다.")

        if item.get("category") not in ALLOWED_CATEGORIES:
            errors.append(f"{label}: 허용되지 않은 주제 분류입니다.")

        status = item.get("status")
        if status not in ALLOWED_STATUSES:
            errors.append(f"{label}: 허용되지 않은 상태입니다.")

        sources = item.get("verified_sources")
        if isinstance(sources, list):
            if status in {
                "자료 확인",
                "원고 작성",
                "의료·표현 검수",
                "네이버 입력",
                "임시저장 완료",
            } and not sources:
                errors.append(f"{label}: 현재 상태에는 하나 이상의 확인된 출처가 필요합니다.")
            for source_index, source in enumerate(sources, start=1):
                source_label = f"{label} 출처 {source_index:02d}"
                if not isinstance(source, dict):
                    errors.append(f"{source_label}: 객체가 아닙니다.")
                    continue
                missing_source = sorted(REQUIRED_SOURCE_FIELDS - set(source))
                if missing_source:
                    errors.append(
                        f"{source_label}: 필수 필드 누락: {', '.join(missing_source)}"
                    )
                url = source.get("url")
                if not isinstance(url, str) or not re.match(r"^https?://", url):
                    errors.append(f"{source_label}: 원문 URL은 http 또는 https 주소여야 합니다.")

        if item.get("medical_safety_mode") is True and status not in {
            "입력 완료",
            "주제 분석",
            "자료 확인",
            "원고 작성",
            "의료·표현 검수",
            "네이버 입력",
            "임시저장 완료",
            "실패 또는 사용자 확인 필요",
        }:
            errors.append(f"{label}: 의료 안전 모드의 상태가 올바르지 않습니다.")

    for left_index in range(len(titles)):
        left = titles[left_index]
        if not isinstance(left, dict) or not isinstance(left.get("original_title"), str):
            continue
        for right_index in range(left_index + 1, len(titles)):
            right = titles[right_index]
            if not isinstance(right, dict) or not isinstance(right.get("original_title"), str):
                continue
            score = similarity(left["original_title"], right["original_title"])
            if score >= 0.78:
                left_refs = left.get("similar_to") if isinstance(left.get("similar_to"), list) else []
                right_refs = right.get("similar_to") if isinstance(right.get("similar_to"), list) else []
                if (right_index + 1) not in left_refs and (left_index + 1) not in right_refs:
                    errors.append(
                        f"제목 {left_index + 1:02d}과 {right_index + 1:02d}은 유사도 "
                        f"{score:.2f}이지만 similar_to에 표시되지 않았습니다."
                    )

    return errors


def self_test() -> int:
    expected = [
        "자동차보험 치료비는 누가 부담할까요?",
        "교통사고 후 병원은 언제 가야 할까요?",
        "운동 후 허리가 아픈 이유는 무엇일까요?",
    ]
    sample = {
        "research_date": "2026-08-27",
        "titles": [
            {
                "number": number,
                "original_title": title,
                "category": "병원·건강·의료 정보",
                "medical_safety_mode": True,
                "core_question": "조사 단계에서 확인할 핵심 질문입니다.",
                "required_materials": ["공식 자료 확인 필요"],
                "verified_sources": [],
                "unverified_items": ["아직 자료 조사 전"],
                "writing_cautions": ["확인 전 단정 금지"],
                "similar_to": [],
                "status": "주제 분석",
            }
            for number, title in enumerate(expected, start=1)
        ],
    }
    errors = validate_ledger(sample, expected)
    if errors:
        print("SELF-TEST FAILED")
        for error in errors:
            print(f"- {error}")
        return 1
    print("SELF-TEST PASSED: 제목 3개의 수, 순서, 원문, 의료 안전 모드를 확인했습니다.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="정보성 블로그 조사 장부를 검증합니다.")
    parser.add_argument("ledger", nargs="?", type=Path, help="검증할 JSON 장부 경로")
    parser.add_argument(
        "--expected-title",
        action="append",
        default=None,
        help="입력 원본 제목. 입력 순서대로 여러 번 지정할 수 있습니다.",
    )
    parser.add_argument("--self-test", action="store_true", help="내장 예시로 구조를 검증합니다.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.self_test:
        return self_test()
    if args.ledger is None:
        print("오류: JSON 장부 경로 또는 --self-test가 필요합니다.", file=sys.stderr)
        return 2
    try:
        data = json.loads(args.ledger.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"오류: 장부를 읽을 수 없습니다: {exc}", file=sys.stderr)
        return 2

    errors = validate_ledger(data, args.expected_title)
    if errors:
        print(f"검증 실패: {len(errors)}개 문제를 발견했습니다.")
        for error in errors:
            print(f"- {error}")
        return 1
    print(f"검증 통과: 제목 {len(data['titles'])}개의 구조와 안전 규칙을 확인했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

