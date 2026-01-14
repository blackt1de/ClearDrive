//
//  SettingsView.swift
//  ClearDrive
//
//  Settings tab - Server config, preferences, and account
//

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var apiClient: APIClient
    @EnvironmentObject var vehicleStore: VehicleStore
    @AppStorage("serverURL") private var serverURL = "http://192.168.1.100:8000"
    @AppStorage("useMetricUnits") private var useMetricUnits = false
    @AppStorage("enableNotifications") private var enableNotifications = true

    @State private var isTestingConnection = false
    @State private var connectionResult: ConnectionTestResult?

    var body: some View {
        ZStack {
            Color.cdBackground
                .ignoresSafeArea()

            Form {
                // Server Configuration
                serverSection

                // Demo Mode (for testing)
                demoSection

                // Preferences
                preferencesSection

                // OBD Info
                obdSection

                // Account
                accountSection

                // About
                aboutSection

                // Data Management
                dataSection
            }
            .scrollContentBackground(.hidden)
        }
        .navigationTitle("Settings")
    }

    // MARK: - Data Section

    @State private var showingClearAlert = false

    private var dataSection: some View {
        Section {
            Button(role: .destructive) {
                showingClearAlert = true
            } label: {
                Label("Clear All Data", systemImage: "trash")
            }
            .alert("Clear All Data?", isPresented: $showingClearAlert) {
                Button("Cancel", role: .cancel) {}
                Button("Clear", role: .destructive) {
                    vehicleStore.clearAllData()
                }
            } message: {
                Text("This will remove all saved vehicles and scan history. You'll need to run new scans.")
            }
        } header: {
            Text("Data")
        } footer: {
            Text("Clear saved data if you're experiencing issues with blank screens or missing data.")
        }
        .listRowBackground(Color.cdCardBackground)
    }

    // MARK: - Server Section

    private var serverSection: some View {
        Section {
            VStack(alignment: .leading, spacing: CDSpacing.small) {
                Text("Server URL")
                    .font(.caption)
                    .foregroundStyle(Color.cdTextSecondary)

                TextField("http://your-server:8000", text: $serverURL)
                    .textFieldStyle(.roundedBorder)
                    .autocapitalization(.none)
                    .keyboardType(.URL)
                    .onChange(of: serverURL) { _, newValue in
                        apiClient.baseURL = newValue
                        connectionResult = nil
                    }
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

            if let result = connectionResult {
                HStack {
                    Image(systemName: result.success ? "checkmark.circle.fill" : "xmark.circle.fill")
                        .foregroundStyle(result.success ? Color.cdSuccess : Color.cdCritical)
                    Text(result.message)
                        .font(.caption)
                        .foregroundStyle(result.success ? Color.cdSuccess : Color.cdCritical)
                }
            }
        } header: {
            Text("Server Configuration")
        }
        .listRowBackground(Color.cdCardBackground)
    }

    // MARK: - Preferences Section

    private var preferencesSection: some View {
        Section {
            Toggle("Use Metric Units", isOn: $useMetricUnits)
            Toggle("Enable Notifications", isOn: $enableNotifications)
        } header: {
            Text("Preferences")
        }
        .listRowBackground(Color.cdCardBackground)
    }

    // MARK: - Demo Mode Section

    private var demoSection: some View {
        Section {
            Toggle("Demo Mode", isOn: $apiClient.isDemoMode)

            if apiClient.isDemoMode {
                Text("Demo mode uses simulated vehicle data and random diagnostic codes for testing.")
                    .font(.caption)
                    .foregroundStyle(Color.cdTextSecondary)
            }
        } header: {
            Text("Testing")
        } footer: {
            Text("Enable demo mode to test the app without a real OBD adapter.")
        }
        .listRowBackground(Color.cdCardBackground)
    }

    // MARK: - OBD Section

    private var obdSection: some View {
        Section {
            NavigationLink {
                TroubleshootingView()
            } label: {
                Label("Troubleshooting", systemImage: "wrench.and.screwdriver")
            }
        } header: {
            Text("OBD Adapter")
        }
        .listRowBackground(Color.cdCardBackground)
    }

    // MARK: - Account Section

    private var accountSection: some View {
        Section {
            NavigationLink {
                SubscriptionView()
            } label: {
                HStack {
                    Label("Subscription", systemImage: "creditcard")
                    Spacer()
                    Text("Active")
                        .font(.caption)
                        .foregroundStyle(Color.cdSuccess)
                }
            }

            Button(action: {}) {
                Label("Restore Purchases", systemImage: "arrow.clockwise")
            }
        } header: {
            Text("Account")
        }
        .listRowBackground(Color.cdCardBackground)
    }

    // MARK: - About Section

    private var aboutSection: some View {
        Section {
            HStack {
                Text("Version")
                Spacer()
                Text("1.0.0")
                    .foregroundStyle(Color.cdTextSecondary)
            }

            NavigationLink {
                AboutView()
            } label: {
                Label("About ClearDrive", systemImage: "info.circle")
            }

            Link(destination: URL(string: "mailto:support@cleardrive.app")!) {
                Label("Contact Support", systemImage: "envelope")
            }
        } header: {
            Text("About")
        }
        .listRowBackground(Color.cdCardBackground)
    }

    // MARK: - Actions

    private func testConnection() {
        isTestingConnection = true
        connectionResult = nil

        Task {
            do {
                let healthy = try await apiClient.checkHealth()
                await MainActor.run {
                    connectionResult = ConnectionTestResult(
                        success: healthy,
                        message: healthy ? "Connected to server" : "Server not responding"
                    )
                    isTestingConnection = false
                }
            } catch {
                await MainActor.run {
                    connectionResult = ConnectionTestResult(
                        success: false,
                        message: "Failed: \(error.localizedDescription)"
                    )
                    isTestingConnection = false
                }
            }
        }
    }
}

