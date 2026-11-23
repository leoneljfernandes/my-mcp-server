"""Ejemplo actualizado de consumo desde LangGraph v1 / LangChain v1.

Requisitos (en el proyecto de agentes, fuera de este MCP Server):
    uv add langchain langchain-mcp-adapters langchain-google-genai
    # o langchain-anthropic / langchain-openai según el LLM que elijas

Notas de compatibilidad (2026):
- `langchain-mcp-adapters>=0.1.0` eliminó `async with MultiServerMCPClient(...)`:
  se instancia directamente y se llama `await client.get_tools()`.
- `langgraph.prebuilt.create_react_agent` está deprecado en favor de
  `from langchain.agents import create_agent`.
"""

from __future__ import annotations

import asyncio
import os
from typing import Any


async def build_specialized_agent(role: str, task: str) -> dict[str, Any]:
    """Conecta al DevTeam Skills MCP remoto e inicializa un agente especializado por rol."""
    # Imports dentro de la función para mantener el repo del MCP desacoplado de LLMs.
    from langchain.agents import create_agent  # type: ignore[import-not-found]
    from langchain_mcp_adapters.client import MultiServerMCPClient  # type: ignore[import-not-found]

    mcp_url = os.environ.get("DEVTEAM_MCP_URL", "http://localhost:8000/mcp")
    mcp_api_key = os.environ.get("MCP_API_KEY", "")

    headers: dict[str, str] = {}
    if mcp_api_key:
        headers["Authorization"] = f"Bearer {mcp_api_key}"

    client = MultiServerMCPClient(
        {
            "devteam_skills": {
                "transport": "streamable_http",
                "url": mcp_url,
                "headers": headers,
            }
        }
    )

    tools = await client.get_tools()

    # Inyecta el bundle del rol (reglas de precedencia + skills core + catálogo on_demand)
    get_role_skills_tool = next(t for t in tools if t.name == "get_role_skills")
    role_system_prompt: str = await get_role_skills_tool.ainvoke(
        {"role": role, "include_on_demand": False}
    )

    agent = create_agent(
        model="google_genai:gemini-2.5-pro",
        tools=tools,
        system_prompt=role_system_prompt,
    )

    result: dict[str, Any] = await agent.ainvoke(
        {"messages": [{"role": "user", "content": task}]}
    )
    return result


if __name__ == "__main__":
    output = asyncio.run(
        build_specialized_agent(
            role="backend",
            task="Diseñá el endpoint POST /api/v1/orders siguiendo las skills del equipo.",
        )
    )
    print(output["messages"][-1].content)
