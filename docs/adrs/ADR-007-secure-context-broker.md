# ADR-007: Secure Context Broker

## Decision

Mọi retrieved candidate phải được policy re-authorization và masking trước khi được serialize thành
LLM evidence. LLM không được nhận unauthorized text rồi mới lọc ở output.

## Consequence

Security correctness tăng; candidate pool cần lớn hơn để giữ Authorized Recall@K.
