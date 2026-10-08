import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";

const read = (relative: string) =>
  fs.readFileSync(path.resolve(process.cwd(), relative), "utf8");

test("personal settings route mounts the Mnemosyne settings screen directly", () => {
  const layout = read("app/(settings)/settings/layout.tsx");
  const page = read("app/(settings)/settings/page.tsx");
  assert.match(page, /MnemosyneSettings/);
  for (const provider of [
    "UiSettingsProvider",
    "ModelCatalogProvider",
    "SettingsDraftProvider",
  ]) {
    assert.doesNotMatch(layout, new RegExp(`<${provider}>`));
  }

  const providers = [
    read("features/settings/store/UiSettingsProvider.tsx"),
    read("features/settings/store/ModelCatalogProvider.tsx"),
    read("features/settings/store/SettingsDraftProvider.tsx"),
  ];
  for (const source of providers) {
    assert.match(source, /useMemo/);
  }
});

test("legacy settings provider slices remain independently memoized", () => {
  const ui = read("features/settings/store/UiSettingsProvider.tsx");
  const catalog = read("features/settings/store/ModelCatalogProvider.tsx");
  const draft = read("features/settings/store/SettingsDraftProvider.tsx");
  for (const source of [ui, catalog, draft]) {
    assert.match(source, /useMemo/);
    assert.doesNotMatch(source, /\}, \[source\]\)/);
  }
});

test("appearance consumes only the UI preference slice", () => {
  const appearance = read(
    "features/settings/sections/AppearanceSettingsSection.tsx",
  );
  assert.match(appearance, /useUiSettings\(\)/);
  assert.doesNotMatch(appearance, /useSettings\(\)/);
});

test("settings mounts one feature section on demand, never route modules", () => {
  const page = read("components/settings/SettingsPageContent.tsx");
  assert.match(page, /dynamic\(/);
  assert.match(page, /<Component key=\{key\}/);
  assert.doesNotMatch(page, /CategoryScroll/);
});
