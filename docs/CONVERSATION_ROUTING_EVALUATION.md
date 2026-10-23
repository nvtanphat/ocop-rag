# Conversation routing: decision and measured evaluation

Baseline: `c7ed601` on `dev`, checked before editing. Implementation starts at
`bd88290`; subsequent fixes cover API model availability, measured model policy,
and public checkpoint context. Research sources and alternative designs are in
[CONVERSATION_ROUTING_RESEARCH.md](CONVERSATION_ROUTING_RESEARCH.md).

## Inspection findings

The original router extracts catalog-backed slots, builds language facets, applies
private/follow-up/scope policies, scores business intents, and selects registered
capabilities/tools. Private scoring, dossier actions, authority and normative-star
signals outrank generic lookup signals. Tool planning and AuthContext remain server
owned. LLM routing only runs after the scope gate, when no deterministic intent
score matched. Consequently, a greeting cannot reach that fallback: short messages
become CLARIFY, longer messages without domain signals become OUT_OF_SCOPE.

FOLLOWUP requires a previous `last_query` and an opener, resolved plural reference,
or a pronoun/closing cue without an explicit new location/document. An explicit
document after an opener can still continue the conversation while replacing scope.
Memory stores the last knowledge query, intent/capabilities, slots, a standalone
question, recent referents, citation references and corpus version. Answers are not
stored as evidence. Previously, the first unanswered turn could establish a false
topic; a social message accidentally treated as FOLLOWUP could overwrite standalone
query and age evidence. Pending clarification existed in the store but was not passed
to routing. Public checkpoint sanitization also discarded memory/pending state.

## Selected architecture

Use one bounded dialogue policy around the existing business router. The finite,
typed `DialogueDecision` represents multiple acts, context action and diagnostic
origin independently of business `Intent`. A single CONVERSATION result denotes the
processing path; there are no new business enums for every social act.

The offline fast path composes nine communicative forms, address/particle grammar,
and punctuation. It must consume the entire message before permitting social bypass.
It does not use substring triggers or an exhaustive utterance dictionary. Mixed
messages retain their task remainder, then use the existing slot/facet/intent/tool
policy. Unknown wording abstains. Grammar and localized responses are separate;
public capability descriptions come from the same tool registry used by planning.

The existing LangGraph conditional edge sends conversation turns directly to answer;
the dependency-free runner makes the same decision. Business tools, evidence grading,
recovery, generation, provenance/claim gates and authorization remain in place.
Clarification resumes only ordinary missing-topic/document slots, never identity,
authorization or a version conflict. Bare criterion fragments gain their structural
noun when resumed. Correction with a replacement target retains compatible document
scope. Unspecified corrections ask for detail. Rephrase/source requests re-run the
active knowledge question against the current corpus; rephrase style is a separate
generation instruction, excluded from retrieval terms and coverage scoring.

Social turns preserve the entire knowledge snapshot and pending clarification,
including evidence age. Private turns cannot become a later public repair query.
Expired topics are not revived by social traffic. Checkpoints retain only sanitized,
bounded public memory and pending context. Explicit document switches clear old
targets even when the earlier form had no document; singular references compose
structure nouns and demonstratives rather than enumerating complete phrases.

Both HTTP adapters skip model construction for an already certain social turn,
including when `use_llm=true` and model configuration is missing. Corpus-readiness
checks remain the API's responsibility. No frontend or ingestion changes are needed.

### Why the other candidates were not selected

The real local `google/embeddinggemma-300m` model was tested with dev-only exemplars
and a leave-one-out dev threshold search penalizing false social routing tenfold.
The selected threshold was 0.75. Holdout social recall was 75%, versus 90% for the
offline policy. Its warm router P95 was 90.53 ms and startup was 16.91 seconds. It
does not justify adding a runtime model dependency to conversation handling.

A structured fallback using the configured answer model was also tested. It accepts
only a finite act, task-presence flag and confidence; it never accepts tools, slots,
permissions or answer text. Extra fields, malformed output, low confidence and model
errors abstain. The self-reported confidence is **not** a calibrated probability.
The bounded experiment uses one attempt with an eight-second transport timeout.
It recovered one additional holdout social case, but made 12 model calls across
122 turns, with four service failures and P95 4.30 seconds. The workflow therefore
does not enable it in production. The explicit router test seam remains available
for reproducible comparison. Existing business-router and grounded-answer LLM calls
are unaffected. No additional package or model was installed/downloaded.

## Dataset and protocol

`tests/ocop/fixtures/conversation_eval.json` contains 42 development and 50 holdout
messages; the existing 30-case business fixture is evaluated with its original
session contexts, giving 122 single-turn cases. Seven real HTTP conversations add
23 turns, covering the four requested scenarios plus clarification and safety.
There are 46 focused dialogue-policy tests in addition to the existing backend suite.

Holdout examples are not inserted into model prompts, semantic exemplars or cue
lists. The semantic threshold is selected only on development data. A generic token
boundary/backtracking bug in the grammar parser was corrected after initial
evaluation; the final run is a validation rerun on the same holdout, not a claim of a
second unseen holdout. Initial results were social recall 85% offline / 95% assisted
on holdout; the final parser reaches 90% / 95%. Multi-turn failures motivated the
document-scope fixes, separately from classifier threshold selection.

