# 우리카드 OCR POC 시연 시나리오

> 두 가지 버전 — **5분 조이밍** (의사결정자 대상) / **15분 깊이 시연** (실무 평가자 대상).
> 시연 전 체크리스트는 맨 아래.

---

## 5분 시연 (의사결정자 / C-레벨)

> 목적: "이 솔루션을 도입하면 무엇이 달라지는가" 한 그림으로 보여주기.

| 시간 | 화면 | 멘트 |
|---|---|---|
| 0:00 | 브라우저 `http://127.0.0.1:3006/` 열기 | "우리카드 양식 문서 OCR POC 데모입니다. 단순 OCR이 아니라 **문서 특화 AI 서비스**로 설계되어 있습니다." |
| 0:15 | 좌측 사이드바 — **문서 유형 = 🔍 자동 감지** | "사용자가 문서 종류를 모를 때 자동 감지가 기본값입니다." |
| 0:25 | 좌측 사이드바 — **PII 마스킹 = 부분 마스킹**, 자동 전처리 ON | "PII 정책과 저품질 복원이 한 클릭으로 적용됩니다." |
| 0:40 | 시연용 가맹점 가입신청서 업로드 (`test/KakaoTalk_Photo_2026-05-20-13-12-50.png`) | "스마트폰으로 찍은 가맹점 신청서입니다." |
| 0:50 | 처리 중 (~50초) — 진행률 stream | (대기 중 자동 분류·전처리·OCR·grounding·PII 마스킹·도장 검출이 모두 자동으로 돌고 있다고 설명) |
| 1:40 | 상단 메트릭 바 — **자동 분류: 가맹점 가입신청서 / 추출 N건 / 교차검증 / 도장·서명 / 결과 N분 후 자동 삭제** | "0.3초 만에 자동 분류했고, 추출 N건 중 시스템이 **근거를 확인한 항목은 녹색, 못 찾은 항목은 빨간색**으로 표시됩니다." |
| 2:30 | 우측 패널 — 필드 카드들. 한 카드 hover → 원본 이미지 박스 강조 | "이 추출값이 원본의 어느 영역에서 나왔는지 즉시 확인 가능합니다." |
| 2:50 | 한 필드 값 클릭 → inline 수정 → ✓ 승인 | "필요하면 평가자께서 직접 수정·승인하실 수 있습니다." |
| 3:10 | 우측 상단 **🛡 교차검증** 메트릭 클릭 → 비교 모드 토글 → 가운데 패널에 Qwen vs GLM-OCR side-by-side | "두 모델이 독립적으로 동일하게 인식한 필드만 ✓ 교차검증 배지가 붙고 신뢰도 0.95로 승격됩니다." |
| 3:40 | **품질/표** 탭 → SR 적용 배지 + 표 인식 6×3 → "HTML 미리보기" | "모바일로 찍어 흐려진 사진은 자동 진단 후 **Real-ESRGAN으로 SR**해서 OCR합니다. 격자선 표 안의 행/열 인덱스도 자동 회귀하므로 병합 셀이 어긋나지 않습니다." |
| 4:00 | **📄 리포트** 버튼 → PDF로 저장 | "최종 결과는 우리카드 핵심시스템 호환 JSON 또는 PDF 리포트로 즉시 export 됩니다." |
| 4:20 | 마무리 멘트 | "단순 OCR 아니라 **저해상도·구조·문맥·근거·보안 위험까지 이해하고 사람 검수까지 한 흐름에 통합**한 문서 특화 AI 입니다. 우리카드 시스템과 즉시 연동 가능합니다." |
| 4:50 | Q&A 버퍼 |  |

---

## 15분 시연 (실무 평가자 / 보안·컴플라이언스)

> 목적: 기술적 깊이 + 보안·감사 요건 충족 + 운영 가능성 입증.

### Step 1 — 화면 구조 소개 (1:00)

- 상단 글로벌 바: 브랜드 / 엔진 토글 / 메트릭 / 자동 삭제 배지
- 좌측 사이드바: 문서 유형·마스킹·전처리·혼합문서 분리 옵션
- 가운데 3-열: 원본 이미지 / Raw OCR / 추출 항목
- 우측 패널 토글: 추출 항목 ↔ 영역 OCR(손글씨)

### Step 2 — 자동 분류 + 자동 전처리 (2:00)

