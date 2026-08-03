"""Local klaude server: owns runtime execution and serves clients over a Unix domain socket.

Keep this module import-light; CLI thin clients import submodules directly
(e.g. ``klaude_code.server.paths``).
"""
