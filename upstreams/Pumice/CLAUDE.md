# Pumice — agent notes

Local-first PDF annotation app for iPadOS. Swift 6 strict concurrency. Shipped
on the App Store as of v0.2.0
([apps.apple.com/ca/app/pumice/id6772806425](https://apps.apple.com/ca/app/pumice/id6772806425)).

This file is durable guidance for any AI agent working in this repo. The PRD,
submission notes, and personal status snapshots live elsewhere (see "Where
things live" below).

## Hard rules

1. **iPadOS only**. Never add `macOS` to `Package.swift`, `project.yml`, or
   anywhere else. The product is intentionally iPad-only. `SUPPORTS_MACCATALYST`
   and `SUPPORTS_MAC_DESIGNED_FOR_IPHONE_IPAD` are `NO` and must stay `NO`.
2. **PII out of source**. `DEVELOPMENT_TEAM`, `PRODUCT_BUNDLE_IDENTIFIER_PREFIX`,
   `fastlane/.env`, and `*.p8` files are gitignored. `Config/Local.xcconfig`
   holds the local team id; `Config/Local.xcconfig.example` is the template that
   ships. Never inline a real team id, Apple ID, or API key into a tracked file.
3. **PRD is canonical in the vault**, not in this repo. Do not copy the PRD here.
4. **Conventional Commits**. No `Co-Authored-By`, no "Generated with Claude",
   no AI attribution of any kind in commit messages. Follow the
   [spec](https://www.conventionalcommits.org/en/v1.0.0/#specification).
5. **No em-dashes** in commit messages, code comments, or public-facing copy
   (README, the website at `pumice.polivoxia.ca`, App Store metadata).

## Build system

The Xcode project is generated from `project.yml` via
[xcodegen](https://github.com/yonaskolb/XcodeGen). `Pumice.xcodeproj/` is
gitignored. Workflow:

```sh
xcodegen generate
open Pumice.xcodeproj
```

After editing `project.yml`, regenerate before building. Fastlane's `build`
lane regenerates automatically.

### `TARGETED_DEVICE_FAMILY` gotcha

xcodegen silently injects `TARGETED_DEVICE_FAMILY = "1,2"` at the iOS-app
target level, which overrides any project-level setting. For an iPad-only
build you MUST set it on the `Pumice` target's `settings.base` too (already
done in `project.yml`). If you ever see `UIDeviceFamily = [1, 2]` in the
shipped Info.plist, check that the target-level override is still present.
Verification:

```sh
unzip -p build/fastlane/Pumice.ipa Payload/Pumice.app/Info.plist \
  | plutil -p - | grep -A 4 UIDeviceFamily
```

Should print only `0 => 2`.

## Architecture

### Targets

- `Pumice` (`Sources/`): the iPad app. SwiftUI shell + `UIViewControllerRepresentable`
  wrapping a `PDFReaderViewController`.
- `PumiceTests` (`Tests/PumiceTests/`): iOS integration tests that need a host
  app (PDFKit, UIDocumentPicker).
- `PumiceUITests` (`Tests/PumiceUITests/`): XCUITest target used by fastlane
  `snapshot` to capture App Store screenshots.
- `PumiceCore` (`Packages/PumiceCore/`): pure Swift package, no UIKit. Holds
  `ExtractionEngine`, `HighlightSerialization`, `InkSerialization`,
  `Coordinates`, `AnnotationID`. ~96% test coverage via `swift test`.

### Reader subsystem (`Sources/Reader/`)

Where the load-bearing PDFKit gotchas live. Don't refactor these without
re-reading the surrounding comments:

- `PumiceCanvasView` subclasses `PDFPageView` to capture Apple Pencil strokes
  directly. Required because `PKCanvasView` doesn't compose with `PDFView`'s
  scrolling.
- The custom `Ink` annotation subclass overrides `draw(with:in:)` because
  iOS PDFKit generates broken `/AP` appearance streams for default `.ink`
  annotations. Without this subclass, annotations don't render in Preview,
  Adobe, or any non-PDFKit viewer.
- `PenSettings` is mirrored into the view controller via
  `UIViewControllerRepresentable`. Every `@Published` property MUST be
  compared-before-assigned in `updateUIViewController` or you'll create a
  `publish → updateUIViewController → publish` loop. Compile-time can't catch
  this; it manifests as a CPU spin.
- `PDFAnnotation.quadrilateralPoints` is in coordinates LOCAL to
  `bounds.origin`, not page coordinates. The `HighlightAnnotationBuilder` in
  `PumiceCore` is built around this; don't "fix" it.

### Vault subsystem (`Sources/Vault/`, `Sources/Browser/`)

- `VaultStore` is `@MainActor`. Single source of truth for the vault root URL,
  resolved security-scoped bookmark, and the recent-vaults list.
- Vault browsing is lazy (`VaultDirectoryLister`). The pre-`95ff6de`
  behaviour did an upfront recursive scan and was unusable on real vaults.
  If you find yourself reaching for `FileManager.enumerator` at the root,
  stop and read the existing lazy implementation.
- Writes to File-Provider-backed locations (Möbius Sync, iCloud Drive, third-
  party providers) MUST go through `NSFileCoordinator`. Without it, the bytes
  stay in an iOS per-app overlay and never sync. This already bit us; the
  coordination is in place in `VaultStore.save` and friends.

### Onboarding (`Sources/Onboarding/`)

`OnboardingView` is the first-run flow that walks the user into selecting a
vault root (the security-scoped folder `VaultStore` then bookmarks). The UI
test bootstrap below exists specifically to bypass this when capturing
screenshots.

### UI test bootstrap

The app honours a `PUMICE_UITEST_VAULT` launch argument in DEBUG builds only.
Setting it triggers `VaultStore.bootstrapUITestVault()`, which generates a
synthetic vault under `Documents/UITestSampleVault/` containing two PDFs
(`Letters/Letter I.pdf`, `Letters/Letter II.pdf` produced from public-domain
Frankenstein excerpts via `MarkdownPDFConverter`) and two markdown notes
(`Notes/Reading Notes.md`, `Notes/Themes and Symbols.md`). Used by
`bundle exec fastlane screenshots` to produce App Store screenshots without
dragging the user through onboarding. Stripped from Release.

## Testing

```sh
# Pure logic, fast
swift test --package-path Packages/PumiceCore

# iOS integration (needs simulator)
xcodebuild test \
  -project Pumice.xcodeproj \
  -scheme Pumice \
  -destination 'platform=iOS Simulator,name=iPad Pro 13-inch (M5)'

# Screenshots
bundle exec fastlane screenshots
```

## App Store submission

Submission tooling lives in `fastlane/`. Credentials live in
`fastlane/.env` (gitignored). Lanes:

- `preflight` — sanity-check env + xcconfig + .p8 file
- `setup_signing` — `cert` + `sigh` via ASC API; generates Distribution cert
  and App Store profile
- `seed_review_detail` — workaround for fastlane 2.230's
  `review_attachment_file` nil-guard bug. MUST run before the first
  `upload` on a fresh App Store version.
- `build` — `xcodegen generate` then archive + export App Store .ipa
- `upload` — push the .ipa + metadata to App Store Connect
- `upload_screenshots` — push screenshots only
- `submit` — flip the submission flag for review
- `release` — full pipeline: build → upload → submit
- `asc_inspect` — print the current ASC record state
- `asc_check` — verify API key auth works

### Submission notes

- **Primary locale is `en-CA`**, not `en-US`. Metadata lives in
  `fastlane/metadata/en-CA/`. Putting it in `en-US/` triggers a misleading
  "name is already used by another app" error.
- **Bump `CURRENT_PROJECT_VERSION` in `project.yml`** before every re-upload;
  Apple rejects duplicate build numbers within the same `MARKETING_VERSION`.
- **Pricing and App Privacy** can NOT be set via fastlane 2.230. The new App
  Store Connect price-points API and the App Privacy questionnaire endpoint
  are not wired in. Set both in the ASC web UI.
- **SnapshotHelper.swift** in `Tests/PumiceUITests/` has hand-applied
  `nonisolated(unsafe)` markings for Swift 6 strict concurrency. If you
  update the upstream helper, re-apply those.

## Versioning

- `MARKETING_VERSION` in `project.yml` is the user-facing semver
  (`0.2.0`).
- `CURRENT_PROJECT_VERSION` is the integer build number. Bump it for every
  upload to App Store Connect, even if `MARKETING_VERSION` didn't change.
- Tag releases as `vX.Y.Z` at the commit that produced the shipped binary.

## Where things live

| Thing | Location |
|---|---|
| PRD | The user's private Obsidian vault, at `Polivoxia/Projects/Pumice/PRD.md` (not this repo). The vault's absolute path varies per machine: on this VPS it is `~/apps/obsidian/Polivoxia/...`, on the user's Mac it is elsewhere. Resolve the `Polivoxia` vault root for the current device, then append the relative path. |
| Older submission notes | Same vault, `Polivoxia/Projects/Pumice/Submission/`. |
| Public website source | The live VPS at `pumice.polivoxia.ca`. A handoff package used to live in `~/Documents/FileShare/Pumice/` but has been wiped. |
| ASC API key | `~/.appstoreconnect/private_keys/AuthKey_5RVT7QRG98.p8` (per-user, not in repo) |
| Local team id | `Config/Local.xcconfig` (gitignored, copy from `Local.xcconfig.example`) |
| Fastlane env | `fastlane/.env` (gitignored) |

## Iterating on hardware

```sh
git clone git@github.com:theagitist/Pumice.git
cd Pumice
cp Config/Local.xcconfig.example Config/Local.xcconfig
# edit Local.xcconfig to set your DEVELOPMENT_TEAM and bundle prefix
xcodegen generate
open Pumice.xcodeproj
# Cmd-R to iPad
```
