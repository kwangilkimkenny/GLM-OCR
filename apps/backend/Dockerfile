# 使用官方Python 3.12镜像作为基础镜像
FROM python:3.12-slim

# 设置工作目录
WORKDIR /app

# 设置环境变量
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    DISPLAY=:99 \
    HOME=/tmp

# 安装系统依赖
# - poppler-utils: PDF处理依赖 (pdf2image)
# - libgomp1: OpenMP支持 (某些CV库需要)
# - libglib2.0-0: GLib支持
# - libsm6: X11库支持
# - libxext6: X11扩展库
# - libxrender-dev: X11渲染库
# - libgl1: OpenGL支持
# - libreoffice*: LibreOffice套件 (Word文档转PDF)
# - fonts-*: 字体支持 (中文文档显示)
RUN sed -i 's/deb.debian.org/mirrors.tuna.tsinghua.edu.cn/g' /etc/apt/sources.list.d/debian.sources &&\ 
    apt-get update && apt-get install -y --no-install-recommends \
    poppler-utils \
    libgomp1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    libgl1 \
    libreoffice-writer \
    libreoffice-calc \
    libreoffice-impress \
    libreoffice-core \
    fonts-dejavu \
    fonts-liberation \
    fonts-noto-cjk \
    fonts-wqy-zenhei \
    && rm -rf /var/lib/apt/lists/* \
    && libreoffice --version \
    && libreoffice --headless --version

# Node.js 20 — HWPX runner (open-hangul-ai hwpx-cli) 가 ESM Node 18+ 요구.
RUN curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && rm -rf /var/lib/apt/lists/* \
 && node --version && npm --version

# 复制项目文件
COPY pyproject.toml ./
COPY app ./app
COPY tools ./tools

# HWPX runner — open-hangul-ai npm 패키지 설치 (production only).
# package-lock.json 을 커밋하지 않는 정책이라 `npm ci` 대신 `npm install` 을 사용한다.
# 재현성은 package.json 의 caret 범위에 의존 — 운영 환경에서 정확한 빌드 재현이 필요하면
# `tools/hwpx-runner` 에 lockfile 을 commit 한 뒤 이 명령을 `npm ci --omit=dev` 로 되돌릴 것.
RUN cd /app/tools/hwpx-runner \
 && npm install --omit=dev --no-fund --no-audit \
 && ls node_modules/open-hangul-ai/bin/hwpx-cli.mjs \
 && node node_modules/open-hangul-ai/bin/hwpx-cli.mjs --version

# 创建一个空的README.md（因为pyproject.toml中引用了它）
RUN touch README.md

# 安装uv包管理器并安装项目依赖
RUN pip install --no-cache-dir uv -i https://pypi.tuna.tsinghua.edu.cn/simple && \
    uv pip install --system -e .


# 暴露端口 (默认8000，可通过环境变量配置)
EXPOSE 8000

# 设置健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import requests; requests.get('http://localhost:8000/health')" || exit 1

# 运行应用（激活虚拟环境）
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]