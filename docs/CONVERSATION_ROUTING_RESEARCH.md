# Conversation-aware routing research

Research date: 2026-10-23. This note records design evidence and proposed experiments; it does not claim benchmark results. Existing decisions in ADR-007 (catalog-backed entities), ADR-008 (budgets/versioning), ADR-009 (claim checks/session privacy), and ADR-010 (adopt measured improvements without unnecessary dependencies) remain constraints.

## Findings from primary sources

| System | Observed mechanism | Applicable principle |
| --- | --- | --- |
| Rasa CALM | Dialogue understanding considers conversation context and business logic, producing commands rather than only an isolated intent. Multiple command generators can coexist. | Represent a message's conversational action separately from its business task. A greeting and a knowledge question can coexist. [Dialogue understanding](https://learning.rasa.com/rasa-pro/dialogue-understanding/) |
| Rasa CALM | Commands include starting a flow, setting/correcting a slot, clarification, small talk and knowledge answers. Repair patterns handle corrections and context changes through the same flow policy. | Model pending clarification and correction as state transitions; social interruption should preserve the suspended knowledge topic. Borrow this separation, without importing a flow engine. [CALM command/repair whitepaper](https://info.rasa.com/hubfs/PDF_Content/CALM_Compliance_Starter_Pack_whitepaper_202401.pdf?hsLang=en), [repair overview](https://learning.rasa.com/rasa-pro/deviations-from-happypath/) |
| Aurelio Semantic Router | Exemplars are embedded and matched against query meaning. The current main branch distinguishes indexed routing, decision models, and chains that fall through when uncertain. | Fast decisions and semantic generalization are useful, but uncertainty must fall back to the existing router. Route similarity is not authorization. [Official repository](https://github.com/aurelio-labs/semantic-router) |
| Aurelio Semantic Router | Routes support confidence thresholds and no-match. Raw similarity is not necessarily a probability. Calibration uses separate labeled queries; fitting on stored utterances produces misleading scores. | Compare conservative social precision on independent paraphrases, negative/mixed examples and holdout. Never calibrate on evaluation holdout. [Routes](https://docs.aurelio.ai/docs/semantic-router/v1/user-guide/components/routes), [calibration](https://docs.aurelio.ai/docs/semantic-router/v1/user-guide/features/calibration) |
| LangGraph | Routing examples use a structured decision and conditional edges to a finite set of nodes. Workflows may have predetermined paths. | Add one lightweight conversation branch to the existing graph; a supervisor or additional agents are unnecessary. [Routing workflow](https://docs.langchain.com/oss/python/langgraph/workflows-agents) |
| LangGraph | Checkpointers hold thread-scoped graph state; stores serve cross-thread data. | Dialogue continuity belongs in the existing session/thread boundary. This task does not justify a new cross-session memory database. [Persistence](https://docs.langchain.com/oss/python/langgraph/persistence) |
| LlamaIndex | Selectors choose single or multiple choices using text or structured schemas. Routers compose existing query engines/retrievers described as tools. | Keep capability descriptions grounded in the existing registry; separate selection from execution and allow mixed purposes. A single social label must not suppress a business task. [Router guide](https://developers.llamaindex.ai/python/framework/module_guides/querying/router/) |
| Haystack | ConditionalRouter evaluates configured conditions and emits the selected named outputs; unsafe template rendering is dangerous when user controlled. | Keep graph destinations and executable tools server controlled. A model's decision is input to validated policy, never an executable tool name or user-supplied routing expression. [ConditionalRouter](https://docs.haystack.deepset.ai/docs/conditionalrouter) |

These sources explain mechanisms, not evidence that any vendor's classifier performs well on Vietnamese OCOP dialogue. In particular, semantic-router's English quickstart model and public speed claims do not establish local accuracy, latency or cost.

## Proposed minimal architecture

Keep `Intent` responsible for OCOP business tasks. Add a small orthogonal dialogue decision carrying communicative acts, handling mode (conversation, knowledge, clarification/repair), context action (preserve, resume, replace), confidence and diagnostic origin. Multiple acts may accompany one task; the execution mode remains singular and validated.

Run existing slot/entity/business analysis before permitting social bypass. Explicit document/article/form/criterion requests, private operations, mixed social/task messages and authorization-sensitive requests retain business routing. A social classifier must account for the entire utterance; detecting a greeting substring is insufficient. Unknown or low-confidence classifications abstain. Short text alone does not establish either social meaning or ambiguity.

Use a small normalized exemplar classifier as an offline-capable baseline, compared with a compact compositional language policy. Prototype semantic similarity with the configured embedding infrastructure only when locally available, without downloading a model or introducing a dependency. For ambiguous remainder, an optional existing structured LLM can suggest dialogue acts/task/context dependency. Validate outputs against the finite contract, reject unexpected fields and preserve deterministic fallback on timeout, malformed output or missing credentials. No classifier supplies tool names, authorization or reference rules.

The existing LangGraph route node can select a conversation answer node or the current planner/tools/evidence/generation path. Registry-derived capability help and short greetings need no retrieval or citation. Explanation/source requests resume the last knowledge task and use corpus-revalidated evidence; they must not present a previous answer as authoritative source material. Corrections should replace the corrected target while retaining only compatible document scope. Unsupported correction targets receive clarification.

Maintain separate session fields for the last knowledge query/scope/referents/evidence, pending clarification, and optional latest dialogue action. A social response does not update the knowledge snapshot. Pending clarification can survive a social interruption and resolve from a later slot answer. Corpus changes still invalidate stale evidence. Preserve existing redaction, private-data exclusions, AuthContext and session ownership checks.

This is an architectural recommendation inferred from the cited patterns and OCOP constraints, not a decision to ship every classifier above. Production selection must follow the experiments below.

## Alternatives and selection gates

| Candidate | Benefit to test | Cost/risk | Shipping gate |
| --- | --- | --- | --- |
| Existing router | Stable business behavior | Social turns commonly become clarification/out-of-scope | Retain as measured baseline |
| Conservative compositional fast path | Offline, low latency and no model calls | Limited paraphrase/typo coverage | Improve independent social cases with zero observed business bypass |
| Lightweight exemplar similarity | Broader paraphrases without per-case rules | Lexical similarity may confuse mixed utterances | Beat compositional policy on holdout and mixed negatives |
| Existing dense embeddings | Semantic generalization | Encoding latency, cold start, score calibration, model availability | Material measured gain after per-route no-match calibration; report cold/warm latency separately |
| Structured LLM fallback | Contextual/mixed understanding | Variable latency/cost and provider availability | Improve ambiguous cases without overriding clear deterministic business routes; prove unavailable-model fallback |
| New CALM/framework/model | Rich dialogue machinery | Dependency and migration burden | Not justified for this focused extension without evidence that existing seams cannot satisfy acceptance |

## Evaluation protocol

Keep development examples, threshold/calibration examples and holdout disjoint. Holdout cases must not become exemplars, prompt demonstrations or vocabulary additions. Record candidate configuration and baseline Git SHA with results. Include multi-turn scenarios separately because correct single-turn labels do not prove memory correctness.

Report routing accuracy, macro F1, per-group social precision/recall, mixed-task accuracy and business-intent preservation. Define false social bypass as actual knowledge-task messages routed to conversation-only divided by all actual knowledge-task messages. Report counts and denominator, especially when the observed count is zero. Compare warm P50/P95 latency, model invocations and tool invocations per turn; identify whether network/provider timings were measured or unavailable. Tool calls avoided means observed execution count, not tools merely proposed in a Route.

Exercise social interruption followed by document/article/form continuation, clarification-slot replies, correction and topic switching, two isolated sessions, stale corpus references, model unavailable/malformed outputs, and adversarial requests for unauthorized tools. Run HTTP acceptance and the existing demo using the sample corpus; no full-corpus ingestion is needed. Preserve source bytes and score/star verification gates throughout.
