# Use the model from other programs

While a model runs, `llama-server` answers the OpenAI API on this computer. Any program that lets you set an
"OpenAI-compatible" address can use your local model instead of a cloud service. Back to the
[documentation home](../README.md).

> **Screenshots and video:** not recorded yet; see [How the pictures are made](../media/README.md).

## The values

The setup page shows these, filled in, while a chat it started is running (under **Use it from other programs**).
They come from `utils/clients.py`. `PORT` is the port the server runs on: `8080` by default, or the `PORT` you set.
When it is taken, the setup page names the program holding it and offers the next free port; the values it shows
are always for the port the server really uses.

| Setting | Value |
| --- | --- |
| Address (base URL) | `http://127.0.0.1:PORT/v1` |
| API key | any text, e.g. `sk-local`. It is not checked, because `llama-server` checks a key only when it was started with `--api-key`. |
| Model | the model's name. With one model loaded, `llama-server` answers whatever name is asked for. With *Serve all my models* (router mode), the name chooses the model. |

To try it from a terminal:

```bash
curl http://127.0.0.1:8080/v1/chat/completions -H "Content-Type: application/json" \
  -d '{"model": "local", "messages": [{"role": "user", "content": "Say hello in French."}]}'
```

## Open WebUI

Admin Panel > Settings > Connections > OpenAI API, then:

- URL `http://127.0.0.1:PORT/v1`, or `http://host.docker.internal:PORT/v1` when Open WebUI runs in Docker;
- API key `sk-local`.

Then pick the model in a new chat. Starting Open WebUI and using its documents and web search are covered in
[Using Open WebUI](../open-webui.md).

## Continue (VS Code, JetBrains)

Add to Continue's `config.yaml`. Note that `apiBase` has no `/v1`:

```yaml
name: Local llama.cpp
version: 0.0.1
schema: v1

models:
  - name: MODEL
    provider: llama.cpp
    model: MODEL
    apiBase: http://127.0.0.1:PORT
```

## aider

In your project's folder:

```bash
OPENAI_API_BASE=http://127.0.0.1:PORT/v1 OPENAI_API_KEY=sk-local aider --model openai/MODEL
```

```powershell
$env:OPENAI_API_BASE="http://127.0.0.1:PORT/v1"; $env:OPENAI_API_KEY="sk-local"; aider --model openai/MODEL
```

aider may warn that it does not know this model; that is expected. The setup page shows this command only when it
finds `aider` on your PATH, and says so when it does not.

## Good to know

- `llama-server` listens on this computer only, unless you start it with `--host`. Other computers cannot reach it.
- Speed is this computer's: the setup page's speed test tells you what to expect. Several programs using the same
  server at once share it.
