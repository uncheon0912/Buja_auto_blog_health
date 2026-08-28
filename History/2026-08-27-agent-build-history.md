# 정보성 블로그 제목·자료 수집 에이전트 구축 이력

## 작업 정보

- 작업일: 2026-08-27 (Asia/Seoul)
- 프로젝트: `E:\Codex\Testall_2\Buja_auto_blog_helath`
- 작업 유형: 신규 프로젝트 전용 Codex 에이전트 스킬 구축
- 기존 파일 변경: 없음
- 기존 파일 삭제·덮어쓰기·이름 변경: 없음

## 사용자 요구와 결정

- 사용자가 제공한 제목의 개수, 순서, 원문을 유지한다.
- 사용자 승인 없이 제목을 수정하거나 키워드를 추가하지 않는다.
- 동일하거나 유사한 제목을 삭제하지 않고 표시한다.
- 각 제목을 지정된 정보 유형으로 분류한다.
- 의료 관련 제목에는 의료 안전 모드를 적용한다.
- 최신성이 필요한 내용은 웹 검색으로 확인하고 공식 출처를 우선한다.
- 확인되지 않은 수치, 사례, 통계, 치료 효과를 만들지 않는다.
- 의료법 제56조·제57조와 의료광고 관련 공식 자료를 작성 시점에 다시 확인한다.
- 의료 관련 최종 원고는 자동 발행하지 않고 임시저장까지만 처리한다.
- 작업 결과와 사용자 결정은 프로젝트 내부 `History` 폴더에 기록한다.
- 사용자는 OpenAI API 값을 넣지 않고 Codex 내부 기능으로만 진행하도록 결정했다.
- 2026-08-27 사용자가 사전 구현 계획을 승인했다.

## 구현 방식

- 별도 API 키나 외부 유료 검색 API를 사용하지 않는 프로젝트 전용 Codex 스킬
- 핵심 실행 규칙과 의료·출처·출력 정책을 분리한 점진적 참조 구조
- Python 표준 라이브러리만 사용하는 오프라인 결과 장부 검증기
- 프로젝트 밖의 전역 스킬 폴더에는 설치하지 않음

## 생성 파일

- `2026-08-27-information-blog-research-agent/SKILL.md`
- `2026-08-27-information-blog-research-agent/agents/openai.yaml`
- `2026-08-27-information-blog-research-agent/references/2026-08-27-medical-safety-policy.md`
- `2026-08-27-information-blog-research-agent/references/2026-08-27-research-source-policy.md`
- `2026-08-27-information-blog-research-agent/references/2026-08-27-output-schema.md`
- `2026-08-27-information-blog-research-agent/scripts/2026-08-27-validate-research-output.py`
- `2026-08-27-agent-usage-guide.md`
- `History/2026-08-27-agent-build-history.md`

## 검증 결과

### 내장 예시 검증

- 입력: 사용자 예시 제목 3개
- 확인 항목: 제목 수, 입력 순서, 원문 일치, 의료 안전 모드
- 결과: 통과
- 출력: `SELF-TEST PASSED: 제목 3개의 수, 순서, 원문, 의료 안전 모드를 확인했습니다.`

### 스킬 형식 검증

- 검사 도구: skill-creator `quick_validate.py`
- Windows 기본 cp949 실행에서는 UTF-8 한국어 파일을 읽지 못해 검사기 자체가 중단됨
- `PYTHONUTF8=1` 환경에서 재실행
- 결과: 통과
- 출력: `Skill is valid!`

## 안전 경계

- 조사 결과의 출처 내용 자체는 실행 시점에 웹 원문을 열어 확인해야 한다.
- 파일 구조 검증은 출처의 진실성을 대신하지 않는다.
- 네이버 입력은 사용자의 명시적 요청이 있을 때만 진행한다.
- 의료 관련 원고는 발행·예약 발행·공개 전환을 수행하지 않는다.
