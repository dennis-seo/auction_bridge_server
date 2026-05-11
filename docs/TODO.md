# TODO — Onbid 통합 백엔드 로드맵

스케줄러/도메인 확장 작업 트래킹. **항목 완료 시 체크박스 ✓로 표시하고 PR 머지 후 줄 자체를 삭제**한다. 이 파일은 "남은 일"만 살아있게 유지.

> 우선순위 표기는 `[P0]`(즉시) / `[P1]`(이번 분기) / `[P2]`(여유 생기면) 기준.

---

## A. 운영 정합성 (이번 #7 PR 직속)

- [ ] **A3. `/admin/*` 인증 게이트** — 현재 prod에도 무인증 노출. 간단한 헤더 토큰(`X-Admin-Key`) 또는 IP allowlist. `CLAUDE.md`의 "1차에는 인증 없이 local 한정" 주석 제거. `[P0]`

## B. 미사용 도메인 (스키마 신설 필요)

- [ ] **B1. 공고 도메인 (#10/#11/#13)** — `announcements` 테이블 + 매물과 N:1 관계. 공고 단위 메타(공고명/공고기관/공고유형/PDF URL) 보강. UI 요건 확정 후 착수. `[P2]`
- [ ] **B2. 공고 입찰결과 (#14/#15)** — 현재 매물 단위 `#8/#9`로 90%+ 커버됨. 공고 단위 결과 화면이 필요할 때만. `[P2]`
- [ ] **B3. 정부재산 도메인 (#20/#21/#22)** — 국유/공유/친일귀속 일반재산. 새 메뉴 의도 확정 후. `[P2]`
- [ ] **B4. 지역별 입찰 통계 (#25)** — 자체 DB 집계로 80% 산출 가능. 외부 API 결과와 비교용으로만 필요할 때. `[P2]`

## C. 마스터/유틸 (주 1회 cron)

- [ ] **C1. 코드 및 주소 마스터 sync (#24)** — `code_master(category, code, name)` 테이블 + 주 1회 `Sun 04:00 KST` cron. 현재 하드코딩된 `ASSET_TYPE_LABELS_KO` 등 점진적으로 마스터 참조로 전환. `pbancKindCd`(공고유형), `exctStatCd`(집행상태) 신규 반영. `[P1]`

## D. 기존 코드 개선

- [ ] **D1. realty / movable 전용 엔드포인트 분리** — 자동차 `/api/v1/vehicles` 패턴을 부동산/동산에도 동일 적용. 자산타입별 필터/리스트/통계 일관성. `[P1]`
- [ ] **D2. `auction_movable_details` 인덱스 추가** — 동산 검색/필터 endpoint 만들 때 함께. 후보: `(maker, model_name)`, `commodity_name`. `[P2]`
- [ ] **D3. 정정공고(`crtnYn=Y`) 처리** — 현재 boolean만 저장. `crtnLstClgList`(정정내역 array)를 별도 JSONB 컬럼 또는 별도 테이블로 보관. 매물 상세에 "변경 이력" 섹션. `[P2]`
- [ ] **D4. Quota 사용량 메트릭** — 단계별 `api_calls` 집계를 Cloud Run 구조화 로그로 emit. Grafana/Looker로 일일 quota 사용률 추적. `[P1]`
- [ ] **D5. `bid_info` 핵심 필드 컬럼 승격** — 슬림화(A2) 후 사용 패턴 1~2개월 관찰. 가장 많이 SQL 필터에 쓰이는 boolean 3~5개(공동입찰/대리입찰/전자보증서)를 column으로 승격해 인덱스 가능하게. `[P2]`

## E. 회의/검증 필요 (티켓화 전 단계)

- [ ] **E1. `enrich_bid_info` 우선순위** — 현재 active 매물 중 미보강 N건을 ID 순으로 선택. 입찰 임박(`bid_end_at`)이 가까운 매물부터 보강하는 게 가치 큼. `list_auctions_missing_bid_info`의 ORDER BY 변경 검토. `[P2]`
- [ ] **E2. `auctions.raw` 압축/만료** — 일별 누적되는 raw JSONB가 DB 용량 늘림. 일정 시간 지난 SOLD/FAILED row의 raw를 NULL로 비우는 retention 정책. `[P2]`

---

## 작업 흐름 컨벤션

1. 항목 시작할 때 PR 브랜치명에 라벨 포함: `feat/A2-bid-info-slim`, `feat/B1-announcements`.
2. PR 머지 후 본 파일에서 **해당 줄 삭제** (체크박스 두지 않고 그냥 삭제). 히스토리는 git log로 추적.
3. 새로 발견된 작업은 **카테고리(A~E) + 우선순위([P0~P2])** 만 정해 추가. 상세 설명은 PR 문서에서.
