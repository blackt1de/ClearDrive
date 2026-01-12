import SwiftUI

struct ScanView: View {
    @EnvironmentObject var obdManager: OBDManager
    @EnvironmentObject var apiClient: APIClient

    @State private var year = ""
    @State private var make = ""
    @State private var model = ""
    @State private var selectedTrim: Trim?
    @State private var availableTrims: [Trim] = []

    @State private var isScanning = false
    @State private var scanResult: ScanResult?
    @State private var showingResults = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            ScrollView {
                VStack(spacing: 24) {
                    // Logo Header
                    VStack(spacing: 8) {
                        Image(systemName: "car.circle.fill")
                            .font(.system(size: 60))
                            .foregroundStyle(.green)
                            .shadow(color: .green.opacity(0.5), radius: 20)

                        Text("ClearDrive")
                            .font(.title)
                            .fontWeight(.bold)

                        Text("AI-Powered Car Diagnostics")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.top, 20)

                    // Vehicle Info Card
                    VStack(alignment: .leading, spacing: 16) {
                        Text("VEHICLE INFO")
                            .font(.caption)
                            .fontWeight(.semibold)
                            .foregroundStyle(.secondary)

                        HStack(spacing: 12) {
                            VehicleTextField(title: "Year", text: $year, placeholder: "2020")
                                .frame(width: 80)
                                .keyboardType(.numberPad)
                                .onChange(of: year) { _, _ in fetchTrims() }

                            VehicleTextField(title: "Make", text: $make, placeholder: "Honda")
                                .onChange(of: make) { _, _ in fetchTrims() }

                            VehicleTextField(title: "Model", text: $model, placeholder: "Civic")
                                .onChange(of: model) { _, _ in fetchTrims() }
                        }

                        if !availableTrims.isEmpty {
                            VStack(alignment: .leading, spacing: 8) {
                                Text("TRIM")
                                    .font(.caption2)
                                    .foregroundStyle(.secondary)

                                ScrollView(.horizontal, showsIndicators: false) {
                                    HStack(spacing: 8) {
                                        ForEach(availableTrims) { trim in
                                            TrimButton(
                                                trim: trim,
                                                isSelected: selectedTrim?.id == trim.id
                                            ) {
                                                selectedTrim = trim
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                    .padding(20)
                    .background(Color(.systemGray6).opacity(0.5))
                    .clipShape(RoundedRectangle(cornerRadius: 20))

                    // OBD Connection Status
                    OBDStatusCard(obdManager: obdManager)

                    // Scan Button
                    Button(action: startScan) {
                        HStack(spacing: 12) {
                            if isScanning {
                                ProgressView()
                                    .tint(.white)
                            } else {
                                Image(systemName: "magnifyingglass")
                            }
                            Text(isScanning ? "Scanning..." : "Scan Vehicle")
                                .fontWeight(.semibold)
                        }
                        .frame(maxWidth: .infinity)
                        .padding(.vertical, 16)
                        .background(
                            canScan ? Color.green : Color.gray
                        )
                        .foregroundStyle(.white)
                        .clipShape(RoundedRectangle(cornerRadius: 16))
                    }
                    .disabled(!canScan || isScanning)

                    if let error = errorMessage {
                        Text(error)
                            .font(.caption)
                            .foregroundStyle(.red)
                            .padding()
                            .background(Color.red.opacity(0.1))
                            .clipShape(RoundedRectangle(cornerRadius: 8))
                    }

                    Spacer(minLength: 50)
                }
                .padding()
            }
            .navigationTitle("")
            .navigationBarHidden(true)
            .background(Color(.systemBackground))
            .sheet(isPresented: $showingResults) {
                if let result = scanResult {
                    ResultsView(result: result)
                }
            }
        }
    }

    private var canScan: Bool {
        !year.isEmpty && !make.isEmpty && !model.isEmpty && obdManager.isConnected
    }

    private func fetchTrims() {
        guard year.count == 4, !make.isEmpty, !model.isEmpty else {
            availableTrims = []
            return
        }

        Task {
            do {
                let trims = try await apiClient.getTrims(year: year, make: make, model: model)
                await MainActor.run {
                    availableTrims = trims
                    selectedTrim = trims.first
                }
            } catch {
                print("Failed to fetch trims: \(error)")
            }
        }
    }

    private func startScan() {
        isScanning = true
        errorMessage = nil

        Task {
            do {
                // Read codes from OBD adapter
                let codes = try await obdManager.readDTCCodes()

                // Send to server for diagnosis
                let result = try await apiClient.diagnose(
                    year: year,
                    make: make,
                    model: model,
                    trim: selectedTrim?.name ?? "",
                    codes: codes
                )

                await MainActor.run {
                    scanResult = result
                    showingResults = true
                    isScanning = false
                }
            } catch {
                await MainActor.run {
                    errorMessage = error.localizedDescription
                    isScanning = false
                }
            }
        }
    }
}

struct VehicleTextField: View {
    let title: String
    @Binding var text: String
    let placeholder: String

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(title.uppercased())
                .font(.caption2)
                .foregroundStyle(.secondary)

            TextField(placeholder, text: $text)
                .textFieldStyle(.plain)
                .padding(12)
                .background(Color(.systemGray5))
                .clipShape(RoundedRectangle(cornerRadius: 12))
        }
    }
}

struct TrimButton: View {
    let trim: Trim
    let isSelected: Bool
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            Text(trim.name)
                .font(.caption)
                .fontWeight(isSelected ? .semibold : .regular)
                .padding(.horizontal, 12)
                .padding(.vertical, 8)
                .background(isSelected ? Color.green : Color(.systemGray5))
                .foregroundStyle(isSelected ? .white : .primary)
                .clipShape(Capsule())
        }
    }
}

struct OBDStatusCard: View {
    @ObservedObject var obdManager: OBDManager

    var body: some View {
        VStack(alignment: .leading, spacing: 12) {
            HStack {
                Text("OBD CONNECTION")
                    .font(.caption)
                    .fontWeight(.semibold)
                    .foregroundStyle(.secondary)

                Spacer()

                Circle()
                    .fill(obdManager.isConnected ? Color.green : Color.red)
                    .frame(width: 8, height: 8)

                Text(obdManager.isConnected ? "Connected" : "Disconnected")
                    .font(.caption)
                    .foregroundStyle(obdManager.isConnected ? .green : .red)
            }

            if !obdManager.isConnected {
                Button(action: { obdManager.startScanning() }) {
                    HStack {
                        Image(systemName: "antenna.radiowaves.left.and.right")
                        Text("Connect to OBD Adapter")
                    }
                    .font(.subheadline)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(Color.blue.opacity(0.2))
                    .foregroundStyle(.blue)
                    .clipShape(RoundedRectangle(cornerRadius: 12))
                }
            } else if let deviceName = obdManager.connectedDeviceName {
                HStack {
                    Image(systemName: "checkmark.circle.fill")
                        .foregroundStyle(.green)
                    Text(deviceName)
                        .font(.subheadline)

                    Spacer()

                    Button("Disconnect") {
                        obdManager.disconnect()
                    }
                    .font(.caption)
                    .foregroundStyle(.red)
                }
            }
        }
        .padding(20)
        .background(Color(.systemGray6).opacity(0.5))
        .clipShape(RoundedRectangle(cornerRadius: 20))
    }
}

#Preview {
    ScanView()
        .environmentObject(OBDManager())
        .environmentObject(APIClient())
}
