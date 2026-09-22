# Config Notes

## Adding Or Upgrading A Model

Follow the checklist in [`docs/add-model.md`](../../../docs/add-model.md). It covers the field
reference, thinking-tier naming, provider resolution order, pricing, and verification.

The rule that governs most edits: `model_id` is the real upstream id, `model_name` is the selector.
Follow the upstream name — when a new version changes it (a generation that writes its version into
the name, e.g. `gpt-5.6-sol` → `gpt-6-sol`), rename `model_name` to match. `model_alias` lists only
equivalent spellings of the *current* model (upstream full name, habitual shorthand, `-latest`);
previous names and previous ids are not kept as aliases, so old selectors stop resolving.

## Builtin Config Is Asset-Loaded

`assets/builtin_config.yaml` is read through `importlib.resources` and cached
(`builtin_config.py::_load_builtin_yaml`), so it must stay a package asset and must parse without
the Python-side defaults. User config (`~/.klaude/config.yaml`) merges over it field by field
(`merge.py`), which is why an omitted field in user config keeps the builtin value instead of
resetting it.
