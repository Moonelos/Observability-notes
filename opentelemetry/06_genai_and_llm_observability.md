# GenAI And LLM Observability

The executable lifecycle lab below was checked with Python 3.14.7 and OTel SDK 1.45.1 on 2026-10-14. Historical convention names in existing tables are retained with an explicit current-development migration boundary in the streaming section; the lab uses custom application metric names.

LLM systems need the same observability foundations as every distributed system:
latency, errors, saturation, dependency behavior, logs, and trace context. They
also need extra detail that normal HTTP or database instrumentation does not
understand: model names, token usage, streaming behavior, prompts, outputs,
retrieval, tools, agents, memory, cost, and quality.

OpenTelemetry is the vendor-neutral instrumentation layer for those events.
Langfuse is the LLM-focused observability product that can use this telemetry to
show prompts, generations, sessions, scores, costs, and evaluations.

This page explains how the pieces fit together. The goal is not just "set some
attributes on spans." The goal is to make an LLM trace tell the story of one
user request from the API boundary, through retrieval and model calls, through
tool execution, and finally into Langfuse or another backend.

Compatibility reviewed against OpenTelemetry semantic conventions v1.44.0 and
semconv-genai commit `46d43c89` (2026-08-09) on 2026-08-10.

## 🧭 The Mental Model

The normal OpenTelemetry model still applies:

```text
User request
  creates an HTTP server span
  carries trace context through application code
  creates child spans for dependencies
  exports spans, metrics, and logs through the SDK or Collector
  stores them in one or more backends
```

GenAI observability adds domain-specific child spans:

```text
HTTP POST /chat
  agent.invoke support-assistant
    retrieval product_docs
    embeddings text-embedding-3-small
    chat gpt-4o-mini
    execute_tool lookup_order
    chat gpt-4o-mini
```

Each span has a different job:

| Span | What it explains |
| --- | --- |
| HTTP server span | Which user request triggered the work. |
| Workflow or agent span | The full logical LLM task. |
| Retrieval span | What knowledge search happened before generation. |
| Embedding span | Which embedding model was called and how many tokens it used. |
| Inference span | Which model generated output, how long it took, and how many tokens it used. |
| Tool span | Which external action the model or agent requested. |
| Memory span | What long-term memory was read or written. |
| Evaluation or scoring span | How quality, safety, or policy checks were applied. |

The trace gives causality. Metrics give aggregate behavior. Logs give detailed
events. Langfuse turns the LLM parts into product-facing observability: prompt
versions, sessions, model outputs, costs, scores, and datasets.

## 📌 What GenAI Observability Should Answer

A useful LLM trace should answer questions in several layers.

| Question | Signal |
| --- | --- |
| Which endpoint or job triggered this LLM work? | Parent HTTP, worker, or cron span. |
| Which user, tenant, session, or experiment was involved? | Resource, span attributes, baggage, or Langfuse trace metadata. |
| Which model was requested? | `gen_ai.request.model`. |
| Which model actually responded? | `gen_ai.response.model`. |
| Which provider or platform served it? | `gen_ai.provider.name`. |
| Was it streaming? | `gen_ai.request.stream`. |
| How long did the operation take? | Span duration and `gen_ai.client.operation.duration`. |
| How long until the first streamed chunk? | `gen_ai.response.time_to_first_chunk` and streaming metrics. |
| How many tokens were used? | `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`, token metrics. |
| Did retrieval help or hurt? | Retrieval and embedding child spans plus retrieved document metadata. |
| Did tools fail? | `execute_tool` spans with status and `error.type`. |
| Did the agent loop? | Repeated model and tool spans under one agent/workflow span. |
| Was the output good? | Langfuse scores, eval spans, or custom quality metrics. |
| Was sensitive content captured? | Explicit opt-in payload attributes and masking policy. |

If your trace only shows "called OpenAI" and a duration, it is not enough for a
production LLM system. It tells you that a dependency was slow, but not why the
workflow behaved the way it did.

> 💡 **Key insight:** Wrapping a model call in a single opaque span tells you latency but not causality — separate spans for retrieval, embedding, inference, tool execution, and evaluation are what let you answer "was it the retrieval, the model, or the tool that made this request fail?"

## ⚠️ Stability And Compatibility

The GenAI semantic conventions are still Development. That has practical
consequences:

- do use the current `gen_ai.*` names for new instrumentation;
- do not scatter string literals across the codebase;
- keep provider-specific logic in one helper module;
- document which convention version or check date your app follows;
- expect automatic instrumentations and backends to lag behind the latest names;
- prefer additive migration over renaming attributes in every call site.

A small compatibility layer is worth it:

```python
# observability/genai_attributes.py

GENAI_OPERATION_NAME = "gen_ai.operation.name"
GENAI_PROVIDER_NAME = "gen_ai.provider.name"
GENAI_REQUEST_MODEL = "gen_ai.request.model"
GENAI_RESPONSE_MODEL = "gen_ai.response.model"
GENAI_REQUEST_STREAM = "gen_ai.request.stream"
GENAI_RESPONSE_ID = "gen_ai.response.id"
GENAI_FINISH_REASONS = "gen_ai.response.finish_reasons"
GENAI_INPUT_TOKENS = "gen_ai.usage.input_tokens"
GENAI_OUTPUT_TOKENS = "gen_ai.usage.output_tokens"
GENAI_REASONING_OUTPUT_TOKENS = "gen_ai.usage.reasoning.output_tokens"
GENAI_CACHE_READ_INPUT_TOKENS = "gen_ai.usage.cache_read.input_tokens"
GENAI_CACHE_CREATION_INPUT_TOKENS = "gen_ai.usage.cache_creation.input_tokens"
GENAI_TIME_TO_FIRST_CHUNK = "gen_ai.response.time_to_first_chunk"
GENAI_CONVERSATION_ID = "gen_ai.conversation.id"
GENAI_CONVERSATION_COMPACTED = "gen_ai.conversation.compacted"
GENAI_OUTPUT_TYPE = "gen_ai.output.type"

ERROR_TYPE = "error.type"

LANGFUSE_OBSERVATION_INPUT = "langfuse.observation.input"
LANGFUSE_OBSERVATION_OUTPUT = "langfuse.observation.output"
```

This looks boring, which is exactly the point. When the convention evolves, one
module changes instead of every LLM call site.

Use one error pattern for every GenAI operation in this chapter. Put a low-cardinality `error.type` on the failed span, pass `record_exception=False`, then re-raise. The Python context manager still sets error status because `set_status_on_exception` remains enabled, but it does not create the legacy exception span event. Emit exception details once through the correlated logs pipeline at the owning service boundary; do not put `str(exc)` in span status.

## 🏷️ Operation Vocabulary

Use `gen_ai.operation.name` to describe the logical GenAI operation.

