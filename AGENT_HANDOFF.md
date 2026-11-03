# Narcissus 开发交接

更新时间：2026-11-04。

本仓库根目录即当前应用源码。前端采用纸感编辑风，技术栈为 Next.js / React / TypeScript；后端为 FastAPI、Celery、PostgreSQL / pgvector 与 S3 兼容存储。运行参数通过私有 `.env` 提供，提交时只保留 `.env.example`。

## 维护入口

- `frontend/app/page.tsx`：书房、笔记本搜索和管理。
- `frontend/app/editorial.css`：统一视觉与响应式布局。
- `frontend/components/shared.tsx`：Narcissus 品牌与 CSS 书册插画。
- `frontend/app/notebooks/[id]/page.tsx`：资料、对话与创作工作区。
- `frontend/app/api/[...path]/route.ts`：同域代理，透传会话与流式响应。
- `backend/app/main.py`：API 与请求来源检查。
- `backend/app/security.py`：会话与安全基础设施。
- `backend/app/tasks.py`：Celery 入口。

## 部署边界

前端改动使用 `docker compose up -d --build --no-deps web`。操作已有环境时先核对项目标识、私有配置和卷映射，保留现有数据；不要把新安装默认名字直接套用到旧卷。后端升级及数据库迁移是独立操作，按实际迁移状态执行。

当前源码包含 `009_vector_hnsw.py`；线上迁移状态需要运行时核对。只更新 web 不运行迁移。

`BACKEND_REQUEST_MARKER` 可在只更新前端时兼容现有后端。默认值为 `narcissus`，新安装无需覆盖。私有兼容配置不应提交到仓库。

## 验证

前端通过 Docker 生产构建与 TypeScript 检查；浏览器使用隔离 API 数据检查桌面、手机、Markdown 和常用交互。详见 `docs/EDITORIAL-REDESIGN.md`。历史验证记录不是当前服务状态的保证，真实生成需要单独配置并验证对应服务。
