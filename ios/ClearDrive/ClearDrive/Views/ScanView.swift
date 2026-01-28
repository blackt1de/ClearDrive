//
//  ScanView.swift
//  ClearDrive
//
//  OBD-first scan flow - auto-detects vehicle via VIN, falls back to manual entry
//

import SwiftUI

// Wrapper structs for sheet(item:) pattern - guarantees data is passed correctly
struct BodyStyleSheetData: Identifiable {
    let id = UUID()
    let trim: TrimOption
    let options: [BodyStyleOption]
}

struct TransmissionSheetData: Identifiable {
    let id = UUID()
    let trim: TrimOption
    let options: [TransmissionOption]
}

struct ColorSheetData: Identifiable {
    let id = UUID()
    let trim: TrimOption
    let transmission: TransmissionOption
    let colors: [TrimColor]
}

struct ScanView: View {
    @EnvironmentObject var apiClient: APIClient
    @EnvironmentObject var vehicleStore: VehicleStore
    @EnvironmentObject var obdManager: OBDManager

    @Binding var selectedVehicle: VehicleInfo?
    @Binding var selectedVehicleImage: String?
    @Binding var obdStatus: OBDConnectionStatus
    @Binding var lastScanResult: ScanResult?
    @Binding var liveData: LiveOBDData?

    // Scan state
    @State private var scanPhase: ScanPhase = .ready
    @State private var statusMessage = ""
    @State private var errorMessage: String?

    // Manual entry fallback
    @State private var showManualEntry = false
    @State private var year = ""
    @State private var make = ""
    @State private var model = ""

    // Trim selection
    @State private var trims: [TrimOption] = []
    @State private var selectedTrim: TrimOption?
    @State private var showTrimSheet = false

    // Body style selection - use wrapper for sheet(item:) pattern
    @State private var selectedBodyStyle: BodyStyleOption?
    @State private var bodyStyleSheetData: BodyStyleSheetData?

    // Transmission selection - use wrapper for sheet(item:) pattern
    @State private var selectedTransmission: TransmissionOption?
    @State private var transmissionSheetData: TransmissionSheetData?

    // Color selection - use wrapper for sheet(item:) pattern
    @State private var selectedColor: TrimColor?
    @State private var colorSheetData: ColorSheetData?

    // Results
    @State private var scanResult: ScanResult?
    @State private var showingResults = false

    // Detected vehicle from VIN
    @State private var detectedVehicle: VehicleInfo?

    // OBD Connection
    @State private var showOBDConnection = false
    @State private var readDTCs: [String] = []
    @State private var readVIN: String?

    enum ScanPhase {
        case ready
        case connecting
        case readingVIN
        case detectingVehicle
        case selectingTrim
        case scanning
        case complete
        case error
    }