| Operation | Use it for |
| --- | --- |
| `chat` | Chat-style model call. |
| `generate_content` | Multimodal content generation. |
| `text_completion` | Legacy or plain text completion operation. |
| `embeddings` | Embedding model call. |
| `retrieval` | Retrieval from a vector store, search system, or managed GenAI retrieval API. |
| `create_agent` | Creating or configuring an agent. |
| `invoke_agent` | One agent invocation. |
| `execute_tool` | A tool execution requested by the model or agent. |
| `invoke_workflow` | A coordinated GenAI workflow composed of agents or operations. |
| `plan` | Agent planning or task decomposition. |
| `search_memory` | Search or query memory records. |
| `create_memory` | Create memory records. |
| `update_memory` | Update memory records. |
| `upsert_memory` | Create or update memory records without choosing which upfront. |
| `delete_memory` | Delete memory records. |
| `create_memory_store` | Create or initialize a memory store. |
| `delete_memory_store` | Delete or deprovision a memory store. |

Keep custom operations low-cardinality. Do not put prompt text, user IDs,
request IDs, document IDs, or dynamic task descriptions in operation names.

## 🏷️ Provider Names

Use `gen_ai.provider.name` for the provider or platform known to the
instrumentation.

Common current values include:

| Provider value | Meaning |
| --- | --- |
| `openai` | OpenAI. |
| `azure.ai.openai` | Azure OpenAI. |
| `azure.ai.inference` | Azure AI Inference. |
| `anthropic` | Anthropic. |
| `aws.bedrock` | AWS Bedrock. |
| `gcp.gemini` | Gemini API endpoint. |
| `gcp.vertex_ai` | Vertex AI endpoint. |
| `gcp.gen_ai` | Google GenAI endpoint when the exact backend is broader or unknown. |
| `cohere` | Cohere. |
| `mistral_ai` | Mistral AI. |
| `ibm.watsonx.ai` | IBM watsonx.ai. |
| `perplexity` | Perplexity. |
| `x_ai` | xAI. |
| `deepseek` | DeepSeek. |
| `groq` | Groq. |
| `moonshot_ai` | Moonshot AI. |

The provider value should reflect the client instrumentation's best knowledge.
If you call a proxy that forwards to multiple providers, you may know only the
proxy platform at span start. If the final upstream provider becomes known later,
record it separately with an application attribute such as
`app.llm.upstream_provider`.

## 🗺️ Trace Shape For LLM Applications

A good trace has stable boundaries:

```text
server span: POST /api/chat
  application span: chat_controller
    workflow span: invoke_workflow support_rag
      retrieval span: retrieval product_docs
      embedding span: embeddings text-embedding-3-small
      inference span: chat gpt-4o-mini
      tool span: execute_tool order_lookup
      inference span: chat gpt-4o-mini
      evaluation span: app.eval answer_groundedness
```

The parent span should represent the user's request or job. The GenAI spans
should represent the work performed to satisfy it. Do not make every internal
function a span. Span the operations that explain latency, cost, error, and
decision-making.

Useful parent attributes:

| Attribute | Why |
| --- | --- |
| `service.name` | Which service produced the trace. Usually a resource attribute. |
| `deployment.environment.name` | Separate dev, staging, and production. |
| `http.route` | Low-cardinality endpoint name. |
| `enduser.id` or application user attribute | User correlation, if allowed by policy. |
| `app.tenant.id` | Tenant correlation, if allowed and bounded. |
| `gen_ai.workflow.name` | Product workflow, such as `support_rag`. |
| `app.experiment.name` | A/B or prompt experiment, if low-cardinality. |

For Langfuse, prefer Langfuse-specific trace metadata for fields that need to be
filterable in Langfuse. Plain OTel attributes may still be retained, but they
may not be first-class filters in Langfuse.

## 📦 Inference Spans

An inference span represents one physical model request. It should start when
that attempt is issued and end when its response is fully received, it fails, or
it is cancelled. A retry is another physical request and gets another inference
span; the parent agent/workflow span represents the logical operation across
attempts. If a provider SDK retries invisibly, use its supported retry hooks or
configure application-owned retries when per-attempt latency and failures are
operationally important. Do not wrap an already traced provider/framework call
with a second inference span.

Recommended inference shape:

| Field | Value |
| --- | --- |
| Span name | `{gen_ai.operation.name} {gen_ai.request.model}`, for example `chat gpt-4o-mini`. |
| Span kind | `CLIENT` for remote provider calls. Use `INTERNAL` for in-process models. |
| Required attributes | `gen_ai.operation.name`, `gen_ai.provider.name`. |
| Important creation-time attributes | Operation, provider, request model, route, tenant, and sampling-relevant flags. |
| Response attributes | Response ID, response model, finish reasons. |
| Usage attributes | Input, output, cache, and reasoning token counts when available. |
| Error attributes | Span status and bounded `error.type`; exception detail belongs in one correlated log record. |

Common inference attributes:

| Purpose | Attribute |
| --- | --- |
| Operation | `gen_ai.operation.name` |
| Provider | `gen_ai.provider.name` |
| Conversation or thread | `gen_ai.conversation.id` |
| Effective model context was compacted | `gen_ai.conversation.compacted` |
| Requested model | `gen_ai.request.model` |
| Actual response model | `gen_ai.response.model` |
| Requested output type | `gen_ai.output.type` |
| Candidate count | `gen_ai.request.choice.count` |
| Temperature | `gen_ai.request.temperature` |
| Top-p | `gen_ai.request.top_p` |
| Top-k | `gen_ai.request.top_k` |
| Max output tokens | `gen_ai.request.max_tokens` |
| Stop sequences | `gen_ai.request.stop_sequences` |
| Frequency penalty | `gen_ai.request.frequency_penalty` |
| Presence penalty | `gen_ai.request.presence_penalty` |
| Reasoning effort | `gen_ai.request.reasoning.level` |
| Seed | `gen_ai.request.seed` |
| Streaming flag | `gen_ai.request.stream` |
| Response ID | `gen_ai.response.id` |
| Finish reasons | `gen_ai.response.finish_reasons` |
| Time to first streamed chunk | `gen_ai.response.time_to_first_chunk` |
| Input tokens | `gen_ai.usage.input_tokens` |
| Output tokens | `gen_ai.usage.output_tokens` |
| Cache read input tokens | `gen_ai.usage.cache_read.input_tokens` |
| Cache creation input tokens | `gen_ai.usage.cache_creation.input_tokens` |
| Reasoning output tokens | `gen_ai.usage.reasoning.output_tokens` |
| Error class | `error.type` |

The older `gen_ai.system` name appears in older libraries and dashboards. Treat
it as legacy compatibility. Prefer `gen_ai.provider.name` in new raw
instrumentation.

## 🛠️ Manual Inference Span Example

