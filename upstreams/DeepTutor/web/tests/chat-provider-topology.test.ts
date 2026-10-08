import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const source = (relative: string) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf8");

test("the personal workspace does not mount the legacy chat runtime", () => {
  assert.doesNotMatch(source("app/(workspace)/layout.tsx"), /ChatRuntimeProvider|ReadingProvider|AppShell/);
  assert.doesNotMatch(
    source("app/(workspace)/learning/reading/layout.tsx"),
    /ChatRuntimeProvider|ChatStateAdapterProvider/,
  );
  assert.match(source("app/(workspace)/learning/reading/page.tsx"), /MnemosyneLibrary/);
});

test("Mastery study inherits the workspace runtime without nesting", () => {
  assert.doesNotMatch(
    source("app/(workspace)/learning/mastery/[pathId]/sessions/layout.tsx"),
    /ChatRuntimeProvider/,
  );
});

test("the runtime provider mounts one live state owner", () => {
  const provider = source("features/chat/ChatRuntimeProvider.tsx");
  assert.match(provider, /ChatStateAdapterProvider/);
  assert.doesNotMatch(provider, /createChatStore|ChatActions|ChatStoreProvider/);
  assert.match(provider, /cannot be nested/);
});
