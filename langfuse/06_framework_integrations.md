# Framework Integrations

Last verified against official Langfuse and OpenTelemetry documentation on 2026-07-24.

Role: implementation for readers already using their selected framework/provider. Read
[SDK context/lifecycle](02_python_sdk_v4.md) first; this chapter teaches adapter ownership rather
than LangChain or LiteLLM programming. The local SDK smoke is the common context baseline.
Provider/framework calls below need their named packages, credentials and configured project;
they are integration examples, with external execution gates retained explicitly.

## 🧭 Mental Model

Use framework integrations when your application already relies on an LLM framework, model SDK, gateway, or auto-instrumentation layer. Use manual SDK instrumentation when you need exact trace shape and business-specific observations.

Framework integrations are adapters. They listen to events from LangChain, LangGraph, OpenAI SDK, LiteLLM, or OpenTelemetry-native libraries and turn those events into Langfuse observations.

```text
framework/model gateway event
  -> Langfuse integration callback/wrapper/OTel span
  -> Langfuse observation
  -> optional manual root span adds product context
```

They solve "capture the internals I already delegated to this framework." They do not know your product workflow, privacy policy, release strategy, feedback model, or which business decisions deserve spans. In production, the best pattern is often a manual root observation plus integration-generated children.

The callback, wrapper, and SDK paths in this chapter are intentionally Langfuse-aware. If application tracing must remain backend-independent, use the OpenTelemetry-native path: emit standard OTel, `gen_ai.*`, and organization-owned `app.*` attributes to a Collector, then add Langfuse mappings only in its Langfuse pipeline. The complete implementation boundary is defined in [03_otel_ingestion_and_mapping.md#vendor-neutral-application-contract](03_otel_ingestion_and_mapping.md#vendor-neutral-application-contract).

## 📐 Integration Decision Table

| Stack | Recommended integration |
| --- | --- |
| LangChain or LangGraph | `langfuse.langchain.CallbackHandler` |
| OpenAI Python SDK | `langfuse.openai` drop-in wrapper |
| LiteLLM Proxy | `langfuse_otel` callback in LiteLLM proxy config |
| LiteLLM SDK | Langfuse LiteLLM SDK integration or OpenAI-compatible wrapper path |
| Existing vendor-neutral OpenTelemetry instrumentation | OTLP to a Collector; its Langfuse exporter uses OTLP/HTTP and destination-specific mappings |
| Mixed custom code plus framework calls | Wrap the workflow with Langfuse SDK spans and pass the integration callback inside the active context |

## 🔌 Tested Versions and Support Boundaries

Use a lockfile and rerun trace-shape tests on every integration upgrade. This guide's July 20, 2026 baseline is:

| Integration | Compatible baseline for these examples | Sync / async / streaming | Boundary and shutdown rule |
| --- | --- | --- | --- |
| LangChain/LangGraph callback | `langfuse>=4.14,<5`, `langchain>=1,<2`, `langchain-openai>=1,<2`, `langgraph>=1,<2` | `invoke`/`ainvoke`, batch, stream/astream are supported by the callback | Framework-created generations only; flush in CLI, worker, and serverless exits. |
| Langfuse OpenAI wrapper | `langfuse>=4.14,<5`, `openai>=1.92,<3` | Sync, async, functions/tools, and streaming; request `stream_options={"include_usage": True}` for streamed usage | Stable OpenAI client APIs are supported. Assistants API is not; beta APIs may require manual `@observe`. Flush short-lived processes. |
| LiteLLM `langfuse_otel` | `langfuse>=4.14,<5`, `litellm>=1.65,<2`, matched OTel SDK/exporter packages | Sync/async/streaming depends on the LiteLLM call/proxy path; validate usage on the final stream chunk | The published integration does not promise one universal minimum LiteLLM release; pin the exact tested proxy/SDK build and flush/shut down its OTel provider on short-lived exits. |
| OpenInference or other OTel-native instrumentation | `langfuse>=4.14,<5` for prompt propagation; `opentelemetry-sdk>=1.39,<2` with matching `0.60b0+` instrumentation | Determined by that instrumentor; test sync, async, and streaming separately | Only accepted spans with correct GenAI fields and destination mapping appear. Force-flush the provider in serverless/batch jobs. |

The ranges are compatibility bounds, not permission to resolve new dependencies during deployment. Lock an exact set after the smoke tests pass. If a package's official page does not publish a minimum version for a feature, the locked, staging-tested version is the support contract.

Decision points:

- Prefer the integration closest to the model call when you mainly need provider prompt/output/usage/cost.
- Prefer manual SDK spans when you need business-specific workflow shape, capture policy, scores, or product metadata.
- Prefer gateway instrumentation when many services share one model gateway and application changes are expensive.
- Prefer raw OTel when platform teams need runtime-neutral routing and Collector controls.
- Avoid double-instrumenting the same model call unless you intentionally want both views and know how to de-duplicate analysis.

## 💬 Link Managed Prompts Through Auto-Instrumentation

Python SDK 4.14.0 or later can propagate a managed prompt to generations created by integrations that do not expose a Langfuse `prompt=` parameter:

```python
from langfuse import get_client, propagate_attributes

langfuse = get_client()
prompt = langfuse.get_prompt("support-answer", label="production")
compiled = prompt.compile(question="How do I reset SSO?")

with propagate_attributes(prompt=prompt):
    result = auto_instrumented_model_call(compiled)
```

Use the same scope directly around the call that creates generations:

```python
# LangChain or an OpenInference-instrumented provider
with propagate_attributes(prompt=prompt):
    result = chain.invoke(
        {"question": "How do I reset SSO?"},
        config={"callbacks": [CallbackHandler()]},
    )

# Langfuse OpenAI wrapper
with propagate_attributes(prompt=prompt):
    response = client.responses.create(model="gpt-4o-mini", input=compiled)

# LiteLLM SDK with the langfuse_otel callback
litellm.callbacks = ["langfuse_otel"]
with propagate_attributes(prompt=prompt):
    response = litellm.completion(
        model="gpt-4o-mini",
        messages=[{"role": "user", "content": compiled}],
    )
```

Prompt propagation links only generation observations, not roots, chains, retrievers, agents, or tools. An explicit observation-level prompt always wins. A fallback prompt has no persisted Langfuse version and cannot be linked; skip propagation when `prompt.is_fallback` is true and record a bounded fallback flag instead.

## 🧩 LangChain and LangGraph

Langfuse integrates with LangChain through LangChain callbacks. The callback captures chains, LLM calls, tools, retrievers, and LangGraph agent executions.

Install:

```bash
pip install "langfuse==4.17.0" "langchain>=1,<2" "langchain-openai>=1,<2" "langgraph>=1,<2"
```

Basic usage:

```python
from langchain.agents import create_agent
from langfuse import get_client
from langfuse.langchain import CallbackHandler

langfuse = get_client()
langfuse_handler = CallbackHandler()


def add_numbers(a: int, b: int) -> int:
    """Add two numbers together."""
    return a + b


agent = create_agent(
    model="openai:gpt-5-mini",
    tools=[add_numbers],
    system_prompt="You are a helpful math tutor.",
)

agent.invoke(
    {"messages": [{"role": "user", "content": "what is 42 + 58?"}]},
    config={"callbacks": [langfuse_handler]},
)
```

Lifecycle:

1. Application creates or receives a LangChain/LangGraph run.
2. `CallbackHandler` listens to framework events.
3. The callback creates observations for chains, retrievers, tools, and LLM calls.
4. If an active Langfuse root observation exists, callback observations nest under it.
5. `propagate_attributes()` or invocation metadata adds trace-level user/session/tags.

Layered explanation:

- Beginner intuition: the callback traces what LangChain does for you.
- Technical mechanics: LangChain invokes callbacks around chain, model, retriever, tool, and graph events.
- Production implications: create a product-level root span when one user request contains custom app logic plus framework calls.
- Common mistakes: passing a handler without user/session/version context, reusing handler state unsafely in concurrent flows, and relying on deprecated trace I/O helpers in new code.

### Nest Framework Calls in a Product Trace

For production workflows, create a root observation and propagate trace attributes before invoking LangChain or LangGraph. The callback will attach framework spans under the current trace.

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langfuse import get_client, propagate_attributes
from langfuse.langchain import CallbackHandler

langfuse = get_client()


def answer_with_chain(user_input: str, user_id: str, session_id: str) -> str:
    with langfuse.start_as_current_observation(
        as_type="span",
        name="langchain.answer",
        input={"query": user_input},
    ) as root:
        with propagate_attributes(
            trace_name="langchain.answer",
            user_id=user_id,
            session_id=session_id,
            tags=["langchain"],
            metadata={"feature": "chat"},
        ):
            handler = CallbackHandler()
            prompt = ChatPromptTemplate.from_template("Respond to: {input}")
            chain = prompt | ChatOpenAI(model_name="gpt-4o")

            result = chain.invoke(
                {"input": user_input},
                config={"callbacks": [handler]},
            )

            answer = result.content
            root.update(output={"answer": answer})
            return answer
```

You can also set dynamic trace attributes via LangChain invocation metadata, but the SDK `propagate_attributes()` path is easier to reason about when the trace includes both framework and custom application work.

## 🧩 OpenAI Python SDK

The OpenAI Python integration is a drop-in wrapper. It works with OpenAI and Azure OpenAI and automatically tracks prompts/completions, streaming, async calls, function/tool calls, latencies, API errors, token usage, and cost where available.

Install:

```bash
pip install "langfuse==4.17.0" "openai>=1.92,<3"
```

Switch imports:

```python
from langfuse.openai import OpenAI

client = OpenAI()

response = client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "Explain RAG in one sentence."}],
)
```

Alternative imports include:

```python
from langfuse.openai import AsyncOpenAI, AzureOpenAI, AsyncAzureOpenAI, openai
```

### Add Trace Attributes

For simple calls, pass Langfuse attributes through metadata:

```python
from langfuse.openai import OpenAI