The exact provider client differs by SDK. This explanatory excerpt uses a
chat-completions-shaped client to show the OpenTelemetry pattern. It depends on the attribute constants discussed above and a configured client; use the complete fake-provider lab below to execute and verify the lifecycle without credentials:

```python
import json
import os
import time
from collections.abc import Sequence
from typing import Any

from opentelemetry import trace
from opentelemetry.trace import SpanKind

from observability.genai_attributes import (
    ERROR_TYPE,
    GENAI_FINISH_REASONS,
    GENAI_INPUT_TOKENS,
    GENAI_OPERATION_NAME,
    GENAI_OUTPUT_TOKENS,
    GENAI_OUTPUT_TYPE,
    GENAI_PROVIDER_NAME,
    GENAI_REQUEST_MODEL,
    GENAI_RESPONSE_ID,
    GENAI_RESPONSE_MODEL,
)

tracer = trace.get_tracer(__name__)


def complete_chat(
    client: Any,
    messages: Sequence[dict[str, Any]],
    *,
    route: str,
    capture_content: bool = False,
) -> str:
    model = os.getenv("LLM_MODEL", "gpt-4o-mini")

    attributes = {
        GENAI_OPERATION_NAME: "chat",
        GENAI_PROVIDER_NAME: "openai",
        GENAI_REQUEST_MODEL: model,
        GENAI_OUTPUT_TYPE: "text",
        "http.route": route,
    }

    with tracer.start_as_current_span(
        f"chat {model}",
        kind=SpanKind.CLIENT,
        attributes=attributes,
        record_exception=False,
    ) as span:
        start = time.perf_counter()

        try:
            response = client.chat.completions.create(
                model=model,
                messages=list(messages),
                temperature=0.2,
                max_tokens=800,
            )
        except Exception as exc:
            span.set_attribute(ERROR_TYPE, type(exc).__name__)
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        first_choice = response.choices[0]
        answer = first_choice.message.content or ""

        span.set_attribute(GENAI_RESPONSE_MODEL, response.model)
        span.set_attribute(GENAI_RESPONSE_ID, response.id)
        span.set_attribute(GENAI_FINISH_REASONS, [first_choice.finish_reason])
        span.set_attribute("app.llm.duration_ms", elapsed_ms)

        if response.usage:
            span.set_attribute(GENAI_INPUT_TOKENS, response.usage.prompt_tokens)
            span.set_attribute(GENAI_OUTPUT_TOKENS, response.usage.completion_tokens)

        if capture_content:
            input_messages = [
                {
                    "role": message["role"],
                    "parts": [{"type": "text", "content": message["content"]}],
                }
                for message in messages
            ]
            output_messages = [
                {
                    "role": "assistant",
                    "parts": [{"type": "text", "content": answer}],
                    "finish_reason": first_choice.finish_reason,
                }
            ]
            span.set_attribute("gen_ai.input.messages", json.dumps(input_messages))
            span.set_attribute("gen_ai.output.messages", json.dumps(output_messages))

        return answer
```

Notes:

- `gen_ai.operation.name`, `gen_ai.provider.name`, and `gen_ai.request.model`
  are set at span creation time so a sampler can use them.
- Prompt and output content are controlled by `capture_content`.
- When content capture is enabled, this example records the same `messages`
  sequence passed to the provider. If the caller passes accumulated chat
  history on every agent step, earlier messages are repeated on every inference
  span by design.
- The span name uses the low-cardinality operation and model, not a prompt or
  user-specific label.
- `error.type` is low-cardinality. Use exception class names or provider error
  codes, not full error messages.
- `record_exception=False` prevents a legacy exception span event. The re-raised exception still makes the context manager set `ERROR`; the `except` block adds only bounded `error.type`, while the service logging boundary owns the exception log event and stack trace.
- This wrapper is where provider-specific response parsing belongs.

## 🔄 Streaming

Streaming has two different latency stories:

- total operation duration: how long until the stream ends;
- time to first received chunk: transport-visible data may contain only metadata; first text is a separate application timing.

For streaming requests:

| Field | Use |
| --- | --- |
| `gen_ai.request.stream` | Set to `true` at span creation time. |
| `gen_ai.response.time_to_first_chunk` | Seconds from request issuance to first chunk received. |
| `gen_ai.client.operation.time_to_first_chunk` | Metric for aggregate first-chunk latency. |
| `gen_ai.client.operation.time_per_output_chunk` | Metric for aggregate chunk pacing. |
| Span duration | Full stream duration. |

### A complete physical-attempt lab

Use the Python SDK environment from [02](02_python_instrumentation.md), then run from the repository root:

```bash
python examples/local/otel_genai_test.py
```

Success prints `PASS physical attempts, metadata/text clocks, cancellation, failure cleanup, privacy, usage and agent metrics`. This runs a fake provider with real SDK span export and metric aggregation; no provider account or Collector is required. The complete wrapper is [otel_genai.py](../examples/local/otel_genai.py), and [otel_genai_test.py](../examples/local/otel_genai_test.py) owns the reproducible client and assertions. The wrapper accepts a tracer and a meter-backed `Measurements` object so application startup retains sole ownership of the providers. A production adapter must normalize the provider's chunk/usage schema and disable hidden retries; the fake verifies lifecycle and accounting, not provider billing or transport compatibility.

Follow one support-agent attempt. Its clock starts when it issues the request. The first received chunk at 0.1s supplies metadata with no text. The next at 0.4s contains text, and the final chunk at 0.5s supplies usage. The wrapper finalizes at 0.6s.

```mermaid
sequenceDiagram
  participant A as support agent
  participant W as stream_attempt wrapper
  participant M as fake model
  participant S as SDK measurements
  A->>W: begin /chat physical attempt
  W->>M: create stream once at 0s
  M-->>W: metadata chunk at 0.1s
  W->>S: first chunk histogram 0.1s
  M-->>W: text delta at 0.4s
  W->>S: first text histogram 0.4s
  W-->>A: yield text without telemetry buffer
  alt completed
    M-->>W: final usage input 10 output 2 at 0.5s
    W->>M: close stream
    W->>S: success duration 0.6s and tokens 10 plus 2
  else caller cancels after text
    A->>W: close generator
    W->>M: close stream in finally
    W->>S: cancelled duration and usage_missing
  end
```

The first chunk histogram is 0.1s, while user-visible first text is 0.4s. Neither clock identifies HTTP first byte, and neither counts tokens: a chunk can contain metadata, multiple text fragments, or no text at all. Final provider usage contributes 10 input and 2 output tokens, only once at completion. Span attributes allow an individual investigation; `Counter.add` and `Histogram.record` separately create the aggregates that chapter 05 queries.

