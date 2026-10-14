"""The agent's sandboxed workspace, and reading and writing files of any type.

Pure, synchronous helpers with no knowledge of the loop or the API: `workspace`
(safe path resolution), `readers`, `writers` and `images`. The async tool
wrappers that expose them to the model live in `agent_runtime.tools`.
"""