client = OpenAI()

client.chat.completions.create(
    model="gpt-4o-mini",
    messages=[{"role": "user", "content": "1 + 1 ="}],
    name="calculator.chat",
    metadata={
        "langfuse_session_id": "session_123",
        "langfuse_user_id": "user_456",
        "langfuse_tags": ["calculator"],
        "feature": "calculator",
    },
)
```

For larger workflows, use an enclosing Langfuse span:

```python
from langfuse import get_client, propagate_attributes
from langfuse.openai import OpenAI

langfuse = get_client()
client = OpenAI()

with langfuse.start_as_current_observation(as_type="span", name="calculator.request"):
    with propagate_attributes(
        trace_name="calculator.request",
        session_id="session_123",
        user_id="user_456",
        tags=["calculator"],
    ):
        client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "user", "content": "1 + 1 ="}],
        )
```

Flush before exit in scripts and serverless functions:

```python
from langfuse import get_client

get_client().flush()
```

The OpenAI wrapper is best for client-side OpenAI SDK calls. Langfuse notes that tracing the OpenAI Assistants API is not supported by this integration because Assistants have server-side state that cannot be captured completely without additional API requests. For agentic systems, prefer explicit agent/tool/generation observations or a framework integration that exposes the workflow steps.

> ⚠️ **Watch out:** The `langfuse.openai` wrapper does not support the OpenAI Assistants API — using it there produces incomplete or missing traces without any error.

Lifecycle:

1. Replace OpenAI imports with the Langfuse OpenAI wrapper.
2. Calls to supported stable OpenAI SDK APIs create Langfuse generation observations.
3. Metadata and active Langfuse context attach calls to the right trace/session/user.
4. Streaming calls can capture usage when the provider returns usage data, such as final chunks with included usage.
5. Scripts and serverless functions flush before exit.

Layered explanation:

- Beginner intuition: use the OpenAI client as usual, but calls appear in Langfuse.
- Technical mechanics: the wrapper intercepts supported OpenAI SDK calls and records generation fields.
- Production implications: wrappers are fast to adopt, but they only see model calls; add manual spans for retrieval, policy, routing, and persistence.
- Common mistakes: forgetting to handle empty streaming chunks that carry usage, assuming beta APIs are fully supported, and using the wrapper plus manual generation spans for the same call.

### See which actor owns the generation

For a direct call, the wrapper surrounds the actual provider operation inside the product root:

```mermaid
sequenceDiagram
  participant A as application / support.answer root
  participant W as Langfuse OpenAI wrapper
  participant P as model provider
  participant L as Langfuse exporter
  A->>W: approved SSO messages under active root
  W->>P: one completion request
  P-->>W: answer + usage 820 / 164
  W->>L: one generation, parent support.answer
  W-->>A: answer
  A->>L: root output and business observations
