# Using Open WebUI with llama-cpp-launchpad

[Open WebUI](https://github.com/open-webui/open-webui) is a separate project with conversation history, document upload
(RAG) and web search. It can talk to the OpenAI-compatible API that `llama-server` exposes while launchpad runs:

```
http://localhost:8080/v1
```

Your model runs offline either way. Web search, if you turn it on below, is done by Open WebUI: it fetches results from
the internet and pastes them into the prompt. The model itself does not browse. Back to the [README](../README.md).

## 1. Start Open WebUI on port 3000

Launchpad uses port `8080`, so run Open WebUI on `3000`. Open WebUI needs Python 3.11–3.12; `uv` or Docker avoid
installing that yourself.

```bash
# A: uv (downloads Python 3.12 for you)
uvx --python 3.12 open-webui serve --port 3000

# B: a dedicated virtual environment with uv
uv venv .venv-312 --python 3.12
.\.venv-312\Scripts\Activate.ps1   # Linux/macOS: source .venv-312/bin/activate
uv pip install open-webui
open-webui serve --port 3000

# C: Docker
docker run -d -p 3000:8080 --add-host=host.docker.internal:host-gateway -v open-webui:/app/backend/data --name open-webui --restart always ghcr.io/open-webui/open-webui:main
```

## 2. Connect it to launchpad

1. Open `http://localhost:3000` and create your local account.
2. Go to **Settings** (or **Admin Panel**) → **Connections** → **OpenAI API**.
3. Set the URL:
   - pip / uv install: `http://localhost:8080/v1`
   - Docker: `http://host.docker.internal:8080/v1`
4. Enter any placeholder API key (e.g. `sk-launchpad`).
5. Press the verify button; your running model should be listed. Click **Save**.

While a chat runs, the [setup page](setup-page.md#start-chatting) shows these exact values for your machine.

## 3. Optional: web search

1. **Settings** → **Web Search** → turn **Enable Web Search** on.
2. Pick a search engine. `duckduckgo` needs no API key.
3. In a chat, enable the web search toggle and ask a question that needs current information.

Menu names above are Open WebUI's and change between its releases; check its own documentation if they differ.
