# Upstream source audit

The repository retains exact source snapshots of the two specified upstreams. The
audit manifest is `integration/upstreams.json`; it records original file hashes,
license, source commit, and later unit/integration modifications. Snapshots are
Git archive content, not subtree history. Embedded `.git`, local user data and
credentials were excluded.

| Upstream | Source pin | License and project constraints |
|---|---|---|
| [Pumice](https://github.com/theagitist/Pumice) | `a688aae2e6bce069ee256063c2a53afdcfe7de21` | MIT; iPadOS app, Swift 6, XcodeGen, signing values excluded. |
| [DeepTutor](https://github.com/HKUDS/DeepTutor) | `6cf793bd868ba5ecbe64722936d4be8fab5a01df` | Apache-2.0; original LICENSE and third-party notices retained. |

## Reused runtime boundaries

- Pumice provides PDFKit page display, Pencil rendering and the XcodeGen iPad app. UNIT-03 replaces source-PDF mutation with a hash-verified original cache, a persistent local Reader facade, and a sidecar/outbox for annotations. UNIT-04 composes that facade with the paired API and the integrated Tutor/Quiz/Learning screens. The exact unit refs are in [the integration handoff](handoffs/integration.md).
- DeepTutor provides the process-level FastAPI container, persistent `ReadingStore`, parser, RAG initializer, native WebSocket turn store/replay, provider catalog and web application. The integration registers one Mnemosyne service graph during app lifespan and reuses its native `/ws` transport and Reading material identity.
- DeepTutor's original sources include broad multi-user/auth and optional tool capabilities. Mnemosyne adds a separate personal pairing/session boundary and disables optional skills/MCP for its Tutor request. Provider keys are held server-side.
- PDF page locator and geometry contracts are explicit at the adapter boundary: Mnemosyne page indexes are zero based, while ReadingStore locator is one based. Source citations are rechecked against the immutable Library document version before they can drive Reader commands.
- Library/annotation state remains in ReadingStore and the Library adapter. A separate versioned SQLite store persists Mnemosyne quiz grading, attempts, assessment, mastery, Memory, progress and activity. This avoids changing UNIT-01-owned schema files.

## Provenance and current evidence

`integration/upstreams.json` stores pinned original blob/SHA-256 values and
`modified_originals` overrides for the exact upstream files changed by unit or
integration work. New adapters/tests appear in `integration_added_files`.
`integration/ownership.json` assigns each changed product path to one owner.
The six supplied commits are ancestors of the current integration branch HEAD.

Available commands and actual current results are recorded in
[`docs/VALIDATION.md`](VALIDATION.md). Compose syntax and selected web/contract
checks run in this Linux executor. The current environment cannot execute the
full PDF HTTP flow, real LLM/RAG, Docker daemon, macOS/Xcode build or physical
iPad Pencil acceptance; none of those are described as passing.
