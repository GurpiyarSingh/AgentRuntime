"""The agent core: transcript types, events, the loop, and the model binding.

Import from the submodules (`agent.loop`, `agent.messages`, ...). Nothing
is re-exported here, which keeps importing a message type from pulling in
the loop and, through it, the tools that themselves use message types.
"""
