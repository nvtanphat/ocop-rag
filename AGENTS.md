# OCOP GraphRAG development rules
- Treat `data/raw/ocop` PDFs as immutable authoritative source bytes for ingestion.
- Preserve source PDF page, bounding box, evidence ID, source SHA-256 in extraction and citations.
- Separate unverified OCR candidates from verified domain facts.
- Do not use unverified score values for definitive ranking.
- The public OCOP index must never contain private data.
- Use `python tools/cli.py --help` for the supported OCOP pipeline commands.
- Keep frontend on `/api/ocop/*`; do not add unrelated-domain endpoints.
- Router may select several tools but never execute unregistered tool names; default maximum is five calls.
- Historical year changes must not silently override an explicitly pinned OCOP decision version.
- Rule/checklist tools read verified reference rules matching active corpus version, never client/LLM-supplied rules.
- A valid citation marker is NOT evidence of semantic entailment; verified score/star assertions need extra deterministic checks.
- This is one end-to-end system; do not create development stages in runtime or frontend.

## Working style
The repository owner reviews the result afterwards, so favour progress over caution.
- Act on the request directly. Do not ask for confirmation on local, reversible work: editing code, config and docs, rebuilding the graph or index, re-embedding, deleting generated data under `data/processed`, and running the test suite.
- Changing the ontology, builder, grounding or other fingerprinted code is allowed when the goal needs it. Say what will be rebuilt, then do it.
- There is no approval step. After extraction the owner edits one file (`data/extraction/entities-relations.md`); apply what it says and do not invent edits the owner did not make.
- Prefer one simple design over several defensive layers. Do not add guards, fallbacks or flags for cases that cannot happen.
- Report limits and failures plainly, then continue with the next step instead of stopping to ask.

Hard limits that stay: source PDFs stay unchanged, private data never enters the public index, and provenance (page, bbox, evidence ID, SHA-256) is never fabricated.

## Agent skills

### Issue tracker

GitHub issues. See `docs/agents/issue-tracker.md`.

### Triage labels

Default five-role vocabulary. See `docs/agents/triage-labels.md`.

### Domain docs

Single-context (`GLOSSARY.md` + `docs/adr/`). See `docs/agents/domain.md`.

