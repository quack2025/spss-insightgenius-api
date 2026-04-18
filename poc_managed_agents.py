"""
InsightGenius × Claude Managed Agents — POC
Ejecuta un pipeline completo de análisis SPSS de forma autónoma.
"""

import anthropic
import httpx
import json
import os

# Config
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY", "")  # Set via: export ANTHROPIC_API_KEY=sk-ant-...
INSIGHTGENIUS_API_KEY = os.environ.get("INSIGHTGENIUS_API_KEY", "")  # Set via env var
STUDY_FILE_ID = "875241b9-3d10-4165-ae4c-74aebeb1a826"

# Long timeout for SSE streaming (agent can take minutes)
client = anthropic.Anthropic(
    api_key=ANTHROPIC_API_KEY,
    timeout=httpx.Timeout(600.0, connect=30.0),
)

# --- 1. Create Agent ---
print("Creating agent...")
agent = client.beta.agents.create(
    model="claude-sonnet-4-6",
    name="InsightGenius Analyst",
    description="Expert market research analyst using InsightGenius for SPSS analysis",
    system=f"""You are an expert market research analyst.

You have access to InsightGenius tools for professional SPSS data analysis.
These tools provide deterministic statistical results with significance testing.

CRITICAL RULES:
- For EVERY tool call, you MUST pass: api_key="{INSIGHTGENIUS_API_KEY}"
- For tools that need a file, pass: file_id="{STUDY_FILE_ID}"
- NEVER calculate statistics yourself — always use the tools
- After analysis, write a concise executive summary

Start with spss_get_metadata, then frequencies, then a crosstab, then create a tabulation Excel.
""",
    mcp_servers=[
        {
            "type": "url",
            "url": "https://spss.insightgenius.io/mcp/sse",
            "name": "insightgenius",
        }
    ],
    tools=[
        {
            "type": "mcp_toolset",
            "mcp_server_name": "insightgenius",
        }
    ],
)
print(f"Agent: {agent.id}")

# --- 2. Create Environment ---
print("Creating environment...")
environment = client.beta.environments.create(name="poc-env")
print(f"Environment: {environment.id}")

# --- 3. Create Session ---
print("Creating session...")
session = client.beta.sessions.create(
    agent=agent.id,
    environment_id=environment.id,
)
print(f"Session: {session.id}")

# --- 4. Send task ---
task = f"""First, verify connectivity by calling spss_get_server_info (no parameters needed).

Then analyze the survey data:

Step 1: Call spss_get_server_info (no params)
Step 2: Call spss_get_metadata with file_id="{STUDY_FILE_ID}" and api_key="{INSIGHTGENIUS_API_KEY}"
Step 3: Call spss_analyze_frequencies with file_id="{STUDY_FILE_ID}", api_key="{INSIGHTGENIUS_API_KEY}", variable=(pick a demographic from metadata)
Step 4: Write an executive summary

IMPORTANT: Every tool call must include api_key="{INSIGHTGENIUS_API_KEY}". For file operations also include file_id="{STUDY_FILE_ID}".
If a tool call crashes, try it again once.
"""

print("Sending task...")
client.beta.sessions.events.send(
    session_id=session.id,
    events=[{"type": "user.message", "content": [{"type": "text", "text": task}]}],
)

# --- 5. Stream results ---
print("\n{'='*60}")
print("PIPELINE RUNNING")
print(f"{'='*60}\n")

tool_count = 0
for event in client.beta.sessions.events.stream(session_id=session.id):
    data = event.data if hasattr(event, 'data') else event
    etype = getattr(data, 'type', '')

    if etype == 'agent.message':
        content = getattr(data, 'content', None)
        if content:
            for block in (content if isinstance(content, list) else [content]):
                text = getattr(block, 'text', '')
                if text:
                    print(text, flush=True)

    elif etype == 'agent.tool_use' or 'tool_use' in etype:
        tool_count += 1
        name = getattr(data, 'name', '?')
        tool_input = getattr(data, 'input', {})
        print(f"\n  [{tool_count}] TOOL: {name}", flush=True)
        if isinstance(tool_input, dict):
            for k, v in tool_input.items():
                val = str(v)[:80]
                print(f"       {k}: {val}", flush=True)

    elif etype == 'agent.tool_result' or 'tool_result' in etype:
        content = getattr(data, 'content', '')
        preview = str(content)[:200] if content else ''
        print(f"  -> RESULT: {preview}...", flush=True)

    elif etype == 'agent.thinking':
        thinking = getattr(data, 'thinking', '')
        if thinking:
            preview = str(thinking)[:100]
            print(f"  [thinking] {preview}...", flush=True)

    elif etype == 'session.status_idle':
        # Check if session is truly done
        print(f"\n  [STATUS] Session idle", flush=True)

    elif etype == 'session.status_running':
        pass  # Normal

    elif 'error' in etype:
        print(f"\n  [ERROR] {data}", flush=True)

    elif etype in ('span.model_request_start', 'span.model_request_end', 'user.message'):
        pass

    else:
        print(f"  [{etype}]", flush=True)

print(f"\n{'='*60}")
print(f"PIPELINE COMPLETE — {tool_count} tool calls")
print(f"Session: {session.id}")
print(f"Agent: {agent.id}")
print(f"{'='*60}")