The capture-disabled wrapper retains only timestamps, usage, model identity and numeric chunk count. It forwards each text fragment to the caller without concatenating it into a telemetry buffer. The caller and provider still necessarily hold the content they use; the privacy promise is about avoiding an additional instrumentation-owned history. This is not proof that arbitrary provider libraries never buffer internally. Content capture, if added, needs a bounded, explicitly enabled buffer and the masking policy below.

A consumer that stops iterating must close the generator promptly. Garbage collection is not a reliable cleanup protocol. The complete caller pattern is:

```python
from contextlib import closing

# tracer and measured are application-owned objects from the lab/startup.
with closing(stream_attempt(client, tracer, measured)) as stream:
    for text in stream:
        send_to_user(text)
        if user_disconnected():
            break
```

This is an explanatory integration excerpt; `send_to_user` and disconnect detection belong to your transport. The executable test uses the same `closing` boundary. On generator close, `GeneratorExit` becomes bounded `app.outcome="cancelled"`, the provider stream closes, one duration is recorded and the span ends. This example treats user cancellation as an outcome rather than a span error; server timeouts or operational cancellation can have a different explicit policy. On provider failure, the wrapper exports `ERROR` and bounded exception class, closes the stream and re-raises. Cleanup failure also records an error and finalizes; it can supersede the original exception, so production should preserve both safely in the approved log boundary. Exception text is never attached to this span.

Do not leave a `start_as_current_span` context active across yielded text: caller code resumes before the generator does and would inherit that span. This wrapper uses `start_span` with the existing parent and ends it explicitly. If provider instrumentation needs the span active, attach it only around provider creation and each iterator advancement, restoring Context before yielding. Alternatively let the provider instrumentation own inference spans and keep this wrapper for aggregate measurement; avoid duplicate receipts for the same attempt.

### Unknown usage and real aggregate recording

Cancellation before the final usage chunk leaves usage **unknown**. The lab records `app.llm.usage_missing += 1`, with no token measurement for that attempt. Recording zero would claim the provider consumed no tokens despite partial generation. Four tested attempts (success, cancellation, failure, retry success) produce four request counts and four duration observations. Successful usage is `(10+2) + (3+1) = 16` tokens; the two incomplete attempts increment missing-usage count. A retry is a new physical request with its own cost and latency, even when it belongs to the same logical agent run.

The application's measurement carrier creates `llm.requests`, `llm.request.duration`, and `llm.tokens`. Every token measurement includes bounded `http.route`, `gen_ai.request.model`, `gen_ai.provider.name`, `app.outcome`, and `gen_ai.token.type`; the route selector in chapter 05 therefore has an actual measurement source. The SDK remains independent of trace sampling. Its counter and histogram aggregates are asserted in the test rather than inferred from span attributes. This uses the collection's custom application names; do not simultaneously record equivalent auto-instrumentation counts into the same SLO.

Agent measurements have a different boundary: the complete `agent_run` context records application-owned `steps` and `tool_calls` at invocation termination. In the fixture one invocation executes two steps and one tool call, producing an `agent.steps` histogram observation of 2 and an `agent.tool.calls` counter increment of 1. Update those values where work actually occurs, including failed steps if your definition includes them. A nested agent owns its own counts; adding its calls again to the parent's direct-call totals double-counts work. The fixture validates the carrier, not an agent framework adapter or cancellation semantics for every framework.

### Current convention boundary

The table above reflects this collection's historical `client.operation.*` convention vocabulary. Current GenAI conventions remain development status and now separate inference metrics into `gen_ai.client.inference.duration`, `.time_to_first_chunk`, and `.time_per_output_chunk`; `gen_ai.client.operation.duration` excludes inference in the [current schema](https://github.com/open-telemetry/semantic-conventions-genai/blob/main/model/gen-ai/metrics.yaml) (checked 2026-10-14). The canonical timings are request issuance through completion, error or cancellation. Do not silently rename a deployed metric: query both old and candidate streams during a bounded canary, compare counts and units, update recording rules/dashboards, then retire the old stream without double-summing them. The custom `llm.*` lab names isolate the accounting lesson from this preview migration.

Do not create a span per token. That explodes trace volume and makes the trace
harder to read. Record aggregate streaming metrics and, if you need full content,
capture the final assembled output or store chunk events in a system designed for
payload review.

> ⚠️ **Watch out:** Creating a child span for each streamed token generates thousands of spans per request, overwhelms your Collector and backend, and makes the trace completely unreadable — one span per inference call is the right granularity.

## 🔒 Content Capture

Prompts, system instructions, tool definitions, tool arguments, retrieved
documents, and model outputs can contain sensitive data. OpenTelemetry GenAI
content attributes are opt-in for that reason.

Keep `CAPTURE_AI_CONTENT=false` by default and gate collection itself, not only
the final `span.set_attribute(...)` calls. A streaming wrapper that always
buffers chunks, tool results, or retrieved documents still creates a sensitive
in-memory payload even if it later decides not to export the attribute. With
capture disabled, retain model identity, token usage, timing, finish reason,
bounded outcomes, and errors without accumulating content.

Current opt-in content attributes include:

| Attribute | Meaning |
| --- | --- |
| `gen_ai.system_instructions` | System messages or instructions. |
| `gen_ai.input.messages` | Chat history or model input. |
| `gen_ai.output.messages` | Model responses. |
| `gen_ai.tool.definitions` | Tool definitions available to the model or agent. |
| `gen_ai.tool.call.arguments` | Tool execution arguments. |
| `gen_ai.tool.call.result` | Tool execution result. |
| `gen_ai.retrieval.query.text` | Retrieval query text. |
| `gen_ai.retrieval.documents` | Retrieved document details. |

These `gen_ai.*` fields use the standard GenAI content schemas; serialize the
message/part objects as JSON when the language API accepts only scalar
attributes. `langfuse.observation.input` and
`langfuse.observation.output` are backend-specific mapping fields, not
OpenTelemetry semantic conventions. Set them separately only on the Langfuse
export path when its UI should receive an intentionally captured payload.

When a provider accepts system instructions separately from chat history, the
standard shape is an array of content parts:

```python
system_instructions = [
    {"type": "text", "content": "Answer from approved support sources only."}
]
span.set_attribute(
    "gen_ai.system_instructions",
    json.dumps(system_instructions),
)
```

Do not pull a `system`-role message out of a provider's chat-history array just
to populate this field. In that API shape it remains a role-bearing entry in
`gen_ai.input.messages`, as the inference example shows.

### Full Request Versus Filtered Telemetry

`gen_ai.input.messages` is scoped to one inference operation, not to the whole
trace. Its standard meaning is the chat history provided to the model, with
messages in the order they were sent. A provider-faithful stateless agent trace
therefore repeats context across calls:

```text
inference 1 input = [system, user]
inference 2 input = [system, user, assistant(tool_call), tool(result)]
```