    var body: some View {
        ZStack {
            // Smooth gradient background
            ZStack {
                Color.cdBackground

                LinearGradient(
                    stops: [
                        .init(color: Color(hex: "101513"), location: 0),
                        .init(color: Color(hex: "0B0E0C"), location: 0.25),
                        .init(color: Color.cdBackground, location: 0.5),
                        .init(color: Color(hex: "080A09"), location: 1.0)
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )

                // Ambient glow behind logo area
                RadialGradient(
                    stops: [
                        .init(color: Color.cdPrimaryBright.opacity(0.15), location: 0),
                        .init(color: Color.cdPrimary.opacity(0.06), location: 0.35),
                        .init(color: Color.clear, location: 0.7)
                    ],
                    center: .init(x: 0.5, y: 0.12),
                    startRadius: 30,
                    endRadius: 350
                )
            }
            .ignoresSafeArea()

            // Subtle top glow arc
            VStack {
                GlowingArc(color: .cdPrimaryBright, intensity: 0.3)
                    .offset(y: -100)
                Spacer()
            }
            .ignoresSafeArea()

            ScrollView(showsIndicators: false) {
                VStack(spacing: CDSpacing.xlarge) {
                    Spacer().frame(height: CDSpacing.large)

                    // Hero section
                    heroSection

                    // Main content based on mode
                    if apiClient.isDemoMode || showManualEntry {
                        manualEntrySection
                    } else {
                        obdScanSection
                    }

                    // Error display
                    if let error = errorMessage {
                        errorBanner(error)
                    }

                    Spacer().frame(height: 100)
                }
                .padding(.horizontal, CDSpacing.large)
            }
        }
        .sheet(isPresented: $showTrimSheet) {
            TrimSelectionSheet(
                trims: trims,
                selectedTrim: $selectedTrim,
                onSelect: { trim in
                    selectedTrim = trim
                    showTrimSheet = false
                    handleTrimSelected(trim)
                }
            )
        }
        .sheet(item: $bodyStyleSheetData) { data in
            let _ = print("[ScanView] Opening body style sheet via item pattern")
            let _ = print("[ScanView]   trim: \(data.trim.name)")
            let _ = print("[ScanView]   options count: \(data.options.count)")
            let _ = print("[ScanView]   options: \(data.options.map { $0.name })")
            BodyStyleSelectionSheet(
                options: data.options,
                selectedOption: $selectedBodyStyle,
                onSelect: { bodyStyle in
                    selectedBodyStyle = bodyStyle
                    bodyStyleSheetData = nil
                    handleBodyStyleSelected(bodyStyle, trim: data.trim)
                }
            )
        }
        .sheet(item: $transmissionSheetData) { data in
            let _ = print("[ScanView] Opening transmission sheet via item pattern")
            let _ = print("[ScanView]   options: \(data.options.map { $0.label })")
            TransmissionSelectionSheet(
                options: data.options,
                selectedOption: $selectedTransmission,
                onSelect: { transmission in
                    selectedTransmission = transmission
                    transmissionSheetData = nil
                    handleTransmissionSelected(transmission, trim: data.trim)
                }
            )
        }
        .sheet(item: $colorSheetData) { data in
            let _ = print("[ScanView] Opening color sheet via item pattern")
            let _ = print("[ScanView]   colors: \(data.colors.map { $0.name })")
            ColorSelectionSheet(
                colors: data.colors,
                selectedColor: $selectedColor,
                onSelect: { color in
                    selectedColor = color
                    colorSheetData = nil
                    handleColorSelected(color, trim: data.trim, transmission: data.transmission)
                },
                onSkip: {
                    colorSheetData = nil
                    handleColorSelected(nil, trim: data.trim, transmission: data.transmission)
                }
            )
        }
        .sheet(isPresented: $showingResults) {
            if let result = scanResult {
                ResultsView(result: result, liveData: liveData)
            }
        }
        .sheet(isPresented: $showOBDConnection) {
            OBDConnectionView()
        }
        .onAppear {
            // Pre-fill for demo mode
            if apiClient.isDemoMode && year.isEmpty {
                year = "2025"
                make = "Audi"
                model = "A4"
            }
        }
    }

    // MARK: - Hero Section

    private var heroSection: some View {
        VStack(spacing: CDSpacing.large) {
            // Animated car with glow
            ZStack {
                // Reflection/glow underneath
                Ellipse()
                    .fill(
                        RadialGradient(
                            colors: [
                                statusColor.opacity(0.3),
                                Color.clear
                            ],
                            center: .center,
                            startRadius: 20,
                            endRadius: 100
                        )
                    )
                    .frame(width: 200, height: 40)
                    .offset(y: 60)
                    .blur(radius: 10)

                Image(systemName: heroIcon)
                    .font(.system(size: 80))
                    .foregroundStyle(
                        LinearGradient(
                            colors: [
                                Color.cdTextPrimary,
                                Color.cdTextSecondary
                            ],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
                    .shadow(color: statusColor.opacity(0.3), radius: 30, y: 10)
            }
            .frame(height: 140)

            // Title with logo
            HStack(spacing: CDSpacing.small) {
                Image("Logo")
                    .resizable()
                    .aspectRatio(contentMode: .fit)
                    .frame(width: 44, height: 44)
                    .clipShape(RoundedRectangle(cornerRadius: 10))

                VStack(alignment: .leading, spacing: 2) {
                    Text("ClearDrive")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(Color.cdTextPrimary)

                    Text(heroSubtitle)
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(Color.cdTextTertiary)
                }
            }

            // Status pill
            statusPill
        }
    }

    private var heroIcon: String {
        switch scanPhase {
        case .connecting, .readingVIN, .detectingVehicle:
            return "antenna.radiowaves.left.and.right"
        case .scanning:
            return "magnifyingglass"
        case .complete:
            return "checkmark.circle.fill"
        case .error:
            return "exclamationmark.triangle.fill"
        default:
            return "car.side.fill"
        }
    }

    private var heroSubtitle: String {
        if apiClient.isDemoMode {
            return "Your Car's Best Friend"
        }
        switch scanPhase {
        case .ready: return "Your Car's Best Friend"
        case .connecting: return "Connecting to OBD..."
        case .readingVIN: return "Reading VIN..."
        case .detectingVehicle: return "Detecting Vehicle..."
        case .selectingTrim: return "Select Your Trim"
        case .scanning: return "Running Diagnostics..."
        case .complete: return "Your Car's Best Friend"
        case .error: return "Connection Issue"
        }
    }

    private var statusColor: Color {
        switch scanPhase {
        case .complete: return .cdSuccess
        case .error: return .cdCritical
        case .connecting, .readingVIN, .detectingVehicle, .scanning: return .cdWarning
        default: return .cdPrimaryBright
        }
    }

    private var statusPill: some View {
        HStack(spacing: 8) {
            Circle()
                .fill(obdStatusColor)
                .frame(width: 8, height: 8)

            Text(obdStatusText)
                .font(.system(size: 13, weight: .medium))
                .foregroundStyle(Color.cdTextSecondary)
        }
        .padding(.horizontal, 16)
        .padding(.vertical, 10)
        .background(Color.cdCardBackground)
        .clipShape(Capsule())
    }

    private var obdStatusColor: Color {
        if apiClient.isDemoMode { return .cdWarning }
        if obdManager.connectionState.isConnected { return .cdSuccess }
        return .cdTextTertiary
    }

    private var obdStatusText: String {
        if apiClient.isDemoMode { return "Demo Mode" }
        if obdManager.connectionState == .ready { return "OBD Ready" }
        if obdManager.connectionState.isConnected { return "OBD Connected" }
        return "OBD Not Connected"
    }

    // MARK: - OBD Scan Section

    private var obdScanSection: some View {
        VStack(spacing: CDSpacing.large) {
            // OBD Connection status card
            obdConnectionCard

            // Info card
            VStack(alignment: .leading, spacing: CDSpacing.medium) {
                HStack(spacing: CDSpacing.small) {
                    Image(systemName: "info.circle.fill")
                        .foregroundStyle(Color.cdPrimaryBright)
                    Text("How It Works")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Color.cdTextPrimary)
                }

                VStack(alignment: .leading, spacing: CDSpacing.small) {
                    stepRow(number: 1, text: "Connect Bluetooth OBD adapter")
                    stepRow(number: 2, text: "Tap 'Scan Vehicle' below")
                    stepRow(number: 3, text: "We read VIN & codes from your car")
                    stepRow(number: 4, text: "Get AI-powered diagnostics")
                }
            }
            .padding(CDSpacing.medium)
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(Color.cdCardBackground)
            )

            // Main scan button
            scanButton

            // Manual entry option
            Button {
                showManualEntry = true
            } label: {
                Text("Enter vehicle manually instead")
                    .font(.system(size: 14))
                    .foregroundStyle(Color.cdPrimaryBright)
            }
        }
    }

    private var obdConnectionCard: some View {
        Button {
            showOBDConnection = true
        } label: {
            HStack(spacing: CDSpacing.medium) {
                ZStack {
                    Circle()
                        .fill(obdManager.connectionState.isConnected ? Color.cdSuccess.opacity(0.15) : Color.cdPrimary.opacity(0.15))
                        .frame(width: 50, height: 50)

                    Image(systemName: obdManager.connectionState.isConnected ? "checkmark.circle.fill" : "antenna.radiowaves.left.and.right")
                        .font(.system(size: 22))
                        .foregroundStyle(obdManager.connectionState.isConnected ? Color.cdSuccess : Color.cdPrimaryBright)
                }

                VStack(alignment: .leading, spacing: 4) {
                    Text(obdManager.connectionState.isConnected ? "OBD Connected" : "Connect OBD Adapter")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(Color.cdTextPrimary)

                    if let device = obdManager.connectedDevice {
                        Text(device.name)
                            .font(.system(size: 13))
                            .foregroundStyle(Color.cdSuccess)
                    } else {
                        Text("Tap to connect your Bluetooth adapter")
                            .font(.system(size: 13))
                            .foregroundStyle(Color.cdTextSecondary)
                    }
                }

                Spacer()

                Image(systemName: "chevron.right")
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color.cdTextTertiary)
            }
            .padding(CDSpacing.medium)
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(Color.cdCardBackground)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16)
                            .stroke(obdManager.connectionState.isConnected ? Color.cdSuccess.opacity(0.3) : Color.cdPrimary.opacity(0.2), lineWidth: 1)
                    )
            )
        }
    }

    private func stepRow(number: Int, text: String) -> some View {
        HStack(spacing: CDSpacing.small) {
            ZStack {
                Circle()
                    .fill(Color.cdPrimary.opacity(0.2))
                    .frame(width: 24, height: 24)
                Text("\(number)")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color.cdPrimaryBright)
            }
            Text(text)
                .font(.system(size: 14))
                .foregroundStyle(Color.cdTextSecondary)
        }
    }

    // MARK: - Manual Entry Section

    private var manualEntrySection: some View {
        VStack(spacing: CDSpacing.medium) {
            if !apiClient.isDemoMode {
                // Back to OBD button
                Button {
                    showManualEntry = false
                    errorMessage = nil
                } label: {
                    HStack(spacing: 6) {
                        Image(systemName: "arrow.left")
                        Text("Back to OBD Scan")
                    }
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(Color.cdPrimaryBright)
                }
            }

            SectionHeader(title: "Vehicle Information")

            HStack(spacing: CDSpacing.small) {
                inputField(label: "Year", text: $year, placeholder: "2025", keyboardType: .numberPad)
                    .frame(width: 80)
                inputField(label: "Make", text: $make, placeholder: "Audi")
                inputField(label: "Model", text: $model, placeholder: "A4")
            }

            manualScanButton
        }
    }

    private func inputField(label: String, text: Binding<String>, placeholder: String, keyboardType: UIKeyboardType = .default) -> some View {
        VStack(alignment: .leading, spacing: 6) {
            Text(label.uppercased())
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(Color.cdTextTertiary)
                .tracking(0.5)

            TextField(placeholder, text: text)
                .keyboardType(keyboardType)
                .font(.system(size: 16, weight: .medium))
                .foregroundStyle(Color.cdTextPrimary)
                .padding(.horizontal, 14)
                .padding(.vertical, 14)
                .background(Color.cdCardBackground)
                .clipShape(RoundedRectangle(cornerRadius: 12))
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.cdPrimary.opacity(0.2), lineWidth: 1)
                )
        }
    }

    // MARK: - Buttons

    private var scanButton: some View {
        LuxuryButton(
            scanButtonTitle,
            icon: scanButtonIcon,
            isLoading: isScanning
        ) {
            startOBDScan()
        }
        .disabled(isScanning)
        .padding(.top, CDSpacing.medium)
    }

    private var scanButtonTitle: String {
        switch scanPhase {
        case .connecting: return "Connecting..."
        case .readingVIN: return "Reading VIN..."
        case .detectingVehicle: return "Detecting..."
        case .scanning: return "Analyzing..."
        default: return "Scan Vehicle"
        }
    }

    private var scanButtonIcon: String? {
        isScanning ? nil : "magnifyingglass"
    }

    private var isScanning: Bool {
        switch scanPhase {
        case .connecting, .readingVIN, .detectingVehicle, .scanning:
            return true
        default:
            return false
        }
    }

    private var manualScanButton: some View {
        LuxuryButton(
            manualButtonTitle,
            icon: isLoadingTrims ? nil : "magnifyingglass",
            isLoading: isLoadingTrims || scanPhase == .scanning
        ) {
            findTrims()
        }
        .disabled(year.isEmpty || make.isEmpty || model.isEmpty || isLoadingTrims || scanPhase == .scanning)
        .opacity(year.isEmpty || make.isEmpty || model.isEmpty ? 0.5 : 1)
        .padding(.top, CDSpacing.medium)
    }

    @State private var isLoadingTrims = false

    private var manualButtonTitle: String {
        if isLoadingTrims { return "Finding Trims..." }
        if scanPhase == .scanning { return "Analyzing..." }
        return "Find My Vehicle"
    }

    // MARK: - Error Banner

    private func errorBanner(_ message: String) -> some View {
        HStack(spacing: CDSpacing.small) {
            Image(systemName: "exclamationmark.triangle.fill")
                .foregroundStyle(Color.cdWarning)

            Text(message)
                .font(.system(size: 13))
                .foregroundStyle(Color.cdTextPrimary)
                .multilineTextAlignment(.leading)

            Spacer()

            Button {
                errorMessage = nil
            } label: {
                Image(systemName: "xmark")
                    .font(.system(size: 12, weight: .bold))
                    .foregroundStyle(Color.cdTextTertiary)
            }
        }
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.cdWarning.opacity(0.1))
                .overlay(
                    RoundedRectangle(cornerRadius: 12)
                        .stroke(Color.cdWarning.opacity(0.3), lineWidth: 1)
                )
        )
    }

    // MARK: - OBD Scan Flow

    private func startOBDScan() {
        errorMessage = nil

        // Check if OBD adapter is connected via Bluetooth
        guard obdManager.connectionState == .ready else {
            if obdManager.connectionState.isConnected {
                // Connected but not initialized
                errorMessage = "Please initialize the OBD adapter first"
            } else {
                // Not connected at all
                errorMessage = "Please connect to your OBD adapter first"
                showOBDConnection = true
            }
            return
        }

        scanPhase = .readingVIN

        Task {
            // Step 1: Read VIN from local OBD
            let vin = await obdManager.readVIN()

            if let vin = vin {
                await MainActor.run {
                    readVIN = vin
                    scanPhase = .detectingVehicle
                }

                // Step 2: Decode VIN via server - VIN gives us everything we need
                do {
                    let vehicleInfo = try await apiClient.decodeVIN(vin)

                    await MainActor.run {
                        detectedVehicle = vehicleInfo
                    }

                    print("[ScanView] VIN decoded: \(vehicleInfo.displayName)")
                    print("  - trim: \(vehicleInfo.trim ?? "nil")")
                    print("  - engine: \(vehicleInfo.engine ?? "nil")")
                    print("  - drive: \(vehicleInfo.driveType ?? "nil")")
                    print("  - transmission: \(vehicleInfo.transmission ?? "nil")")

                    // Check if VIN gave us the critical diagnostic info (engine matters most)
                    let hasEngine = vehicleInfo.engine != nil && !vehicleInfo.engine!.isEmpty

                    // Always fetch trims to get color options for image matching
                    print("[ScanView] Fetching trims to get color options...")
                    let fetchedTrims = try await apiClient.getTrims(
                        year: vehicleInfo.year,
                        make: vehicleInfo.make,
                        model: vehicleInfo.model
                    )

                    // Find colors from trims
                    let availableColors = fetchedTrims.first?.colorsExterior ?? []
                    print("[ScanView] Found \(availableColors.count) exterior colors")

                    if hasEngine {
                        // VIN gave us engine - check if we need transmission or color selection
                        await MainActor.run {
                            selectedVehicle = vehicleInfo
                            year = vehicleInfo.year
                            make = vehicleInfo.make
                            model = vehicleInfo.model

                            if let firstTrim = fetchedTrims.first {
                                // Check if trim has multiple transmission options
                                if firstTrim.transmissionOptions.count > 1 {
                                    print("[ScanView] VIN scan: showing transmission selection (\(firstTrim.transmissionOptions.count) options)")
                                    transmissionSheetData = TransmissionSheetData(trim: firstTrim, options: firstTrim.transmissionOptions)
                                } else if !availableColors.isEmpty {
                                    // No transmission choice needed - show color selection
                                    let trans = firstTrim.transmissionOptions.first ?? TransmissionOption(name: vehicleInfo.transmission ?? "", label: vehicleInfo.transmission ?? "")
                                    selectedTransmission = trans
                                    colorSheetData = ColorSheetData(
                                        trim: firstTrim,
                                        transmission: trans,
                                        colors: availableColors
                                    )
                                } else {
                                    // No transmission or color choice - proceed directly
                                    if let trans = firstTrim.transmissionOptions.first {
                                        selectedTransmission = trans
                                    }
                                    runLocalOBDDiagnostic(vehicle: vehicleInfo, trimId: firstTrim.id)
                                }
                            } else {
                                // No trims fetched - proceed directly
                                runLocalOBDDiagnostic(vehicle: vehicleInfo, trimId: nil)
                            }
                        }
                    } else {
                        // VIN missing engine info - need to ask user to pick trim
                        print("[ScanView] VIN missing engine - need trim selection")

                        await MainActor.run {
                            if fetchedTrims.isEmpty {
                                // No trims available - just use what we have
                                selectedVehicle = vehicleInfo
                                runLocalOBDDiagnostic(vehicle: vehicleInfo, trimId: nil)
                            } else if fetchedTrims.count == 1 {
                                // Only one trim - use it but still ask for color
                                var vehicle = vehicleInfo
                                vehicle.engine = fetchedTrims[0].engine ?? vehicleInfo.engine
                                selectedVehicle = vehicle
                                year = vehicleInfo.year
                                make = vehicleInfo.make
                                model = vehicleInfo.model

                                if !fetchedTrims[0].colorsExterior.isEmpty {
                                    colorSheetData = ColorSheetData(
                                        trim: fetchedTrims[0],
                                        transmission: TransmissionOption(name: vehicle.transmission ?? "", label: vehicle.transmission ?? ""),
                                        colors: fetchedTrims[0].colorsExterior
                                    )
                                } else {
                                    runLocalOBDDiagnostic(vehicle: vehicle, trimId: fetchedTrims[0].id)
                                }
                            } else {
                                // Multiple trims - ask user
                                trims = fetchedTrims
                                year = vehicleInfo.year
                                make = vehicleInfo.make
                                model = vehicleInfo.model
                                scanPhase = .selectingTrim
                                showTrimSheet = true
                            }
                        }
                    }
                } catch {
                    print("[ScanView] VIN decode error: \(error)")
                    await MainActor.run {
                        scanPhase = .error
                        errorMessage = "Could not decode VIN. Please enter your vehicle manually."
                        showManualEntry = true
                    }
                }
            } else {
                // VIN read failed - fall back to manual
                await MainActor.run {
                    scanPhase = .error
                    errorMessage = "Could not read VIN from vehicle. Please enter your vehicle information manually."
                    showManualEntry = true
                }
            }
        }
    }

    /// Run diagnostic using locally-read OBD data
    private func runLocalOBDDiagnostic(vehicle: VehicleInfo, trimId: String?, color: String? = nil) {
        scanPhase = .scanning

        Task {
            // Step 1: Read DTCs from local OBD
            let dtcs = await obdManager.readDTCs()
            let pendingDtcs = await obdManager.readPendingDTCs()
            let allCodes = Array(Set(dtcs + pendingDtcs)) // Deduplicate

            // Step 2: Read live data
            let liveData = await obdManager.readLiveData()

            await MainActor.run {
                readDTCs = allCodes
            }

            // Step 3: Send to server for AI interpretation
            do {
                let result = try await apiClient.interpretOBDData(
                    vehicle: vehicle,
                    trimId: trimId,
                    codes: allCodes,
                    rpm: liveData.rpm,
                    speed: liveData.speed,
                    coolantTemp: liveData.coolant,
                    color: color,
                    transmission: selectedTransmission?.name
                )
                print("[ScanView] Local OBD diagnostic complete!")
                print("  - vehicleImageURL: \(result.vehicleImageURL ?? "nil")")
                print("  - dontPanic: \(result.dontPanic?.prefix(50) ?? "nil")...")

                await MainActor.run {
                    print("[ScanView] Setting state on MainActor (local OBD)...")
                    scanResult = result
                    lastScanResult = result
                    selectedVehicleImage = result.vehicleImageURL
                    print("[ScanView] selectedVehicleImage set to: \(selectedVehicleImage ?? "nil")")

                    vehicleStore.saveVehicle(
                        vehicle,
                        imageURL: result.vehicleImageURL,
                        trimId: trimId,
                        scanResult: result
                    )
                    vehicleStore.addScanResult(result)

                    scanPhase = .complete
                    showingResults = true
                }
            } catch {
                await MainActor.run {
                    scanPhase = .error
                    errorMessage = "Diagnostic failed: \(error.localizedDescription)"
                }
            }
        }
    }

    private func runDiagnosticWithDetectedVehicle(_ vehicle: VehicleInfo, trimId: String?) {
        // Use local OBD reading if connected, otherwise fall back to server
        if obdManager.connectionState == .ready {
            runLocalOBDDiagnostic(vehicle: vehicle, trimId: trimId)
        } else {
            // Fall back to server-based scan (demo mode or manual entry)
            runServerDiagnostic(vehicle: vehicle, trimId: trimId, transmission: selectedTransmission?.name)
        }
    }

    /// Run diagnostic using server-side OBD reading (for demo mode or when local OBD not available)
    private func runServerDiagnostic(vehicle: VehicleInfo, trimId: String?, color: String? = nil, transmission: String? = nil) {
        scanPhase = .scanning

        Task {
            do {
                let result = try await apiClient.performFullScan(vehicle: vehicle, trimId: trimId, color: color, transmission: transmission)
                print("[ScanView] Server diagnostic complete!")
                print("  - vehicleImageURL: \(result.vehicleImageURL ?? "nil")")
                print("  - dontPanic: \(result.dontPanic?.prefix(50) ?? "nil")...")

                await MainActor.run {
                    print("[ScanView] Setting state on MainActor...")
                    scanResult = result
                    lastScanResult = result
                    selectedVehicleImage = result.vehicleImageURL
                    print("[ScanView] selectedVehicleImage set to: \(selectedVehicleImage ?? "nil")")

                    vehicleStore.saveVehicle(
                        vehicle,
                        imageURL: result.vehicleImageURL,
                        trimId: trimId,
                        scanResult: result
                    )
                    vehicleStore.addScanResult(result)

                    scanPhase = .complete
                    showingResults = true
                }
            } catch {
                await MainActor.run {
                    scanPhase = .error
                    errorMessage = "Diagnostic failed: \(error.localizedDescription)"
                }
            }
        }
    }

    // MARK: - Manual Entry Flow

    private func findTrims() {
        guard !year.isEmpty, !make.isEmpty, !model.isEmpty else {
            errorMessage = "Please enter year, make, and model"
            return
        }

        isLoadingTrims = true
        errorMessage = nil

        Task {
            do {
                let fetchedTrims = try await apiClient.getTrims(year: year, make: make, model: model)
                await MainActor.run {
                    isLoadingTrims = false
                    if fetchedTrims.isEmpty {
                        errorMessage = "No trims found for \(year) \(make) \(model)"
                    } else {
                        trims = fetchedTrims
                        showTrimSheet = true
                    }
                }
            } catch {
                await MainActor.run {
                    isLoadingTrims = false
                    errorMessage = "Error: \(error.localizedDescription)"
                }
            }
        }
    }

    private func runDiagnosticWithTrim(_ trim: TrimOption) {
        let vehicle = VehicleInfo(
            year: year,
            make: make,
            model: model,
            trim: trim.name,
            engine: trim.engine,
            fuelType: trim.fuelType,
            driveType: trim.driveType,
            transmission: trim.transmission,
            bodyStyle: selectedBodyStyle?.name ?? trim.bodyStyle,
            horsepower: trim.horsepower,
            torque: trim.torque,
            mpgCity: trim.mpgCity,
            mpgHighway: trim.mpgHighway,
            mpgCombined: trim.mpgCombined,
            tankCapacity: trim.tankCapacity,
            colorsExterior: trim.colorsExterior.map { VehicleColor(name: $0.name, rgb: $0.rgb) },
            colorsInterior: trim.colorsInterior.map { VehicleColor(name: $0.name, rgb: $0.rgb) },
            isTruck: trim.isTruck,
            isElectric: trim.isElectric,
            isPluginHybrid: trim.isPluginHybrid
        )
        selectedVehicle = vehicle
        errorMessage = nil

        // Use local OBD if connected, otherwise use server
        if obdManager.connectionState == .ready {
            runLocalOBDDiagnostic(vehicle: vehicle, trimId: trim.id)
        } else {
            runServerDiagnostic(vehicle: vehicle, trimId: trim.id, transmission: selectedTransmission?.name)
        }
    }

    // MARK: - Manual Entry Selection Handlers

    /// Called when user selects a trim in manual entry mode
    private func handleTrimSelected(_ trim: TrimOption) {
        print("[ScanView] handleTrimSelected: \(trim.name)")
        print("  - hasBodyStyleChoice: \(trim.hasBodyStyleChoice)")
        print("  - bodyStyleOptions count: \(trim.bodyStyleOptions.count)")
        print("  - bodyStyleOptions: \(trim.bodyStyleOptions.map { $0.name })")
        print("  - hasTransmissionChoice: \(trim.hasTransmissionChoice)")
        print("  - transmissionOptions: \(trim.transmissionOptions.map { $0.name })")
        print("  - trim.transmission: \(trim.transmission ?? "nil")")

        // Store selected trim
        selectedTrim = trim

        // Check if this trim has body style choice (like web frontend)
        if trim.hasBodyStyleChoice && !trim.bodyStyleOptions.isEmpty {
            print("[ScanView] Creating body style sheet data with \(trim.bodyStyleOptions.count) options")
            // Use sheet(item:) pattern - pass data directly to guarantee it's available
            bodyStyleSheetData = BodyStyleSheetData(trim: trim, options: trim.bodyStyleOptions)
            return
        }

        // No body style choice - go directly to transmission selection
        showTransmissionSelectionOrProceed(for: trim)
    }

    /// Determines whether to show transmission selection or proceed with scan
    /// Trusts CarsXE data - only prompts if multiple options available
    private func showTransmissionSelectionOrProceed(for trim: TrimOption) {
        print("[ScanView] showTransmissionSelectionOrProceed called for trim: \(trim.name)")
        print("  - transmissionOptions.count: \(trim.transmissionOptions.count)")
        print("  - transmissionOptions: \(trim.transmissionOptions.map { $0.name })")
        print("  - trim.transmission: \(trim.transmission ?? "nil")")
        print("  - hasTransmissionChoice: \(trim.hasTransmissionChoice)")

        // If CarsXE provides multiple transmission options, show selection
        if trim.transmissionOptions.count > 1 {
            print("[ScanView] CarsXE has \(trim.transmissionOptions.count) transmission options - showing selection")
            transmissionSheetData = TransmissionSheetData(trim: trim, options: trim.transmissionOptions)
            return
        }

        // If CarsXE provides exactly one option, use it (car only has one transmission)
        if trim.transmissionOptions.count == 1 {
            print("[ScanView] CarsXE has 1 transmission option - using: \(trim.transmissionOptions[0].name)")
            selectedTransmission = trim.transmissionOptions[0]
            handleTransmissionSelected(trim.transmissionOptions[0], trim: trim)
            return
        }

        // No transmission options array - use trim's transmission field if available
        if let trimTrans = trim.transmission, !trimTrans.isEmpty {
            print("[ScanView] Using trim's transmission field: \(trimTrans)")
            let transOption = TransmissionOption(name: trimTrans, label: trimTrans)
            selectedTransmission = transOption
            handleTransmissionSelected(transOption, trim: trim)
            return
        }

        // No transmission info from CarsXE - proceed without (will use vehicle default)
        print("[ScanView] No transmission info from CarsXE - proceeding without")
        handleTransmissionSelected(TransmissionOption(name: "", label: ""), trim: trim)
    }

    /// Called when user selects a body style in manual entry mode
    private func handleBodyStyleSelected(_ bodyStyle: BodyStyleOption, trim: TrimOption) {
        // Delay to allow body style sheet to fully dismiss before showing transmission sheet
        DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
            self.showTransmissionSelectionOrProceed(for: trim)
        }
    }

    /// Called when user selects a transmission in manual entry mode
    private func handleTransmissionSelected(_ transmission: TransmissionOption, trim: TrimOption) {
        print("[ScanView] handleTransmissionSelected")
        print("  - year: '\(year)', make: '\(make)', model: '\(model)'")
        print("  - trim: '\(trim.name)', trimId: '\(trim.id)'")
        print("  - transmission: '\(transmission.name)'")
        print("  - colorsExterior count: \(trim.colorsExterior.count)")

        // Check if we have exterior colors to show - offer color selection
        if !trim.colorsExterior.isEmpty {
            print("[ScanView] Showing color selection with \(trim.colorsExterior.count) colors")
            // Delay to allow transmission sheet to fully dismiss
            DispatchQueue.main.asyncAfter(deadline: .now() + 0.4) {
                self.colorSheetData = ColorSheetData(
                    trim: trim,
                    transmission: transmission,
                    colors: trim.colorsExterior
                )
            }
            return
        }

        // No colors available - proceed directly to scan
        handleColorSelected(nil, trim: trim, transmission: transmission)
    }

    /// Called when user selects a color (or skips) - works for both VIN decode and manual entry flows
    private func handleColorSelected(_ color: TrimColor?, trim: TrimOption, transmission: TransmissionOption) {
        print("[ScanView] handleColorSelected")
        print("  - color: \(color?.name ?? "none/skipped")")

        // Use VIN-decoded vehicle ONLY if it matches the current scan's year/make/model
        // Otherwise use trim data (manual entry flow)
        let vehicle: VehicleInfo
        let isVINFlow = selectedVehicle != nil &&
            selectedVehicle?.year == year &&
            selectedVehicle?.make.lowercased() == make.lowercased() &&
            selectedVehicle?.model.lowercased() == model.lowercased()

        if isVINFlow, let existingVehicle = selectedVehicle {
            // VIN decode flow - use the VIN-decoded vehicle, just update colors
            vehicle = VehicleInfo(
                year: existingVehicle.year,
                make: existingVehicle.make,
                model: existingVehicle.model,
                trim: existingVehicle.trim ?? trim.name,
                engine: existingVehicle.engine ?? trim.engine,
                fuelType: existingVehicle.fuelType ?? trim.fuelType,
                driveType: existingVehicle.driveType ?? trim.driveType,
                transmission: existingVehicle.transmission ?? transmission.name,
                bodyStyle: existingVehicle.bodyStyle ?? selectedBodyStyle?.name ?? trim.bodyStyle,
                horsepower: existingVehicle.horsepower ?? trim.horsepower,
                torque: existingVehicle.torque ?? trim.torque,
                mpgCity: existingVehicle.mpgCity ?? trim.mpgCity,
                mpgHighway: existingVehicle.mpgHighway ?? trim.mpgHighway,
                mpgCombined: existingVehicle.mpgCombined ?? trim.mpgCombined,
                tankCapacity: existingVehicle.tankCapacity ?? trim.tankCapacity,
                colorsExterior: trim.colorsExterior.map { VehicleColor(name: $0.name, rgb: $0.rgb) },
                colorsInterior: trim.colorsInterior.map { VehicleColor(name: $0.name, rgb: $0.rgb) },
                isTruck: trim.isTruck,
                isElectric: trim.isElectric,
                isPluginHybrid: trim.isPluginHybrid
            )
            print("[ScanView] Using VIN-decoded vehicle: \(vehicle.displayName)")
        } else {
            // Manual entry flow - create vehicle from trim data
            vehicle = VehicleInfo(
                year: year,
                make: make,
                model: model,
                trim: trim.name,
                engine: trim.engine,
                fuelType: trim.fuelType,
                driveType: trim.driveType,
                transmission: transmission.name,
                bodyStyle: selectedBodyStyle?.name ?? trim.bodyStyle,
                horsepower: trim.horsepower,
                torque: trim.torque,
                mpgCity: trim.mpgCity,
                mpgHighway: trim.mpgHighway,
                mpgCombined: trim.mpgCombined,
                tankCapacity: trim.tankCapacity,
                colorsExterior: trim.colorsExterior.map { VehicleColor(name: $0.name, rgb: $0.rgb) },
                colorsInterior: trim.colorsInterior.map { VehicleColor(name: $0.name, rgb: $0.rgb) },
                isTruck: trim.isTruck,
                isElectric: trim.isElectric,
                isPluginHybrid: trim.isPluginHybrid
            )
            print("[ScanView] Created vehicle from manual entry: \(vehicle.displayName)")
        }

        print("  - engine: \(vehicle.engine ?? "nil")")
        print("  - transmission: \(vehicle.transmission ?? "nil")")

        selectedVehicle = vehicle
        selectedColor = color
        errorMessage = nil

        // Use local OBD if connected, otherwise use server
        // Pass selected color for image lookup
        if obdManager.connectionState == .ready {
            runLocalOBDDiagnostic(vehicle: vehicle, trimId: trim.id, color: color?.name)
        } else {
            runServerDiagnostic(vehicle: vehicle, trimId: trim.id, color: color?.name, transmission: selectedTransmission?.name)
        }
    }
}

