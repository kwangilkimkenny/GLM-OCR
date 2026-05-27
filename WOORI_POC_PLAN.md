# 우리카드 OCR POC — 시연 웹사이트 개발 계획

> 작성일: 2026-05-26
> 목적: 우리카드 대상 OCR 인식 솔루션 POC. 금융권 양식 문서의 OCR 정확도와 필드 추출 능력을 라이브로 시연하는 데모 사이트.

---

## 1. 컨텍스트 (왜 이 계획인가)

### 1.1 입력 자료에서 확인된 사실
- `test/`, `test-preproc/`의 KakaoTalk 사진 2장은 실제 **「우리카드 가맹점 가입신청서」** 양식이다. 즉 시연 도메인이 이미 정해져 있다.
- `붙임3. AI_OCR POC관련 문서별 추출 항목.xlsx` — 문서 유형별 추출 항목 정의가 별도 존재 (계약된 POC 스펙).

### 1.2 자체 평가(2026-05-20)에서 얻은 제약
| 모드 | 결과 |
|---|---|
| **Ollama (glm-ocr:latest, F16)** — 주주명부 스크린샷 | ✅ 숫자 100%, 한글 일부 오인식 (구 이름, 회사명) |
| **Ollama** — 우리카드 가맹점 신청서 (전처리·원본 둘 다) | ⚠️ 양식 헤더와 계좌/전화 패턴은 잡지만 본문 한글은 환각 다수 |
| **vLLM (TRITON_ATTN, enforce-eager)** — 동일 입력 | ❌ 디코더 루프 붕괴 ("주식회회회회…", "안전대학교" 반복) — 현재 런처 설정으론 사용 불가 |

→ **결론**: 단일 엔진(GLM-OCR)만으로는 우리카드 양식 문서를 안정적으로 다룰 수 없다. POC 사이트는 **(a) 다중 엔진 백엔드를 가정하고**, **(b) GLM-OCR의 약점을 후처리·검증으로 보완**하는 구조여야 한다. 이 한계를 숨기지 말고, "비교·검증·신뢰도"를 데모의 셀링 포인트로 노출한다 — 금융권 평가자가 가장 원하는 가치이기도 하다.

### 1.3 재사용 가능한 기존 자산
| 자산 | 위치 | 활용 |
|---|---|---|
| FastAPI + SQLAlchemy 비동기 태스크 시스템 | `apps/backend/app/` | 그대로 사용 (업로드, 상태조회, 결과조회 엔드포인트) |
| `PipelineFlow` (PDF→이미지→레이아웃+OCR→병합) | `apps/backend/app/core/flows/pipeline_flow.py` | 우리카드 플로우의 기반 |
| 컨버터 (pdf/image/word) | `apps/backend/app/utils/converters/` | 다포맷 업로드 지원 |
| React 19 + TanStack Router + Tailwind v4 | `apps/frontend/` | 그대로 사용 |
| 좌측 업로드 / 좌중 PDF 미리보기 / 우측 결과 (md/json) 2-열 레이아웃 | `apps/frontend/src/routes/_ocr/OCRPage.tsx` | 3-열로 확장 |
| Bounding box 하이라이트 오버레이 | `apps/frontend/src/components/ocr/HighlightOverlay.tsx` | 추출 필드 ↔ 원본 이미지 연결 |
| GLM-OCR SDK | `glmocr/` | 1차 엔진 |
| 이미지 전처리 파이프라인 | `preprocess.py` | 백엔드에 통합 |

→ **새로 만들지 않는다. 확장한다.**

---

## 2. 시연 시나리오 (UX 흐름)

평가자가 5분 안에 "이 솔루션 쓸 수 있겠다"고 느끼게 만드는 4-step 데모.

```
[Step 1] 문서 유형 선택
   ┌─────────────────────────────────────────────┐
   │  ◉ 가맹점 가입신청서   ○ 신분증            │
   │  ○ 사업자등록증       ○ 통장 사본          │
   │  ○ 자유 업로드                              │
   └─────────────────────────────────────────────┘

[Step 2] 파일 업로드 (드래그&드롭 or 샘플 선택)
   - 시연용 샘플 프리셋 버튼 (우리카드 양식 그대로)
   - 카메라 캡처 (모바일 시연 대비, 선택)

[Step 3] 처리 화면 (3-열 + 상단 진행률)
   ┌──────────────┬──────────────┬──────────────┐
   │ 원본+하이라이트 │ Raw OCR 결과 │ 정규화된 필드 │
   │              │ (md/json)    │ (검증/마스킹) │
   │              │              │              │
   │ 박스 클릭 시  │ 텍스트 클릭   │ 필드 → 원본  │
   │ 매칭 영역    │ 시 원본 점프  │ 매칭 박스 강조 │
   └──────────────┴──────────────┴──────────────┘
   상단: 엔진 선택 (GLM-OCR / Clova OCR / 두 엔진 비교) + 신뢰도 게이지

[Step 4] 결과 검증 & Export
   - 필드별 신뢰도, 마스킹 토글, 수동 보정 UI
   - "이 결과를 우리카드 핵심시스템(가맹점관리) 양식 JSON으로 export" 버튼
   - 처리 시간/엔진/모델 메타데이터 표시 (감사 추적용)
```

