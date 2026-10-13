---
name: manage-catalog
description: >-
  Use this skill when inspecting, adding, updating, or validating curated GGUF models
  in utils/models.catalog, ensuring correct syntax, accurate byte sizes, and appropriate tags.
license: MIT
compatibility: Python 3.9+ (Windows, macOS, Linux)
metadata:
  standard: agentskills.io
---

# Manage Catalog Skill

This skill explains how to inspect, add, update, and validate curated models in `utils/models.catalog`.

## Catalog File Format

`utils/models.catalog` is a pipe-delimited (`|`) flat text file read by `utils/model_setup.py`.

```text
name|Hugging Face repo|file|size in bytes|tags|note
```

### Field Definitions

| Field | Example | Description |
|-------|---------|-------------|
| **`name`** | `gemma-3-4b-it-Q4_K_M` | Unique short identifier for the model. |
| **`Hugging Face repo`** | `ggml-org/gemma-3-4b-it-GGUF` | Public Hugging Face repository (`<org>/<repo>`). Must not be gated or private. |
| **`file`** | `gemma-3-4b-it-Q4_K_M.gguf` | Filename inside the repository. |
| **`size in bytes`** | `2489757856` | Exact file size in bytes (used for memory fit calculation and disk preflight checks). |
| **`tags`** | `chat,translation` | Comma-separated tags: `chat`, `translation`, `coding`, `fast`. |
| **`note`** | `Best small all-rounder; keeps to vous or tu` | Human-friendly description displayed in CLI and setup UI. |

---

## Validation Checklist for New Models

When adding a new entry to `utils/models.catalog`:

1. **Verify Public Accessibility**:
   The repo must be public on `huggingface.co`. Gated models (requiring a Hugging Face token) must not be included.
2. **Obtain Exact File Size**:
   Fetch the exact byte size via Hugging Face API or curl header:
   ```bash
   curl -sI https://huggingface.co/<repo>/resolve/main/<file> | grep -i content-length
   ```
3. **Verify Quantization**:
   Prefer `Q4_K_M` as the default sweet-spot between quality and memory footprint. For small models (<2B), `Q8_0` or `Q4_K_M` are standard.
4. **Valid Tags**:
   Must include at least one of: `chat`, `translation`, `coding`, `fast`.
5. **Run Catalog Validation Tests**:
   Execute the recommend tests to ensure parsing succeeds:
   ```bash
   python -m unittest tests.test_model_setup.TestRecommend.test_catalog_is_well_formed -v
   ```
