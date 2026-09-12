"""
Async MCP Test Client Harness for Database Auditor MCP.
Connects over stdio transport, performs tool discovery, reads resources, and executes queries.
"""

import asyncio
import os
import sys
from mcp.client.session import ClientSession
from mcp.client.stdio import stdio_client, StdioServerParameters


async def run_client_harness():
    print("=" * 60)
    print("STARTING DATABASE AUDITOR MCP CLIENT TEST HARNESS")
    print("=" * 60)

    server_script = os.path.abspath("server.py")
    server_params = StdioServerParameters(
        command=sys.executable,
        args=[server_script],
        env=dict(os.environ),
    )

    async with stdio_client(server_params) as (read, write):
        async with ClientSession(read, write) as session:
            # 1. Initialize MCP session
            await session.initialize()
            print("\n[OK] MCP Client session initialized successfully.")

            # 2. Tool Discovery
            tools_response = await session.list_tools()
            tool_names = [t.name for t in tools_response.tools]
            print(f"\n[INFO] Discovered Tools ({len(tool_names)}):", tool_names)
            assert "execute_safe_query" in tool_names
            assert "profile_table" in tool_names
            assert "get_database_health" in tool_names

            # 3. Read Resource: schema://current
            print("\n[READ] Reading Resource: 'schema://current'...")
            res_current = await session.read_resource("schema://current")
            assert res_current is not None
            print("   -> Resource payload received successfully.")

            # 4. Read Resource: schema://table/users
            print("\n[READ] Reading Resource: 'schema://table/users'...")
            res_users = await session.read_resource("schema://table/users")
            assert res_users is not None
            print("   -> Table schema payload received successfully.")

            # 5. Call Tool: execute_safe_query
            print("\n[TOOL] Calling Tool: execute_safe_query('SELECT * FROM tenants')...")
            query_res = await session.call_tool("execute_safe_query", {"sql": "SELECT * FROM tenants"})
            print("   -> Tool Output Preview:")
            query_text = query_res.content[0].text if query_res.content else ""
            print("\n".join(query_text.splitlines()[:10]))
            assert "Acme Corp" in query_text

            # 6. Call Tool: execute_safe_query with rejected DDL (DROP TABLE)
            print("\n[SECURITY] Testing Security Defense: execute_safe_query('DROP TABLE users')...")
            rejection_res = await session.call_tool("execute_safe_query", {"sql": "DROP TABLE users"})
            rejection_text = rejection_res.content[0].text if rejection_res.content else ""
            print("   -> Guardrail Rejection Message:")
            safe_text = rejection_text.encode("ascii", errors="replace").decode("ascii")
            print("\n".join(safe_text.splitlines()[:5]))
            assert "SECURITY GUARDRAIL REJECTION" in rejection_text

            # 7. Call Tool: get_database_health
            print("\n[HEALTH] Calling Tool: get_database_health()...")
            health_res = await session.call_tool("get_database_health", {})
            health_text = health_res.content[0].text if health_res.content else ""
            assert "Database Health & Audit Summary" in health_text
            print("   -> Database health check completed.")

            print("\n" + "=" * 60)
            print("ALL CLIENT HARNESS INTEGRATION TESTS PASSED SUCCESSFULLY!")
            print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_client_harness())
