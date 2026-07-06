"""Direct Markdown-to-LLM test client for the TrueFoundry OpenAI gateway.

This script is intentionally isolated from the backend agent loop so you can
send one Markdown file directly to the configured model and inspect the raw
assistant response.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path

import httpx
from dotenv import load_dotenv
from openai import AsyncOpenAI


THIS_DIR = Path(__file__).resolve().parent
DEFAULT_ENV_PATH = THIS_DIR / ".env"
DEFAULT_MD_PATH = THIS_DIR / "prompt.md"


def load_local_env(env_path: Path) -> None:
    """Load this test folder's .env and fail fast if credentials are absent."""
    if not env_path.exists():
        raise FileNotFoundError(
            f"Missing env file: {env_path}\n"
            "Copy backend_v3/.env to md_llm_test/.env or run this from the prepared workspace."
        )
    load_dotenv(env_path, override=True)


def resolve_input_path(raw_path: str | None) -> Path:
    """Resolve Markdown path from cwd first, then from this script folder."""
    if not raw_path:
        return DEFAULT_MD_PATH

    path = Path(raw_path).expanduser()
    if path.is_absolute() or path.exists():
        return path.resolve()
    return (THIS_DIR / path).resolve()


def build_messages(markdown: str, question: str | None, system_prompt: str, raw: bool) -> list[dict]:
    """Build an OpenAI chat message payload for a direct Markdown test."""
    if raw:
        content = markdown
        if question:
            content = f"{markdown}\n\n---\n\n{question}"
        return [{"role": "user", "content": content}]

    question_text = question or "Respond to this Markdown exactly as you would in the application."
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": (
                "Use the following Markdown as the complete test input.\n\n"
                "<markdown>\n"
                f"{markdown}\n"
                "</markdown>\n\n"
                f"Test request: {question_text}"
            ),
        },
    ]


def create_client() -> AsyncOpenAI:
    """Create an OpenAI-compatible client for TrueFoundry."""
    api_key = os.getenv("TRUEFOUNDRY_OPENAI_API_KEY", "").strip()
    base_url = os.getenv("TRUEFOUNDRY_OPENAI_BASE_URL", "https://tfy-dev.aiops.cloudapps.cargill.com").strip()
    ca_bundle = os.getenv("CUSTOM_CA_BUNDLE_PATH")

    if not api_key:
        raise ValueError("TRUEFOUNDRY_OPENAI_API_KEY is missing in md_llm_test/.env")

    # Match backend_v3 behavior: corporate proxy env vars can interfere locally.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        os.environ.pop(key, None)

    http_client = httpx.AsyncClient(verify=ca_bundle) if ca_bundle else None
    return AsyncOpenAI(api_key=api_key, base_url=base_url, http_client=http_client)


async def call_llm(args: argparse.Namespace) -> str:
    """Load Markdown, call the configured model, and return assistant text."""
    env_path = Path(args.env).expanduser().resolve() if args.env else DEFAULT_ENV_PATH
    load_local_env(env_path)

    md_path = resolve_input_path(args.markdown)
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    markdown = md_path.read_text(encoding="utf-8")
    system_prompt = args.system or os.getenv(
        "MD_TEST_SYSTEM_PROMPT",
        "You are a concise assistant testing how the application LLM responds to Markdown input.",
    )
    model = args.model or os.getenv("TRUEFOUNDRY_OPENAI_MODEL", "openai/gpt-5-mini")
    temperature = args.temperature
    if temperature is None:
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))

    messages = build_messages(markdown, args.question, system_prompt, args.raw)
    client = create_client()

    if args.show_config:
        print(f"env: {env_path}")
        print(f"markdown: {md_path}")
        print(f"model: {model}")
        print(f"base_url: {os.getenv('TRUEFOUNDRY_OPENAI_BASE_URL')}")
        print()

    try:
        response = await client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=temperature,
        )
        return response.choices[0].message.content or ""
    finally:
        await client.close()


