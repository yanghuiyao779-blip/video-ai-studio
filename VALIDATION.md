# V2 打包前验证

## 已通过

- Python `compileall`：通过。
- Frontend `App.jsx / api.js / main.jsx` TypeScript JSX 解析：通过。
- Backend unit tests：**9 passed**。
- Alembic 空 SQLite 迁移：通过。
  - `0001_initial`
  - `0002_product_ux_fields`
  - `0003_local_uploads`
- SQLite 迁移后确认新增字段：
  - `summary_preset`
  - `summary_instruction`
  - `error_code`
  - `source_type`
  - `source_filename`
  - `source_path`
- FastAPI 本地上传 API 冒烟测试：通过。
- queued task 取消 API：通过。
- processing task 协作式取消状态：API 冒烟测试通过（`processing → cancel_requested`）。
- ASR 后文字稿检查点：已覆盖实现；在外部 LLM 调用前写入可复用的 `result.json` / TXT / SRT。
- cancelled task 删除与文件清理 API：通过。
- Health 响应结构：通过。
- 中文错误分类测试：通过。
- 中文 Markdown exporter 测试：通过。
- V1 安全存储测试继续通过：API Key 加密/解密与密码哈希未回退。

## 前端依赖构建说明

当前打包执行环境访问 npm registry 时安装依赖超时，因此没有在本环境完成真正的：

```bash
npm install
npm run build
```

但 JSX 已由 TypeScript 编译器完成语法解析。

你之前的 V1 已经在实际 Docker 环境成功执行过同样的 Node/Vite 构建链路；V2 仍沿用相同的 React + Vite + Nginx 架构，只修改应用代码和 UI。

## Docker

当前执行环境没有可用 Docker daemon，因此最终镜像构建需要在实际部署机完成：

```bash
docker compose up -d --build
```

后端容器会先执行：

```bash
alembic upgrade head
```

再启动 FastAPI。
