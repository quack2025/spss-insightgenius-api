"""
InsightGenius × Claude Agent SDK — POC
Uses the Agent SDK (claude_agent_sdk.query) to run analysis pipeline.
"""

import asyncio
import sys
import io

# Fix Windows cp1252 encoding for emojis
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')

from claude_agent_sdk import query, ClaudeAgentOptions

INSIGHTGENIUS_API_KEY = os.environ.get("INSIGHTGENIUS_API_KEY", "")  # Set via env var
STUDY_FILE_ID = os.environ.get("STUDY_FILE_ID", "")  # Get from https://spss.insightgenius.io/upload


async def run_pipeline():
    options = ClaudeAgentOptions(
        system_prompt=f"""You are an expert market research analyst.
You have access to InsightGenius MCP tools for SPSS data analysis.

RULES:
- For EVERY tool call, pass: api_key="{INSIGHTGENIUS_API_KEY}"
- For file operations, also pass: file_id="{STUDY_FILE_ID}"
- NEVER calculate statistics yourself — use the tools
- Write a concise executive summary after analysis
""",
        mcp_servers="mcp_config.json",
        permission_mode="bypassPermissions",
    )

    prompt = f"""Analyze this survey data step by step:

1. Call spss_get_server_info (no params needed) to verify connectivity
2. Call spss_get_metadata with file_id="{STUDY_FILE_ID}", api_key="{INSIGHTGENIUS_API_KEY}"
3. Based on metadata, call spss_analyze_frequencies on a key variable
4. Call spss_analyze_crosstab for a KPI × demographic
5. Write executive summary

Remember: api_key="{INSIGHTGENIUS_API_KEY}" in every call. file_id="{STUDY_FILE_ID}" for file operations.
"""

    print("=" * 60)
    print("INSIGHTGENIUS × CLAUDE AGENT SDK — PIPELINE")
    print("=" * 60)
    print()

    tool_count = 0
    async for message in query(prompt=prompt, options=options):
        if hasattr(message, 'content'):
            for block in message.content:
                if hasattr(block, 'text') and block.text:
                    print(block.text, flush=True)
                elif hasattr(block, 'type') and block.type == 'tool_use':
                    tool_count += 1
                    name = getattr(block, 'name', '?')
                    print(f"\n  [{tool_count}] TOOL: {name}", flush=True)
                    tool_input = getattr(block, 'input', {})
                    if isinstance(tool_input, dict):
                        for k, v in tool_input.items():
                            print(f"       {k}: {str(v)[:80]}", flush=True)
                elif hasattr(block, 'type') and block.type == 'tool_result':
                    content = getattr(block, 'content', '')
                    print(f"  -> RESULT ({str(content)[:100]}...)", flush=True)
        elif hasattr(message, 'text') and message.text:
            print(message.text, flush=True)

    print()
    print("=" * 60)
    print(f"PIPELINE COMPLETE — {tool_count} tool calls")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(run_pipeline())
