# Mnemosyne integration snapshot

This branch integrates the available Mnemosyne work on top of `main`. The
integrated source is runnable for the Library/session API and the existing
DeepTutor web shell, but it is **not product ready**: the supplied UNIT-03 ref
(`codex/unit-03-reader` at `ae202f0cf1096d5fcc0ab1ecd325ac20a0d8e4b1`) is not
fetchable from this workspace or its configured origin, and no durable
Mnemosyne learning store is connected.

## Run the server

Use a persistent runtime directory outside this checkout. From the repository
root:

```sh
cd upstreams/DeepTutor
export DEEPTUTOR_HOME="$(pwd)/../../../mnemosyne-runtime"
python -m pip install -e ".[dev]"
python -m uvicorn deeptutor.api.main:app --host 0.0.0.0 --port 8001
```

The server creates its data tree under `DEEPTUTOR_HOME`. To issue a short-lived
pairing code from the same environment and runtime directory, open another
shell and run:

```sh
cd upstreams/DeepTutor
export DEEPTUTOR_HOME="$(pwd)/../../../mnemosyne-runtime"
python -m deeptutor.mnemosyne.pairing issue
```

Enter that code in the Mnemosyne web or iPad pairing screen. Each code expires
after ten minutes and succeeds once. The server stores only its hash; device
bearer sessions can be revoked from the app. Configure
`MNEMOSYNE_ALLOWED_ORIGINS` as a comma-separated list of exact browser origins
when the web UI is served from a different origin. Native bearer requests may
omit `Origin`; browser cookie writes and browser WebSocket upgrades require an
allowed exact origin.

## Run the web app

The DeepTutor Compose setup runs its web server and API behind the same local
origin, which the Mnemosyne browser client requires. From `upstreams/DeepTutor`:

```sh
python scripts/docker_compose.py up -d --build
```

Set the browser's externally visible origin before bringing up Compose, for
example `MNEMOSYNE_ALLOWED_ORIGINS=http://localhost:3782`. After the container
is running, issue a pairing code inside the same persistent container:

```sh
docker exec -it deeptutor python -m deeptutor.mnemosyne.pairing issue
```

The Compose project keeps runtime data under `upstreams/DeepTutor/data` unless
the deployment maps that directory elsewhere. Configure the provider through
the upstream DeepTutor settings before using LLM-backed study features. Compose
configuration can be checked without starting containers:

```sh
docker compose -f docker-compose.yml config --quiet
```

## Checks

From the repository root, install the local check dependencies and run the
source/contract checks:

```sh
python -m pip install -r checks/audit-environment.txt
python checks/validate_contracts.py --require-ready
python checks/sync_contracts.py --check
python checks/source_adapters.py
python checks/integration_pdf_flow.py --allow-index-unavailable
node --disable-warning=MODULE_TYPELESS_PACKAGE_JSON checks/web-consumer.mjs
```

The PDF flow check uses the two-page fixture and isolated temporary storage. It
prints the actual RAG `index_state`; without `--allow-index-unavailable` it
exits nonzero unless DeepTutor reports a ready index.

For the existing web production build:

```sh
cd upstreams/DeepTutor/web
npm ci
npm run contracts:check
npm run typecheck
npm run test:node
npm run test:unit -- --maxWorkers=1 --reporter=dot
npm run build
```

See [docs/VALIDATION.md](docs/VALIDATION.md) for checks actually run on this
integration branch and the limits of each result.

## Current integration limits

- The paired Library API has been exercised with the two-page PDF through
  parsing, search, source verification, annotation retry/tombstone, export, and
  SQLite reopen. The fixture reached `index_state=failed` because this executor
  lacks `llama_index`; RAG indexing is not verified here.
- The server has no `LearningStateStore` implementation or mounted tutor-turn,
  quiz, assessment, memory, progress, and review API handlers. Those routes
  return no success state because they are absent.
- The UNIT-04 iPad composition references durable Reader/Pencil types that do
  not exist in the supplied Pumice tree. The exact UNIT-03 ref is known, but
  its source commit is unavailable from this workspace and origin, so the
  source cannot produce an iPad app until that source is made reachable and
  integrated.
- The contract remains 0.1.0 because this change wires existing DTOs and does
  not alter their schemas. The integrated branch does not claim product
  readiness or Cloud/device acceptance.
