import Foundation
import PumiceCore

/// UNIT-04 owns network and screens; it calls Reader facade instead of its DB.
@MainActor protocol MnemosyneSyncWorker: AnyObject {
    func synchronize() async throws
}

@MainActor struct MnemosyneAppDependencies {
    let reader: any MnemosyneReaderFacade
    let syncWorker: any MnemosyneSyncWorker
    let serverURL: URL
}

/// UNIT-04 connects this composition seam to PumiceApp/LaunchView.
@MainActor func makeIPadApp(reader: any MnemosyneReaderFacade,
                           syncWorker: any MnemosyneSyncWorker,
                           serverURL: URL) -> MnemosyneAppDependencies {
    MnemosyneAppDependencies(reader: reader, syncWorker: syncWorker, serverURL: serverURL)
}