1. 문서 유형 = **🔍 자동 감지**, 자동 전처리 ON, 마스킹 = partial
2. 가맹점 신청서 업로드
3. 처리 후 상단 메트릭 바 강조:
   - `📌 자동 분류: 가맹점 가입신청서 (0.3s)`  ← Qwen2.5-VL 분류 prompt, 한 단어 응답
   - `처리: ~50s` ← Layout(PP-DocLayoutV3 GPU 0) + OCR(Qwen2.5-VL-7B vLLM GPU 1) sequential
   - `추출: 6` + `근거 X/Y` ← Grounding validator
   - `🔒 결과 N분 후 자동 삭제` ← cleanup_worker, settings.RETENTION_MINUTES
4. 멘트: "양식 위치가 일정하면 후처리 추출기로, 일정하지 않으면 표 셀 라벨 매칭으로 잡습니다."

### Step 2-bis — **저해상도 자동 복원 + 표 구조 인식 (Phase 6)** (2:00)

1. 사이드바: **자동 품질 진단 + SR** ✓ , **표 구조 인식** ✓
2. 의도적으로 저해상도(예: 600×900, 스마트폰으로 찍어 압축된 사업자등록증) 이미지 업로드
3. 처리 후 상단 메트릭 바에 신규 배지 노출:
   - `SR 적용 1p` ← Real-ESRGAN 4× 자동 적용 (가중치 미설치 시 OpenCV ESPCN → LANCZOS 자동 폴백)
   - `표 1개 (gridline)` ← 격자선 검출로 행/열 인덱스 회귀 완료
4. **품질/표** 탭 클릭 → 페이지별 진단 결과:
   - `해상도 600 × 900` → `업스케일 ×2.67`
   - `진단 노트`: `short_side=600 → upscale`, `brightness=228 비정상`, `contrast<35 → binarize`
   - SR 백엔드 자동 선택 chip
5. 같은 탭 하단 **표 구조 인식 (6×3, 병합 6개)** → "HTML 미리보기" 클릭 시 정확한 셀 병합으로 렌더
6. 멘트:
   > "원본 사업자등록증을 모바일로 찍어오면 보통 DPI 100 이하라 글자가 patch 미만으로 사라집니다. 시스템이 자동으로 진단하고 Real-ESRGAN 으로 SR을 적용한 뒤 OCR 합니다. 격자선 표 안의 행/열 인덱스는 LORE++ 폴백인 격자선 휴리스틱이 회귀합니다. 운영자가 별도 설정할 필요 없이 한 번에 끝납니다."
7. 운영 점검: 새 터미널에서
   ```bash
   curl -s http://127.0.0.1:8000/api/v1/system/phase6-status | jq '.data.super_resolution.auto_selected, .data.table_structure'
   ```
   → 현재 자동 선택된 SR 백엔드 + 표 인식 백엔드 가용성을 한 줄로 점검.

### Step 3 — Near-Zero Hallucination (Grounding) (2:00)

1. 우측 필드 패널 위쪽 메트릭: `근거 6/8`
2. ⚠ **근거없음** 빨간 배지 필드 hover → 원본 이미지에 박스 표시는 없음 (애초에 원문에 없는 값)
3. 멘트: "후처리(체크섬 복원·사전 매칭)로 만들어진 값도 raw OCR 텍스트에 substring으로 존재하지 않으면 시스템이 자수합니다. 환각 차단의 마지막 안전망입니다."

### Step 4 — 비교 모드 (교차검증) (2:00)

1. 상단 엔진 토글 = **비교 모드** 클릭
2. 같은 신청서 다시 업로드 (~3분, primary→secondary sequential)
3. 가운데 OCRResults가 [Qwen / GLM-OCR / 비교 / JSON] 4탭. "비교" 탭에서 두 raw markdown side-by-side
4. 우측 필드 카드의 **🛡 교차검증** 배지 (두 모델 동일 값 = 녹색), **⚠ 엔진 간 차이** (다른 값 = 주황색)
5. 우상단 메트릭: `교차검증 1/8 ⚠ 2`
6. 멘트: "단일 모델 신뢰도보다 두 모델 합의가 더 강한 신호입니다. 우리카드 평가 자리에서 가장 명확한 신뢰성 지표입니다."

### Step 5 — PII 정책 + 마스킹 시연 (1:30)

