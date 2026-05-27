# hwpx-runner

`HwpxConverter` (`app/utils/converters/hwpx.py`) 가 호출하는 Node CLI 래퍼.

## 설치

```bash
cd apps/backend/tools/hwpx-runner
npm ci
```

Docker 이미지 빌드 시 `Dockerfile` 의 `npm ci --omit=dev` 단계에서 자동 설치된다.

## 사용 (수동 검증)

```bash
# 버전 확인
./node_modules/.bin/hwpx-cli --version

# 메타데이터만 빠르게
./node_modules/.bin/hwpx-cli info ../../tests/fixtures/sample.hwpx

# 구조화 JSON 추출 (Python 어댑터 입력)
./node_modules/.bin/hwpx-cli convert ../../tests/fixtures/sample.hwpx --to json --pretty -o /tmp/out.json

# 미리보기 PDF 생성 (UI 용)
./node_modules/.bin/hwpx-cli convert ../../tests/fixtures/sample.hwpx --to pdf -o /tmp/preview.pdf
```

## 트러블슈팅

- `command not found: node` → Node.js 18+ 설치 필요
- `--password` 가 필요한 암호화 HWPX 는 `ConversionFailedError` 로 정중히 거부
- 대용량 (50MB+) 문서가 OOM 으로 죽으면 `NODE_OPTIONS="--max-old-space-size=2048"` 환경변수
