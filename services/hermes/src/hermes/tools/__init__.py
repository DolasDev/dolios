"""Tool functions exposed to Hermes personas.

Each module here groups tools by external surface — `pegasus.py` will wrap
the Pegasus API client once it exists. Personas declare which tools they may
invoke via the `tools:` allowlist in personas/<name>.yaml; the loader in
hermes.agent will resolve those entries against the functions defined here.
"""