This duplication comes from the OpenTelemetry GenAI model-call semantics before
the data reaches Langfuse or another backend.

The content attributes are opt-in, and the conventions explicitly allow an
instrumentation to offer filtering or truncation. Choose the representation
deliberately:

| Capture policy | `gen_ai.input.messages` | Consequence |
| --- | --- | --- |
| No content | Omitted; this is the OTel default | Keeps model, usage, timing, and errors without prompt content. |
| Provider-faithful | Full message list actually sent for that call | Supports exact debugging and replay but repeats history and increases privacy, size, and storage risk. |
| Filtered or delta view | Selected messages, still in the standard message-array schema and original order | Reduces volume and review noise but is not a complete record of the model request. |

The standard attribute does not define an `input_delta` wrapper. If telemetry
keeps only new context, preserve the standard list of `{role, parts}` messages
and add a documented organization-owned marker such as
`app.gen_ai.input.capture_mode="delta"` plus an omitted-message count when it is
known. That prevents a backend or reviewer from mistaking the filtered view for
a replayable request.

Do not set `gen_ai.conversation.compacted=true` merely because telemetry was
filtered. That field means the effective conversation context used by the model
was itself compacted, for example by summarizing older turns before the request.
Telemetry-only filtering and model-input compaction are different operations.

Production policy should answer:

- Which environments may capture content?
- Which tenants or users are excluded?
- What masking happens before export?
- Which backend is allowed to store raw prompts and outputs?
- How long is content retained?
- Who can view it?
- What happens if a trace is sampled out?

A common production split is:

```text
General observability backend
  receives spans, metrics, logs, durations, error types, model names, and token counts
  does not receive raw prompts or raw outputs

Langfuse
  receives LLM payloads when policy allows it
  stores prompt, output, scores, sessions, and evaluation data
```

If your OpenTelemetry backend is a general APM tool, be careful about sending
large prompt payloads there. Attribute size limits, retention, indexing cost, and
access control may all be wrong for LLM content.

## 🗺️ RAG Trace Shape

Retrieval-augmented generation should not be one opaque model span. Split it
into the operations that can fail or degrade independently:

```text
HTTP POST /ask
  invoke_workflow product_rag
    embeddings text-embedding-3-small
    retrieval product_docs
    app.rerank product_docs
    chat gpt-4o-mini
```

Why the split matters:

| Problem | Where it shows up |
| --- | --- |
| Slow embedding provider | Embedding span latency. |
| Slow vector database | Retrieval span latency. |
| Poor context quality | Retrieval attributes and Langfuse scores. |
| Prompt too large | Input token counts on the generation span. |
| Expensive responses | Output token counts and model name. |
| Hallucination | Evaluation scores connected to retrieved document context. |

### Embeddings

Embedding spans use the `embeddings` operation:

```python
def embed_texts(client, texts: list[str], *, model: str) -> list[list[float]]:
    with tracer.start_as_current_span(
        f"embeddings {model}",
        kind=SpanKind.CLIENT,
        attributes={
            "gen_ai.operation.name": "embeddings",
            "gen_ai.provider.name": "openai",
            "gen_ai.request.model": model,
            "app.embedding.input_count": len(texts),
        },
        record_exception=False,
    ) as span:
        try:
            response = client.embeddings.create(model=model, input=texts)
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            raise

        if response.usage:
            span.set_attribute("gen_ai.usage.input_tokens", response.usage.prompt_tokens)

        vectors = [item.embedding for item in response.data]
        if vectors:
            span.set_attribute("gen_ai.embeddings.dimension.count", len(vectors[0]))

        return vectors
```

Use bounded attributes such as `app.embedding.input_count` and
`gen_ai.embeddings.dimension.count`. Do not record every input string unless
content capture is explicitly allowed.

### Retrieval

Retrieval spans use the `retrieval` operation. If the data source has a stable
identifier, the span name can include it:

```python
def retrieve_documents(vector_store, query_vector: list[float], *, top_k: int):
    data_source_id = "product_docs"

    with tracer.start_as_current_span(
        f"retrieval {data_source_id}",
        attributes={
            "gen_ai.operation.name": "retrieval",
            "gen_ai.data_source.id": data_source_id,
            "gen_ai.retrieval.top_k": top_k,
        },
        record_exception=False,
    ) as span:
        try:
            docs = vector_store.search(query_vector, top_k=top_k)
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            raise

        span.set_attribute("app.retrieval.result_count", len(docs))
        if docs:
            span.set_attribute("app.retrieval.top_score", docs[0].score)

        return docs
```

Retrieval query text and retrieved documents are opt-in sensitive content. Prefer
small operational attributes by default:

| Safe by default | Opt-in only |
| --- | --- |
| data source ID | query text |
| top-k | document text |
| result count | full document metadata |
| top score | user-specific search filters |
| retriever version | raw chunks |

### Reranking

The GenAI conventions do not need to cover every app-specific step. If your
reranker is a model call, use an inference span. If it is internal application
logic, use an `app.rerank` span with bounded attributes:

```python
with tracer.start_as_current_span(
    "app.rerank product_docs",
    attributes={
        "app.rerank.input_count": len(docs),
        "app.rerank.strategy": "cross_encoder_v2",
    },
    record_exception=False,
) as span:
    ranked_docs = rerank(query, docs)
    span.set_attribute("app.rerank.output_count", len(ranked_docs))
```

## 🛠️ Tool Execution

Tools are important because agent failures often come from tools, not the model.
A tool span should represent the actual tool execution, not merely the model's
decision to call a tool. Create one span per execution attempt so a transient
failure and its successful retry remain separately visible under the agent
span.

Recommended tool shape:

| Field | Value |
| --- | --- |
| Span name | `execute_tool {gen_ai.tool.name}` |
| Span kind | Usually `INTERNAL` for tools executed by app code. |
| Required attributes | `gen_ai.operation.name=execute_tool`, `gen_ai.tool.name`. |
| Recommended attributes | Tool call ID, tool description, tool type. |
| Opt-in content | Tool arguments and result. |

Example:

```python
def execute_tool(tool_registry, call) -> dict:
    tool_name = normalize_tool_name(call.name)

    with tracer.start_as_current_span(
        f"execute_tool {tool_name}",
        attributes={
            "gen_ai.operation.name": "execute_tool",
            "gen_ai.tool.name": tool_name,
            "gen_ai.tool.call.id": call.id,
            "gen_ai.tool.type": "function",
        },
        record_exception=False,
    ) as span:
        try:
            tool = tool_registry[tool_name]
            result = tool(**call.arguments)
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            raise

        span.set_attribute("app.tool.result_size_bytes", len(str(result).encode()))
        return result
```

Tool names should be bounded. If users can create arbitrary tool names, map them
to a small set such as `custom_tool` and put the user-defined name somewhere that
is not used for metrics or high-cardinality indexing.

