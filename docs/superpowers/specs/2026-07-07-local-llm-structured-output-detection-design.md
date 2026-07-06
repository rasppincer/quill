# Design Spec: LAN IP-Based Proactive Local Model Structured Output Detection

This design spec outlines how we will proactively detect local/LAN LLM endpoints and bypass structured outputs (JSON schema) for them, ensuring compatibility with local models like Gemma that struggle with structured schema formatting. We also complete the prompt composition simplification from the pivot plan.

---

## 1. Objectives

1. **Proactive Local API Detection**: Check `client.api_base` against standard LAN IP addresses and localhost/127.0.0.1.
2. **De-escalate response_format for Local Endpoints**: Disable structured outputs for these endpoints.
3. **Prompt Composition Simplification**: Refactor `compose_prompt` in `context_assembler.py` to return a single unified `prompt` key.
4. **Backward-Compatible UI & Test Updates**: Update the UI (`piece.js`) and tests to handle the simplified single-prompt format.

---

## 2. Proposed Changes

### A. Add LAN IP Checker Helper
We will add `is_local_api` as a helper function in `src/quill/stage_runner.py` (or a utility file) to identify local/LAN endpoints:
```python
def is_local_api(api_base: str | None) -> bool:
    if not api_base:
        return False
    from urllib.parse import urlparse
    try:
        parsed = urlparse(api_base)
        hostname = parsed.hostname
        if not hostname:
            return False
        hostname = hostname.lower()
        if hostname in ("localhost", "127.0.0.1", "::1"):
            return True
        if hostname.startswith("192.168.") or hostname.startswith("10."):
            return True
        if hostname.startswith("172."):
            parts = hostname.split('.')
            if len(parts) >= 2:
                try:
                    second_octet = int(parts[1])
                    if 16 <= second_octet <= 31:
                        return True
                except ValueError:
                    pass
    except Exception:
        pass
    return False
```

### B. Integrate in Stage Runner (`src/quill/stage_runner.py`)
In `run_stage` and `_generate_chaptered`, check if the endpoint is local and deactivate structured outputs:
```python
cfg = load_model_config()
use_structured = cfg.get("structured_output", False)

if use_structured and is_local_api(client.api_base):
    use_structured = False
```

### C. Simplify `compose_prompt` in `ContextAssembler` (`src/quill/context_assembler.py`)
Remove the split branch in `compose_prompt` for content/feedback stages. Return a single unified prompt format:
```python
system_prompt = PromptBuilder.system_prompt(stage, piece, "generate" if is_content else "feedback")
base["prompt"] = {
    "system": system_prompt,
    "user": sc.prompt,
    "char_count": len(sc.prompt),
}
```
Also remove the deprecated `"is_content_stage"` key from `base`.

### D. Update piece.js Tab Loading (`src/quill/static/js/piece.js`)
Update the prompt rendering logic to check for the new `prompt` key:
```javascript
let promptText = '';
if (data.prompt) {
    promptText = data.prompt.user || '';
} else if (data.generate) {
    promptText = data.generate.user || '';
} else if (data.single_call) {
    promptText = data.single_call.user || '';
}
```

### E. Update Test Suite
Update `tests/test_runner.py`'s tests asserting `compose_prompt` properties to expect the simplified single-prompt structure.

---

## 3. Verification

### Automated Tests
- Run `.venv/bin/pytest tests/test_phase2b_task2_compose_prompt.py` (which should now pass).
- Run `.venv/bin/pytest tests/test_runner.py` (which should pass after test adjustments).
