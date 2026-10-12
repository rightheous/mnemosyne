import SwiftUI

@main
struct MnemosyneApp: App {
    @StateObject private var model = MnemosyneAppModel()

    var body: some Scene {
        WindowGroup {
            MnemosyneRootView(model: model)
        }
    }
}
