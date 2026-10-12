# Integrated branch checks and unresolved acceptance

2026-10-12 · branch `codex/mnemosyne-integration` · contract `0.1.0`.
The contract/source gate passes, but this branch is **not product ready**. Every
result below reflects the merged source and the integrated wiring. A check of a
fixture, source adapter, or bridge does not imply a complete app/device flow.

## Checks run

| Check | Result and scope |
|---|---|
| `python checks/validate_contracts.py --require-ready` | PASS: 30 OpenAPI operations, 4 schemas, 80 schema instances, 19 rejection cases, 10 annotation sync steps, 4 geometry cases, compose service, ownership, and source gates. This validates the shared bundle and integration metadata, not every planned endpoint. |
| `python checks/sync_contracts.py --check` | PASS: both source copies have the same 10-file bundle and manifest. Contract remains 0.1.0; the integration changes did not change DTO schemas. |
| `python checks/source_adapters.py` | PASS: the two-page fixture parses and searches through the real ReadingStore/PyMuPDF adapter; citation/page/rect rejection, native turn framing, SQLite turn replay after reopen, duplicate event append, geometry, and capability mapping pass. Its OpenAI-compatible streaming test used a local fake provider with no credential; it is not a live LLM check. |
| `python checks/integration_pdf_flow.py --allow-index-unavailable` | PARTIAL: live loopback HTTP exercised pairing, PDF upload, two parsed pages, search, source verification, annotation mutation/retry, deletion tombstone, derived export, SQLite reopen, original SHA preservation, session revocation, and WebSocket bearer bridge. The real indexer reported `failed` because `llama_index` is not installed in this executor. Without `--allow-index-unavailable`, this command exits nonzero unless indexing reaches `ready`. |
| Server import and OpenAPI routes | PASS: `deeptutor.api.main` imports and exposes `/v1/session/pair`, `/v1/session`, and `/v1/readiness`. Library routes are mounted in the actual lifespan after service registration; the flow check assembled the same authenticated router with a real Library service. Full application lifespan and background services were not started. |
| Python `compileall` | PASS for `deeptutor/mnemosyne` and `deeptutor/api/main.py`. |
| Ruff | PASS for the integration-auth modules, bootstrap and flow check; the scoped command ignores `I001` because UNIT-01-owned `library.py` has that import-order finding in the tracked merge base. Format checks pass on the integration-owned modules. No formatting was applied to unit-owned Library/Tutor files. |
| Web contracts and typecheck | PASS: `npm run contracts:check` and `npm run typecheck`. |
| `checks/web-consumer.mjs` | PASS: TypeScript wire decoder, PDF.js real fixture pages, four geometry cases, native frame sequence and replay rules. `actualBrowserVerified=false`; this is not a browser UI test. The check now transpiles only the source decoder and stubs its unused HTTP client import. |
| Web production build | **BLOCKED**: Next.js compiled config but could not fetch Google Fonts (Geist/Lora) under the managed network policy. This is not a successful product build. |
| `docker compose -f upstreams/DeepTutor/docker-compose.yml config --quiet` | PASS: Compose syntax/configuration only. |
| Docker image build/start | **NOT RUN**: Docker socket access returned `permission denied` for `/var/run/docker.sock`. No container or Windows WSL2 acceptance was performed. |
| Cloud runtime check | **NOT AVAILABLE**: the connected Cloud runtime reported no execution capability or configured secrets for this task. No Cloud deployment/check was run. |
| Real LLM request | **NOT RUN**: no provider credentials were available. PDF indexing stopped at the missing `llama_index` dependency; the fake streaming adapter result above is a separate local transport check. |
| macOS/Xcode/iPad | **NOT AVAILABLE**: no Swift compiler, Xcode/iPadOS SDK, Simulator, or iPad Pencil device is present in this Linux executor. |

The web npm install succeeded with a fresh temporary cache and
`--replace-registry-host=always --registry=https://registry.npmjs.org/`; the
pinned lockfile includes a small number of `npmmirror.com` tarballs that the
managed network rejected with HTTP 403. The repository lockfile was not changed.

## Requirement implementation and verification

See [the integration handoff](handoffs/integration.md) for the per-requirement
implementation/verification table and the exact unavailable unit refs. The
main product blockers in this branch are concrete missing code: UNIT-03's
durable iPad Reader/local store, a durable Mnemosyne LearningStateStore and
mounted Tutor/Quiz/Assessment/Memory APIs, and provider/settings callbacks.
They are not reported as completed or as a later phase.

## Repeat these checks

From the repository root, install the audit dependencies and the DeepTutor
development package. The web install needs Node 24 and may need the official
registry override used above.

```sh
python -m pip install -r checks/audit-environment.txt
cd upstreams/DeepTutor
python -m pip install -e ".[dev]"
cd ../..
python checks/validate_contracts.py --require-ready
python checks/sync_contracts.py --check
python checks/source_adapters.py
python checks/integration_pdf_flow.py --allow-index-unavailable
node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON checks/web-consumer.mjs
```

For a strict PDF flow run, omit `--allow-index-unavailable`; it exits with
status 2 unless the configured DeepTutor index pipeline reports `ready`.
Run the live LLM, Compose, Xcode, and device checks in their real configured
environments. Do not interpret their absence here as a pass.
