"""Chainlit chat UI for Hermes.

Forwards messages to the hermes service over HTTP. Streaming and tool-call
visualization come later — this is the minimum needed to talk to the agent.
"""
from __future__ import annotations

import os

import chainlit as cl
import httpx


HERMES_URL = os.environ.get("HERMES_URL", "http://hermes:8000")
REQUEST_TIMEOUT = 120.0


@cl.on_chat_start
async def on_start() -> None:
    cl.user_session.set("session_id", cl.user_session.get("id"))
    await cl.Message(content="Hermes online. What do you need?").send()


@cl.on_message
async def on_message(msg: cl.Message) -> None:
    payload = {
        "message": msg.content,
        "session_id": cl.user_session.get("session_id"),
    }
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        try:
            r = await client.post(f"{HERMES_URL}/chat", json=payload)
            r.raise_for_status()
            reply = r.json().get("reply", "(empty reply)")
        except httpx.HTTPError as exc:
            reply = f"Error reaching hermes ({HERMES_URL}): {exc}"

    await cl.Message(content=reply).send()
