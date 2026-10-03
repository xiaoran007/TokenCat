# Antigravity metadata fixture provenance

The integration tests construct SQLite databases and protobuf messages in memory
from synthetic counters, request IDs, model names, and dates. No user database,
conversation, prompt, or credentials are copied into these fixtures.

Field definitions were verified against protobuf descriptors embedded in the
installed, official Antigravity `language_server` dated 2026-09-30:

- `CortexStepGeneratorMetadata`: `chat_model=1`, `step_indices=2` (packed uint32).
- `ChatModelMetadata`: `usage=4`, `chat_start_metadata=9`, `response_model=19`,
  `response_model_full=22`. Other fields can contain complete prompts/tools.
- `ChatStartMetadata`: `created_at=4` (`google.protobuf.Timestamp`).
- `ModelUsageStats`: `model=1` (enum), `input_tokens=2`, `output_tokens=3`,
  `cache_write_tokens=4` (deprecated but still a counter), `cache_read_tokens=5`,
  `api_provider=6` (enum), `message_id=7`, `thinking_output_tokens=9`,
  `response_output_tokens=10`, `response_id=11`, `provider_assigned_message_id=12`.
- `CortexStepMetadata`: `created_at=1`, `finished_generating_at=7`,
  `completed_at=8`, `model_usage=9`, `last_completed_chunk_at=22`,
  `model_info=24`, `started_at=32`.
- `ModelInfo`: `model_name=8`.
- `CortexTrajectoryMetadata`: `parent_conversation_id=5`, `workspace_uris=7`.
  Agent scripts, static configuration, and other metadata are skipped.
- `APIProvider`: Google Vertex=3, Google Gemini=24, Anthropic Vertex=26,
  Google Evergreen=30, OpenAI Vertex=31.

Read-only inspection of 416 local generation records found output consistently
included thinking + response. Cache reads frequently exceeded uncached input.
398 generations omitted `chat_start_metadata.created_at`; linked step metadata
provided real per-request timestamps. Two additional requests had usage only in
step metadata. These observations motivate the synthetic regression cases.

The reader projects SQLite `substr` ranges for protobuf framing and the selected
numeric/identifier fields. It does not load full `data`/`metadata` blobs, the
`step_payload` column, response headers, or other app databases.

Identity regressions cover response IDs arriving after an initial scan and a
process restart, generation metadata arriving before the corresponding step,
and previously unidentified App/CLI copies becoming identifiable as one request.
Hashed positional and request aliases retain the original ledger identity;
confirmed duplicate ledger rows merge before the new alias map is committed.
