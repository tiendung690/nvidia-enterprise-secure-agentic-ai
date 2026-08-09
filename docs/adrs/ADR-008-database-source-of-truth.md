# ADR-008: Database as operational source of truth

## Decision

Operational state được đọc qua typed read-only tools và parameterized tenant-scoped repositories.
PDF/vector index không dùng để trả lời trạng thái real-time và LLM không có arbitrary SQL tool.

## Consequence

Query deterministic và audit được; mỗi capability phải được thiết kế/version/test riêng.