```

The wrapper owns the one model receipt; the app owns the task and retrieval/guardrail evidence.
A manual `generation` around that wrapped call would add a second receipt for the same provider
operation. Use a generic business span around framework work when you need extra context.

## 🧩 LiteLLM Proxy

LiteLLM Proxy can log all model calls through a central gateway to Langfuse using the `langfuse_otel` callback.

Set credentials:

```bash
export LANGFUSE_PUBLIC_KEY="pk-lf-..."
export LANGFUSE_SECRET_KEY="sk-lf-..."
export LANGFUSE_OTEL_HOST="https://cloud.langfuse.com"
```

Example `litellm_config.yaml`:

```yaml
model_list:
  - model_name: gpt-5.1
    litellm_params:
      model: gpt-5.1

litellm_settings:
  callbacks: ["langfuse_otel"]
```

Start the proxy:

```bash
litellm --config /path/to/litellm_config.yaml
```

Use this path when:

- multiple services call models through the same gateway;
- you want provider-level observability without changing every application;
- you still propagate user/session/tags from application requests where possible.

If the application already uses the Langfuse SDK or OpenTelemetry exporter directly, avoid double-instrumenting the same model call through both the app and the proxy unless you intentionally want both views.

> ⚠️ **Watch out:** Double-instrumenting a model call (e.g., both app SDK and LiteLLM proxy) produces duplicate generations in Langfuse, inflating token counts and making cost analytics unreliable.

The proxy adds a network boundary, so correlation metadata must reach another process:

```mermaid
sequenceDiagram
  participant A as application / product root
  participant P as LiteLLM Proxy
  participant M as model provider
  participant L as Langfuse
  A->>P: model request + supported correlation metadata
  P->>M: one provider request
  M-->>P: answer + usage
  P->>L: langfuse_otel generation
  P-->>A: answer
  A->>L: root + retrieval/tool observations
