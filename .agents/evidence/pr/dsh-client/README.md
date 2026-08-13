# DeepSeek Harness client evidence

`dsh-real-trace-viewer.png` renders a redacted trace captured during a real
DeepSeek Harness 0.0.1-rc.2 tool-use E2E run on 2026-08-13. The source run sent
`POST /chat/completions` to the official DeepSeek API through a process-local
`DEEPSEEK_BASE_URL` capture relay and completed successfully.

The screenshot preserves the real request and response structure while replacing
the system prompt, user prompt, reasoning, tool result, identifiers, local path,
and authorization value. The raw trace and discovery bundle are intentionally not
committed.
