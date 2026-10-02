# Upstream source integration

Source: https://github.com/bytedance/deer-flow
Commit: 5b83cb502c967e2952d32155a21c01ee739f1660
License: MIT (LICENSE included).

Copied complete source modules from backend/packages/harness/deerflow/agents/middlewares:
model_response.py, model_length_termination_detectors.py, tool_receipt.py, receipt_verification.py.

Only imports were mapped to MASP's message compatibility classes; tool_result_meta's constant is inlined. Algorithms, citation format, hashing, verdict semantics and length detectors remain upstream code. The message classes adapt the existing Chat Completions transport without adding a second orchestration framework. Recovery and execution integration live in masp/model_runtime.py and the lead/child loops.
