import SwiftUI

struct ContentView: View {
    @EnvironmentObject var obdManager: OBDManager
    @EnvironmentObject var apiClient: APIClient

    @State private var selectedTab = 0

    var body: some View {
        TabView(selection: $selectedTab) {
            ScanView()
                .tabItem {
                    Image(systemName: "car.fill")
                    Text("Scan")
                }
                .tag(0)

            HistoryView()
                .tabItem {
                    Image(systemName: "clock.fill")
                    Text("History")
                }
                .tag(1)

            SettingsView()
                .tabItem {
                    Image(systemName: "gear")
                    Text("Settings")
                }
                .tag(2)
        }
        .tint(.green)
    }
}

#Preview {
    ContentView()
        .environmentObject(OBDManager())
        .environmentObject(APIClient())
}