// MARK: - Trim Selection Sheet

struct TrimSelectionSheet: View {
    let trims: [TrimOption]
    @Binding var selectedTrim: TrimOption?
    let onSelect: (TrimOption) -> Void

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                Color.cdBackground
                    .ignoresSafeArea()

                ScrollView {
                    VStack(spacing: CDSpacing.medium) {
                        // Info banner
                        HStack(spacing: CDSpacing.small) {
                            Image(systemName: "info.circle.fill")
                                .foregroundStyle(Color.cdPrimaryBright)
                            Text("Select your trim for accurate diagnostics")
                                .font(.system(size: 13))
                                .foregroundStyle(Color.cdTextSecondary)
                        }
                        .padding(CDSpacing.medium)
                        .frame(maxWidth: .infinity)
                        .background(Color.cdPrimary.opacity(0.1))
                        .clipShape(RoundedRectangle(cornerRadius: 12))

                        // Trim options
                        ForEach(trims) { trim in
                            TrimRow(
                                trim: trim,
                                isSelected: selectedTrim?.id == trim.id
                            ) {
                                onSelect(trim)
                            }
                        }
                    }
                    .padding(CDSpacing.medium)
                }
            }
            .navigationTitle("Select Trim")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                    .foregroundStyle(Color.cdTextSecondary)
                }
            }
        }
    }
}