---

## 3. 단계별 개발 계획

### Phase 1 — 도메인 확장 (1주)
**목표**: 데모 앱을 우리카드 컨텍스트로 가져오기.

**프론트엔드**
- `apps/frontend/src/routes/_ocr/OCRPage.tsx` 를 3-열 레이아웃으로 변경 (현재 2-열).
- 우리카드 컬러 토큰 적용 (`#1428A0` 계열을 Tailwind theme에 추가).
- 헤더에 "우리카드 OCR POC" 브랜딩, 푸터에 "테스트 환경 / 실서비스 아님" 명시.
- 문서 유형 선택 패널 (Step 1)을 좌측 사이드바에 추가.
- 시연용 샘플 프리셋 카드 (가입신청서/신분증/통장사본 각 2~3장).

**백엔드**
- `apps/backend/app/schemas/task.py` 에 `document_type` 필드 추가 (Enum: `merchant_application | id_card | bank_book | business_reg | freeform`).
- 업로드 API (`POST /api/v1/tasks/upload`)에 `document_type` Form 파라미터 추가.
- `PipelineFlow` 가 `document_type` 을 `ProcessingContext` 로 전달.

**전처리 통합**
- 루트의 `preprocess.py` 를 `apps/backend/app/utils/image_preprocess.py` 로 이동/통합.
- 신청서·신분증은 deskew + CLAHE 자동 적용, 통장은 binarize 추가 옵션.

**산출물 체크리스트**
- [ ] 새 3-열 레이아웃이 기존 2-열을 대체
- [ ] 문서 유형 4종 + 자유 모드가 동작
- [ ] 우리카드 브랜드가 일관되게 적용

---

### Phase 2 — 필드 추출 & 검증 (1.5주)
**목표**: Raw OCR 텍스트를 "필드 단위 구조화 데이터"로 만든다. 이게 POC의 핵심 가치.

**필드 추출기** (`apps/backend/app/core/extractors/`, 신규)
- `base.py` — `FieldExtractor` 추상 클래스 (`extract(raw_text, raw_blocks) -> dict[field_name, ExtractedField]`).
- `ExtractedField` 스키마: `value`, `bbox`, `confidence`, `validation_status`, `masked_value`.
- `merchant_application.py` — XLSX 「붙임3」 명세에 정의된 항목을 정규식 + 키워드 매칭 + 위치 추정으로 추출.
  - 예: 사업자등록번호 `\d{3}-\d{2}-\d{5}`, 계좌번호, 대표자명 (행 라벨 "대표자" 인접), 사업장 주소 등.
- `id_card.py` — 주민등록증/운전면허증. 주민번호·발급일·발급기관.
- `bank_book.py` — 은행명, 계좌번호, 예금주.
- `business_reg.py` — 사업자등록증.

**검증기** (`apps/backend/app/core/validators/`, 신규)
- 주민번호 체크섬, 사업자번호 체크섬.
- 계좌번호 → 은행별 자릿수·포맷 검증.
- 발급기관 사전 매칭.
- 한글 고유명사(회사명/주소)는 **OCR 후보 ↔ 사전(법정동, 우리카드 가맹점 DB 샘플)** Levenshtein 매칭으로 자동 교정.

**마스킹** (`apps/backend/app/core/masking.py`, 신규)
- 주민번호 뒷 7자리, 카드번호 가운데 8자리, 계좌번호 가운데 자릿수.
- 마스킹은 default ON. UI 토글로 평가자가 풀 수 있게 (감사 로그에 남김).

**프론트엔드**
- 우측(3번째 열)에 필드 카드 리스트 (필드명 / 추출값 / 신뢰도 게이지 / 검증 배지 / 마스킹 토글).
- 필드 카드 hover → 원본 이미지의 매칭 bbox 강조 (기존 `HighlightOverlay.tsx` 재사용).
- 추출 실패한 필수 항목은 빨간 배지로 강조하고 수동 입력 가능하게 (사용자 보정 흐름).

