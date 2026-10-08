import SwiftUI

/// Modal sheet that lists the user's recent vaults (excluding the
/// currently-open one) with swipe-left-to-delete. Reached from the
/// sidebar's "..." menu. Tapping a row switches to that vault; the
/// sheet dismisses itself afterwards. Tapping "Connect a new vault…"
/// at the bottom opens the document picker for adding a vault.
struct VaultManageSheet: View {
    @EnvironmentObject private var vault: VaultStore
    @Environment(\.dismiss) private var dismiss

    @State private var recents: [VaultStore.AvailableRecent] = []
    @State private var showingPicker = false

    var body: some View {
        NavigationStack {
            List {
                Section {
                    if let current = currentDisplay {
                        Label(current, systemImage: "checkmark.circle.fill")
                            .foregroundStyle(.primary)
                    } else {
                        Text("No vault open")
                            .foregroundStyle(.secondary)
                    }
                } header: {
                    Text("Current")
                }

                Section {
                    if recents.isEmpty {
                        Text("No other vaults yet. Connect one to keep it here for next time.")
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(recents) { entry in
                            Button {
                                vault.switchTo(entry.id)
                                dismiss()
                            } label: {
                                Label {
                                    VStack(alignment: .leading, spacing: 2) {
                                        Text(entry.displayName)
                                            .foregroundStyle(.primary)
                                        Text(entry.url.path)
                                            .font(.caption2)
                                            .foregroundStyle(.secondary)
                                            .lineLimit(1)
                                            .truncationMode(.middle)
                                    }
                                } icon: {
                                    Image(systemName: "folder")
                                }
                            }
                            .swipeActions(edge: .trailing, allowsFullSwipe: true) {
                                Button(role: .destructive) {
                                    vault.remove(entry.id)
                                    refresh()
                                } label: {
                                    Label("Delete", systemImage: "trash")
                                }
                            }
                        }
                    }
                } header: {
                    Text("Recent")
                } footer: {
                    Text("Swipe a vault to remove it from this list. Pumice doesn't touch the files; you can re-connect it later.")
                        .font(.caption2)
                }

                Section {
                    Button {
                        showingPicker = true
                    } label: {
                        Label("Connect a new vault…", systemImage: "folder.badge.plus")
                    }
                }
            }
            .navigationTitle("Vaults")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") { dismiss() }
                }
            }
            .sheet(isPresented: $showingPicker) {
                VaultPicker(
                    onPick: { url in
                        showingPicker = false
                        guard url.startAccessingSecurityScopedResource() else { return }
                        vault.adopt(pickedURL: url)
                        dismiss()
                    },
                    onCancel: { showingPicker = false }
                )
                .ignoresSafeArea()
            }
        }
        .onAppear(perform: refresh)
        .onChange(of: vault.vaults) { _, _ in refresh() }
    }

    private var currentDisplay: String? {
        vault.vaults.first?.displayName
    }

    private func refresh() {
        recents = vault.availableRecentVaults()
    }
}
