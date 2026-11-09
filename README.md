---
name: create-project
description: Create a basic project directory named project_name under the existing absolute directory root_dir specified by the user, and generate a README.md. Use it when the user asks to create, set up, or initialize an empty project; do not use it to initialize a project for a specific language or framework, or to overwrite an existing project.
---

- Model and other API configuration: `.env`
- MCP server configuration: `plugins/<plugin_name>/<version>/.mcp.json`
- Skill configuration: `plugins/<plugin_name>/<version>/skills`
- React frontend: `webui/frontier`
- Backend agent run command: `python -m uvicorn cli:app --reload`
- Frontend React run command: `npm start`
- Web page: [local](http://127.0.0.1:3000/)

# Create Project

## Objective

Safely create a new project directory under the specified `root_dir`, and generate a `README.md` that contains the project name.

## Required inputs

Determine the following before starting:

- `root_dir`: an existing absolute directory in which to store the project.
- `project_name`: the name of the project to create.

If `root_dir` or `project_name` is missing, ask the user; do not guess.

## Input validation

Validate before running any command:

1. `root_dir` must be an absolute path.
2. `root_dir` must already exist.
3. `project_name` must match:

```text
^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$
```

## Configuration

```.env
DEEPSEEK_API_KEY=""
DEEPSEEK_BASE_URL="https://api.deepseek.com"
DEEPSEEK_MODEL_NAME="deepseek-v4-flash"
TAVILY_API_KEY=""
#LLAMA_API_KEY=ollama
#LLAMA_BASE_URL=http://127.0.0.1:1234/v1 # openai api
# LLAMA_BASE_URL=http://127.0.0.1:11434 # ollama api
#LLAMA_MODEL_NAME=llama-3.1:latest

# RAG server configuration
# Use stream HTTP
#RAG_MCP_PYTHON=python
#RAG_SERVER_DIR=D:\Documents\RAG
#RAG_SERVER_PATH=D:\Documents\RAG\rag_mcp_server.py
RAG_CORPUS_DB_PATH=D:\Documents\RAG\data\corpus\corpus.db
RAG_VECTOR_DB_PATH=D:\Documents\RAG\data\vector\vector.db
RAG_MODEL_PATH=model/corpus/bge-small-zh-v1.5   # Must be a relative path, because the corresponding model_path value stored in the database is a relative path

CHECKPOINT_BACKEND=sqlite
#CHECKPOINT_BACKEND=postgres

MCP_RETRY_INTERVAL_SECONDS=7
```
