//
//  OBDConnectionView.swift
//  ClearDrive
//
//  Bluetooth OBD adapter discovery and connection
//

import SwiftUI

struct OBDConnectionView: View {
    @EnvironmentObject var obdManager: OBDManager
    @Environment(\.dismiss) private var dismiss

    @State private var isInitializing = false
    @State private var showError = false
    @State private var errorMessage = ""

    var body: some View {
        NavigationStack {
            ZStack {
                Color.cdBackground
                    .ignoresSafeArea()

                ScrollView {
                    VStack(spacing: CDSpacing.large) {
                        // Status header
                        statusHeader

                        // Connected device info
                        if obdManager.connectionState.isConnected {
                            connectedDeviceCard
                        }

                        // Device list or scanning
                        if !obdManager.connectionState.isConnected {
                            deviceListSection
                        }

                        // Instructions
                        instructionsCard
                    }
                    .padding(CDSpacing.medium)
                }
            }
            .navigationTitle("OBD Adapter")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                    .foregroundStyle(Color.cdPrimaryBright)
                }
            }
            .alert("Connection Error", isPresented: $showError) {
                Button("OK", role: .cancel) {}
            } message: {
                Text(errorMessage)
            }
        }
    }

    // MARK: - Status Header

    private var statusHeader: some View {
        VStack(spacing: CDSpacing.medium) {
            ZStack {
                Circle()
                    .fill(statusColor.opacity(0.15))
                    .frame(width: 100, height: 100)
                    .blur(radius: 15)

                Circle()
                    .fill(statusColor.opacity(0.1))
                    .frame(width: 80, height: 80)

                Image(systemName: statusIcon)
                    .font(.system(size: 36))
                    .foregroundStyle(statusColor)
            }

            Text(obdManager.connectionState.description)
                .font(.system(size: 18, weight: .semibold))
                .foregroundStyle(Color.cdTextPrimary)

            if obdManager.connectionState == .scanning {
                ProgressView()
                    .tint(Color.cdPrimaryBright)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CDSpacing.large)
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(Color.cdCardBackground)
        )
    }

    private var statusColor: Color {
        switch obdManager.connectionState {
        case .ready: return .cdSuccess
        case .connected: return .cdSuccess
        case .connecting, .scanning: return .cdWarning
        case .error: return .cdCritical
        case .disconnected: return .cdTextTertiary
        }
    }

    private var statusIcon: String {
        switch obdManager.connectionState {
        case .ready: return "checkmark.circle.fill"
        case .connected: return "link.circle.fill"
        case .connecting, .scanning: return "antenna.radiowaves.left.and.right"
        case .error: return "exclamationmark.triangle.fill"
        case .disconnected: return "antenna.radiowaves.left.and.right.slash"
        }
    }

    // MARK: - Connected Device Card

    private var connectedDeviceCard: some View {
        VStack(spacing: CDSpacing.medium) {
            if let device = obdManager.connectedDevice {
                HStack(spacing: CDSpacing.medium) {
                    ZStack {
                        Circle()
                            .fill(Color.cdSuccess.opacity(0.15))
                            .frame(width: 50, height: 50)

                        Image(systemName: "car.circle.fill")
                            .font(.system(size: 24))
                            .foregroundStyle(Color.cdSuccess)
                    }

                    VStack(alignment: .leading, spacing: 4) {
                        Text(device.name)
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(Color.cdTextPrimary)

                        Text("Signal: \(device.rssi) dBm")
                            .font(.system(size: 12))
                            .foregroundStyle(Color.cdTextSecondary)
                    }

                    Spacer()

                    if obdManager.connectionState == .connected && !isInitializing {
                        Button {
                            initializeAdapter()
                        } label: {
                            Text("Initialize")
                                .font(.system(size: 14, weight: .semibold))
                                .foregroundStyle(.white)
                                .padding(.horizontal, 16)
                                .padding(.vertical, 8)
                                .background(Color.cdPrimaryBright)
                                .clipShape(Capsule())
                        }
                    } else if isInitializing {
                        ProgressView()
                            .tint(Color.cdPrimaryBright)
                    }
                }
            }

            Button {
                obdManager.disconnect()
            } label: {
                HStack {
                    Image(systemName: "xmark.circle")
                    Text("Disconnect")
                }
                .font(.system(size: 14, weight: .medium))
                .foregroundStyle(Color.cdCritical)
            }
        }
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color.cdCardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(Color.cdSuccess.opacity(0.3), lineWidth: 1)
                )
        )
    }

    // MARK: - Device List Section

    private var deviceListSection: some View {
        VStack(spacing: CDSpacing.medium) {
            HStack {
                Text("Available Devices")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color.cdTextPrimary)

                Spacer()

                Button {
                    if obdManager.connectionState == .scanning {
                        obdManager.stopScanning()
                    } else {
                        obdManager.startScanning()
                    }
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: obdManager.connectionState == .scanning ? "stop.fill" : "arrow.clockwise")
                        Text(obdManager.connectionState == .scanning ? "Stop" : "Scan")
                    }
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color.cdPrimaryBright)
                }
            }

            if obdManager.discoveredDevices.isEmpty {
                VStack(spacing: CDSpacing.small) {
                    Image(systemName: "antenna.radiowaves.left.and.right.slash")
                        .font(.system(size: 32))
                        .foregroundStyle(Color.cdTextTertiary)

                    Text("No devices found")
                        .font(.system(size: 14))
                        .foregroundStyle(Color.cdTextSecondary)

                    Text("Make sure your OBD adapter is powered on")
                        .font(.system(size: 12))
                        .foregroundStyle(Color.cdTextTertiary)
                }
                .frame(maxWidth: .infinity)
                .padding(.vertical, CDSpacing.xlarge)
            } else {
                VStack(spacing: CDSpacing.small) {
                    ForEach(obdManager.discoveredDevices) { device in
                        DeviceRow(device: device) {
                            obdManager.connect(to: device)
                        }
                    }
                }
            }
        }
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color.cdCardBackground)
        )
    }

    // MARK: - Instructions Card

    private var instructionsCard: some View {
        VStack(alignment: .leading, spacing: CDSpacing.medium) {
            HStack(spacing: CDSpacing.small) {
                Image(systemName: "info.circle.fill")
                    .foregroundStyle(Color.cdPrimaryBright)
                Text("Setup Instructions")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color.cdTextPrimary)
            }

            VStack(alignment: .leading, spacing: CDSpacing.small) {
                instructionRow(number: 1, text: "Plug OBD adapter into your car's OBD-II port")
                instructionRow(number: 2, text: "Turn ignition to ON (engine can be off)")
                instructionRow(number: 3, text: "Wait for adapter's light to turn on")
                instructionRow(number: 4, text: "Tap 'Scan' above to find the adapter")
                instructionRow(number: 5, text: "Select your adapter from the list")
            }

            Text("The OBD-II port is usually under the dashboard near the steering wheel.")
                .font(.system(size: 12))
                .foregroundStyle(Color.cdTextTertiary)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color.cdPrimary.opacity(0.08))
        )
    }

    private func instructionRow(number: Int, text: String) -> some View {
        HStack(alignment: .top, spacing: CDSpacing.small) {
            ZStack {
                Circle()
                    .fill(Color.cdPrimary.opacity(0.2))
                    .frame(width: 22, height: 22)

                Text("\(number)")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(Color.cdPrimaryBright)
            }

            Text(text)
                .font(.system(size: 13))
                .foregroundStyle(Color.cdTextSecondary)
        }
    }

    // MARK: - Actions

    private func initializeAdapter() {
        isInitializing = true

        Task {
            let success = await obdManager.initializeAdapter()
            await MainActor.run {
                isInitializing = false
                if !success {
                    errorMessage = "Failed to initialize adapter. Please try reconnecting."
                    showError = true
                }
            }
        }
    }
}