## 🔄 Agents And Workflows

Agents and workflows are the parent concepts around multiple GenAI operations.
Use them when a single user-visible task may involve several model calls, tool
calls, retrievals, or memory operations.

Use one trace per user turn or agent invocation. Do not keep a trace open for an
entire conversation: it creates misleading durations, unbounded trace size, and
tail-sampling windows that never see a complete trace. Correlate the separate
turn traces with `gen_ai.conversation.id`; keep that high-cardinality value off
metrics.

```text
invoke_agent support_agent
  plan
  retrieval product_docs
  chat gpt-4o-mini
  execute_tool lookup_order
  chat gpt-4o-mini
```

Use `invoke_agent` when the unit is one agent execution. Use `invoke_workflow`
when the unit is a broader process that may coordinate multiple agents or steps.
Use `plan` for a planning or decomposition step when that step is meaningful for
debugging.

Example:

```python
def run_support_agent(request: SupportRequest) -> AgentAnswer:
    with tracer.start_as_current_span(
        "invoke_agent support_agent",
        attributes={
            "gen_ai.operation.name": "invoke_agent",
            "gen_ai.agent.name": "support_agent",
            "gen_ai.workflow.name": "support_rag",
        },
        record_exception=False,
    ) as span:
        try:
            plan = make_plan(request)
            docs = retrieve_for_plan(plan)
            answer = call_model_with_tools(request, docs)
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            raise

        span.set_attribute("app.agent.step_count", plan.step_count)
        span.set_attribute("app.agent.tool_call_count", answer.tool_call_count)
        return answer
```

A workflow uses the same error contract and the workflow-specific standard
attributes:

```python
def run_support_workflow(request: SupportRequest) -> AgentAnswer:
    with tracer.start_as_current_span(
        "invoke_workflow support_rag",
        attributes={
            "gen_ai.operation.name": "invoke_workflow",
            "gen_ai.workflow.name": "support_rag",
        },
        record_exception=False,
    ) as span:
        try:
            return run_support_agent(request)
        except Exception as exc:
            span.set_attribute("error.type", type(exc).__name__)
            raise
```

The agent span should not contain raw chain-of-thought. If you capture a plan,
capture a product-safe summary or use Langfuse with a deliberate privacy policy.

Measure model time-to-first-chunk, agent time-to-first-chunk, and HTTP/API first
byte separately. The model value measures provider responsiveness; the agent
value includes planning, retrieval, tools, and possibly several model calls;
the API value also includes transport and serialization. Reusing one timestamp
for all three produces plausible but operationally misleading dashboards.

## 📦 Memory

Memory spans are useful when an agent reads or writes long-term user, tenant, or
task memory.

Use the standard operation names when they fit:

| Operation | Example |
| --- | --- |
| `search_memory` | Search existing memories before generation. |
| `create_memory` | Add a new memory record. |
| `update_memory` | Edit a known memory record. |
| `upsert_memory` | Create or update based on matching logic. |
| `delete_memory` | Remove a memory. |
| `create_memory_store` | Initialize a memory store. |
| `delete_memory_store` | Delete a memory store. |

Memory data is often sensitive. By default, record operational facts:

- memory store name or bounded ID;
- operation type;
- result count;
- latency;
- error type;
- record category if low-cardinality.

Avoid raw memory content in general traces unless the user, product, and
compliance posture explicitly allow it.

## 📊 GenAI Metrics

Traces explain one request. Metrics explain the fleet.

The following client and workflow names are a **historical convention reference** for this collection's pinned examples. Current development conventions distinguish inference-specific names; use [the current convention boundary](#current-convention-boundary) above before implementing a new producer or dashboard:

| Metric | Unit | Meaning |
| --- | --- | --- |
| `gen_ai.client.operation.duration` | `s` | Duration of a GenAI client operation. |
| `gen_ai.client.token.usage` | `{token}` | Number of input and output tokens. |
| `gen_ai.client.operation.time_to_first_chunk` | `s` | Streaming time to first chunk. |
| `gen_ai.client.operation.time_per_output_chunk` | `s` | Streaming chunk pacing. |

The historical reference also includes model-server metrics and workflow duration metrics for systems
that host models or orchestrate workflows:

| Metric | Unit | Meaning |
| --- | --- | --- |
| `gen_ai.server.request.duration` | `s` | Model server request duration. |
| `gen_ai.server.time_to_first_token` | `s` | Server-side first token latency. |
| `gen_ai.server.time_per_output_token` | `s` | Server-side output token pacing. |
| `gen_ai.workflow.duration` | `s` | End-to-end GenAI workflow duration. |

Agent and tool conventions add metrics for the orchestration work itself:

| Metric | Unit | Meaning |
| --- | --- | --- |
| `gen_ai.invoke_agent.duration` | `s` | Duration of one agent invocation. |
| `gen_ai.invoke_agent.inference_calls` | `{inference_call}` | Inference calls made during one agent invocation. |
| `gen_ai.invoke_agent.tool_calls` | `{tool_call}` | Tool calls made during one agent invocation. |
| `gen_ai.execute_tool.duration` | `s` | Duration of one tool execution. |

The per-invocation call-count metrics describe fan-out; they are not failure
counters. Use their standard attributes and a low-cardinality `error.type` on
duration measurements when the operation fails. Keep `app.*` counters only for
product facts that these instruments do not express.

Token usage should be emitted when the count is readily available. If a provider
reports billable tokens and raw tokens separately, report billable tokens for the
semantic convention metric.

Useful metric attributes:

| Attribute | Why |
| --- | --- |
| `gen_ai.operation.name` | Compare chat, embeddings, retrieval, and tools. |
| `gen_ai.provider.name` | Compare providers. |
| `gen_ai.request.model` | Compare requested model choices. |
| `gen_ai.response.model` | Detect provider-side model changes. |
| `gen_ai.token.type` | Split input and output token usage. |
| `error.type` | Alert on error classes. |
| `server.address` | Separate provider endpoints when safe and bounded. |

Be strict about cardinality. Do not put user IDs, prompts, conversation IDs,
document IDs, or trace IDs on metrics.

Application-specific metrics can still be useful:

| Metric | Why |
| --- | --- |
| `app.agent.tool_calls` | Detect agent loops and tool explosion. |
| `app.rag.retrieval_result_count` | Detect empty retrievals. |
| `app.rag.top_score` | Detect degraded retrieval quality. |
| `app.llm.estimated_cost` | Track spend by workflow, model, and tenant tier. |
| `app.guardrail.blocks` | Alert on safety or policy changes. |
| `app.eval.score` | Monitor quality drift. |

Use semantic convention metrics where they fit. Use `app.*` metrics for product
or business behavior that OpenTelemetry cannot standardize.

## 🗄️ Langfuse And OpenTelemetry

