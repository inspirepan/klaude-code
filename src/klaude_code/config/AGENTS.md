# Config Notes

## Adding Or Upgrading A Model

Follow the checklist in [`docs/add-model.md`](../../../docs/add-model.md). It covers the field
reference, thinking-tier naming, provider resolution order, pricing, and verification.

The rule that governs most edits: `model_name` is the stable public selector (it appears in user
configs, `sub_agent_models`, and README examples), while `model_id` is the real upstream id. Upgrade
a model line by bumping `model_id` and moving the old version number into `model_alias` — never by
renaming `model_name`.

## Builtin Config Is Asset-Loaded

`assets/builtin_config.yaml` is read through `importlib.resources` and cached
(`builtin_config.py::_load_builtin_yaml`), so it must stay a package asset and must parse without
the Python-side defaults. User config (`~/.klaude/config.yaml`) merges over it field by field
(`merge.py`), which is why an omitted field in user config keeps the builtin value instead of
resetting it.
