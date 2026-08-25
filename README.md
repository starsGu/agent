---
name: create-project
description: 在用户指定的已存在绝对目录 root_dir 下创建名为 project_name 的基础项目目录，并生成 README.md。当用户要求新建、创建或初始化一个空项目时使用；不用于初始化特定语言、框架或覆盖已有项目。
---

模型等 api 配置 在 .env
mcp 服务器配置在plugins/<plugin_name>/<version>/.mcp.json
skill 配置在 plugins/<plugin_name>/<version>/skills

react前端在 webui/froniter

后端 agent运行命令 python -m uvicorn cli:app --reload
前端 react运行命令 npm start
网页 [local](http://127.0.0.1:3000/)

# Create Project

## Objective

在指定的 `root_dir` 下安全创建新的项目目录，并生成包含项目名称的 `README.md`。

## Required inputs

开始前确定：

- `root_dir`：用于存放项目的已存在绝对目录。
- `project_name`：需要创建的项目名称。

如果缺少 `root_dir` 或 `project_name`，必须询问用户，不要自行猜测。

## Input validation

执行任何命令前验证：

1. `root_dir` 必须是绝对路径。
2. `root_dir` 必须已经存在。
3. `project_name` 必须符合：

```text
^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$

## 

```.env
DEEPSEEK_API_KEY=""
DEEPSEEK_BASE_URL="https://api.deepseek.com"
DEEPSEEK_MODEL_NAME="deepseek-v4-flash"
TAVILY_API_KEY=""
#LLAMA_API_KEY=ollama
#LLAMA_BASE_URL=http://127.0.0.1:1234/v1 # openai api
# LLAMA_BASE_URL=http://127.0.0.1:11434 # ollama api
#LLAMA_MODEL_NAME=llama-3.1:latest

# RAG 服务器的配置
# 使用stream http
#RAG_MCP_PYTHON=python
#RAG_SERVER_DIR=D:\Documents\RAG
#RAG_SERVER_PATH=D:\Documents\RAG\rag_mcp_server.py
RAG_CORPUS_DB_PATH=D:\Documents\RAG\data\corpus\corpus.db
RAG_VECTOR_DB_PATH=D:\Documents\RAG\data\vector\vector.db
RAG_MODEL_PATH=model/corpus/bge-small-zh-v1.5   # 需要写相对路径，因为数据库里的对应model_path字段的值是相对路径

CHECKPOINT_BACKEND=sqlite
#CHECKPOINT_BACKEND=postgres

MCP_RETRY_INTERVAL_SECONDS=7