Macro F1 below uses processing classes (social/business/clarify/out-of-scope),
excluding repair actions, which are scored separately. Existing business accuracy
uses exact intent labels. Mixed accuracy checks the appropriate business, private
clarification or out-of-scope path, rather than merely checking “not social”.
False-social bypass measures social predictions on the business/mixed/legacy groups.
Latency is one local warm run, not a production SLA or a statistical confidence bound.

| Metric | Before | Production after |
| --- | ---: | ---: |
| Holdout social accuracy / recall (20 messages) | 0/20 (0%) | 18/20 (90%) |
| Social precision, all messages | no social predictions | 100% |
| Existing business intent accuracy (30 cases) | 30/30 (100%) | 30/30 (100%) |
| Mixed-intent accuracy (14 cases) | 14/14 (100%) | 14/14 (100%) |
| Overall routing accuracy (122 cases) | 70/122 (57.38%) | 114/122 (93.44%) |
| Processing-class macro F1 | 0.4268 | 0.7892 |
| Follow-up continuity after social turn, HTTP | 2/3 | 3/3 |
| Pending clarification resolution, HTTP | 0/1 | 1/1 |
| Fresh-session isolation, HTTP | 1/1 | 1/1 |
| False social bypass | 0% | 0% |
| Warm routing P50 | 0.88 ms | 1.02 ms |
| Warm routing P95 | 1.33 ms | 1.31 ms |
| Dialogue model calls / turn in production | 0 | 0 |
| Business tools used on HTTP social turns | 0 | 0 |

The latency difference at this scale is measurement noise. The added policy is
sub-millisecond work, not a measured speedup. The old router already avoided tools
for these social HTTP examples by returning clarification, so measured tool calls
avoided are **zero**, rather than claiming fictitious savings. Rephrase/source
requests intentionally incur current-corpus retrieval for verification. Routing
model-call counts exclude grounded-answer generation and the unchanged optional
business-intent LLM fallback.

## Regression and HTTP evidence

The original clean baseline passes 789 backend tests. A clean checkout is necessary
because the user's existing frontend/API changes and local generated directories
cause three unrelated failures in the shared workspace (API fake-agent signature,
release hygiene, and a frontend import assertion). Those changes were preserved.
The public API commit includes only the model-construction change; its pre-existing
partial-corpus edits were not staged.

Final test counts and detailed measured outcomes are recorded in
[evaluations/conversation-results.json](evaluations/conversation-results.json).
The final clean backend suite passes **835 tests**; OCR passes **109 tests** with
one skip. The backend lint command passes.
The HTTP acceptance suite passed **23/23 without LLM**, and **23/23 with the real
answer LLM**. Social turns had zero business tools and citations; business turns
retained evidence or an explicit insufficient-evidence outcome. The sample corpus
was reused, and the full 583-page ingestion was not run.

The existing demo was run through all 15 HTTP turns with the real model. The first
run passed 14/15; Q04 was rejected by evidence/claim publication. Q04 passed when
tested separately on the clean baseline and on the next complete run. The next
complete run also passed **14/15**, with Q03 rejected as
`citation_verification_failed`; Q04 passed. Both outcomes are preserved in the
machine-readable evidence. Model wording and source-verification variance is reported as
failure, never reclassified as a pass or repaired by weakening a verification gate.

Reproduce from the repository root, keeping run artifacts outside a clean CI tree:

```powershell
python tools/benchmark_conversation.py --semantic --llm --out reports/conversation-routing.json
python tools/serve_sample.py --root D:/AgentAI/OCOP-RAG/ocop-work-sample --port 8015
python tools/conversation_http_e2e.py --base-url http://127.0.0.1:8015
python tools/conversation_http_e2e.py --base-url http://127.0.0.1:8015 --real-llm
python -X utf8 tools/demo_chat_e2e.py --base-url http://127.0.0.1:8015 --root D:/AgentAI/OCOP-RAG/ocop-work-sample --real-llm --out reports/demo.json
python -m ruff check --select F ai_core backend ocop_contracts tools tests
python -m pytest tests/ocop -q
python -m pytest ocr/tests -q
```

## Changed files and remaining limits

Runtime: `contracts.py`, `dialogue.py`, `router.py`, `language.py`, `memory.py`,
`sessions.py`, `planner.py`, `workflow.py`, `answer.py`, `capabilities.py` under
`ai_core/orchestration/ocop/`; `configs/ocop_language.yaml`; and the two
`backend/api/ocop_{routes,debug}.py` adapters. Evaluation: the conversation fixture,
`test_dialogue_policy.py`, `tools/benchmark_conversation.py`,
`tools/conversation_http_e2e.py`, this report, the research note, and the compact
machine-readable evidence.

Offline grammar is deliberately conservative: unfamiliar paraphrases/slang can
still ask for clarification, and two holdout social phrases remain unmatched. Five
of eight unrelated-domain examples retain the original router's CLARIFY outcome
rather than OUT_OF_SCOPE; neither path executes tools or invents an external answer.
The evaluation does not establish general multilingual accuracy. Social composition
currently recognizes leading acts; trailing social language remains in business
query prose. A source request revalidates the active topic, not an exact prior-answer
sentence, because answer text is deliberately not stored. Unspecified corrections
need user detail. HTTP isolation evidence is one fresh-session scenario, supported
by existing session/memory tests; it is not a concurrency/load-test claim. The sample
contains unreviewed extraction, so normal candidate labels and score/star gates still
apply. Persisted model-generated answers remain sensitive to model wording variance.
