# 우리카드 OCR POC v2 — 문서 특화 AI 서비스 업그레이드 계획

> 작성일: 2026-05-26 · 베이스: `WOORI_POC_PLAN.md` (v1)
> 목적: 7개 핵심 기술 영역을 모두 반영한 **문서 특화 AI 서비스**로 v1에서 한 단계 진화.

## 0. 한 줄

> "문서를 글자로 읽는 OCR을 넘어, **구조·문맥·위치·관계·보안 위험까지 이해하고 정형 데이터로 변환**하는 문서 특화 AI."
> v1이 "단일 추출 파이프라인"이었다면 v2는 **근거 기반 추출 + Human-in-the-Loop 검수 + 보안 비식별화**가 1급 시민.

## 1. 7개 기술 영역 → 현재 상태 매트릭스

| # | 기술 영역 | v1 현황 (이미 갖춤) | v2 추가 (이 plan) |
|---|---|---|---|
| 1 | **문서 특화 VLM** | Qwen2.5-VL-7B + GLM-OCR + PP-DocLayoutV3 (vLLM 라우팅, 비교 모드) | 도장/서명 layout 클래스 노출, 표 셀 추출기 더 강화, **자동 문서 유형 분류 (VLM)** |
| 2 | **Near-Zero Hallucination** | 정규식 + 체크섬 + 사전매칭 + 교차검증 + bbox 역매칭 | **Grounding validator**: source_match 가 raw OCR 에 실제 존재하는지 substring·fuzzy 검증, 미존재면 `ungrounded` 상태로 강제 표시 + confidence↓ |
| 3 | **문서 구조화·파싱** | 4종 도메인 추출기 (가맹점/신분증/통장/사업자등록증), 표 셀 라벨 47개 | **자동 문서 유형 분류**, **혼합 문서 분리** (PDF 다중 문서), 표 추출기 강화 |
| 4 | **개인정보 탐지·비식별화** | 주민·외국인 RRN 마스킹, 계좌·휴대폰 마스킹 | **이메일·주소·이름 자동 탐지**, **마스킹 정책 (none/partial/full)** API, PII 통계 응답, 감사로그 영속화 |
| 5 | **저품질 문서 복원** | `preprocess.py` 단독 스크립트 (deskew/CLAHE/unsharp) | **백엔드 자동 전처리 토글**, 초해상화 (선택, RealESRGAN/bicubic), OCR 전 자동 정제 파이프라인 |
| 6 | **서명·도장 검출·위변조** | PP-Layout 이 stamp/signature 클래스를 인식 (사용 안 함) | **stamp/signature 블록 별도 응답** + UI 시각화, (선택) embedding 기반 유사도 비교 |
| 7 | **Human-in-the-Loop** | 카드 hover→bbox 강조, 마스킹 토글 | **인라인 값 편집**, **필드별 ✓/✗ 승인**, **수정 이력 audit**, **승인된 JSON Export**, 학습 피드백 자료 적재 |

## 2. Phase 분해 (4-5주)

### Phase 1 — Trust 강화 (이번 라운드 즉시 시작)
가장 시연 임팩트가 크고 v1 결과를 그대로 신뢰성 ↑.

| 트랙 | 범위 | 추정 |
|---|---|---|
| **1-A. Grounding** | `core/validators/grounding.py`. 모든 ExtractedField에 적용. raw OCR에 source_match 부분 존재 여부 → ok/fuzzy/ungrounded | 백엔드 ~100줄 + 테스트 |
| **1-B. PII 확장** | `core/validators/pii.py`. 이메일·주소·이름. `masking_level` API 파라미터. PII 통계 응답 | 백엔드 ~150줄 + 테스트 |
| **1-C. HITL** | 카드 인라인 편집·승인 배지·Export. 수정 이력 store audit | 프론트 ~250줄 |
| **1-D. 도장/서명 노출** | layout_ocr 응답에 stamps/signatures 별도, 우리카드 신청서 데모용 | 백엔드 ~30줄 |

### Phase 2 — 자동화 (다음 라운드)
- **2-A. 자동 문서 유형 분류** — Qwen2.5-VL에게 분류 prompt → 결과로 라우팅 (사용자가 freeform으로 올려도 자동 매핑)
- **2-B. 자동 전처리** — `preprocess.py`를 layout_ocr 전에 자동 적용 토글 (deskew/CLAHE/binarize)
- **2-C. 혼합 문서 분리** — 여러 문서가 섞인 PDF에서 자동 분할 (페이지별 분류 + 클러스터링)

### Phase 3 — 보안/관측성
- **3-A. 감사로그 영속화** — `audit_log` 테이블, 누가 언제 무엇을 수정·승인했는지 SQLite 보관
- **3-B. 자동 삭제 워커** — 업로드 파일 N분 후 자동 삭제, 메트릭 노출
- **3-C. 메트릭 대시보드** — 처리 건수·평균 신뢰도·교차검증율·승인율 추이