1. 사이드바 PII 마스킹 = **부분 마스킹** ↔ **완전 마스킹** ↔ **마스킹 없음** 토글
2. 우측 패널 카드의 휴대폰·계좌·이름·이메일·주소 마스킹 즉시 변경
3. 우측 패널 상단 마스킹 ON/OFF 토글로 다시 한 번 토글 가능 (감사 로그 남음)
4. 멘트: "신용정보·개인정보보호법에 따라 노출 정책을 단일 슬라이더로 통제합니다. 모든 변경은 audit_log 테이블에 자동 적재됩니다."

### Step 6 — 도장/서명 검증 (2:00)

1. 상단 메트릭의 `🖋 도장/서명 N + 매칭 ✓K` 칩 hover
2. (사전 등록된 우리카드 직인 PNG가 `apps/backend/data/seal_library/`에 있다고 가정) → 매칭 시 ✓
3. 멘트: "PP-Layout이 잡은 도장/서명 영역을 사전 등록된 우리카드 직인과 perceptual hash로 자동 대조합니다. 위변조 1차 검출이 가능하고, 사람 검수가 필요한 경우에만 평가자에게 흘러갑니다."

### Step 7 — Human-in-the-Loop (2:30)

1. 우측 패널의 한 필드 값 클릭 → inline 편집 → Enter → "수정됨" 배지
2. ✓ 승인 / ✗ 거부 버튼 → 즉시 색상 변화
3. **🔘 전체 승인** 버튼 → 모두 녹색
4. **⬇ Export** 버튼 → JSON 다운로드 (수정 이력, grounding, PII 통계, 감사 로그 포함)
5. **📄 리포트** 버튼 → 새 탭에 print-friendly 페이지 → cmd+P → PDF 저장
6. 멘트: "AI 결과를 그대로 신뢰하지 않고 평가자가 직접 수정·승인하시는 한 흐름에 통합되어 있습니다. 학습 피드백 자료로도 활용 가능합니다."

### Step 8 — 영역 OCR (손글씨) (1:30)

1. 우측 패널 탭 [영역 OCR] 클릭 → 자동으로 "영역 그리기 ON"
2. 가운데 이미지의 사업자번호 칸 위를 마우스 드래그 → 박스 그리기
3. 영역 이름 inline 수정 → "사업자번호" → "영역 OCR 실행"
4. ~2초 후 영역 카드에 손글씨 인식 결과 + bbox 강조
5. 멘트: "양식에 손글씨로 채워진 부분만 평가자가 직접 지정하실 수 있습니다. 영역당 2~3초, 페이지 전체 OCR(50초) 대비 빠릅니다."

### Step 9 — 운영 / 보안 (Q&A 대비)

대비 질문 + 한 줄 답변:

| 질문 | 답변 |
|---|---|
| 데이터 보관 정책? | `RETENTION_MINUTES=30` 환경변수, 30초마다 cleanup_worker가 만료된 task 디렉토리 삭제. `/api/v1/system/storage`로 현재 디스크 사용량 노출. |
| 감사 로그 어디 저장? | SQLite `audit_log` 테이블. `POST/GET /api/v1/audit`. 누가(IP/User-Agent) 언제 어떤 필드를 수정·승인했는지. |
| 모델 어디서? | GPU 0 = PP-DocLayoutV3 (레이아웃), GPU 1 = Qwen2.5-VL-7B-AWQ via vLLM 8080, Ollama 11434는 GLM-OCR 비교 baseline. |
| 한국어 양식 정확도? | 비교 모드에서 두 모델 일치 항목은 95%+, Qwen 단독은 라이브 평가에서 8~9 필드 중 6~7 grounded. PII와 핵심 숫자(사업자번호·계좌·연락처)는 사전 매칭으로 99% 신뢰. |
| 다른 양식에도 확장? | 4종 추출기(`merchant_application`/`id_card`/`bank_book`/`business_reg`) + freeform. 새 양식 추가 시 `core/extractors/` 디렉토리에 신규 모듈 1개 추가 + `registry.py` 등록만으로 끝. |
| 라이브 운영시 GPU? | 현재 Quadro RTX 5000 ×2(16GB)에서 Qwen2.5-VL-7B-AWQ 단일 GPU. A100 1장이면 32B-AWQ까지 가능. |
| 시스템 통합? | Export JSON이 우리카드 핵심시스템 호환 schema. Flask `glmocr.server` 또는 FastAPI `/api/v1/tasks/upload` 둘 다 REST. |
| 저해상도/모바일 사진 처리? | (Phase 6) `auto_quality=true`로 자동 진단 → Real-ESRGAN 4× SR + deshadow + 조명 보정 + 적응 이진화. 가중치 미설치 시 OpenCV ESPCN → LANCZOS 안전 폴백. `/api/v1/system/phase6-status`로 백엔드 가용성 노출. |
| 표 안의 행/열 정확도? | (Phase 6-D) `table_structure=true`로 격자선 휴리스틱(LORE++ 폴백) 행/열 인덱스 회귀. 병합 셀 검출 정확. 응답의 `tables[].cells[]`에 `row/col/row_span/col_span` 노출, HTML 직렬화도 동시 제공. |

