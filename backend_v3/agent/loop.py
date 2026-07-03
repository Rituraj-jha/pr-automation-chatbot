"""Agent loop — ReAct-style tool-calling loop with guardrails."""
from __future__ import annotations

import json
import logging
from typing import Any

from models.state import Session, Message
from agent.context_builder import build_system_prompt, build_conversation_messages
from agent.guardrails import (
    guardrail_auto_inject_state,
    guardrail_auto_derive,
    guardrail_auto_review,
    guardrail_block_pr_without_review,
    guardrail_session_field_persistence,
    guardrail_auto_check_intake_id,
)
from services.llm import chat_with_tools
from tools.registry import TOOL_FUNCTIONS, TOOL_SCHEMAS
from db.repository import load_user_profile, save_message

logger = logging.getLogger(__name__)

MAX_TOOL_ITERATIONS = 10


async def run_agent_turn(session: Session, user_message: str) -> str:
    """
    Process one user message through the agent loop.

    Guardrails (code-enforced, not prompt-dependent):
    1. Auto-inject current session state before first LLM call
    2. Auto-trigger derive_fields when set_fields returns collection_complete
    3. Auto-trigger review_yaml when generate_yaml succeeds
    4. Block create_pr if any resource is in REVIEWING state
    5. Persist field values to session_fields table for cross-resource reuse
    """
    # Record user message
    session.add_message("user", user_message)
    await save_message(session.session_id, session.messages[-1])

    # Load user profile for context
    profile = await load_user_profile(session.user_id)

    # Build system prompt
    system_prompt = build_system_prompt(session, profile)

    # Build message history for LLM
    llm_messages: list[dict] = [{"role": "system", "content": system_prompt}]
    llm_messages.extend(build_conversation_messages(session))

    # Guardrail 1: auto-inject fresh state
    await guardrail_auto_inject_state(llm_messages)

    # Agent loop
    for iteration in range(MAX_TOOL_ITERATIONS):
        # Call LLM
        response = await chat_with_tools(llm_messages, tools=TOOL_SCHEMAS)

        # If no tool calls — we have the final response
        if not response.get("tool_calls"):
            content = response.get("content", "")
            session.add_message("assistant", content)
            await save_message(session.session_id, session.messages[-1])
            return content

        # Has tool calls — execute them
        llm_messages.append(response)

        for tool_call in response["tool_calls"]:
            func_name = tool_call["function"]["name"]
            try:
                args = json.loads(tool_call["function"]["arguments"])
            except json.JSONDecodeError:
                args = {}

            # Guardrail 4: Block PR if resources are in REVIEWING
            blocked = await guardrail_block_pr_without_review(func_name, args)
            if blocked:
                result = blocked
            else:
                # Execute tool
                tool_fn = TOOL_FUNCTIONS.get(func_name)
                if tool_fn is None:
                    result = json.dumps({"error": f"Unknown tool: {func_name}"})
                else:
                    try:
                        result = await tool_fn(**args)
                    except Exception as e:
                        logger.exception(f"Tool {func_name} failed")
                        result = json.dumps({"error": str(e)})

            # Guardrail 2: auto-derive if collection just completed
            result = await guardrail_auto_derive(func_name, result, tool_call["id"])

            # Guardrail 3: auto-review after generate_yaml
            result = await guardrail_auto_review(func_name, result, tool_call["id"])

            # Guardrail 5: persist session fields
            await guardrail_session_field_persistence(func_name, result)

            # Guardrail 6: auto-check intake ID after set_fields
            result = await guardrail_auto_check_intake_id(func_name, result)

            # Add tool result to LLM messages
            llm_messages.append({
                "role": "tool",
                "tool_call_id": tool_call["id"],
                "content": result,
            })

            logger.debug(f"Tool: {func_name}({args}) → {result[:200]}")

    # Exceeded max iterations
    session.add_message("assistant", "I'm having trouble processing this. Could you rephrase?")
    await save_message(session.session_id, session.messages[-1])
    return session.messages[-1].content
