# 一次性验收服务镜像：Node 20 + Python 3.11 + Playwright Chromium。
FROM node:20-bookworm

# 安装 Python 3、pip、venv 与 Playwright Chromium 所需的系统库
RUN apt-get update && apt-get install -y --no-install-recommends \
        python3 python3-pip python3-venv \
        fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/*

ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
WORKDIR /workspace

# Python 依赖（FastAPI 应用 + pytest）；Debian 12 的系统 Python 需要
# --break-system-packages 才能用 pip 安装包。
COPY api/requirements.txt /workspace/api/requirements.txt
COPY api/requirements-dev.txt /workspace/api/requirements-dev.txt
RUN python3 -m pip install --break-system-packages --no-cache-dir \
        -r /workspace/api/requirements-dev.txt

# 前端依赖（含 Playwright 浏览器）
COPY web/package.json web/package-lock.json /workspace/web/
WORKDIR /workspace/web
RUN npm ci && npx playwright install --with-deps chromium

# 拷贝全部源码
WORKDIR /workspace
COPY api ./api
COPY web ./web
COPY verify ./verify
COPY scripts ./scripts

WORKDIR /workspace
