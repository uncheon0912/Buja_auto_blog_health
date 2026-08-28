#!/usr/bin/env python3
"""Validate a draft-save run manifest without launching or controlling a browser."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ALLOWED_REVIEW_STATUSES = {"통과", "자동 수정 후 통과"}
FORBIDDEN_SECRET_KEYS = {
    "naver_id",
    "username",
    "user_id",
    "password",
    "passwd",
    "cookie",
    "cookies",
    "session",
    "session_id",
    "auth_code",
    "otp",
    "captcha_answer",
}
REQUIRED_ITEM_FIELDS = {
    "number",
    "total",
    "title",
    "draft_path",
    "review_status",
    "reviewed_sha256",
    "medical",
    "already_completed",
}
TITLE_RE = re.compile(r"\[NAVER_TITLE\](.*?)\[/NAVER_TITLE\]", re.DOTALL)
BOX_RE = re.compile(
    r"\[TITLE_BOX_LIGHT_GREEN_CENTER\](.*?)\[/TITLE_BOX_LIGHT_GREEN_CENTER\]",
    re.DOTALL,
)


def configure_output() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8")


def find_secret_keys(value: Any, location: str = "manifest") -> list[str]:
    findings: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            if str(key).lower() in FORBIDDEN_SECRET_KEYS:
                findings.append(f"{location}.{key}")
            findings.extend(find_secret_keys(child, f"{location}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            findings.extend(find_secret_keys(child, f"{location}[{index}]"))
    return findings


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def read_draft(
    path: Path,
    relative_path: str,
    virtual_files: dict[str, bytes] | None,
) -> tuple[bytes | None, str | None]:
    if virtual_files is not None:
        content = virtual_files.get(relative_path.replace("\\", "/"))
        if content is None:
            return None, "가상 원고를 찾을 수 없습니다."
        return content, None
    if path.is_symlink():
        return None, "심볼릭 링크 원고는 허용하지 않습니다."
    if not path.is_file():
        return None, "원고 파일이 존재하지 않습니다."
    try:
        return path.read_bytes(), None
    except OSError as exc:
        return None, f"원고 파일을 읽을 수 없습니다: {exc}"


def validate_manifest(
    data: Any,
    project_root: Path,
    virtual_files: dict[str, bytes] | None = None,
) -> tuple[list[str], dict[str, Any]]:
    errors: list[str] = []
    summary: dict[str, Any] = {
        "total": 0,
        "completed": 0,
        "pending": 0,
        "resume_from": None,
        "planned_waits": 0,
    }

    if not isinstance(data, dict):
        return ["실행 명세의 최상위 값은 객체여야 합니다."], summary

    secret_keys = find_secret_keys(data)
    if secret_keys:
        errors.append(
            "실행 명세에 저장하면 안 되는 로그인·인증 필드가 있습니다: "
            + ", ".join(secret_keys)
        )

    items = data.get("items")
    if not isinstance(items, list) or not items:
        return errors + ["items는 하나 이상의 원고 항목을 가진 배열이어야 합니다."], summary

    total = len(items)
    summary["total"] = total
    resume_from = data.get("resume_from", 1)
    if not isinstance(resume_from, int) or not 1 <= resume_from <= total + 1:
        errors.append(f"resume_from은 1부터 {total + 1} 사이의 정수여야 합니다.")
        resume_from = 1
    summary["resume_from"] = resume_from

    resolved_root = project_root.resolve()
    seen_paths: set[Path] = set()
    first_incomplete: int | None = None
    completed_count = 0

    for index, item in enumerate(items, start=1):
        label = f"항목 {index:02d}"
        if not isinstance(item, dict):
            errors.append(f"{label}: 객체가 아닙니다.")
            continue

        missing = sorted(REQUIRED_ITEM_FIELDS - set(item))
        if missing:
            errors.append(f"{label}: 필수 필드 누락: {', '.join(missing)}")

        if item.get("number") != index:
            errors.append(f"{label}: number는 제목 순서와 같은 {index}이어야 합니다.")
        if item.get("total") != total:
            errors.append(f"{label}: total은 전체 제목 수 {total}이어야 합니다.")

        title = item.get("title")
        if not isinstance(title, str) or not title:
            errors.append(f"{label}: title은 비어 있지 않은 문자열이어야 합니다.")

        status = item.get("review_status")
        if status not in ALLOWED_REVIEW_STATUSES:
            errors.append(
                f"{label}: 검수 상태 '{status}'는 네이버 입력이 허용되지 않습니다."
            )

        if not isinstance(item.get("medical"), bool):
            errors.append(f"{label}: medical은 true 또는 false여야 합니다.")
        completed = item.get("already_completed")
        if not isinstance(completed, bool):
            errors.append(f"{label}: already_completed는 true 또는 false여야 합니다.")
            completed = False
        if completed:
            completed_count += 1
        elif first_incomplete is None:
            first_incomplete = index

        relative = item.get("draft_path")
        if not isinstance(relative, str) or not relative.strip():
            errors.append(f"{label}: draft_path는 프로젝트 상대 경로여야 합니다.")
            continue
        relative_normalized = relative.replace("\\", "/")
        candidate = (resolved_root / relative_normalized).resolve()
        if not is_within(candidate, resolved_root):
            errors.append(f"{label}: 원고 경로가 현재 프로젝트 밖을 가리킵니다.")
            continue
        if candidate in seen_paths:
            errors.append(f"{label}: 같은 원고 파일 경로가 중복됐습니다.")
        seen_paths.add(candidate)

        content_bytes, read_error = read_draft(candidate, relative_normalized, virtual_files)
        if read_error:
            errors.append(f"{label}: {read_error}")
            continue
        assert content_bytes is not None
        try:
            content_text = content_bytes.decode("utf-8")
        except UnicodeDecodeError:
            errors.append(f"{label}: 원고는 UTF-8 텍스트여야 합니다.")
            continue

        reviewed_hash = item.get("reviewed_sha256")
        if not isinstance(reviewed_hash, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", reviewed_hash):
            errors.append(f"{label}: reviewed_sha256은 64자리 SHA-256이어야 합니다.")
        elif sha256_bytes(content_bytes).lower() != reviewed_hash.lower():
            errors.append(f"{label}: 현재 원고가 검수 당시 원고와 다릅니다. 재검수가 필요합니다.")

        title_blocks = TITLE_RE.findall(content_text)
        box_blocks = BOX_RE.findall(content_text)
        if len(title_blocks) != 1 or title_blocks[0] != title:
            errors.append(f"{label}: [NAVER_TITLE]이 원본 제목과 문자 단위로 일치하지 않습니다.")
        if len(box_blocks) != 1 or box_blocks[0] != title:
            errors.append(f"{label}: 제목 박스가 원본 제목과 문자 단위로 일치하지 않습니다.")
        if len(title_blocks) == 1 and len(box_blocks) == 1 and title_blocks[0] != box_blocks[0]:
            errors.append(f"{label}: 상단 제목과 제목 박스가 서로 다릅니다.")

    if first_incomplete is None:
        first_incomplete = total + 1
    if resume_from != first_incomplete:
        errors.append(
            f"resume_from은 첫 미완료 번호 {first_incomplete}이어야 합니다. 현재 {resume_from}입니다."
        )
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            expected_completed = index < first_incomplete
            if item.get("already_completed") is not expected_completed:
                errors.append(
                    f"항목 {index:02d}: 완료 항목은 앞에서부터 연속돼야 합니다."
                )

    pending_count = total - completed_count
    summary["completed"] = completed_count
    summary["pending"] = pending_count
    summary["planned_waits"] = max(0, pending_count - 1)
    return errors, summary


def sample_draft(title: str) -> bytes:
    return (
        f"[NAVER_TITLE]{title}[/NAVER_TITLE]\n\n"
        "[DIVIDER]\n\n"
        f"[TITLE_BOX_LIGHT_GREEN_CENTER]{title}[/TITLE_BOX_LIGHT_GREEN_CENTER]\n\n"
        "검수 완료 원고 본문"
    ).encode("utf-8")


def sample_manifest(contents: list[tuple[str, bytes]], statuses: list[str] | None = None) -> dict[str, Any]:
    total = len(contents)
    if statuses is None:
        statuses = ["통과"] * total
    items = []
    for index, ((title, content), status) in enumerate(zip(contents, statuses), start=1):
        items.append(
            {
                "number": index,
                "total": total,
                "title": title,
                "draft_path": f"Contents/{index:02d}.md",
                "review_status": status,
                "reviewed_sha256": sha256_bytes(content),
                "medical": True,
                "already_completed": False,
            }
        )
    return {"resume_from": 1, "items": items}


def self_test(project_root: Path) -> int:
    titles = ["첫 번째 제목", "두 번째 제목"]
    contents = [(title, sample_draft(title)) for title in titles]
    virtual_files = {f"Contents/{index:02d}.md": content for index, (_, content) in enumerate(contents, start=1)}

    valid = sample_manifest(contents)
    errors, summary = validate_manifest(valid, project_root, virtual_files)
    if errors or summary["planned_waits"] != 1:
        print("SELF-TEST FAILED: 정상 실행 명세")
        for error in errors:
            print(f"- {error}")
        return 1

    blocked = sample_manifest(contents, ["통과", "근거 부족"])
    blocked_errors, _ = validate_manifest(blocked, project_root, virtual_files)
    if not any("허용되지 않습니다" in error for error in blocked_errors):
        print("SELF-TEST FAILED: 미통과 상태 차단")
        return 1

    tampered = sample_manifest(contents)
    tampered["items"][0]["reviewed_sha256"] = "0" * 64
    tampered_errors, _ = validate_manifest(tampered, project_root, virtual_files)
    if not any("검수 당시 원고와 다릅니다" in error for error in tampered_errors):
        print("SELF-TEST FAILED: 원고 변조 차단")
        return 1

    wrong_order = sample_manifest(contents)
    wrong_order["items"][1]["number"] = 1
    order_errors, _ = validate_manifest(wrong_order, project_root, virtual_files)
    if not any("제목 순서" in error for error in order_errors):
        print("SELF-TEST FAILED: 순서 오류 차단")
        return 1

    print("SELF-TEST PASSED: 정상, 미통과 상태, 원고 변조, 순서 오류를 확인했습니다.")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="네이버 임시저장 실행 명세를 사전 점검합니다.")
    parser.add_argument("manifest", nargs="?", type=Path, help="검사할 JSON 실행 명세")
    parser.add_argument(
        "--project-root",
        type=Path,
        default=Path.cwd(),
        help="원고 파일이 있어야 하는 프로젝트 루트",
    )
    parser.add_argument("--self-test", action="store_true", help="파일 생성 없이 내장 예시를 검사합니다.")
    return parser.parse_args()


def main() -> int:
    configure_output()
    args = parse_args()
    project_root = args.project_root.resolve()
    if args.self_test:
        return self_test(project_root)
    if args.manifest is None:
        print("오류: 실행 명세 경로 또는 --self-test가 필요합니다.", file=sys.stderr)
        return 2
    try:
        data = json.loads(args.manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"오류: 실행 명세를 읽을 수 없습니다: {exc}", file=sys.stderr)
        return 2

    errors, summary = validate_manifest(data, project_root)
    if errors:
        print(f"사전 점검 실패: {len(errors)}개 문제를 발견했습니다.")
        for error in errors:
            print(f"- {error}")
        print("브라우저 자동화를 시작하지 마세요.")
        return 1

    print("사전 점검 통과")
    print(f"- 전체 제목: {summary['total']}개")
    print(f"- 완료됨: {summary['completed']}개")
    print(f"- 처리 예정: {summary['pending']}개")
    print(f"- 재개 번호: {summary['resume_from']}")
    print(f"- 예정된 60초 대기: {summary['planned_waits']}회")
    print("사용자에게 PC 사용 중단 안내를 하고 확인받은 뒤에만 브라우저 자동화를 시작하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

