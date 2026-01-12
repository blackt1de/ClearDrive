import SwiftUI

@main
struct ClearDriveApp: App {
    @StateObject private var obdManager = OBDManager()
    @StateObject private var apiClient = APIClient()

    var body: some Scene {
        WindowGroup {
            ContentView()
                .environmentObject(obdManager)
                .environmentObject(apiClient)
                .preferredColorScheme(.dark)
        }
    }
}