Langfuse can receive OpenTelemetry traces and map GenAI attributes into its LLM
observability model. The key design choice is what you want Langfuse to own
versus what your general observability backend owns.

Recommended split:

```text
OpenTelemetry SDK
  emits traces, metrics, and logs

OpenTelemetry Collector
  receives OTLP
  redacts or filters attributes
  routes traces to Langfuse and APM
  routes metrics to metrics backend
  routes logs to log backend

Langfuse
  receives LLM-focused traces and payloads
  shows sessions, observations, prompts, outputs, costs, metadata, and scores
```

Important Langfuse details:

- Langfuse supports OTLP over HTTP, with HTTP/JSON and HTTP/protobuf.
- Langfuse does not support OTLP/gRPC for this integration yet.
- Langfuse maps selected OTel attributes to trace-level and observation-level
  fields.
- `langfuse.trace.metadata.*` and `langfuse.observation.metadata.*` become
  first-level filterable metadata in Langfuse.
- Unmapped OTel attributes may be stored under metadata attributes but are not
  necessarily directly filterable.
- Langfuse understands useful GenAI fields such as request model, response
  model, and token usage.

Use Langfuse-specific metadata when product users need to filter on a field:

```python
with tracer.start_as_current_span(
    "chat gpt-4o-mini",
    attributes={
        "gen_ai.operation.name": "chat",
        "gen_ai.provider.name": "openai",
        "gen_ai.request.model": "gpt-4o-mini",
        "langfuse.trace.metadata.tenant_tier": "enterprise",
        "langfuse.observation.metadata.prompt_version": "support-v42",
    },
    record_exception=False,
) as span:
    ...
```

Use Langfuse input and output fields when you intentionally send content:

```python
span.set_attribute("langfuse.observation.input", json.dumps({"messages": messages}))
span.set_attribute("langfuse.observation.output", json.dumps({"content": answer}))
```

Do not assume that every OTel attribute becomes a nice Langfuse filter. Decide
which fields matter for Langfuse workflows and write them with the Langfuse
metadata prefixes.

> 💡 **Key insight:** A plain OTel span attribute like `app.tenant_tier` lands in Langfuse's raw metadata but is not directly filterable in its UI — only `langfuse.trace.metadata.*` and `langfuse.observation.metadata.*` keys become first-class filter fields in Langfuse.

## 🔀 Collector Routing For LLM Systems

The Collector is where you can send different signals and attributes to
different places.

Example shape:

```text
Application
  OTLP traces, metrics, logs
    |
    v
Collector
  traces pipeline:
    redact secrets
    batch
    export to Langfuse
    export to APM

  metrics pipeline:
    batch
    export to Prometheus-compatible backend

  logs pipeline:
    redact secrets
    batch
    export to log backend
```

For LLM content, use explicit policy:

| Destination | Recommended content |
| --- | --- |
| APM backend | Trace shape, durations, error types, model names, token counts. |
| Metrics backend | Aggregates only. No prompts, user content, or IDs. |
| Log backend | Application logs with trace correlation and masking. |
| Langfuse | Prompts, outputs, sessions, scores, and metadata when allowed. |

If you fan out traces to both Langfuse and a general APM backend, consider
redacting prompt/output attributes before the APM export while preserving them
for Langfuse. This can be done with separate Collector pipelines or with
application-side policy.

## 🎲 Sampling

Sampling is tricky for LLM systems because rare traces can be expensive and
important. A good sampling policy usually keeps:

- all errors;
- slow requests;
- high-cost requests;
- specific experiments;
- a percentage of normal traffic;
- selected tenants or internal test users;
- traces with tool failures or guardrail blocks.

Sampling attributes need to exist early. Put these at span creation time when
available:

- `gen_ai.operation.name`;
- `gen_ai.provider.name`;
- `gen_ai.request.model`;
- `http.route`;
- workflow name;
- tenant tier;
- experiment name.

Token counts are usually known only after the response, so they are less useful
for head sampling. If you need to keep high-token traces, use tail sampling in a
Collector or backend that can make a decision after span completion.

Do not rely on sampling for privacy. Redaction and content-capture controls must
work whether a trace is sampled or not.

> ⚠️ **Watch out:** Sampling is not a privacy control — a trace that is not sampled today may be sampled tomorrow if traffic patterns change; redaction and content-capture opt-ins must be correct regardless of sampling decisions.

## 📊 Cost And Quality

OpenTelemetry does not standardize every cost and quality field because those
are product-specific. Add application attributes or metrics for your business
logic.

Cost fields:

| Attribute or metric | Use |
| --- | --- |
| `app.llm.estimated_cost_usd` | Estimated cost for one operation. |
| `app.llm.pricing_version` | Which pricing table was used. |
| `app.llm.cache_hit` | Whether provider or application cache helped. |
| `app.workflow.estimated_cost_usd` | Total workflow cost. |

Quality fields:

| Attribute or metric | Use |
| --- | --- |
| `app.eval.groundedness` | RAG answer groundedness score. |
| `app.eval.helpfulness` | Product quality score. |
| `app.eval.policy_violation` | Safety or compliance finding. |
| `app.guardrail.blocked` | Whether output was blocked. |
| `app.guardrail.reason` | Low-cardinality block reason. |

Prefer Langfuse scores for LLM evaluation workflows when you want dataset,
prompt, session, and evaluation views. Use OTel metrics when you want fleet-wide
alerting and dashboards.

## 🔗 Logs And Trace Correlation

LLM logs should be correlated with traces, but they should not become a shadow
payload store by accident.

Good logs:

```text
INFO llm request started route=/chat model=gpt-4o-mini trace_id=...
WARN tool failed tool=lookup_order error_type=TimeoutError trace_id=...
INFO llm response completed model=gpt-4o-mini input_tokens=812 output_tokens=129 trace_id=...
```

Risky logs:

```text
INFO full prompt: ...
INFO full model output: ...
INFO tool arguments: ...
```

Use trace correlation fields in logs so an operator can jump from a log line to
the trace. Keep raw prompt and output capture in Langfuse or a controlled
payload store, not in broad application logs.