### Phase 4 — 위변조·진위
- **4-A. 도장/서명 embedding 유사도** — 사전 등록된 도장과 코사인 유사도
- **4-B. 위변조 흔적 탐지** — 픽셀 통계(JPEG ghost, ELA), 합성 흔적

### Phase 5 — 시연 폴리싱
- 5-A 결과 PDF 리포트 Export
- 5-B 시연 시나리오 5분/15분 두 버전 문서화

## 3. 이번 라운드(Phase 1) 구체 변경 위치

### 백엔드
- `apps/backend/app/core/validators/grounding.py` **(신규)** — substring + fuzzy ratio 매칭
- `apps/backend/app/core/validators/pii.py` **(신규)** — 이메일·주소·이름 detector
- `apps/backend/app/core/extractors/merchant_application.py` — 끝부분에 grounding 호출
- `apps/backend/app/core/extractors/{id_card,bank_book,business_reg}.py` — 동일
- `apps/backend/app/api/tasks.py` — `masking_level` Form param
- `apps/backend/app/core/steps/merge_results.py` — PII 통계 + 도장/서명 별도 응답
- `apps/backend/app/core/steps/layout_ocr.py` — stamp/signature 블록 추출
- `apps/backend/tests/test_grounding.py` **(신규)** — 5+ 케이스

### 프론트
- `apps/frontend/src/store/useOcrStore.ts` — fieldEdits, fieldApprovals, auditLog 상태
- `apps/frontend/src/components/ocr/ExtractedFieldsPanel.tsx` — 인라인 input, ✓/✗ 버튼, "전체 승인" + Export
- `apps/frontend/src/libs/api.ts` — `ApprovalState`, `FieldEdit` 타입
- `apps/frontend/src/routes/_ocr/OCRPage.tsx` — 상단 바에 "승인 N/M" 메트릭

## 4. 검증

각 Phase 종료 시 다음 확인:
- [ ] 단위 테스트 통과 (grounding 5+, PII 5+, 인라인편집 시각)
- [ ] 동일 우리카드 신청서로 라이브 e2e, **ungrounded 필드 0개** (현재 grounding 미적용이라 모두 ungrounded로 잡힐 수도 있음, 그 통계가 의미 있는 지표)
- [ ] 마스킹 정책 별로 응답 비교
- [ ] 프론트에서 값 수정 → "수정됨" 배지 → Export JSON 에 수정값이 들어감

## 5. 위험 / 결정 사항

| 위험 | 대응 |
|---|---|
| Phase 1만 끝나면 7개 영역 중 절반 안 채워짐 | 시연 자리 D-day 기준으로 Phase 2-3 우선순위 조정. v1 그대로도 7개 중 3개(VLM·구조화·HITL 일부)는 충족. v2 Phase 1으로 4개(Grounding·PII·HITL 완성·도장 노출) 추가 → 7개 중 6개 cover. Phase 2 로 자동분류·자동전처리 채움 |
| Grounding 으로 잡힌 ungrounded 케이스가 너무 많으면 시연에서 부정적 | 시연 데이터는 사전 라이브로 한 번 통과시켜 ungrounded 0~1건만 남도록 신청서 선택 |
| 시연 자리에서 평가자가 직접 인라인 수정 시 백엔드 영속화 없으면 새로고침으로 사라짐 | Phase 3 audit_log 영속화 전까지는 store에만 보관. 시연 안내 멘트에 "수정값은 Export 버튼으로 JSON 저장" 명시 |

## 6. 이미 갖춘 자산 재사용 (재구현 금지)

- bbox 역매칭(`extractors/_matching.py`): grounding 도 같은 방식으로 진행
- 마스킹 함수(`merchant_application._mask_account/rrn/phone`): PII detector 가 그대로 import
- 사전(`validators/bank.py`, `region.py`): 신원 검증·주소 정규화에 그대로
- 표 셀 라벨 47개: PII 이름·주소 탐지에서 라벨 매칭으로 활용
- ExtractedFieldsPanel 카드: 인라인 편집·승인 UI 의 베이스
- store: `fieldHighlight`, `hoveredRoiId` 패턴 그대로 fieldEdits/approvals 에 적용

## 7. 한 줄 — Phase 1 끝났을 때 평가자에게 보일 그림

> "추출된 필드 N개 중 시스템이 **근거를 찾은 (grounded)** 항목은 녹색 ✅, **원본에서 찾지 못한 (ungrounded)** 항목은 빨간 ⚠로 즉시 구분됩니다. 평가자가 각 필드를 클릭해 직접 수정하실 수 있고, 만족하시면 ✓로 승인 후 우측 상단 Export 버튼으로 우리카드 핵심시스템용 JSON 을 받으실 수 있습니다."

— 이게 단순 OCR 데모가 아니라 "문서 특화 AI 서비스"의 핵심 차별점.
