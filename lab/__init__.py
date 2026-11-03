"""SePay lab: research pipeline and work flow orchestration over Codex, Claude Code and Antigravity."""
import os

# Packets carry sources, source code and business data. LangGraph/LangSmith must
# never upload traces because of an inherited environment variable.
for _name in ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING", "LANGCHAIN_TRACING_V2"):
    os.environ[_name] = "false"
