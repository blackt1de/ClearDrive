//
//  SettingsView.swift
//  ClearDrive
//
//  Settings tab - Preferences and account
//

import SwiftUI
import WebKit

// MARK: - In-App WebView

struct WebView: UIViewRepresentable {
    let url: URL

    func makeUIView(context: Context) -> WKWebView {
        let webView = WKWebView()
        webView.isOpaque = false
        webView.backgroundColor = .clear
        webView.scrollView.backgroundColor = .clear
        return webView
    }

    func updateUIView(_ webView: WKWebView, context: Context) {
        webView.load(URLRequest(url: url))
    }
}

struct LegalDocumentView: View {
    let title: String
    let url: URL

    var body: some View {
        WebView(url: url)
            .ignoresSafeArea(edges: .bottom)
            .navigationTitle(title)
            .navigationBarTitleDisplayMode(.inline)
    }
}

struct SettingsView: View {
    @EnvironmentObject var apiClient: APIClient
    @EnvironmentObject var vehicleStore: VehicleStore
    @AppStorage("useMetricUnits") private var useMetricUnits = false
    @AppStorage("enableNotifications") private var enableNotifications = true
    @State private var showingEmailCopied = false

    var body: some View {
        ZStack {
            Color.cdBackground
                .ignoresSafeArea()

            Form {
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
                    Text("Free Beta")
                        .font(.caption)
                        .fontWeight(.medium)
                        .foregroundStyle(Color.cdPrimary)
                }
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

            Button {
                let email = "support@cleardriveapp.com"
                if let url = URL(string: "mailto:\(email)"),
                   UIApplication.shared.canOpenURL(url) {
                    UIApplication.shared.open(url)
                } else {
                    // Can't open mail - copy email to clipboard
                    UIPasteboard.general.string = email
                    showingEmailCopied = true
                }
            } label: {
                Label("Contact Support", systemImage: "envelope")
            }
        } header: {
            Text("About")
        }
        .listRowBackground(Color.cdCardBackground)
        .alert("Email Copied", isPresented: $showingEmailCopied) {
            Button("OK", role: .cancel) { }
        } message: {
            Text("support@cleardriveapp.com has been copied to your clipboard.")
        }
    }

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
                        title: "OBD adapter not connecting",
                        solution: "Ensure the OBD adapter is plugged into your car's OBD-II port (usually under the dashboard) and the ignition is ON. Make sure Bluetooth is enabled on your device."
                    )

                    TroubleshootItem(
                        title: "No data received",
                        solution: "Turn your car ignition to ON (not just accessory mode). Wait 10-15 seconds after connecting for the ECU to initialize and respond."
                    )

                    TroubleshootItem(
                        title: "Bluetooth pairing issues",
                        solution: "Go to your device's Bluetooth settings and forget the OBD adapter, then pair it again. Some adapters require a PIN code (usually 1234 or 0000)."
                    )
                }
                .listRowBackground(Color.cdCardBackground)

                Section("Scan Issues") {
                    TroubleshootItem(
                        title: "AI diagnosis taking too long",
                        solution: "AI responses typically take 5-15 seconds. Check your internet connection if it takes longer. Try moving to an area with better cellular or WiFi signal."
                    )

                    TroubleshootItem(
                        title: "VIN not detected",
                        solution: "Not all vehicles support OBD VIN reading (especially pre-2008 models). You can enter your vehicle info manually instead."
                    )

                    TroubleshootItem(
                        title: "Some data not available",
                        solution: "Not all vehicles support every OBD-II parameter. Older vehicles may only support basic data like engine RPM and speed."
                    )
                }
                .listRowBackground(Color.cdCardBackground)

                Section("Live Data Issues") {
                    TroubleshootItem(
                        title: "RPM or speed showing incorrect values",
                        solution: "Ensure your vehicle is running (not just accessory mode). Some vehicles require the engine to be on for accurate readings."
                    )

                    TroubleshootItem(
                        title: "Fuel level not showing",
                        solution: "Fuel level (PID 012F) is not supported by all vehicles. This is a manufacturer-specific feature."
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
                    // Beta Status
                    VStack(spacing: CDSpacing.medium) {
                        ZStack {
                            Circle()
                                .fill(Color.cdPrimary.opacity(0.2))
                                .frame(width: 80, height: 80)
                                .blur(radius: 10)

                            Image(systemName: "star.fill")
                                .font(.system(size: 50))
                                .foregroundStyle(Color.cdPrimary)
                        }

                        Text("Beta Access")
                            .font(.title2)
                            .fontWeight(.bold)

                        Text("All Features Unlocked")
                            .font(.headline)
                            .foregroundStyle(Color.cdSuccess)
                    }
                    .frame(maxWidth: .infinity)
                    .padding(CDSpacing.xlarge)
                    .background(Color.cdCardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: 20))

                    // Beta Notice
                    VStack(spacing: CDSpacing.small) {
                        HStack {
                            Image(systemName: "info.circle.fill")
                                .foregroundStyle(Color.cdPrimary)
                            Text("Beta Program")
                                .font(.headline)
                        }

                        Text("ClearDrive is currently in beta testing. During this period, all premium features are temporarily free for all users. Thank you for helping us improve the app!")
                            .font(.subheadline)
                            .foregroundStyle(Color.cdTextSecondary)
                            .multilineTextAlignment(.center)
                    }
                    .padding(CDSpacing.medium)
                    .background(Color.cdPrimary.opacity(0.1))
                    .clipShape(RoundedRectangle(cornerRadius: 12))

                    // Features
                    VStack(alignment: .leading, spacing: CDSpacing.medium) {
                        Text("INCLUDED FEATURES")
                            .font(.caption)
                            .fontWeight(.semibold)
                            .foregroundStyle(Color.cdTextSecondary)

                        featureRow("AI-Powered Diagnostics", icon: "brain")
                        featureRow("Unlimited Scans", icon: "infinity")
                        featureRow("Complete Scan History", icon: "clock.fill")
                        featureRow("Repair Cost Estimates", icon: "dollarsign.circle")
                        featureRow("Live OBD Data", icon: "gauge.with.needle")
                        featureRow("Vehicle Image Library", icon: "photo")
                    }
                    .padding(CDSpacing.medium)
                    .background(Color.cdCardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: 16))
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

                    Text("AI-Powered Vehicle Diagnostics")
                        .font(.headline)
                        .foregroundStyle(Color.cdTextSecondary)

                    Text("Version 1.0.0 (Beta)")
                        .font(.caption)
                        .foregroundStyle(Color.cdTextTertiary)

                    Divider()
                        .padding(.vertical)

                    // Main description
                    VStack(alignment: .leading, spacing: CDSpacing.medium) {
                        aboutSection(
                            title: "What is ClearDrive?",
                            content: "ClearDrive is an intelligent vehicle diagnostic app that transforms complex OBD-II trouble codes into clear, understandable explanations. Using advanced AI technology, we help you understand exactly what's happening with your vehicle and what steps to take next."
                        )

                        aboutSection(
                            title: "How It Works",
                            content: "Simply connect your Bluetooth OBD-II adapter to your vehicle's diagnostic port, pair it with your phone, and let ClearDrive do the rest. Our app reads diagnostic trouble codes (DTCs) directly from your vehicle's computer and uses AI to provide detailed explanations, severity assessments, and estimated repair costs."
                        )

                        aboutSection(
                            title: "Key Features",
                            content: "Real-time live data monitoring including RPM, speed, coolant temperature, and fuel level. AI-powered diagnostic interpretations that explain issues in plain language. Comprehensive scan history to track your vehicle's health over time. Support for multiple vehicles with detailed specifications and images."
                        )

                        aboutSection(
                            title: "Compatible Vehicles",
                            content: "ClearDrive works with all OBD-II compliant vehicles, which includes most gasoline vehicles sold in the US since 1996 and diesel vehicles since 1997. Some features may vary depending on your specific vehicle's supported OBD-II protocols."
                        )
                    }
                    .padding(CDSpacing.medium)
                    .background(Color.cdCardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: 16))

                    // Links
                    VStack(spacing: CDSpacing.small) {
                        NavigationLink {
                            LegalDocumentView(
                                title: "Privacy Policy",
                                url: URL(string: "https://app.termly.io/policy-viewer/policy.html?policyUUID=77ebe3fd-30c3-42f8-a4f8-e3aaa220edd7")!
                            )
                        } label: {
                            HStack {
                                Text("Privacy Policy")
                                Spacer()
                                Image(systemName: "chevron.right")
                                    .font(.caption)
                            }
                            .foregroundStyle(Color.cdTextSecondary)
                        }

                        Divider()

                        NavigationLink {
                            LegalDocumentView(
                                title: "Terms of Service",
                                url: URL(string: "https://app.termly.io/policy-viewer/policy.html?policyUUID=c9d35c75-d9c6-4418-9114-98224bd9445b")!
                            )
                        } label: {
                            HStack {
                                Text("Terms of Service")
                                Spacer()
                                Image(systemName: "chevron.right")
                                    .font(.caption)
                            }
                            .foregroundStyle(Color.cdTextSecondary)
                        }
                    }
                    .padding(CDSpacing.medium)
                    .background(Color.cdCardBackground)
                    .clipShape(RoundedRectangle(cornerRadius: 16))

                    Spacer(minLength: 50)
                }
                .padding(CDSpacing.large)
            }
        }
        .navigationTitle("About")
    }

    private func aboutSection(title: String, content: String) -> some View {
        VStack(alignment: .leading, spacing: CDSpacing.small) {
            Text(title)
                .font(.headline)
                .foregroundStyle(Color.cdTextPrimary)
            Text(content)
                .font(.subheadline)
                .foregroundStyle(Color.cdTextSecondary)
        }
    }
}

#Preview {
    NavigationStack {
        SettingsView()
            .environmentObject(APIClient())
    }
    .preferredColorScheme(.dark)
}
