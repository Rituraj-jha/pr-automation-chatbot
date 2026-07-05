"""
MiNi — Console Interface
Interactive REPL for testing the agent.
"""
from __future__ import annotations

import asyncio
import getpass
import json
import sys
import uuid
import logging
from pathlib import Path

# Add backend_v3 to path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from models.state import Session
from db.connection import set_db_path, init_db, close_db
from db.repository import load_github_token, load_session_fields, save_github_token, save_session
from tools.session_tools import bind_session
from agent.loop import run_agent_turn

# Configure logging
logging.basicConfig(
    level=logging.WARNING,
    format="%(levelname)s | %(name)s | %(message)s",
)
# Set agent logger to DEBUG for tool visibility
logging.getLogger("agent.loop").setLevel(logging.DEBUG)


def _print_banner():
    print("=" * 56)
    print("  MiNi — Minerva Provisioning Assistant (v3)")
    print("  Commands: /state /reset /debug /user <github-user> /token /auth /quit")
    print("=" * 56)


async def _print_state(session: Session):
    session_fields = await load_session_fields(session.session_id)
    active_route = session_fields.get("__active_route", "") or "not set"

    print("\n┌─── STATE ─────────────────────────────────────────")
    print(f"│ Session: {session.session_id[:8]}...")
    print(f"│ User: {session.user_id}")
    print(f"│ Route: {active_route}")
    print(f"│ Resources: {len(session.resources)}")
    for r in session.resources:
        fields_str = ", ".join(f"{k}={v}" for k, v in r.collected_fields.items())
        derived_str = ", ".join(f"{k}={v}" for k, v in r.derived_fields.items())
        print(f"│   [{r.resource_id}] status={r.status.value}")
        if fields_str:
            print(f"│     collected: {fields_str}")
        if derived_str:
            print(f"│     derived: {derived_str}")
        existence_raw = session_fields.get(f"__resource_existence_detail:{r.resource_id}")
        if existence_raw:
            try:
                existence = json.loads(existence_raw)
                exists_label = "yes" if existence.get("exists") else "no"
                print(f"│     repo_exists: {exists_label} path={existence.get('path')}")
            except json.JSONDecodeError:
                print("│     repo_exists: stored detail could not be parsed")
        if r.yaml_output:
            print(f"│     yaml: generated ✓")
    pending_update_raw = session_fields.get("__pending_update")
    if pending_update_raw:
        try:
            pending_update = json.loads(pending_update_raw)
            print("│ Pending update:")
            print(f"│   resource={pending_update.get('resource_type')} branch={pending_update.get('branch')}")
            print(f"│   file={pending_update.get('file_path')}")
            print(f"│   append_only_valid={pending_update.get('append_only_valid')} status={pending_update.get('status')}")
        except json.JSONDecodeError:
            print("│ Pending update: stored detail could not be parsed")
    print(f"│ Messages: {len(session.messages)}")
    print("└───────────────────────────────────────────────────\n")


async def main():
    # Setup database
    db_path = Path(__file__).parent / "mini.db"
    set_db_path(db_path)
    await init_db()
    print("  [DB ready]")

    # Create a new session
    session = Session(session_id=str(uuid.uuid4()))
    await save_session(session)
    bind_session(session)

    _print_banner()
    await _print_state(session)

    # Main loop
    while True:
        try:
            user_input = input("\nYou > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nBye!")
            break

        if not user_input:
            continue

        # Handle commands
        if user_input.startswith("/"):
            cmd = user_input.lower()
            if cmd == "/quit":
                break
            elif cmd == "/state":
                await _print_state(session)
                continue
            elif cmd == "/reset":
                session = Session(session_id=str(uuid.uuid4()), user_id=session.user_id)
                await save_session(session)
                bind_session(session)
                print("  [Session reset]")
                await _print_state(session)
                continue
            elif cmd.startswith("/user"):
                parts = user_input.split(maxsplit=1)
                if len(parts) != 2 or not parts[1].strip():
                    print("  Usage: /user <github-username>")
                    continue
                github_user = parts[1].strip()
                session = Session(session_id=str(uuid.uuid4()), user_id=github_user)
                await save_session(session)
                bind_session(session)
                print(f"  [Console user set to {github_user}; new session started]")
                await _print_state(session)
                continue
            elif cmd == "/token":
                token = getpass.getpass(f"  Paste GitHub token for {session.user_id} (hidden): ").strip()
                if not token:
                    print("  [No token provided]")
                    continue
                await save_github_token(session.user_id, token)
                print(f"  [GitHub token saved for {session.user_id}]")
                continue
            elif cmd == "/auth":
                token = await load_github_token(session.user_id)
                if token:
                    print(f"  [GitHub token found for {session.user_id}]")
                else:
                    print(f"  [No GitHub token found for {session.user_id}. Use /user <github-user> to reuse frontend auth, or /token to save one.]")
                continue
            elif cmd == "/debug":
                # Toggle debug logging
                agent_logger = logging.getLogger("agent.loop")
                if agent_logger.level == logging.DEBUG:
                    agent_logger.setLevel(logging.WARNING)
                    print("  [Debug OFF]")
                else:
                    agent_logger.setLevel(logging.DEBUG)
                    print("  [Debug ON]")
                continue
            else:
                print(f"  Unknown command: {user_input}")
                continue

        # Process through agent
        try:
            response = await run_agent_turn(session, user_input)
            print(f"\nBot > {response}")
        except Exception as e:
            print(f"\n  [ERROR] {e}")
            logging.getLogger(__name__).exception("Agent error")

    await _print_state(session)

    await close_db()


if __name__ == "__main__":
    asyncio.run(main())