// MARK: - Device Row

struct DeviceRow: View {
    let device: OBDDevice
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: CDSpacing.medium) {
                ZStack {
                    Circle()
                        .fill(device.isLikelyOBD ? Color.cdPrimary.opacity(0.15) : Color.cdCardBackgroundLight)
                        .frame(width: 44, height: 44)

                    Image(systemName: device.isLikelyOBD ? "car.fill" : "antenna.radiowaves.left.and.right")
                        .font(.system(size: 18))
                        .foregroundStyle(device.isLikelyOBD ? Color.cdPrimaryBright : Color.cdTextTertiary)
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text(device.name)
                        .font(.system(size: 15, weight: .medium))
                        .foregroundStyle(Color.cdTextPrimary)

                    HStack(spacing: 8) {
                        signalIndicator
                        if device.isLikelyOBD {
                            Text("OBD Adapter")
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(Color.cdPrimaryBright)
                                .padding(.horizontal, 6)
                                .padding(.vertical, 2)
                                .background(Color.cdPrimary.opacity(0.15))
                                .clipShape(RoundedRectangle(cornerRadius: 4))
                        }
                    }
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Color.cdTextTertiary)
            }
            .padding(CDSpacing.small)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(Color.cdCardBackgroundLight)
            )
        }
    }

    private var signalIndicator: some View {
        HStack(spacing: 2) {
            ForEach(0..<4) { index in
                RoundedRectangle(cornerRadius: 1)
                    .fill(signalColor(for: index))
                    .frame(width: 3, height: CGFloat(4 + index * 2))
            }
        }
    }

    private func signalColor(for bar: Int) -> Color {
        // RSSI typically ranges from -100 (weak) to -40 (strong)
        let strength: Int
        if device.rssi > -50 { strength = 4 }
        else if device.rssi > -60 { strength = 3 }
        else if device.rssi > -70 { strength = 2 }
        else if device.rssi > -80 { strength = 1 }
        else { strength = 0 }

        return bar < strength ? Color.cdSuccess : Color.cdTextTertiary.opacity(0.3)
    }
}

#Preview {
    OBDConnectionView()
        .environmentObject(OBDManager())
        .preferredColorScheme(.dark)
}