---

## 시연 전 체크리스트 (D-30분)

```bash
# 1. 서비스 기동 확인
curl -s -o /dev/null -w 'backend %{http_code}\n' http://127.0.0.1:8000/health
curl -s -X POST --max-time 2 -o /dev/null -w '5002(Qwen) %{http_code}\n' \
  http://127.0.0.1:5002/glmocr/parse -H 'Content-Type: application/json' -d '{}'
curl -s -X POST --max-time 2 -o /dev/null -w '5003(GLM) %{http_code}\n' \
  http://127.0.0.1:5003/glmocr/parse -H 'Content-Type: application/json' -d '{}'

# 2. GPU 메모리 여유
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader

# 3. Phase 6 SR/Det/Table 백엔드 상태 (가중치 가용성)
curl -s http://127.0.0.1:8000/api/v1/system/phase6-status \
  | python -c "import sys,json; d=json.load(sys.stdin)['data']; \
print('SR auto:', d['super_resolution']['auto_selected']); \
print('Det CRAFT:', d['text_detection']['craft']['available']); \
print('Tbl LORE:', d['table_structure']['lore']['available'])"
# 기대 출력: SR auto: realesrgan (또는 opencv-dnn-superres / lanczos-sharpen)

# 3. Ollama 모델 로드 미리 trigger (cold start 회피)
curl -s -X POST http://localhost:11434/api/generate \
  -d '{"model":"glm-ocr:latest","prompt":"hi","stream":false,"options":{"num_predict":5}}'

# 4. vLLM warm-up
curl -s http://127.0.0.1:8080/v1/models
```

**시연 직전 1회 사전 업로드** — vLLM/Ollama warmup용으로 같은 신청서 한 번 처리. 두 번째 실제 시연이 ~30% 빠름.

## 트러블슈팅 (시연 중 발생할 수 있는 것)

| 증상 | 즉시 대응 |
|---|---|
| 업로드 후 분석 실패 (500) | `tail -30 /tmp/backend.log` — 보통 vLLM/Ollama 중 한 쪽 응답 timeout. 엔진 토글을 `qwen` 또는 `glm-ocr` 단일로 |
| 비교 모드 처리 시간 너무 김 | "비교 모드는 두 엔진 순차 실행이라 시간이 두 배 듭니다"로 자연스럽게 설명 — 단일 엔진으로 폴백 |
| 박스가 어긋남 | (이미 해결됨 — 새로고침으로 정상화) |
| 새 신청서에서 추출 0건 | grounding이 너무 엄격할 수도. 사이드바 마스킹 = none + 다른 엔진 시도 |
| Phase 6 "품질/표" 탭이 안 보임 | `auto_quality` 또는 `table_structure` 체크박스가 꺼져 있음. 사이드바에서 체크 후 재업로드 |
| SR 너무 느림 (페이지당 1초+) | Real-ESRGAN이 작동 중. 빠른 시연이 필요하면 `WOORI_SR_MODELS_DIR=/dev/null` 환경변수로 강제 폴백하거나 가중치 일시 제거 → ESPCN(150ms) 또는 LANCZOS(100ms) 자동 폴백 |
| 표가 인식 안 됨 | PP-DocLayoutV3가 "table" 라벨로 잡지 못한 경우. 격자선이 또렷한 양식만 6-D가 동작. 양식에 격자선 없으면 VLM의 마크다운 표로 폴백 |
