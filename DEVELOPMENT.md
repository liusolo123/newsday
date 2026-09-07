# 本地开发环境

本项目以 Python 3.12、Node.js 24 和 [uv](https://docs.astral.sh/uv/) 维护可复现的依赖环境。Python 的 `requirements.txt` 与 `requirements-dev.in` 是人工维护的输入；带 hash 的 `.lock` 文件是提交到仓库的安装来源。前端依赖由 `package-lock.json` 锁定。

## 首次安装

```bash
uv venv --seed --python 3.12 .venv
make install-dev
cp .env.example .env
npm ci
```

在 `.env` 中填写本地数据库和仅供本机使用的密钥，并将 `APP_ENV` 改为 `development`。它已被 Git 忽略，不能复制真实凭据到 `.env.example`、文档或测试代码中。若本地未设置 `DATABASE_URL`，开发命令会自动创建并使用 `data/newsday-dev.db`；该 SQLite 文件被 Git 忽略，仅用于查看和调试页面。已设置 PostgreSQL `DATABASE_URL` 时，仍使用原有 Alembic 迁移流程。

## 启动本地网页

首次需要展示完整新闻列表时，先创建只用于本机的演示数据：

```bash
npm run dev:seed
```

然后使用一条命令启动后端和 Vite 热更新服务：

```bash
npm run dev
```

在浏览器访问 `http://127.0.0.1:8000/zh/`。不要直接访问 5173；它只向 FastAPI 页面提供 CSS、JavaScript 和热更新。`Ctrl+C` 会同时停止两个开发进程。

`dev:seed` 不访问新闻源或润色模型；它只在 `APP_ENV=development` 时创建每个分类 10 条带成功润色记录的本地数据。生产环境会拒绝执行该命令。

## 日常校验

```bash
make check
```

该命令依次执行依赖完整性检查、Ruff 未定义/未使用符号检查、Python 语法编译、全量单元测试和 Vite 生产构建。

## 更新依赖

修改输入文件后，重新生成两个锁定文件，并在提交前安装与验证：

```bash
uv pip compile --generate-hashes -o requirements.lock requirements.txt
uv pip compile --generate-hashes -o requirements-dev.lock requirements-dev.in
make install-dev
make check
```
