ARG PYTHON_IMAGE=python:3.12-slim
FROM node:22-alpine AS renderer-deps
WORKDIR /renderer
COPY renderer/package*.json ./
RUN npm ci --omit=dev --no-audit --no-fund
FROM ${PYTHON_IMAGE}
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
RUN sed -i 's|http://deb.debian.org|https://deb.debian.org|g' /etc/apt/sources.list.d/debian.sources && apt-get -o Acquire::Retries=3 update && apt-get -o Acquire::Retries=3 install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-chi-sim fonts-noto-cjk libcairo2 nodejs && rm -rf /var/lib/apt/lists/*
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && useradd --create-home app
COPY --from=renderer-deps /renderer/node_modules ./renderer/node_modules
COPY . .
USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-proxy-headers"]
