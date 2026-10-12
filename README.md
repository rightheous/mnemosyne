# Mnemosyne integration

Integration branch: `codex/mnemosyne-integration`, based on `main`
`16130d21410d1b2349ffee0757d44462c899ebbf` and preparation commit
`5715a32927e3a73dc28782d306880e3dd1f62441`. It contains all six supplied unit
results and contract `0.2.0`. This is a reviewable integration, not a claim of
device or production acceptance: the live provider, vector index, Docker
daemon, macOS/Xcode toolchain and iPad are unavailable in this executor.

## Run the integrated web and API service

From the repository root, use the pinned DeepTutor Compose profile. It keeps
the original PDF, parsed data, SQLite learning state, settings and workspace
under `upstreams/DeepTutor/data` for backup and restore.

```sh
cd upstreams/DeepTutor
python -m pip install -e ".[dev]"
python scripts/docker_compose.py config --quiet
python scripts/docker_compose.py up -d --build
python scripts/docker_compose.py exec -it deeptutor python -m deeptutor.mnemosyne.pairing issue
```

Open the displayed local web URL and enter the one-time pairing code. The
default Compose bind is loopback. For a private LAN or HTTPS reverse proxy,
set `DEEPTUTOR_BIND_ADDRESS` and `MNEMOSYNE_ALLOWED_ORIGINS` to the reachable
address and exact browser origin before running the script. Keep provider
credentials in the server's private settings UI; never put them in a browser
build, command history or Compose file. The source server can also run without
Docker by setting a persistent `DEEPTUTOR_HOME` and starting
`python -m uvicorn deeptutor.api.main:app --host 127.0.0.1 --port 8001`; that
starts the API and does not serve the web app.

## Run checks

The exact commands and the results from this executor are in
[docs/VALIDATION.md](docs/VALIDATION.md). From the repository root:

```sh
python -m pip install -r checks/requirements.txt
python -m pip install -e "upstreams/DeepTutor[dev]"
python checks/sync_contracts.py --check
python checks/validate_contracts.py --require-ready
python checks/source_adapters.py
python checks/integration_pdf_flow.py --allow-index-unavailable
node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON checks/web-consumer.mjs
```

For web type checks and a production build:

```sh
cd upstreams/DeepTutor/web
npm ci --replace-registry-host=always --registry=https://registry.npmjs.org
npm run contracts:check
npm run typecheck
npm run test:node
npm run test:unit -- --maxWorkers=1 --reporter=dot
npm run build
```

`integration_pdf_flow.py` exercises the checked-in two-page PDF through paired
upload, parsing, search and citation verification, annotation retry/tombstone,
progress retry and SQLite recovery, derived export and original-PDF hash
preservation. In this executor indexing stopped at missing `llama_index`, so
the flow is partial. It reports readiness separately; the fixture does not
stand in for a real LLM, browser, Docker host or iPad.

## Status

Quiz questions and private grading input, quiz attempts, mastery, memory review
and reading progress use durable SQLite state. Web/iPad progress retries carry
stable mutation IDs. Tutor turns use DeepTutor's native `/ws` stream; the web
request envelope now reaches the same adapter as iPad, and Reading material
identity is resolved from the server's Library document version. The durable
Tutor turn receipt endpoint is registered for reconnect. The iPad Reader's
local file/outbox and offline Pencil paths are integrated, but need Xcode and
hardware verification.

Actual RAG indexing and LLM answers require the configured DeepTutor parser,
index dependencies and provider credential. No result in the current
environment counts as a live Tutor answer or device test. See the
[requirement matrix and evidence](docs/handoffs/integration.md).