```

The last arrow supplies product evidence absent from the proxy. Do not assume a trace ID alone
establishes parentage: test the proxy's supported trace/parent metadata and compare IDs in the
resulting tree. If that path cannot preserve parent IDs, document separate correlated traces
rather than claiming a nested tree. A second app-side wrapper generation creates two charge-bearing
observations even though M received one request. Diagnose inflated usage by counting provider
operations and generations before tuning sampling or cost prices.

Lifecycle:

1. Application calls the LiteLLM Proxy instead of providers directly.
2. Proxy routes/authenticates/load-balances provider requests.
3. LiteLLM callback emits Langfuse OTEL data for model calls.
4. Application should still pass trace attributes such as user, session, tags, and workflow where supported.
5. Langfuse shows provider-level generations; application spans still explain business workflow if instrumented.

Layered explanation:

- Beginner intuition: the gateway records all model traffic in one place.
- Technical mechanics: LiteLLM emits OpenTelemetry/Langfuse-compatible callback data from the proxy.
- Production implications: this is strong for centralized model observability, weaker for business context unless applications pass attributes.
- Common mistakes: losing user/session context at the gateway, duplicating traces with SDK instrumentation, and treating gateway traces as a substitute for RAG/tool/agent spans.

## 🔗 OpenTelemetry-Native Libraries

For OpenTelemetry-native or third-party auto-instrumentation libraries:

1. Prefer the current OpenTelemetry GenAI semantic conventions.
2. Export standard OTel, `gen_ai.*`, and documented `app.*` attributes to an OpenTelemetry Collector.
3. Route complete GenAI workflow traces—not only model-call leaf spans—into the Collector's Langfuse pipeline.
4. Add `langfuse.*` attributes in that destination pipeline when first-class trace, observation, metadata, tags, release, version, or other Langfuse fields require an explicit mapping.
5. Keep the original neutral attributes unchanged for other trace backends.
6. Send operational metrics to your metrics backend.

See [03_otel_ingestion_and_mapping.md](03_otel_ingestion_and_mapping.md) and [../opentelemetry/06_genai_and_llm_observability.md](../opentelemetry/06_genai_and_llm_observability.md).

Legacy notes in this repo previously included OpenLLMetry and OpenLIT examples. Treat these as OpenTelemetry-native instrumentation choices: if they emit current OTel spans, route them to the Collector and apply Langfuse-specific enrichment only in its Langfuse pipeline. Use the current project documentation for those packages before copying setup code, because auto-instrumentation package APIs change faster than the OTLP and Langfuse mapping layer.

Layered explanation:

- Beginner intuition: if a library emits OTel GenAI spans, Langfuse can often ingest them.
- Technical mechanics: Langfuse maps standard GenAI fields directly, while a destination-scoped Collector transform fills Langfuse-specific schema gaps.
- Production implications: application instrumentation stays portable even when Langfuse-specific attributes are required for first-class filtering, versions, and metadata.
- Common mistakes: adding vendor attributes inside otherwise neutral application code, assuming all third-party spans are mapped perfectly, not preserving root spans through Collector routing, and missing provider/model/usage attributes.

## 🛠️ Mixing Auto and Manual Instrumentation

The best production traces often combine both:

```text
support.answer             manual root span
  input.normalize          manual span
  langchain.retriever      framework callback
  openai.chat.completions  OpenAI wrapper generation
  guardrail.output         manual guardrail span