def read_runtime_config(args: argparse.Namespace) -> tuple[Path, Path, str, str, str, float]:
    """Load env/Markdown and return common runtime values."""
    env_path = Path(args.env).expanduser().resolve() if args.env else DEFAULT_ENV_PATH
    load_local_env(env_path)

    md_path = resolve_input_path(args.markdown)
    if not md_path.exists():
        raise FileNotFoundError(f"Markdown file not found: {md_path}")

    markdown = md_path.read_text(encoding="utf-8")
    system_prompt = args.system or os.getenv(
        "MD_TEST_SYSTEM_PROMPT",
        "You are a concise assistant testing how the application LLM responds to Markdown input.",
    )
    model = args.model or os.getenv("TRUEFOUNDRY_OPENAI_MODEL", "openai/gpt-5-mini")
    temperature = args.temperature
    if temperature is None:
        temperature = float(os.getenv("LLM_TEMPERATURE", "0.1"))

    return env_path, md_path, markdown, system_prompt, model, temperature


def build_interactive_messages(markdown: str, system_prompt: str, raw: bool) -> list[dict]:
    """Seed an interactive console chat with the selected Markdown file."""
    if raw:
        return [{"role": "user", "content": markdown}]

    return [
        {
            "role": "system",
            "content": (
                f"{system_prompt}\n\n"
                "Use this Markdown as persistent context for the console chat.\n\n"
                "<markdown>\n"
                f"{markdown}\n"
                "</markdown>"
            ),
        }
    ]


async def interactive_chat(args: argparse.Namespace) -> None:
    """Start a console REPL against the configured LLM."""
    env_path, md_path, markdown, system_prompt, model, temperature = read_runtime_config(args)
    messages = build_interactive_messages(markdown, system_prompt, args.raw)
    client = create_client()

    if args.show_config:
        print(f"env: {env_path}")
        print(f"markdown: {md_path}")
        print(f"model: {model}")
        print(f"base_url: {os.getenv('TRUEFOUNDRY_OPENAI_BASE_URL')}")
        print()

    print("Interactive Markdown LLM console started.")
    print("Type your message and press Enter. Commands: /exit, /reset")
    print()

    next_user_input = args.question
    try:
        while True:
            if next_user_input:
                user_input = next_user_input
                next_user_input = None
                print(f"you> {user_input}")
            else:
                user_input = input("you> ").strip()

            if not user_input:
                continue
            if user_input.lower() in {"/exit", "exit", "quit", "/quit"}:
                break
            if user_input.lower() == "/reset":
                messages = build_interactive_messages(markdown, system_prompt, args.raw)
                print("assistant> Conversation reset; Markdown context reloaded.")
                continue

            messages.append({"role": "user", "content": user_input})
            response = await client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=temperature,
            )
            answer = response.choices[0].message.content or ""
            messages.append({"role": "assistant", "content": answer})
            print(f"assistant> {answer}")
            print()
    finally:
        await client.close()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Send a Markdown file directly to the TrueFoundry LLM API.")
    parser.add_argument("markdown", nargs="?", help="Markdown file path. Defaults to md_llm_test/prompt.md.")
    parser.add_argument("-q", "--question", help="Optional test question/request to append after the Markdown.")
    parser.add_argument("-i", "--interactive", action="store_true", help="Start an interactive console chat using the Markdown as context.")
    parser.add_argument("--raw", action="store_true", help="Send only the Markdown as a single user message.")
    parser.add_argument("--system", help="Override the default system prompt for non-raw mode.")
    parser.add_argument("--model", help="Override TRUEFOUNDRY_OPENAI_MODEL for this run.")
    parser.add_argument("--temperature", type=float, help="Override LLM_TEMPERATURE for this run.")
    parser.add_argument("--env", help="Path to env file. Defaults to md_llm_test/.env.")
    parser.add_argument("-o", "--output", help="Optional path to write the assistant response.")
    parser.add_argument("--show-config", action="store_true", help="Print non-secret runtime config before calling the model.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.interactive:
        asyncio.run(interactive_chat(args))
        return

    answer = asyncio.run(call_llm(args))
    print(answer)

    if args.output:
        output_path = Path(args.output).expanduser().resolve()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(answer, encoding="utf-8")


if __name__ == "__main__":
    main()