struct TrimRow: View {
    let trim: TrimOption
    let isSelected: Bool
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack {
                VStack(alignment: .leading, spacing: 4) {
                    Text(trim.name)
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(Color.cdTextPrimary)

                    if let engine = trim.engine {
                        Text(engine)
                            .font(.system(size: 13))
                            .foregroundStyle(Color.cdTextSecondary)
                    }
                }

                Spacer()

                if isSelected {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 20))
                        .foregroundStyle(Color.cdPrimaryBright)
                }
            }
            .padding(CDSpacing.medium)
            .background(
                RoundedRectangle(cornerRadius: 14)
                    .fill(isSelected ? Color.cdPrimary.opacity(0.15) : Color.cdCardBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 14)
                    .stroke(
                        isSelected ? Color.cdPrimaryBright.opacity(0.5) : Color.cdPrimary.opacity(0.1),
                        lineWidth: isSelected ? 1.5 : 1
                    )
            )
        }
    }
}

// MARK: - Body Style Selection Sheet

struct BodyStyleSelectionSheet: View {
    let options: [BodyStyleOption]
    @Binding var selectedOption: BodyStyleOption?
    let onSelect: (BodyStyleOption) -> Void

    @Environment(\.dismiss) private var dismiss

    init(options: [BodyStyleOption], selectedOption: Binding<BodyStyleOption?>, onSelect: @escaping (BodyStyleOption) -> Void) {
        self.options = options
        self._selectedOption = selectedOption
        self.onSelect = onSelect
        print("[BodyStyleSelectionSheet] Initialized with \(options.count) options: \(options.map { $0.name })")
    }