```

> 💡 **Key insight:** Framework integrations capture what the framework does — they cannot know your product workflow, user context, or privacy policy; always wrap them in a manually created root span that carries that context.

Rules:

- Create the product-level root span yourself.
- Propagate user, session, tags, release, version, and metadata early.
- Let framework integrations capture internals.
- Add manual spans for business decisions the framework cannot know about.
- Score the trace or important observations after the framework run finishes.
- Do not use deprecated trace input/output helpers for new code; set input/output on the root observation.

## 📐 Architecture Patterns

| Pattern | Use when | Trace shape |
| --- | --- | --- |
| Manual root + LangChain callback | Product workflow includes custom preprocessing, retrieval, and LangChain execution | `support.answer` root with callback-created chain/tool/generation children. |
| Manual root + OpenAI wrapper | You call OpenAI directly but need product context | Root span for request plus wrapper-created generation children. |
| LiteLLM-only | You mainly need central model call logs across many apps | Proxy generations with app-provided user/session/tags where possible. |
| LiteLLM + app spans | You need both central provider observability and business workflow traces | App root/tool/retriever spans plus gateway model spans; watch for duplication. |
| Vendor-neutral raw OTel | Existing library emits GenAI spans or the app must remain backend-independent | Neutral OTel spans routed through the Collector; only the Langfuse pipeline adds Langfuse mapping attributes. |

## 🔍 Troubleshooting

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| LangChain run appears without user/session | No trace attributes passed or propagated | Wrap the run in SDK context and call `propagate_attributes()`, or pass supported metadata fields. |
| Framework spans are not nested under product trace | Callback invoked outside active Langfuse/OTel context | Create the root observation around the framework call and instantiate/use the handler inside that flow. |
| Duplicate generations | Same model call captured by wrapper, manual generation span, and/or gateway | Pick one primary capture path per model call or document how to reconcile both. |
| OpenAI streaming usage missing | Usage not requested/handled for stream, or final empty choices chunk mishandled | Request usage where provider supports it and handle chunks with empty `choices`. |
| Azure/OpenAI model names look wrong | Deployment name recorded without model name | Pass model metadata where the provider/framework supports it. |
| LiteLLM traces lack product workflow | Gateway sees provider request but not application steps | Add manual app spans and pass user/session/tags through gateway metadata. |
| OTel-native library spans are absent | Collector routing dropped the workflow or kept only model-call leaves | Route the complete GenAI trace and preserve root, parent, and business spans. |
| Sensitive data captured by integration | Wrapper/callback captured provider inputs/outputs | Disable capture where supported, add SDK masking, or redact before model calls. |

## ✅ Integration Checklist

- Choose one primary capture path per model call.
- Add a manual product-level root span when framework traces alone do not explain the workflow.
- Propagate user, session, tags, release, version, environment, and safe metadata.
- Confirm trace trees are nested correctly in staging.
- Verify token usage, model names, streaming behavior, and errors are captured.
- Add manual spans for business decisions the framework cannot know: routing, retrieval policy, guardrails, persistence, fallbacks.
- Attach scores after the framework run or from async feedback/evaluator workers.
- Test privacy controls against wrapper/callback-captured payloads.
- Flush or shut down clients/handlers in scripts, workers, and serverless environments.

## 🔌 Official References

- Langfuse integrations index: <https://langfuse.com/integrations>
- LangChain and LangGraph integration: <https://langfuse.com/integrations/frameworks/langchain>
- OpenAI Python integration: <https://langfuse.com/integrations/model-providers/openai-py>
- LiteLLM Proxy integration: <https://langfuse.com/integrations/gateways/litellm>
- OpenTelemetry integration: <https://langfuse.com/integrations/native/opentelemetry>

## Retain the integration boundary

- The app creates the product root; one adapter owns each actual provider-generation receipt.
- Callbacks/wrappers inherit active context; a proxy additionally needs supported network correlation.
- Duplicate capture inflates apparent token work even when each observation contains correct usage.
- Validate streaming final usage, errors, parent IDs, privacy and flush for the exact locked integration.

**Q: A LangChain callback and a manual generation both record the same call. Why can a richer tree mislead cost analysis?**

<details><summary>Answer</summary>

Both receipts describe one provider operation. If both carry usage, aggregation counts the tokens
twice. Keep the product/business root generic and let one callback/wrapper own the generation.

</details>

**Q: App and proxy traces share an ID, but proxy generation parent is absent. Is the intended nested tree proven?**

<details><summary>Answer</summary>

No. Shared identity correlates records, but parentage also needs the parent ID. Check supported
proxy metadata and receiving behavior with a staging call. Document correlation separately when
that integration cannot carry the complete parent relationship.

</details>

**Try it:** Add trusted user/session scope around the supplied callback workflow without adding
another generation. State the expected hierarchy and which fields you would inspect.

<details><summary>Worked solution</summary>

Open a generic product root, use `propagate_attributes(user_id=..., session_id=...)` with approved
internal IDs, and invoke the callback-enabled chain inside that scope. Update root output, retain
trace ID, and flush on script exit. Callback-generated chain/model observations share the root's
trace; check their actual parent hierarchy (the generation may nest under a callback chain), and
ensure user/session fields exist on relevant observations. Do not demand every generation be a
direct child when the framework legitimately inserts a chain parent.

</details>
