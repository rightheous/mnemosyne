# Pumice

A native iPadOS PDF annotation utility for local-first PKM users.

Pumice edits PDF files directly inside your vault, no sidecar files, no cloud
lock-in, no proprietary formats. Highlight and scribble with Apple Pencil; pan
with your finger; extract annotations to reconcilable Markdown that drops
straight into Obsidian, Logseq, or any other plain-text knowledge graph.

## Status

Version `0.3.0` is live on the App Store: [apps.apple.com/ca/app/pumice/id6772806425](https://apps.apple.com/ca/app/pumice/id6772806425).

Pumice now sits alongside both PDFs and Markdown notes. Tap a `.md` file in the
sidebar to preview headings, lists, blockquotes, and code blocks; tap Convert
to PDF to generate a paginated PDF on device with the same layout. Apple Pencil
drawing with color and width selection, real-time eraser, undo/redo via touch
and Pencil press, debounced autosave, cross-app PDF compatibility (annotations
render in Preview, Adobe, and any standards-conformant viewer), and snap-to-text
highlights with a three-tool model (pencil, highlighter, eraser). Lazy vault
browsing means large vaults open instantly. Sidebar refresh, delete, and
convert all happen in place without collapsing the tree.

Safe-save with `.bak` + atomic replace and the Extract annotations-to-Markdown
action (the `ExtractionEngine` is in PumiceCore with deep test coverage) are
scoped for the next release.

The product requirements document lives in the author's private Obsidian vault
and is intentionally not duplicated in this repo.

## Requirements

- iPadOS 18.0 or later
- Apple Pencil (any generation) recommended
- Xcode 16+ (for development)

## Building

The Xcode project is generated from `project.yml` via
[xcodegen](https://github.com/yonaskolb/XcodeGen):

```sh
brew install xcodegen
xcodegen generate
open Pumice.xcodeproj
```

## License

MIT — see [`LICENSE`](LICENSE).