    var body: some View {
        let _ = print("[BodyStyleSelectionSheet] Rendering body with \(options.count) options")
        NavigationStack {
            ZStack {
                Color.cdBackground
                    .ignoresSafeArea()

                ScrollView {
                    VStack(spacing: CDSpacing.medium) {
                        // Info banner
                        HStack(spacing: CDSpacing.small) {
                            Image(systemName: "car.side.fill")
                                .foregroundStyle(Color.cdPrimaryBright)
                            Text("Select your vehicle's body style")
                                .font(.system(size: 13))
                                .foregroundStyle(Color.cdTextSecondary)
                        }
                        .padding(CDSpacing.medium)
                        .frame(maxWidth: .infinity)
                        .background(Color.cdPrimary.opacity(0.1))
                        .clipShape(RoundedRectangle(cornerRadius: 12))

                        // Debug: Show count of options
                        Text("Options available: \(options.count)")
                            .font(.system(size: 11))
                            .foregroundStyle(Color.cdTextTertiary)

                        // Body style options (like web frontend)
                        ForEach(options) { option in
                            OptionRow(
                                title: option.name,
                                icon: bodyStyleIcon(for: option.name),
                                isSelected: selectedOption?.name == option.name
                            ) {
                                onSelect(option)
                            }
                        }
                    }
                    .padding(CDSpacing.medium)
                }
            }
            .navigationTitle("Body Style")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                    .foregroundStyle(Color.cdTextSecondary)
                }
            }
        }
    }

    private func bodyStyleIcon(for style: String) -> String {
        let lower = style.lowercased()
        if lower.contains("sedan") { return "car.side.fill" }
        if lower.contains("coupe") { return "car.side.fill" }
        if lower.contains("hatchback") { return "car.side.rear.fill" }
        if lower.contains("wagon") || lower.contains("estate") { return "car.side.rear.fill" }
        if lower.contains("suv") || lower.contains("crossover") { return "suv.side.fill" }
        if lower.contains("truck") || lower.contains("pickup") { return "truck.pickup.side.fill" }
        if lower.contains("van") || lower.contains("minivan") { return "bus.fill" }
        if lower.contains("convertible") || lower.contains("cabrio") { return "car.top.radiowaves.rear.right.fill" }
        return "car.side.fill"
    }
}

