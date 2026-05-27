# Phase 6 — 모델 가중치 다운로드 가이드

저해상도 OCR 대응을 위한 Phase 6 모듈은 **가중치 없이도 동작**한다 (휴리스틱 폴백). 정확도를 더 끌어올리려면 아래 가중치를 배치하면 자동 활성화된다.

## 디렉토리 구조

```
apps/backend/data/
├── sr_models/                  # 6-B Super-Resolution
│   └── RealESRGAN_x4plus.pth   # (선택) Real-ESRGAN 4× 가중치
│   └── ESPCN_x4.pb             # (선택) OpenCV dnn_superres 폴백
│   └── EDSR_x4.pb              # (선택) OpenCV dnn_superres 폴백
├── text_det/                   # 6-C CRAFT 텍스트 검출
│   └── craft_mlt_25k.pth       # (선택) CRAFT 가중치
└── table_structure/            # 6-D 표 구조 인식
    └── lore_pp.pth             # (선택) LORE++ 가중치
```

환경 변수로 경로 변경 가능:
- `WOORI_SR_MODELS_DIR`
- `WOORI_TEXT_DET_DIR`
- `WOORI_TABLE_DIR`

## 폴백 동작 (가중치 없을 때)

| 모듈 | 1순위 | 2순위 | 폴백 (항상 동작) |
|---|---|---|---|
| Super-Resolution | Real-ESRGAN (torch) | OpenCV dnn_superres | **LANCZOS + Unsharp** |
| 텍스트 검출 | CRAFT (torch) | — | **MSER (OpenCV 내장)** |
| 표 구조 | LORE++ (torch) | — | **격자선 + Morphology** |

가중치 없는 환경에서도 자동 품질 진단 + LANCZOS 업스케일 + 그림자 제거 + 조명 보정 + 적응 이진화는 모두 동작한다. **저해상도 인식률 대부분 회복 가능**.

## 가중치 설치 절차

### 1. Real-ESRGAN (저해상도 SR, 1순위 권장)

공식 릴리스: https://github.com/xinntao/Real-ESRGAN/releases

```bash
cd apps/backend/data/sr_models/
wget https://github.com/xinntao/Real-ESRGAN/releases/download/v0.1.0/RealESRGAN_x4plus.pth
# 약 64MB. SHA256: 4fa0d38905f75ac06eb49a7951b426670021be3018265fd191d2125df9d682f1
```

설치 후 백엔드 재시작 시 자동 검출. `/api/v1/system/...` 로그에서 `sr_backend: realesrgan` 확인.

### 2. OpenCV dnn_superres (Real-ESRGAN 대안, 더 가벼움)

OpenCV contrib 모듈이 빌드되어 있어야 함. 현재 환경은 미포함이므로 다음 설치 필요:

```bash
pip install opencv-contrib-python==4.13.0
```

가중치:
```bash
cd apps/backend/data/sr_models/
# ESPCN (가벼움, 권장)
wget https://github.com/fannymonori/TF-ESPCN/raw/master/export/ESPCN_x4.pb
# 또는 EDSR (느림, 더 좋음)
wget https://github.com/Saafke/EDSR_Tensorflow/raw/master/models/EDSR_x4.pb
```

### 3. CRAFT (텍스트 영역 검출, 한글 친화)

공식 가중치: https://github.com/clovaai/CRAFT-pytorch

```bash
cd apps/backend/data/text_det/
# 공식 Google Drive 링크에서 craft_mlt_25k.pth 다운로드
# 약 80MB. Naver Clova 가 LICENSE 명시함 (비상업 연구용 → 상용 사용 시 라이선스 확인)
```

> 상용 도입 시: PaddleOCR 의 DBNet++ 한글 모델(`ch_PP-OCRv4_det.pth`)을 대체로 권장. Apache-2.0 라이선스.

### 4. LORE++ (표 구조 인식)

공식 리포: https://github.com/AlibabaResearch/AdvancedLiterateMachinery/tree/main/DocumentUnderstanding/LORE-TSR

```bash
cd apps/backend/data/table_structure/
# 공식 README 에서 PTN 또는 WTW 학습 모델 다운로드 후 lore_pp.pth 로 rename
```

표 추론 시 `from lore_tsr import infer_table_structure` 가 가능해야 자동 사용됨. 패키지 미설치 시 gridline 휴리스틱으로 폴백.

## 동작 확인

```bash
cd apps/backend
python -c "
from app.core import super_resolution, text_detection, table_structure
print('SR backends:')
for b in super_resolution.list_backends():
    print(f'  {b.name}: available={b.available} ({b.note})')
print('CRAFT:', text_detection.backend_status())
print('Table:', table_structure.backend_status())
"
```

## 라이선스 주의

| 모델 | 라이선스 | 상용 사용 |
|---|---|---|
| Real-ESRGAN | BSD-3 | ✅ |
| ESPCN/EDSR | Apache-2.0 | ✅ |
| CRAFT | MIT (코드) + 비상업 학습 모델 | ⚠️ Naver 라이선스 확인 |
| LORE++ | Apache-2.0 | ✅ |
| PaddleOCR DBNet++ | Apache-2.0 (대체 후보) | ✅ |

우리카드 상용 도입 시: **Real-ESRGAN + PaddleOCR DBNet++ + LORE++** 조합 권장.

## Phase 6 신규 OCR 옵션

업로드 API:
```http
POST /api/v1/tasks/upload
formData:
  auto_quality=true        # 이미지 품질 자동 진단 + SR/그림자/조명 자동 적용
  table_structure=true     # 표 구조 인식 (LORE++/gridline) 행/열 인덱스 보장
```

응답 (`/api/v1/tasks/{task_id}`) 에 추가됨:
- `quality_reports[]`: 페이지별 진단 결과 + 적용된 액션
- `tables[]`: 인식된 표의 셀 구조 + HTML 직렬화
