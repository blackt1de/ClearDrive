import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var apiClient: APIClient
    @AppStorage("serverURL") private var serverURL = "http://192.168.1.254:8000"
    @State private var isTestingConnection = false
    @State private var connectionStatus: ConnectionStatus?

    var body: some View {
        NavigationStack {
            Form {
                Section("Server Configuration") {
                    VStack(alignment: .leading, spacing: 8) {
                        Text("Server URL")
                            .font(.caption)
                            .foregroundStyle(.secondary)

                        TextField("http://your-server:8000", text: $serverURL)
                            .textFieldStyle(.roundedBorder)
                            .autocapitalization(.none)
                            .keyboardType(.URL)
                    }

                    Button(action: testConnection) {
                        HStack {
                            if isTestingConnection {
                                ProgressView()
                                    .scaleEffect(0.8)
                            } else {
                                Image(systemName: "network")
                            }
                            Text("Test Connection")
                        }
                    }
                    .disabled(isTestingConnection)

                    if let status = connectionStatus {
                        HStack {
                            Image(systemName: status.isConnected ? "checkmark.circle.fill" : "xmark.circle.fill")
                                .foregroundStyle(status.isConnected ? .green : .red)
                            Text(status.message)
                                .font(.caption)
                        }
                    }
                }

                Section("About") {
                    HStack {
                        Text("Version")
                        Spacer()
                        Text("1.5.0")
                            .foregroundStyle(.secondary)
                    }

                    HStack {
                        Text("Build")
                        Spacer()
                        Text("iOS Native")
                            .foregroundStyle(.secondary)
                    }
                }

                Section("OBD Adapter") {
                    NavigationLink("Supported Adapters") {
                        SupportedAdaptersView()
                    }

                    NavigationLink("Troubleshooting") {
                        TroubleshootingView()
                    }
                }
            }
            .navigationTitle("Settings")
            .onChange(of: serverURL) { _, newValue in
                apiClient.baseURL = newValue
            }
        }
    }

    private func testConnection() {
        isTestingConnection = true
        connectionStatus = nil

        Task {
            do {
                let isHealthy = try await apiClient.checkHealth()
                await MainActor.run {
                    connectionStatus = ConnectionStatus(
                        isConnected: isHealthy,
                        message: isHealthy ? "Connected to server" : "Server unhealthy"
                    )
                    isTestingConnection = false
                }
            } catch {
                await MainActor.run {
                    connectionStatus = ConnectionStatus(
                        isConnected: false,
                        message: "Failed: \(error.localizedDescription)"
                    )
                    isTestingConnection = false
                }
            }
        }
    }
}

struct ConnectionStatus {
    let isConnected: Bool
    let message: String
}

struct SupportedAdaptersView: View {
    var body: some View {
        List {
            Section("Recommended") {
                AdapterRow(name: "OBDLink MX+", protocol: "Bluetooth", compatible: true)
                AdapterRow(name: "OBDLink CX", protocol: "BLE", compatible: true)
                AdapterRow(name: "Veepeak OBDCheck BLE+", protocol: "BLE", compatible: true)
            }

            Section("Compatible") {
                AdapterRow(name: "ELM327 Bluetooth", protocol: "Bluetooth Classic", compatible: true)
                AdapterRow(name: "Generic BLE OBD2", protocol: "BLE", compatible: true)
            }

            Section("Not Compatible") {
                AdapterRow(name: "WiFi OBD2 Adapters", protocol: "WiFi", compatible: false)
                AdapterRow(name: "USB OBD2 Adapters", protocol: "USB", compatible: false)
            }
        }
        .navigationTitle("Supported Adapters")
    }
}

struct AdapterRow: View {
    let name: String
    let `protocol`: String
    let compatible: Bool

    var body: some View {
        HStack {
            VStack(alignment: .leading) {
                Text(name)
                    .font(.headline)
                Text(`protocol`)
                    .font(.caption)
                    .foregroundStyle(.secondary)
            }

            Spacer()

            Image(systemName: compatible ? "checkmark.circle.fill" : "xmark.circle.fill")
                .foregroundStyle(compatible ? .green : .red)
        }
    }
}

struct TroubleshootingView: View {
    var body: some View {
        List {
            Section("Connection Issues") {
                TroubleshootItem(
                    title: "Adapter not found",
                    solution: "Make sure Bluetooth is enabled and the adapter is plugged into your car's OBD port. The car ignition should be ON."
                )

                TroubleshootItem(
                    title: "Connection drops",
                    solution: "Stay within 30 feet of your car. Some adapters may need to be re-paired in Bluetooth settings."
                )

                TroubleshootItem(
                    title: "No data received",
                    solution: "Ensure the car ignition is in the ON position (not just accessory). Wait 10-15 seconds after connecting."
                )
            }

            Section("Server Issues") {
                TroubleshootItem(
                    title: "Cannot connect to server",
                    solution: "Check that your server is running and you have internet/WiFi connection. Verify the server URL in Settings."
                )
            }
        }
        .navigationTitle("Troubleshooting")
    }
}

struct TroubleshootItem: View {
    let title: String
    let solution: String

    var body: some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title)
                .font(.headline)
            Text(solution)
                .font(.subheadline)
                .foregroundStyle(.secondary)
        }
        .padding(.vertical, 4)
    }
}

#Preview {
    SettingsView()
        .environmentObject(APIClient())
}