For point-in-time GenAI checkpoints and exceptions, emit a named OTel
`LogRecord` with `event_name` while the relevant span is active. The record then
keeps its own timestamp, severity, and event attributes plus the current trace
and span IDs. The runnable structlog processor and its duplicate-ingestion guard
are in [Python Instrumentation](02_python_instrumentation.md#emit-named-log-based-events-through-structlog).

## 🛠️ Testing Instrumentation

Test the instrumentation like product code. At minimum, verify:

- the top-level request span exists;
- LLM calls are child spans of the request or workflow;
- model, provider, operation, and token attributes are present;
- errors set span status and `error.type`;
- manual exception paths do not create span events and emit exception details through correlated logs;
- streaming spans record time to first chunk;
- prompt/output capture is disabled by default;
- prompt/output capture can be enabled intentionally;
- full capture preserves the exact per-call message order;
- filtered or delta capture preserves the message schema and emits a capture-mode marker;
- `gen_ai.conversation.compacted` is absent unless the model input itself was compacted;
- baggage or tenant metadata does not leak into metrics;
- Langfuse metadata fields use the right prefix for filtering;
- local Collector routing sends traces and metrics to the expected places.

Example unit test shape:

```python
def test_llm_span_has_semantic_attributes(span_exporter, fake_llm_client):
    complete_chat(fake_llm_client, [{"role": "user", "content": "hello"}], route="/chat")

    spans = span_exporter.get_finished_spans()
    llm_span = next(span for span in spans if span.name.startswith("chat "))

    assert llm_span.attributes["gen_ai.operation.name"] == "chat"
    assert llm_span.attributes["gen_ai.provider.name"] == "openai"
    assert "gen_ai.request.model" in llm_span.attributes
    assert "gen_ai.usage.input_tokens" in llm_span.attributes
    assert "langfuse.observation.input" not in llm_span.attributes
```

Integration tests should run a small app through a local Collector and confirm
that the backend receives what you expect. This catches endpoint, protocol,
header, and redaction mistakes that unit tests cannot see.

## ⚠️ Common Pitfalls

| Pitfall | Why it hurts | Fix |
| --- | --- | --- |
| One huge `llm_call` span for everything | You cannot tell retrieval, tools, and generation apart. | Split by logical operation. |
| Prompt text in span names | High cardinality and sensitive data leakage. | Use low-cardinality names and opt-in content attributes. |
| User IDs on metrics | Cardinality explosion. | Keep user data on traces or Langfuse metadata, not metrics. |
| Missing parent context | LLM spans are disconnected from the request. | Configure context propagation and wrap calls inside request spans. |
| Recording only model latency | Workflow latency may be retrieval, tools, or retries. | Add workflow, retrieval, and tool spans. |
| No token metrics | Cost and prompt growth are invisible. | Record usage attributes and token metrics when available. |
| No streaming first-chunk metric | Streaming UX is invisible. | Record time to first chunk. |
| Full content sent everywhere | Privacy and cost risk. | Route content only to approved backends. |
| Filtered input looks like a full request | Reviewers cannot replay the call and may diagnose the wrong context. | Preserve the standard message schema and add a bounded capture-mode marker. |
| Telemetry truncation sets `gen_ai.conversation.compacted` | Dashboards incorrectly report that the model received compacted context. | Set it only when the effective model input was compacted. |
| Convention strings everywhere | Future updates are painful. | Use a small constants/helper module. |
| Assuming Langfuse filters every OTel attribute | Important metadata becomes hard to search. | Use `langfuse.trace.metadata.*` and `langfuse.observation.metadata.*`. |
| Treating GenAI conventions as fully stable | Future changes cause drift. | Track convention check date and isolate names. |

## ✅ Implementation Checklist

For a new LLM service:

- configure normal OTel tracing, metrics, logs, resources, and propagation;
- create a GenAI attribute constants module;
- wrap each provider call in an inference span;
- set operation, provider, and request model at span creation time;
- record response model, response ID, finish reasons, and token usage;
- ensure escaping errors are recorded once and add low-cardinality `error.type`;
- add retrieval, embedding, tool, memory, agent, and workflow spans where they
  explain real behavior;
- emit GenAI duration and token metrics or equivalent application metrics;
- keep metrics low-cardinality;
- keep prompt and output capture disabled by default;
- choose and document `none`, `full`, `delta`, or `truncated` input capture;
- mark filtered content with an organization-owned capture-mode attribute and
  preserve the standard message-array schema;
- add explicit Langfuse input/output capture when allowed;
- use Langfuse metadata prefixes for fields that need to be filterable;
- route traces, metrics, and logs through a Collector in production;
- redact secrets and sensitive attributes before general-purpose exports;
- add tests for span attributes, error behavior, and content-capture defaults;
- document the GenAI semantic convention check date.

## 🧭 How This Fits With The Other Notes

- [01_concepts.md](01_concepts.md) explains the OpenTelemetry mental model:
  signals, context, SDKs, exporters, the Collector, resources, and backends.
- [02_python_instrumentation.md](02_python_instrumentation.md) shows how to set
  up the Python SDK and exporters that create these spans and metrics.
- [03_production_architecture.md](03_production_architecture.md) explains how
  the Collector routes traces to Langfuse and metrics/logs to other systems.
- [04_multi_service_examples.md](04_multi_service_examples.md) explains how
  trace context crosses service boundaries so LLM spans stay connected.
- [05_custom_metrics_alerting.md](05_custom_metrics_alerting.md) explains how
  to turn GenAI metrics into useful dashboards and alerts.

Once those pieces are connected, GenAI observability stops being a separate
topic. It becomes a domain-specific layer on top of the same OpenTelemetry
pipeline used by the rest of the system.


## Recap and practice

One inference span represents one physical attempt. Metadata-first streams earn a first-chunk observation before they produce user-visible text. Normal completion, provider failure and caller cancellation all own cleanup and exactly one terminal duration. Final usage can be unknown, which must remain visible rather than becoming a zero. Token and agent aggregates require actual metric calls; span attributes alone cannot drive unsampled alerts. Telemetry filtering is distinct from changing what the model receives.

### Check yourself

1. The first chunk contains only the model name. Does it establish first text latency or token usage?
2. A user disconnects before final usage. Should the wrapper increment tokens by zero?
3. An agent retries one failed attempt successfully. How many inference attempts and logical agent runs exist?

<details><summary>Reasoned answers</summary>

1. It establishes first-chunk latency only. Wait for a text delta for first-text timing, and authoritative usage for token totals; chunks are not tokens.
2. No. Close the stream and record cancellation duration plus missing usage. Zero would hide an unknown amount that may still be billed.
3. Two physical attempts inside one run. Each request has its own span/duration and any known usage; the agent boundary records one termination. Hidden client retries must be exposed or disabled before claiming exact attempt accounting.

</details>

### Try it: change chunk order and cancellation

Change the fake so text arrives before metadata, then close after its first text. Predict the two first-latency observations, chunk count, usage_missing and closed state before running the test. Next return a final usage chunk and consume to completion; predict which metrics differ without changing the text.

<details><summary>Worked solution</summary>

For the first text-containing chunk, first-chunk and first-text clocks are equal. Cancellation after it records chunk count 1, closes the provider, and increments missing usage because no authoritative final totals arrived. Completion still has the same first latencies, but processes the later metadata/usage chunks, records a larger chunk count and success duration, adds known input/output totals and does not increment usage_missing. The text alone cannot tell which accounting result occurred.

</details>