// MARK: - Transmission Selection Sheet

struct TransmissionSelectionSheet: View {
    let options: [TransmissionOption]
    @Binding var selectedOption: TransmissionOption?
    let onSelect: (TransmissionOption) -> Void

    @Environment(\.dismiss) private var dismiss

    var body: some View {
        NavigationStack {
            ZStack {
                Color.cdBackground
                    .ignoresSafeArea()

                ScrollView {
                    VStack(spacing: CDSpacing.medium) {
                        // Info banner
                        HStack(spacing: CDSpacing.small) {
                            Image(systemName: "gearshape.2.fill")
                                .foregroundStyle(Color.cdPrimaryBright)
                            Text("Select your transmission type")
                                .font(.system(size: 13))
                                .foregroundStyle(Color.cdTextSecondary)
                        }
                        .padding(CDSpacing.medium)
                        .frame(maxWidth: .infinity)
                        .background(Color.cdPrimary.opacity(0.1))
                        .clipShape(RoundedRectangle(cornerRadius: 12))

                        // Transmission options - show full name (e.g., "6-Speed Manual")
                        ForEach(options) { option in
                            OptionRow(
                                title: option.name,
                                icon: transmissionIcon(for: option.label),
                                isSelected: selectedOption?.name == option.name
                            ) {
                                onSelect(option)
                            }
                        }
                    }
                    .padding(CDSpacing.medium)
                }
            }
            .navigationTitle("Transmission")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                    .foregroundStyle(Color.cdTextSecondary)
                }
            }
        }
    }

    private func transmissionIcon(for trans: String) -> String {
        let lower = trans.lowercased()
        if lower.contains("manual") || lower.contains("mt") { return "gearshift.layout.sixspeed" }
        if lower.contains("cvt") { return "gearshape.fill" }
        return "gearshape.2.fill"
    }
}