struct ConnectionTestResult {
    let success: Bool
    let message: String
}

// MARK: - Sub Views

struct TroubleshootingView: View {
    var body: some View {
        ZStack {
            Color.cdBackground
                .ignoresSafeArea()

            List {
                Section("Connection Issues") {
                    TroubleshootItem(
                        title: "Cannot connect to server",
                        solution: "Check that your server is running and you're on the same network. Verify the server URL in Settings."
                    )

                    TroubleshootItem(
                        title: "OBD adapter not connecting",
                        solution: "Ensure the OBD adapter is plugged into your car and the ignition is ON. Check that the adapter is connected to your server."
                    )

                    TroubleshootItem(
                        title: "No data received",
                        solution: "Turn your car ignition to ON (not just accessory). Wait 10-15 seconds after connecting for the ECU to respond."
                    )
                }
                .listRowBackground(Color.cdCardBackground)

                Section("Scan Issues") {
                    TroubleshootItem(
                        title: "AI diagnosis taking too long",
                        solution: "AI responses typically take 5-15 seconds. Check your internet connection if it takes longer."
                    )

                    TroubleshootItem(
                        title: "VIN not detected",
                        solution: "Not all vehicles support OBD VIN reading. You can enter your vehicle info manually instead."
                    )
                }
                .listRowBackground(Color.cdCardBackground)
            }
            .scrollContentBackground(.hidden)
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
                .foregroundStyle(Color.cdTextSecondary)
        }
        .padding(.vertical, 4)
    }
}

struct SubscriptionView: View {
    var body: some View {
        ZStack {
            Color.cdBackground
                .ignoresSafeArea()

            ScrollView {
                VStack(spacing: CDSpacing.large) {
                    // Status
                    VStack(spacing: CDSpacing.medium) {
                        ZStack {
                            Circle()
                                .fill(Color.cdSuccess.opacity(0.2))
                                .frame(width: 80, height: 80)
                                .blur(radius: 10)

                            Image(systemName: "checkmark.seal.fill")
                                .font(.system(size: 50))
                                .foregroundStyle(Color.cdSuccess)
                        }

                        Text("Active Subscription")
                            .font(.title2)
                            .fontWeight(.bold)

                        Text("$7.99/month")
                            .font(.headline)
                            .foregroundStyle(Color.cdTextSecondary)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(CDSpacing.xlarge)
                    .background(Color.cdCardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: 20))

                    // Features
                    VStack(alignment: .leading, spacing: CDSpacing.medium) {
                        Text("YOUR PLAN INCLUDES")
                            .font(.caption)
                            .fontWeight(.semibold)
                            .foregroundStyle(Color.cdTextSecondary)

                        featureRow("AI-Powered Diagnostics", icon: "brain")
                        featureRow("Unlimited Scans", icon: "infinity")
                        featureRow("Complete History", icon: "clock.fill")
                        featureRow("Cost Estimates", icon: "dollarsign.circle")
                    }
                    .padding(CDSpacing.medium)
                    .background(Color.cdCardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: 16))

                    Button("Manage Subscription") {}
                        .foregroundStyle(Color.cdPrimary)
                }
                .padding(CDSpacing.medium)
            }
        }
        .navigationTitle("Subscription")
    }

    private func featureRow(_ text: String, icon: String) -> some View {
        HStack(spacing: CDSpacing.medium) {
            Image(systemName: icon)
                .foregroundStyle(Color.cdPrimary)
                .frame(width: 24)
            Text(text)
                .font(.subheadline)
            Spacer()
            Image(systemName: "checkmark")
                .foregroundStyle(Color.cdSuccess)
        }
    }
}

struct AboutView: View {
    var body: some View {
        ZStack {
            Color.cdBackground
                .ignoresSafeArea()

            ScrollView {
                VStack(spacing: CDSpacing.large) {
                    ZStack {
                        GlowingArc(color: .cdPrimary, intensity: 0.5)
                            .scaleEffect(0.6)

                        Image(systemName: "car.circle.fill")
                            .font(.system(size: 80))
                            .foregroundStyle(Color.cdPrimary)
                    }
                    .frame(height: 150)

                    Text("ClearDrive")
                        .font(.largeTitle)
                        .fontWeight(.bold)

                    Text("AI-Powered Diagnostics")
                        .font(.headline)
                        .foregroundStyle(Color.cdTextSecondary)

                    Text("Version 1.0.0")
                        .font(.caption)
                        .foregroundStyle(Color.cdTextTertiary)

                    Divider()
                        .padding(.vertical)

                    Text("ClearDrive helps you understand your vehicle's health with AI-powered diagnostic explanations. Simply connect to your OBD adapter and scan for trouble codes.")
                        .font(.subheadline)
                        .foregroundStyle(Color.cdTextSecondary)
                        .multilineTextAlignment(.center)

                    Spacer(minLength: 50)
                }
                .padding(CDSpacing.large)
            }
        }
        .navigationTitle("About")
    }
}

#Preview {
    NavigationStack {
        SettingsView()
            .environmentObject(APIClient())
    }
    .preferredColorScheme(.dark)
}