**산출물 체크리스트**
- [ ] 가맹점 가입신청서 샘플에서 핵심 필드 12+개가 자동 추출
- [ ] 모든 필드에 신뢰도 점수와 검증 결과가 부착
- [ ] 마스킹 ON/OFF 토글이 동작하고 감사 로그에 기록

---

### Phase 3 — 다중 엔진 & 비교 모드 (1주)
**목표**: GLM-OCR 단독의 한계를 정직하게 보여주고, 대체/앙상블 옵션을 시연.

**백엔드**
- `apps/backend/app/core/ocr_engines/` (신규)
  - `glm_ocr.py` — 현재 `glmocr` SDK 호출
  - `clova_ocr.py` — Naver Clova OCR API (한글 양식 강점, 신청 필요)
  - `tesseract_kor.py` — `pytesseract` (이미 backend에 의존성 있음) + 한글 학습 데이터
  - `(optional) azure_form.py` — Azure Document Intelligence (사전학습 prebuilt-id, prebuilt-business-card)
- 공통 인터페이스: `engine.parse(image_path) -> NormalizedOcrResult` (블록 + bbox + raw text + confidence).
- 업로드 API에 `engines: list[str]` 추가, 다중 엔진 시 병렬 실행 후 결과 비교.

**합의 엔진** (`apps/backend/app/core/ensemble.py`, 신규)
- 두 엔진 결과를 필드 단위로 비교 → 일치 시 신뢰도 ↑, 불일치 시 사전 매칭으로 결정 + 사용자 확인 플래그.

**프론트엔드**
- 상단에 엔진 선택 토글 (`GLM-OCR | Clova | 비교 모드`).
- 비교 모드일 때 가운데 열을 좌/우로 split, 차이가 있는 토큰을 색상으로 diff 표시.
- 필드 카드에 "어느 엔진이 채택됐는지" 라벨.

**산출물 체크리스트**
- [ ] 최소 2개 엔진이 같은 입력으로 동작
- [ ] 비교 모드에서 차이가 시각화됨
- [ ] 합의 결과의 신뢰도가 단일 엔진보다 높은 케이스가 한 건 이상 시연 가능

---

### Phase 4 — 금융권 비기능 요구사항 (1주)
**목표**: 보안·감사·운영성 요구사항을 "체크리스트로 보여줄 수 있는 형태"로 구현.

**보안**
- 업로드 파일은 **메모리 처리 우선**, 디스크에 저장하는 경우 임시 디렉터리 + TTL 자동 삭제 (`apps/backend/app/utils/upload_file_manager.py` 확장).
- 응답에서 원본 이미지를 직접 노출하지 않고 서명된 임시 URL 사용.
- HTTPS-only 프로덕션 배포 가이드 (nginx 설정, `apps/frontend/nginx.conf` 확장).

**감사 로그**
- `audit_log` 테이블 추가 (`apps/backend/app/models/audit.py` 신규): 누가 / 언제 / 어떤 문서 / 어떤 필드를 / 마스킹 ON·OFF / 수동 수정 여부.
- 모든 API 호출에 미들웨어로 자동 기록.
- 관리자 페이지(`/admin/audit`) — 시연 시 평가자에게 "이력 추적 가능" 보여주기.

**개인정보 처리방침 표시**
- 첫 진입 시 "테스트 환경 / 입력 데이터는 N시간 후 자동 삭제" 모달.
- 헤더에 "처리 데이터 삭제" 버튼 (즉시 폐기).

**관측성**
- `/api/v1/system/health`, `/metrics` (이미 system.py 라우터 있음) — Prometheus 호환 메트릭 노출.
- 처리 시간 / 엔진별 성공률 / 평균 신뢰도 대시보드 (간단한 Recharts 페이지).

**산출물 체크리스트**
- [ ] 업로드 파일이 N분 후 자동 삭제됨을 시연
- [ ] 감사 로그가 모든 처리에 자동 기록
- [ ] 헬스/메트릭 엔드포인트가 정상

---

### Phase 5 — 시연 폴리싱 (0.5주)
- 시연용 시나리오 문서 (`docs/demo-script.md`, 5분 / 15분 두 버전)
- 샘플 데이터 패키지 (개인정보 마스킹된 가짜 신청서 3종)
- 결과 PDF Export ("우리카드 OCR 분석 리포트")
- 첫 페이지 랜딩 (한 줄 가치 제안 + "데모 시작" CTA)

---

## 4. 아키텍처 다이어그램