// MARK: - Color Selection Sheet

struct ColorSelectionSheet: View {
    let colors: [TrimColor]
    @Binding var selectedColor: TrimColor?
    let onSelect: (TrimColor) -> Void
    let onSkip: () -> Void

    @Environment(\.dismiss) private var dismiss

    // Grid layout for color swatches
    let columns = [
        GridItem(.flexible()),
        GridItem(.flexible()),
        GridItem(.flexible())
    ]

    var body: some View {
        NavigationStack {
            ZStack {
                Color.cdBackground
                    .ignoresSafeArea()

                ScrollView {
                    VStack(spacing: CDSpacing.medium) {
                        // Info banner
                        HStack(spacing: CDSpacing.small) {
                            Image(systemName: "paintpalette.fill")
                                .foregroundStyle(Color.cdPrimaryBright)
                            Text("Select your exterior color for a matching image")
                                .font(.system(size: 13))
                                .foregroundStyle(Color.cdTextSecondary)
                        }
                        .padding(CDSpacing.medium)
                        .frame(maxWidth: .infinity)
                        .background(Color.cdPrimary.opacity(0.1))
                        .clipShape(RoundedRectangle(cornerRadius: 12))

                        // Color swatches in grid
                        LazyVGrid(columns: columns, spacing: CDSpacing.medium) {
                            ForEach(colors) { color in
                                ColorSwatchButton(
                                    color: color,
                                    isSelected: selectedColor?.name == color.name
                                ) {
                                    onSelect(color)
                                }
                            }
                        }

                        // Skip button
                        Button {
                            onSkip()
                        } label: {
                            Text("Skip - I don't know my color")
                                .font(.system(size: 14, weight: .medium))
                                .foregroundStyle(Color.cdTextSecondary)
                                .padding(.vertical, CDSpacing.medium)
                        }
                    }
                    .padding(CDSpacing.medium)
                }
            }
            .navigationTitle("Exterior Color")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                    .foregroundStyle(Color.cdTextSecondary)
                }
            }
        }
    }
}

