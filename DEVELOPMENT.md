# 本地开发环境

本项目以 Python 3.12 和 [uv](https://docs.astral.sh/uv/) 维护可复现的依赖环境。`requirements.txt` 与 `requirements-dev.in` 是人工维护的输入；带 hash 的 `.lock` 文件是提交到仓库的安装来源。

## 首次安装

```bash
uv venv --seed --python 3.12 .venv
make install-dev
cp .env.example .env
```

在 `.env` 中填写本地数据库和仅供本机使用的密钥。它已被 Git 忽略，不能复制真实凭据到 `.env.example`、文档或测试代码中。

## 日常校验

```bash
make check
```

该命令依次执行依赖完整性检查、Ruff 未定义/未使用符号检查、Python 语法编译和全量单元测试。

## 更新依赖

修改输入文件后，重新生成两个锁定文件，并在提交前安装与验证：

```bash
uv pip compile --generate-hashes -o requirements.lock requirements.txt
uv pip compile --generate-hashes -o requirements-dev.lock requirements-dev.in
make install-dev
make check
```