```
┌─────────────────────────────────────────────────────────────┐
│   React 19 SPA (Vite)                                       │
│   - 3-column OCR view (원본 | OCR raw | 추출 필드)          │
│   - 엔진 토글 / 비교 모드 / 마스킹 토글 / Export             │
└─────────────────────────┬───────────────────────────────────┘
                          │ REST + WebSocket(진행률)
┌─────────────────────────▼───────────────────────────────────┐
│   FastAPI (apps/backend)                                    │
│   /tasks/upload  /tasks/{id}  /tasks/{id}/result            │
│   /admin/audit   /metrics                                   │
│                                                              │
│   Pipeline Flow                                              │
│    1. Convert (pdf/word/image → image)                       │
│    2. Preprocess (deskew/CLAHE/optional binarize)            │
│    3. OCR (Engine Manager: GLM-OCR / Clova / Tesseract)      │
│    4. Field Extraction (per document_type)                   │
│    5. Validation + Masking                                   │
│    6. Persist (SQLite + audit_log)                           │
└─────────────────┬───────────────┬───────────────────────────┘
                  │               │
        ┌─────────▼────┐   ┌──────▼──────────┐
        │ glmocr SDK   │   │ Clova / Azure / │
        │ → Ollama     │   │ Tesseract APIs  │
        │   (vLLM은    │   │                 │
        │    당분간 보류)│   └─────────────────┘
        └──────────────┘
```

---

## 5. 즉시 실행 가능한 첫 PR (Day 1 작업 단위)

1. `WOORI_POC_PLAN.md` 커밋 (이 문서) — 이해관계자 공유.
2. `apps/frontend/src/routes/_ocr/OCRPage.tsx` 를 3-열 grid로 변경, 우측에 placeholder "필드 추출 패널" 추가.
3. `apps/backend/app/schemas/task.py` 에 `DocumentType` Enum 추가, 업로드 API 에 옵션 파라미터.
4. `apps/backend/app/core/extractors/__init__.py` + `merchant_application.py` 스켈레톤 — 사업자번호·계좌번호·전화번호 정규식 3개만 우선 구현해서 end-to-end 흐름 검증.

이 4개만 들어가도 "필드 단위로 결과를 보여주는 OCR" 데모가 동작한다. 이후 Phase 2~5는 이 토대 위에서 확장.

---

## 6. 검증 (Verification)

각 Phase 종료 시 다음을 수동으로 확인:

- [ ] `apps/backend` 가 `uv run uvicorn app.main:app --reload` 로 기동되고 `/health` 200
- [ ] `apps/frontend` 가 `pnpm dev` 로 :3006 기동, 좌측 업로드 후 우측 필드 카드까지 흐름 동작
- [ ] `test-originals/스크린샷 2026-05-20 14.48.42.png` 업로드 → 7,000주/1,600주/1,400주 숫자가 필드로 추출
- [ ] `test/KakaoTalk_Photo_2026-05-20-13-12-50.png` 업로드 → "우리카드 가맹점 가입신청서" 문서 유형 자동 분류 + 최소 사업자번호/계좌번호 추출 (한글 환각 영역은 신뢰도 낮음으로 표시)
- [ ] 마스킹 토글이 UI/감사 로그 양쪽에서 동작
- [ ] 처리 후 N분 뒤 업로드 파일이 디스크에서 사라짐

---

## 7. 리스크 & 대응

| 리스크 | 대응 |
|---|---|
| GLM-OCR이 우리카드 양식에 환각 다발 | Phase 3에서 Clova/Tesseract 백업, Phase 2 검증·매칭으로 보정. 데모에서 "왜 다중 엔진인가"의 근거로 사용 |
| Clova OCR 계정·키 발급 지연 | Tesseract+kor 학습 데이터로 우선 시연, Clova는 후속 추가 |
| 평가자가 실제 고객 데이터로 테스트 요구 | 마스킹 자동·즉시삭제·감사로그를 즉시 보여줄 수 있게 Phase 4 우선순위 ↑ |
| vLLM 런처 불안정 | POC 기간 동안은 Ollama만 사용. 안정화는 별도 트랙으로 분리 |
| 한글 사전(법정동/은행/우리카드 가맹점) 부재 | 공공데이터(행안부 법정동 코드) + 은행 코드표 우선 적재, 가맹점 DB는 평가자 측 데이터로 향후 확장 |

---

## 8. 일정 요약

| 주차 | 마일스톤 |
|---|---|
| W1 | Phase 1 완료 (3-열 UI + 도메인 분기) |
| W2~3 | Phase 2 완료 (필드 추출 + 검증 + 마스킹) |
| W4 | Phase 3 완료 (다중 엔진 비교) |
| W5 | Phase 4 완료 (보안/감사) |
| W5.5 | Phase 5 완료 (폴리싱) — 평가 시연 준비 |

총 5~6주 단일 풀스택 개발자 기준. 디자이너 보조 0.5주 (브랜딩·랜딩) 권장.
