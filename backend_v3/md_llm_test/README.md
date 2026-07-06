# Markdown LLM Test Client

This folder lets you send a single Markdown file directly to the TrueFoundry OpenAI-compatible API, without using the backend agent loop, tools, database, or UI.

## Files

- `md_llm_client.py` — CLI client that reads a Markdown file and calls the configured model.
- `prompt.md` — default Markdown input file. Replace it with the document you want to test.
- `.env` — local env file copied from `backend_v3/.env`. This is ignored by git.
- `.env.example` — non-secret env template.

## Usage

From `backend_v3`:

```powershell
python .\md_llm_test\md_llm_client.py --show-config
```

Start an interactive console chat with the default `prompt.md` loaded as context:

```powershell
python .\md_llm_test\md_llm_client.py --interactive --show-config
```

Start an interactive chat with a specific Markdown file:

```powershell
python .\md_llm_test\md_llm_client.py .\context\shared\s3_naming_conventions.md --interactive
```

Inside the interactive console, use `/reset` to reload the Markdown context or `/exit` to quit.

Send a specific Markdown file:

```powershell
python .\md_llm_test\md_llm_client.py .\context\shared\s3_naming_conventions.md --question "What fields can be derived from this document?"
```

Send only the Markdown as a raw user message:

```powershell
python .\md_llm_test\md_llm_client.py .\context\shared\s3_naming_conventions.md --raw
```

Write the assistant response to a file:

```powershell
python .\md_llm_test\md_llm_client.py .\md_llm_test\prompt.md --output .\md_llm_test\last_response.md
```