// MARK: - Color Swatch Button

struct ColorSwatchButton: View {
    let color: TrimColor
    let isSelected: Bool
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            VStack(spacing: CDSpacing.small) {
                // Color swatch circle
                ZStack {
                    Circle()
                        .fill(color.color)
                        .frame(width: 56, height: 56)
                        .shadow(color: color.color.opacity(0.4), radius: isSelected ? 8 : 4, y: 2)

                    // Border for light colors
                    Circle()
                        .stroke(Color.cdTextTertiary.opacity(0.3), lineWidth: 1)
                        .frame(width: 56, height: 56)

                    // Selection indicator
                    if isSelected {
                        Circle()
                            .stroke(Color.cdPrimaryBright, lineWidth: 3)
                            .frame(width: 64, height: 64)

                        Image(systemName: "checkmark")
                            .font(.system(size: 20, weight: .bold))
                            .foregroundStyle(isLightColor ? .black : .white)
                    }
                }

                // Color name
                Text(color.name)
                    .font(.system(size: 11, weight: .medium))
                    .foregroundStyle(Color.cdTextPrimary)
                    .lineLimit(2)
                    .multilineTextAlignment(.center)
                    .frame(height: 30)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, CDSpacing.small)
            .background(
                RoundedRectangle(cornerRadius: 12)
                    .fill(isSelected ? Color.cdPrimary.opacity(0.15) : Color.cdCardBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 12)
                    .stroke(
                        isSelected ? Color.cdPrimaryBright.opacity(0.5) : Color.clear,
                        lineWidth: 1.5
                    )
            )
        }
    }

    // Determine if color is light (for checkmark visibility)
    private var isLightColor: Bool {
        let components = color.rgb.split(separator: ",").compactMap { Double($0.trimmingCharacters(in: .whitespaces)) }
        guard components.count == 3 else { return false }
        // Calculate relative luminance
        let luminance = (0.299 * components[0] + 0.587 * components[1] + 0.114 * components[2]) / 255
        return luminance > 0.5
    }
}

// MARK: - Option Row (Reusable)

struct OptionRow: View {
    let title: String
    let icon: String
    let isSelected: Bool
    let onTap: () -> Void

    var body: some View {
        Button(action: onTap) {
            HStack(spacing: CDSpacing.medium) {
                ZStack {
                    Circle()
                        .fill(isSelected ? Color.cdPrimary.opacity(0.2) : Color.cdCardBackgroundLight)
                        .frame(width: 44, height: 44)

                    Image(systemName: icon)
                        .font(.system(size: 18))
                        .foregroundStyle(isSelected ? Color.cdPrimaryBright : Color.cdTextSecondary)
                }

                Text(title)
                    .font(.system(size: 15, weight: .medium))
                    .foregroundStyle(Color.cdTextPrimary)

                Spacer()

                if isSelected {
                    Image(systemName: "checkmark.circle.fill")
                        .font(.system(size: 20))
                        .foregroundStyle(Color.cdPrimaryBright)
                }
            }
            .padding(CDSpacing.medium)
            .background(
                RoundedRectangle(cornerRadius: 14)
                    .fill(isSelected ? Color.cdPrimary.opacity(0.15) : Color.cdCardBackground)
            )
            .overlay(
                RoundedRectangle(cornerRadius: 14)
                    .stroke(
                        isSelected ? Color.cdPrimaryBright.opacity(0.5) : Color.cdPrimary.opacity(0.1),
                        lineWidth: isSelected ? 1.5 : 1
                    )
            )
        }
    }
}

#Preview {
    ScanView(
        selectedVehicle: .constant(nil),
        selectedVehicleImage: .constant(nil),
        obdStatus: .constant(.disconnected),
        lastScanResult: .constant(nil),
        liveData: .constant(nil)
    )
    .environmentObject(APIClient())
    .environmentObject(VehicleStore())
    .environmentObject(OBDManager())
    .preferredColorScheme(.dark)
}
