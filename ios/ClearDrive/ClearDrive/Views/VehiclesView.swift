//
//  VehiclesView.swift
//  ClearDrive
//
//  Saved vehicles with scan details
//

import SwiftUI
import Combine

// MARK: - Cached Async Image for Vehicles

struct VehicleCachedImage<Content: View, Placeholder: View>: View {
    let url: URL?
    let content: (Image) -> Content
    let placeholder: () -> Placeholder

    @State private var loadedImage: UIImage?
    @State private var isLoading = false
    @State private var loadAttempt = 0

    init(
        url: URL?,
        @ViewBuilder content: @escaping (Image) -> Content,
        @ViewBuilder placeholder: @escaping () -> Placeholder
    ) {
        self.url = url
        self.content = content
        self.placeholder = placeholder
    }

    var body: some View {
        Group {
            if let image = loadedImage {
                content(Image(uiImage: image))
            } else {
                placeholder()
            }
        }
        .onAppear {
            loadImage()
        }
        .onChange(of: url) { _, _ in
            loadedImage = nil
            loadAttempt = 0
            loadImage()
        }
    }

    private func loadImage() {
        guard let url = url, loadedImage == nil, !isLoading else { return }

        isLoading = true
        print("[VehicleCachedImage] Loading: \(url.absoluteString)")

        let config = URLSessionConfiguration.default
        config.requestCachePolicy = .returnCacheDataElseLoad
        config.urlCache = URLCache.shared
        let session = URLSession(configuration: config)

        let task = session.dataTask(with: url) { data, response, error in
            DispatchQueue.main.async {
                isLoading = false

                if let error = error {
                    print("[VehicleCachedImage] Error: \(error.localizedDescription)")
                    if (error as NSError).code == -999 && loadAttempt < 3 {
                        loadAttempt += 1
                        print("[VehicleCachedImage] Retrying (attempt \(loadAttempt))...")
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                            loadImage()
                        }
                    }
                    return
                }

                if let data = data, let uiImage = UIImage(data: data) {
                    print("[VehicleCachedImage] SUCCESS - loaded \(data.count) bytes")
                    loadedImage = uiImage
                } else {
                    print("[VehicleCachedImage] Failed to decode image data")
                }
            }
        }
        task.resume()
    }
}

struct VehiclesView: View {
    @EnvironmentObject var apiClient: APIClient
    @EnvironmentObject var vehicleStore: VehicleStore
    @AppStorage("useMetricUnits") private var useMetricUnits = false

    @Binding var selectedVehicle: VehicleInfo?
    @Binding var selectedVehicleImage: String?
    @Binding var refreshTrigger: UUID  // External trigger to force refresh
    @Binding var liveData: LiveOBDData?  // Live OBD data from ContentView

    private var units: UnitConverter { UnitConverter(useMetric: useMetricUnits) }

    @State private var selectedSavedVehicle: SavedVehicle?
    @State private var isEditMode = false
    @State private var refreshCounter = 0  // Simple counter to force refresh

    var body: some View {
        NavigationStack {
            ZStack {
                // Smooth gradient background
                ZStack {
                    Color.cdBackground

                    // Vertical gradient for depth
                    LinearGradient(
                        stops: [
                            .init(color: Color(hex: "0F1412"), location: 0),
                            .init(color: Color(hex: "0B0E0C"), location: 0.3),
                            .init(color: Color.cdBackground, location: 0.5),
                            .init(color: Color(hex: "080A09"), location: 1.0)
                        ],
                        startPoint: .top,
                        endPoint: .bottom
                    )

                    // Subtle ambient glow
                    RadialGradient(
                        stops: [
                            .init(color: Color.cdPrimary.opacity(0.08), location: 0),
                            .init(color: Color.cdPrimary.opacity(0.03), location: 0.4),
                            .init(color: Color.clear, location: 0.8)
                        ],
                        center: .init(x: 0.5, y: 0.2),
                        startRadius: 50,
                        endRadius: 400
                    )
                }
                .ignoresSafeArea()

                if vehicleStore.savedVehicles.isEmpty {
                    emptyState
                } else {
                    ScrollView(showsIndicators: false) {
                        VStack(spacing: CDSpacing.medium) {
                            // Stats header
                            statsHeader

                            // Vehicles list
                            vehiclesList
                        }
                        .padding(CDSpacing.medium)
                        .padding(.bottom, 100)
                    }
                }
            }
            .navigationTitle("My Vehicles")
            .navigationBarTitleDisplayMode(.large)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    if !vehicleStore.savedVehicles.isEmpty {
                        Button(isEditMode ? "Done" : "Edit") {
                            withAnimation {
                                isEditMode.toggle()
                            }
                        }
                        .foregroundStyle(Color.cdPrimaryBright)
                    }
                }

                ToolbarItem(placement: .topBarTrailing) {
                    NavigationLink {
                        AddVehiclePrompt()
                    } label: {
                        Image(systemName: "plus.circle.fill")
                            .font(.system(size: 24))
                            .foregroundStyle(Color.cdPrimaryBright)
                    }
                }
            }
            .sheet(item: $selectedSavedVehicle) { saved in
                let _ = print("[VehiclesView] Opening detail sheet for: \(saved.vehicle.displayName)")
                let _ = print("  - hasScanResult: \(saved.lastScanResult != nil)")
                let _ = print("  - imageURL: \(saved.lastScanResult?.vehicleImageURL ?? "nil")")
                let _ = print("  - dontPanic: \(saved.lastScanResult?.dontPanic?.prefix(30) ?? "nil")...")
                VehicleDetailSheet(
                    saved: saved,
                    isSelected: selectedVehicle?.displayName == saved.vehicle.displayName,
                    liveData: liveData,
                    onSelect: {
                        selectedVehicle = saved.vehicle
                        selectedVehicleImage = saved.lastScanResult?.vehicleImageURL ?? saved.imageURL
                        selectedSavedVehicle = nil
                    },
                    onDelete: {
                        vehicleStore.removeVehicle(saved)
                        selectedSavedVehicle = nil
                    }
                )
            }
            .onChange(of: refreshTrigger) { _, _ in
                // External trigger from ContentView when scan completes
                refreshCounter += 1
            }
            .onReceive(vehicleStore.objectWillChange) { _ in
                // Refresh when vehicle store changes
                refreshCounter += 1
            }
        }
    }

    // MARK: - Stats Header

    private var statsHeader: some View {
        HStack(spacing: CDSpacing.small) {
            MiniStatCard(
                value: "\(vehicleStore.savedVehicles.count)",
                label: "Vehicles",
                icon: "car.2.fill"
            )
            MiniStatCard(
                value: "\(vehicleStore.scanHistory.count)",
                label: "Total Scans",
                icon: "doc.text.fill"
            )
            MiniStatCard(
                value: overallStatus.text,
                label: "Status",
                icon: overallStatus.icon,
                valueColor: overallStatus.color
            )
        }
    }

    /// Compute overall status based on worst safety rating among all vehicles
    private var overallStatus: (text: String, icon: String, color: Color) {
        guard !vehicleStore.savedVehicles.isEmpty else {
            return ("--", "checkmark.shield.fill", .cdTextSecondary)
        }

        // Find the worst safety rating among all saved vehicles
        var hasCritical = false
        var hasCaution = false
        var hasSafe = false

        for vehicle in vehicleStore.savedVehicles {
            if let result = vehicle.lastScanResult {
                switch result.safetyRating {
                case .critical:
                    hasCritical = true
                case .caution:
                    hasCaution = true
                case .safe:
                    hasSafe = true
                }
            }
        }

        if hasCritical {
            return ("Critical", "exclamationmark.triangle.fill", .cdCritical)
        } else if hasCaution {
            return ("Caution", "exclamationmark.circle.fill", .cdWarning)
        } else if hasSafe {
            return ("Good", "checkmark.shield.fill", .cdSuccess)
        } else {
            return ("--", "questionmark.circle.fill", .cdTextSecondary)
        }
    }

    /// Check if any vehicle has the given safety rating
    private func hasRating(_ rating: SafetyRating) -> Bool {
        vehicleStore.savedVehicles.contains { $0.lastScanResult?.safetyRating == rating }
    }

    // MARK: - Empty State

    private var emptyState: some View {
        VStack(spacing: CDSpacing.xlarge) {
            Spacer()

            ZStack {
                Circle()
                    .fill(Color.cdPrimary.opacity(0.1))
                    .frame(width: 120, height: 120)

                Image(systemName: "car.2.fill")
                    .font(.system(size: 50))
                    .foregroundStyle(Color.cdTextTertiary)
            }

            VStack(spacing: CDSpacing.small) {
                Text("No Vehicles Yet")
                    .font(.system(size: 22, weight: .bold))
                    .foregroundStyle(Color.cdTextPrimary)

                Text("Add your first vehicle to start\ntracking diagnostics")
                    .font(.system(size: 15))
                    .foregroundStyle(Color.cdTextSecondary)
                    .multilineTextAlignment(.center)
            }

            NavigationLink {
                AddVehiclePrompt()
            } label: {
                HStack {
                    Image(systemName: "plus.circle.fill")
                    Text("Add Vehicle")
                }
                .font(.system(size: 16, weight: .semibold))
                .foregroundStyle(.white)
                .padding(.horizontal, 32)
                .padding(.vertical, 16)
                .background(LinearGradient.cdPrimaryGradient)
                .clipShape(RoundedRectangle(cornerRadius: 14))
            }

            Spacer()
        }
        .padding(CDSpacing.medium)
    }

    // MARK: - Vehicles List

    // Computed ID that changes when any vehicle's scan result changes
    private var vehiclesListId: String {
        return "\(refreshCounter)-" + vehicleStore.savedVehicles.map { "\($0.id)-\($0.lastScanResult?.vehicleImageURL ?? "")" }.joined()
    }

    private var vehiclesList: some View {
        VStack(spacing: CDSpacing.medium) {
            ForEach(vehicleStore.savedVehicles) { saved in
                VehicleListCard(
                    saved: saved,
                    isSelected: selectedVehicle?.displayName == saved.vehicle.displayName,
                    isEditMode: isEditMode,
                    onTap: {
                        print("[VehiclesView] Tapped on vehicle: \(saved.vehicle.displayName)")
                        selectedSavedVehicle = saved
                    },
                    onDelete: {
                        withAnimation {
                            vehicleStore.removeVehicle(saved)
                        }
                    }
                )
                .id("\(saved.id)-\(saved.lastScanResult?.vehicleImageURL ?? "none")")  // Force recreate when image URL changes
            }
        }
        .id(vehiclesListId)  // Force re-render when vehicles change
    }
}

// MARK: - Mini Stat Card

struct MiniStatCard: View {
    let value: String
    let label: String
    let icon: String
    var valueColor: Color = .cdTextPrimary

    var body: some View {
        VStack(spacing: 6) {
            Image(systemName: icon)
                .font(.system(size: 18))
                .foregroundStyle(
                    LinearGradient(
                        colors: [Color.cdPrimaryBright, Color.cdPrimary],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )

            Text(value)
                .font(.system(size: 20, weight: .bold, design: .rounded))
                .foregroundStyle(valueColor)

            Text(label)
                .font(.system(size: 10, weight: .medium))
                .foregroundStyle(Color.cdTextTertiary)
                .textCase(.uppercase)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CDSpacing.medium)
        .background(
            ZStack {
                RoundedRectangle(cornerRadius: 14)
                    .fill(LinearGradient.cdCardGradientElevated)
                RoundedRectangle(cornerRadius: 14)
                    .fill(LinearGradient.cdGlassGradient)
            }
        )
        .overlay(
            RoundedRectangle(cornerRadius: 14)
                .stroke(LinearGradient.cdGlassBorder, lineWidth: 0.5)
        )
    }
}

// MARK: - Add Vehicle Prompt

struct AddVehiclePrompt: View {
    @Environment(\.dismiss) private var dismiss

    var body: some View {
        ZStack {
            // Smooth gradient background
            ZStack {
                Color.cdBackground

                LinearGradient(
                    stops: [
                        .init(color: Color(hex: "0F1412"), location: 0),
                        .init(color: Color.cdBackground, location: 0.4),
                        .init(color: Color(hex: "080A09"), location: 1.0)
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )

                RadialGradient(
                    stops: [
                        .init(color: Color.cdPrimaryBright.opacity(0.1), location: 0),
                        .init(color: Color.clear, location: 0.6)
                    ],
                    center: .init(x: 0.5, y: 0.35),
                    startRadius: 50,
                    endRadius: 300
                )
            }
            .ignoresSafeArea()

            VStack(spacing: CDSpacing.xlarge) {
                Spacer()

                ZStack {
                    Circle()
                        .fill(
                            RadialGradient(
                                colors: [Color.cdPrimary.opacity(0.25), Color.cdPrimary.opacity(0.1)],
                                center: .center,
                                startRadius: 20,
                                endRadius: 70
                            )
                        )
                        .frame(width: 140, height: 140)

                    Image(systemName: "car.badge.gearshape.fill")
                        .font(.system(size: 60))
                        .foregroundStyle(
                            LinearGradient(
                                colors: [Color.cdPrimaryBright, Color.cdPrimary],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                }

                VStack(spacing: CDSpacing.small) {
                    Text("Add a Vehicle")
                        .font(.system(size: 24, weight: .bold))
                        .foregroundStyle(Color.cdTextPrimary)

                    Text("Go to the Scan tab to enter your\nvehicle details and run a diagnostic")
                        .font(.system(size: 15))
                        .foregroundStyle(Color.cdTextSecondary)
                        .multilineTextAlignment(.center)
                }

                VStack(spacing: CDSpacing.medium) {
                    HowToStep(number: 1, text: "Go to the Scan tab")
                    HowToStep(number: 2, text: "Enter Year, Make, Model")
                    HowToStep(number: 3, text: "Select your trim")
                    HowToStep(number: 4, text: "Run diagnostic scan")
                }
                .padding(CDSpacing.medium)
                .background(
                    RoundedRectangle(cornerRadius: 16)
                        .fill(Color.cdCardBackground)
                )

                Spacer()

                Button {
                    dismiss()
                } label: {
                    Text("Got It")
                        .font(.system(size: 16, weight: .semibold))
                        .foregroundStyle(Color.cdPrimaryBright)
                }
            }
            .padding(CDSpacing.large)
        }
        .navigationTitle("Add Vehicle")
        .navigationBarTitleDisplayMode(.inline)
    }
}

struct HowToStep: View {
    let number: Int
    let text: String

    var body: some View {
        HStack(spacing: CDSpacing.medium) {
            ZStack {
                Circle()
                    .fill(Color.cdPrimary.opacity(0.2))
                    .frame(width: 32, height: 32)

                Text("\(number)")
                    .font(.system(size: 14, weight: .bold))
                    .foregroundStyle(Color.cdPrimaryBright)
            }

            Text(text)
                .font(.system(size: 15))
                .foregroundStyle(Color.cdTextPrimary)

            Spacer()
        }
    }
}

// MARK: - Vehicle List Card

struct VehicleListCard: View {
    let saved: SavedVehicle
    let isSelected: Bool
    var isEditMode: Bool = false
    let onTap: () -> Void
    var onDelete: (() -> Void)? = nil

    var body: some View {
        HStack(spacing: CDSpacing.medium) {
            // Delete button in edit mode
            if isEditMode {
                Button {
                    onDelete?()
                } label: {
                    Image(systemName: "minus.circle.fill")
                        .font(.system(size: 24))
                        .foregroundStyle(Color.cdCritical)
                }
            }

            Button(action: onTap) {
                HStack(spacing: CDSpacing.medium) {
                    // Vehicle image - pull directly from scan result
                    let _ = print("[VehicleListCard] \(saved.vehicle.displayName) imageURL: \(saved.lastScanResult?.vehicleImageURL ?? "nil")")
                    if let imageURL = saved.lastScanResult?.vehicleImageURL, let url = URL(string: imageURL) {
                        VehicleCachedImage(url: url) { image in
                            image
                                .resizable()
                                .aspectRatio(contentMode: .fit)
                                .frame(width: 100, height: 65)
                                .clipShape(RoundedRectangle(cornerRadius: 10))
                        } placeholder: {
                            vehiclePlaceholder
                        }
                        .frame(width: 100, height: 65)
                    } else {
                        vehiclePlaceholder
                    }

                    // Vehicle info
                    VStack(alignment: .leading, spacing: 3) {
                        Text(saved.vehicle.displayName)
                            .font(.system(size: 15, weight: .semibold))
                            .foregroundStyle(Color.cdTextPrimary)
                            .lineLimit(1)

                        if let engine = saved.vehicle.engine {
                            Text(engine)
                                .font(.system(size: 12))
                                .foregroundStyle(Color.cdTextSecondary)
                                .lineLimit(1)
                        }

                        Text("\(saved.lastScanned, style: .relative) ago")
                            .font(.system(size: 11))
                            .foregroundStyle(Color.cdTextTertiary)
                    }

                    Spacer()

                    if !isEditMode {
                        VStack(alignment: .trailing, spacing: 4) {
                            if isSelected {
                                Text("ACTIVE")
                                    .font(.system(size: 9, weight: .bold))
                                    .foregroundStyle(Color.cdPrimaryBright)
                                    .padding(.horizontal, 8)
                                    .padding(.vertical, 4)
                                    .background(Color.cdPrimary.opacity(0.2))
                                    .clipShape(RoundedRectangle(cornerRadius: 4))
                            }

                            Image(systemName: "chevron.right")
                                .font(.system(size: 13))
                                .foregroundStyle(Color.cdTextTertiary)
                        }
                    }
                }
                .padding(CDSpacing.medium)
                .background(
                    ZStack {
                        RoundedRectangle(cornerRadius: 16)
                            .fill(LinearGradient.cdCardGradientElevated)
                        RoundedRectangle(cornerRadius: 16)
                            .fill(LinearGradient.cdGlassGradient)
                        if isSelected {
                            RoundedRectangle(cornerRadius: 16)
                                .fill(Color.cdPrimary.opacity(0.1))
                        }
                    }
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(
                            isSelected
                                ? LinearGradient(colors: [Color.cdPrimaryBright.opacity(0.5), Color.cdPrimary.opacity(0.2)], startPoint: .topLeading, endPoint: .bottomTrailing)
                                : LinearGradient.cdGlassBorder,
                            lineWidth: isSelected ? 1.5 : 0.5
                        )
                )
            }
        }
    }

    private var vehiclePlaceholder: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 10)
                .fill(LinearGradient.cdCardGradientElevated)
                .frame(width: 100, height: 65)

            Image(systemName: "car.side.fill")
                .font(.system(size: 28))
                .foregroundStyle(Color.cdTextTertiary)
        }
    }
}

// MARK: - Vehicle Detail Sheet

struct VehicleDetailSheet: View {
    let saved: SavedVehicle
    let isSelected: Bool
    let liveData: LiveOBDData?  // Live OBD data from polling
    let onSelect: () -> Void
    let onDelete: () -> Void

    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject var apiClient: APIClient
    @EnvironmentObject var vehicleStore: VehicleStore
    @AppStorage("useMetricUnits") private var useMetricUnits = false

    private var units: UnitConverter { UnitConverter(useMetric: useMetricUnits) }

    // Follow-up question state
    @State private var chatMessages: [ChatMessage] = []
    @State private var currentQuestion = ""
    @State private var isAskingQuestion = false
    @State private var questionsRemaining = 3

    // Service tracking state
    @State private var showMileageEntry = false
    @State private var showServiceLog = false

    var body: some View {
        NavigationStack {
            ZStack {
                // Smooth gradient background
                ZStack {
                    Color.cdBackground

                    LinearGradient(
                        stops: [
                            .init(color: Color(hex: "0F1311"), location: 0),
                            .init(color: Color(hex: "0A0D0B"), location: 0.3),
                            .init(color: Color.cdBackground, location: 0.5),
                            .init(color: Color(hex: "080A09"), location: 1.0)
                        ],
                        startPoint: .top,
                        endPoint: .bottom
                    )

                    RadialGradient(
                        stops: [
                            .init(color: Color.cdPrimary.opacity(0.1), location: 0),
                            .init(color: Color.cdPrimary.opacity(0.03), location: 0.4),
                            .init(color: Color.clear, location: 0.7)
                        ],
                        center: .init(x: 0.5, y: 0.15),
                        startRadius: 40,
                        endRadius: 350
                    )
                }
                .ignoresSafeArea()

                ScrollView(showsIndicators: false) {
                    VStack(spacing: CDSpacing.large) {
                        vehicleHero
                        statsSection

                        // Show full scan results if available
                        if let result = saved.lastScanResult {
                            scanResultsSection(result)
                        } else {
                            noScanSection
                        }

                        // Service section always visible regardless of scan status
                        serviceSection

                        actionsSection
                    }
                    .padding(CDSpacing.medium)
                    .padding(.bottom, 40)
                }
            }
            .navigationTitle("Vehicle Details")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button("Done") {
                        dismiss()
                    }
                    .foregroundStyle(Color.cdPrimaryBright)
                }
            }
            .sheet(isPresented: $showMileageEntry) {
                MileageEntrySheet(
                    savedVehicle: saved,
                    initialMileage: saved.currentMileage ?? liveData?.odometer
                ) { mileage in
                    vehicleStore.updateMileage(for: saved.id, mileage: mileage)
                }
            }
            .sheet(isPresented: $showServiceLog) {
                ServiceLogSheet(
                    savedVehicle: saved,
                    currentMileage: saved.currentMileage ?? liveData?.odometer
                ) { date, mileage in
                    vehicleStore.updateServiceInfo(for: saved.id, date: date, mileage: mileage)
                }
            }
        }
    }

    private var vehicleHero: some View {
        VStack(spacing: CDSpacing.medium) {
            // Pull image directly from scan result
            if let imageURL = saved.lastScanResult?.vehicleImageURL, let url = URL(string: imageURL) {
                VehicleCachedImage(url: url) { image in
                    image
                        .resizable()
                        .aspectRatio(contentMode: .fit)
                        .frame(width: 280, height: 180)
                        .shadow(color: Color.black.opacity(0.4), radius: 20, y: 10)
                } placeholder: {
                    imagePlaceholder
                }
                .frame(width: 280, height: 180)
            } else {
                imagePlaceholder
            }

            VStack(spacing: CDSpacing.xs) {
                Text(saved.vehicle.displayName)
                    .font(.system(size: 20, weight: .bold))
                    .foregroundStyle(Color.cdTextPrimary)

                if let engine = saved.vehicle.engine {
                    Text(engine)
                        .font(.system(size: 14))
                        .foregroundStyle(Color.cdTextSecondary)
                }
            }

            if isSelected {
                HStack(spacing: 6) {
                    Image(systemName: "checkmark.circle.fill")
                    Text("Currently Active")
                        .font(.system(size: 12, weight: .semibold))
                }
                .foregroundStyle(Color.cdPrimaryBright)
                .padding(.horizontal, 12)
                .padding(.vertical, 6)
                .background(Color.cdPrimary.opacity(0.15))
                .clipShape(Capsule())
            }
        }
        .frame(maxWidth: .infinity)
        .padding(CDSpacing.large)
        .background(
            RoundedRectangle(cornerRadius: 20)
                .fill(Color.cdCardBackground)
        )
    }

    private var imagePlaceholder: some View {
        ZStack {
            Color.cdCardBackgroundLight
                .frame(width: 280, height: 180)
                .clipShape(RoundedRectangle(cornerRadius: 12))

            Image(systemName: "car.side.fill")
                .font(.system(size: 60))
                .foregroundStyle(Color.cdTextTertiary)
        }
    }

    private var statsSection: some View {
        HStack(spacing: CDSpacing.small) {
            StatBox(
                title: "Added",
                value: saved.dateAdded.formatted(date: .abbreviated, time: .omitted),
                icon: "calendar"
            )
            StatBox(
                title: "Scans",
                value: saved.lastScanResult != nil ? "1" : "0",
                icon: "doc.text"
            )
            StatBox(
                title: "Health",
                value: saved.lastScanResult?.safetyRating.rawValue.capitalized ?? "--",
                icon: "heart.fill",
                valueColor: saved.lastScanResult?.safetyRating.color ?? .cdTextSecondary
            )
        }
    }

    // MARK: - Scan Results Section

    @ViewBuilder
    private func scanResultsSection(_ result: ScanResult) -> some View {
        // Safety status hero
        safetyStatusCard(result)

        // Vehicle specs (Engine, Transmission, Drive, Fuel)
        vehicleSpecsSection(result)

        // Live OBD data at time of scan (if available)
        if result.rpm != nil || result.speed != nil || result.coolantTemp != nil {
            liveDataSection(result)
        }

        // Last scan timestamp
        lastScanTimestamp(result)

        // DTC Codes if any
        if !result.codes.isEmpty {
            dtcCodesSection(result)
        }

        // All diagnostic tabs
        diagnosticTabsSection(result)

        // Follow-up questions
        followUpCard(result)
    }

    private func vehicleSpecsSection(_ result: ScanResult) -> some View {
        VStack(spacing: CDSpacing.small) {
            HStack(spacing: CDSpacing.small) {
                // Engine - show full name from CarsXE
                SpecWidget(
                    title: "Engine",
                    value: formatEngineSpec(result.engine ?? saved.vehicle.engine),
                    icon: "engine.combustion"
                )
                // Transmission - show full name from CarsXE
                SpecWidget(
                    title: "Trans",
                    value: formatTransSpec(result.transmission ?? saved.vehicle.transmission),
                    icon: "gearshape.2.fill"
                )
            }
            HStack(spacing: CDSpacing.small) {
                // Drive
                SpecWidget(
                    title: "Drive",
                    value: formatDriveSpec(result.drive ?? saved.vehicle.driveType),
                    icon: "car.fill"
                )
                // Fuel
                SpecWidget(
                    title: "Fuel",
                    value: result.fuelType ?? saved.vehicle.fuelType ?? "--",
                    icon: "fuelpump.fill"
                )
            }
            // Bottom row: MPG, Range
            HStack(spacing: CDSpacing.small) {
                SpecWidget(
                    title: "MPG",
                    value: saved.vehicle.mpgDisplay ?? "--",
                    icon: "gauge.with.dots.needle.33percent"
                )
                SpecWidget(
                    title: "Range",
                    value: saved.vehicle.estimatedRange ?? "--",
                    icon: "road.lanes"
                )
            }
        }
    }

    private func formatEngineSpec(_ engine: String?) -> String {
        guard let engine = engine, !engine.isEmpty else { return "--" }

        // Remove HP info in parentheses - just show displacement + type
        var display = engine
        if let parenRange = display.range(of: #"\s*\([^)]*hp[^)]*\)"#, options: [.regularExpression, .caseInsensitive]) {
            display.removeSubrange(parenRange)
        }
        display = display.trimmingCharacters(in: .whitespaces)

        if display.count <= 12 { return display }
        return String(display.prefix(11)) + ".."
    }

    private func formatTransSpec(_ trans: String?) -> String {
        guard let trans = trans, !trans.isEmpty else { return "--" }
        // Show full transmission name from CarsXE
        if trans.count <= 14 { return trans }
        let display = trans
            .replacingOccurrences(of: "-Speed", with: "sp")
            .replacingOccurrences(of: " Automatic", with: " Auto")
            .replacingOccurrences(of: " Manual", with: " Man")
        if display.count <= 14 { return display }
        return String(display.prefix(12)) + ".."
    }

    private func formatDriveSpec(_ drive: String?) -> String {
        guard let drive = drive?.lowercased() else { return "--" }
        if drive.contains("rear") { return "RWD" }
        if drive.contains("front") { return "FWD" }
        if drive.contains("all") || drive.contains("awd") { return "AWD" }
        if drive.contains("4") { return "4WD" }
        return String(drive.prefix(4).uppercased())
    }

    private func liveDataSection(_ result: ScanResult) -> some View {
        // Use current live data if connected, otherwise show scan-time data
        let isLive = liveData?.connected == true
        let displayRpm = isLive ? (liveData?.rpm.map { Int($0) }) : result.rpm
        let displaySpeed = isLive ? (liveData?.speed.map { Int($0) }) : result.speed
        let displayCoolant = isLive ? (liveData?.coolantTemp.map { Int($0) }) : result.coolantTemp
        let displayOdometer = isLive ? liveData?.odometer : nil
        let displayFuelLevel = isLive ? liveData?.fuelLevel : nil

        return VStack(alignment: .leading, spacing: CDSpacing.small) {
            HStack(spacing: CDSpacing.xs) {
                Image(systemName: isLive ? "antenna.radiowaves.left.and.right" : "clock")
                    .font(.system(size: 11))
                    .foregroundStyle(isLive ? Color.cdSuccess : Color.cdPrimaryBright)

                Text("OBD-II \(isLive ? "LIVE" : "DATA")")
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(isLive ? Color.cdSuccess : Color.cdPrimaryBright)
                    .tracking(0.5)

                if isLive {
                    Circle()
                        .fill(Color.cdSuccess)
                        .frame(width: 6, height: 6)
                }

                Spacer()

                Text(isLive ? "CONNECTED" : "AT TIME OF SCAN")
                    .font(.system(size: 9, weight: .medium))
                    .foregroundStyle(isLive ? Color.cdSuccess : Color.cdTextTertiary)
            }
            .padding(.horizontal, CDSpacing.small)

            HStack(spacing: CDSpacing.small) {
                if let rpm = displayRpm {
                    LiveDataWidget(
                        value: "\(rpm)",
                        label: "RPM",
                        icon: "gauge.with.needle",
                        color: isLive ? .cdSuccess : .cdPrimaryBright
                    )
                }
                if let speed = displaySpeed {
                    LiveDataWidget(
                        value: units.speed(speed),
                        label: "Speed",
                        icon: "speedometer",
                        color: isLive ? .cdSuccess : .cdPrimaryBright
                    )
                }
                if let temp = displayCoolant {
                    LiveDataWidget(
                        value: units.temperature(temp),
                        label: "Coolant",
                        icon: "thermometer.medium",
                        color: isLive ? .cdSuccess : .cdPrimaryBright
                    )
                }
            }

            // Show extra live data when connected (odometer, fuel level)
            if isLive && (displayOdometer != nil || displayFuelLevel != nil) {
                HStack(spacing: CDSpacing.small) {
                    if let odo = displayOdometer {
                        LiveDataWidget(
                            value: units.distance(odo),
                            label: "Odometer",
                            icon: "road.lanes",
                            color: .cdSuccess
                        )
                    }
                    if let fuel = displayFuelLevel {
                        LiveDataWidget(
                            value: "\(fuel)%",
                            label: "Fuel",
                            icon: "fuelpump.fill",
                            color: .cdSuccess
                        )
                    }
                }
            }
        }
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color.cdCardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke((isLive ? Color.cdSuccess : Color.cdPrimary).opacity(0.15), lineWidth: 1)
                )
        )
    }

    private func safetyStatusCard(_ result: ScanResult) -> some View {
        VStack(spacing: CDSpacing.medium) {
            // Status icon with glow
            ZStack {
                Circle()
                    .fill(result.safetyRating.color.opacity(0.15))
                    .frame(width: 80, height: 80)
                    .blur(radius: 15)

                Circle()
                    .fill(result.safetyRating.color.opacity(0.1))
                    .frame(width: 60, height: 60)

                Image(systemName: result.safetyRating.icon)
                    .font(.system(size: 28))
                    .foregroundStyle(result.safetyRating.color)
            }

            VStack(spacing: CDSpacing.xs) {
                Text(result.safetyRating.rawValue.uppercased())
                    .font(.system(size: 18, weight: .bold))
                    .foregroundStyle(result.safetyRating.color)

                Text(result.safetyRating.label)
                    .font(.system(size: 13))
                    .foregroundStyle(Color.cdTextSecondary)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CDSpacing.large)
        .background(
            RoundedRectangle(cornerRadius: 16)
                .fill(Color.cdCardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 16)
                        .stroke(result.safetyRating.color.opacity(0.2), lineWidth: 1)
                )
        )
    }

    private func lastScanTimestamp(_ result: ScanResult) -> some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("Last Scanned")
                    .font(.system(size: 11, weight: .semibold))
                    .foregroundStyle(Color.cdTextTertiary)
                    .textCase(.uppercase)

                Text(result.timestamp.formatted(date: .long, time: .shortened))
                    .font(.system(size: 14, weight: .medium))
                    .foregroundStyle(Color.cdTextPrimary)
            }

            Spacer()

            Text("\(result.timestamp, style: .relative) ago")
                .font(.system(size: 12))
                .foregroundStyle(Color.cdTextSecondary)
        }
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.cdCardBackground)
        )
    }

    private func dtcCodesSection(_ result: ScanResult) -> some View {
        VStack(alignment: .leading, spacing: CDSpacing.small) {
            SectionHeader(title: "Diagnostic Codes")

            VStack(spacing: CDSpacing.small) {
                ForEach(result.codes) { code in
                    HStack(spacing: CDSpacing.medium) {
                        Text(code.code)
                            .font(.system(size: 15, weight: .bold, design: .monospaced))
                            .foregroundStyle(Color.cdWarning)
                            .frame(width: 70, alignment: .leading)

                        Text(code.description)
                            .font(.system(size: 13))
                            .foregroundStyle(Color.cdTextPrimary)
                            .lineLimit(2)

                        Spacer()
                    }
                    .padding(CDSpacing.small)
                    .background(Color.cdWarning.opacity(0.08))
                    .clipShape(RoundedRectangle(cornerRadius: 8))
                }
            }
            .padding(CDSpacing.medium)
            .background(
                RoundedRectangle(cornerRadius: 14)
                    .fill(Color.cdCardBackground)
            )
        }
    }

    private func diagnosticTabsSection(_ result: ScanResult) -> some View {
        VStack(spacing: CDSpacing.medium) {
            if let content = result.dontPanic, !content.isEmpty {
                VehicleDiagnosticCard(title: "What's Happening", content: content, icon: "info.circle.fill")
            }

            if let content = result.likelyCauses, !content.isEmpty {
                VehicleDiagnosticCard(title: "Likely Causes", content: content, icon: "questionmark.circle.fill")
            }

            if let content = result.symptoms, !content.isEmpty {
                VehicleDiagnosticCard(title: "What You Might Notice", content: content, icon: "eye.fill")
            }

            if let content = result.ifIgnored, !content.isEmpty {
                VehicleDiagnosticCard(title: "If You Ignore This", content: content, icon: "exclamationmark.triangle.fill", isWarning: true)
            }

            if let content = result.quickChecks, !content.isEmpty {
                VehicleDiagnosticCard(title: "Quick Checks", content: content, icon: "checklist")
            }

            if let content = result.diyFix, !content.isEmpty {
                VehicleDiagnosticCard(title: "DIY Fix", content: content, icon: "wrench.and.screwdriver.fill")
            }

            if let content = result.urgency, !content.isEmpty {
                VehicleDiagnosticCard(title: "When To See A Mechanic", content: content, icon: "clock.fill")
            }

            if let content = result.repairCost, !content.isEmpty {
                VehicleDiagnosticCard(title: "Estimated Cost", content: content, icon: "dollarsign.circle.fill")
            }

            if let content = result.knownIssues, !content.isEmpty {
                VehicleDiagnosticCard(title: "Known Issues", content: content, icon: "doc.text.fill")
            }

            if let content = result.ownerReports, !content.isEmpty {
                VehicleDiagnosticCard(title: "Owner Reports", content: content, icon: "person.2.fill")
            }

            // Service recommendations from AI
            if let serviceRecs = result.serviceRecommendations, !serviceRecs.isEmpty {
                VehicleDiagnosticCard(title: "Service Recommendations", content: serviceRecs, icon: "wrench.and.screwdriver.fill")
            }
        }
    }

    // MARK: - Service Section

    private var serviceSection: some View {
        // Get effective mileage - prefer saved, then live OBD, then nil
        let effectiveMileage = saved.currentMileage ?? liveData?.odometer

        return VStack(alignment: .leading, spacing: CDSpacing.medium) {
            SectionHeader(title: "Service Tracking")

            VStack(spacing: CDSpacing.small) {
                // Current mileage
                HStack {
                    Image(systemName: "road.lanes")
                        .font(.system(size: 16))
                        .foregroundStyle(Color.cdPrimaryBright)
                        .frame(width: 24)

                    VStack(alignment: .leading, spacing: 2) {
                        Text("Current Mileage")
                            .font(.system(size: 12))
                            .foregroundStyle(Color.cdTextTertiary)
                        if let mileage = effectiveMileage {
                            HStack(spacing: 4) {
                                Text(String(format: "%.0f mi", mileage))
                                    .font(.system(size: 15, weight: .semibold))
                                    .foregroundStyle(Color.cdTextPrimary)
                                if saved.currentMileage == nil && liveData?.odometer != nil {
                                    Text("(OBD)")
                                        .font(.system(size: 11))
                                        .foregroundStyle(Color.cdSuccess)
                                }
                            }
                        } else {
                            Text("Not set")
                                .font(.system(size: 15, weight: .semibold))
                                .foregroundStyle(Color.cdTextSecondary)
                        }
                    }

                    Spacer()

                    Button(effectiveMileage != nil ? "Update" : "Set") {
                        showMileageEntry = true
                    }
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(Color.cdPrimaryBright)
                }
                .padding(CDSpacing.medium)
                .background(Color.cdCardBackgroundLight)
                .clipShape(RoundedRectangle(cornerRadius: 10))

                // Next oil change / service status
                HStack {
                    Image(systemName: saved.isOilChangeOverdue ? "exclamationmark.triangle.fill" : "calendar.badge.clock")
                        .font(.system(size: 16))
                        .foregroundStyle(saved.isOilChangeOverdue ? Color.cdWarning : Color.cdPrimaryBright)
                        .frame(width: 24)

                    VStack(alignment: .leading, spacing: 2) {
                        Text("Next Oil Change")
                            .font(.system(size: 12))
                            .foregroundStyle(Color.cdTextTertiary)

                        if saved.isOilChangeOverdue {
                            Text("OVERDUE")
                                .font(.system(size: 15, weight: .bold))
                                .foregroundStyle(Color.cdWarning)
                        } else if let milesLeft = saved.milesUntilOilChange {
                            Text("\(units.distance(Double(milesLeft))) remaining")
                                .font(.system(size: 15, weight: .semibold))
                                .foregroundStyle(milesLeft < 500 ? Color.cdWarning : Color.cdTextPrimary)
                        } else if let nextDate = saved.nextOilChangeDate {
                            Text(nextDate.formatted(date: .abbreviated, time: .omitted))
                                .font(.system(size: 15, weight: .semibold))
                                .foregroundStyle(Color.cdTextPrimary)
                        } else {
                            Text("Log last service to track")
                                .font(.system(size: 15, weight: .semibold))
                                .foregroundStyle(Color.cdTextSecondary)
                        }
                    }

                    Spacer()

                    if saved.lastOilChangeDate != nil {
                        VStack(alignment: .trailing, spacing: 2) {
                            Text("Last")
                                .font(.system(size: 10))
                                .foregroundStyle(Color.cdTextTertiary)
                            Text(saved.lastOilChangeDate!.formatted(date: .abbreviated, time: .omitted))
                                .font(.system(size: 11))
                                .foregroundStyle(Color.cdTextSecondary)
                        }
                    }
                }
                .padding(CDSpacing.medium)
                .background(saved.isOilChangeOverdue ? Color.cdWarning.opacity(0.1) : Color.cdCardBackgroundLight)
                .clipShape(RoundedRectangle(cornerRadius: 10))

                // Estimated range (calculated from fuel % and MPG)
                if let fuelLevel = liveData?.fuelLevel,
                   let combinedMpgStr = saved.vehicle.mpgCombined,
                   let combinedMpg = Double(combinedMpgStr) {
                    let tankStr = saved.vehicle.tankCapacity ?? "15"
                    let tankCapacity = Double(tankStr) ?? 15.0  // Default 15 gal if unknown
                    let gallonsRemaining = tankCapacity * (Double(fuelLevel) / 100.0)
                    let estimatedRangeMiles = Int(gallonsRemaining * combinedMpg)

                    HStack {
                        Image(systemName: "fuelpump.fill")
                            .font(.system(size: 16))
                            .foregroundStyle(fuelLevel < 15 ? Color.cdWarning : Color.cdPrimaryBright)
                            .frame(width: 24)

                        VStack(alignment: .leading, spacing: 2) {
                            Text("Estimated Range")
                                .font(.system(size: 12))
                                .foregroundStyle(Color.cdTextTertiary)
                            HStack(spacing: 4) {
                                Text("~\(units.range(estimatedRangeMiles))")
                                    .font(.system(size: 15, weight: .semibold))
                                    .foregroundStyle(fuelLevel < 15 ? Color.cdWarning : Color.cdTextPrimary)
                                Text("(\(fuelLevel)% fuel)")
                                    .font(.system(size: 12))
                                    .foregroundStyle(Color.cdSuccess)
                            }
                        }

                        Spacer()

                        Text("LIVE")
                            .font(.system(size: 9, weight: .bold))
                            .foregroundStyle(Color.cdSuccess)
                            .padding(.horizontal, 6)
                            .padding(.vertical, 3)
                            .background(Color.cdSuccess.opacity(0.15))
                            .clipShape(RoundedRectangle(cornerRadius: 4))
                    }
                    .padding(CDSpacing.medium)
                    .background(fuelLevel < 15 ? Color.cdWarning.opacity(0.1) : Color.cdCardBackgroundLight)
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                }

                // Log service button
                Button {
                    showServiceLog = true
                } label: {
                    HStack {
                        Image(systemName: "plus.circle.fill")
                        Text(saved.lastOilChangeDate != nil ? "Log New Service" : "Log Last Service")
                    }
                    .font(.system(size: 14, weight: .semibold))
                    .foregroundStyle(Color.cdPrimaryBright)
                    .frame(maxWidth: .infinity)
                    .padding(.vertical, 12)
                    .background(Color.cdPrimary.opacity(0.15))
                    .clipShape(RoundedRectangle(cornerRadius: 10))
                }
            }
            .padding(CDSpacing.medium)
            .background(
                RoundedRectangle(cornerRadius: 14)
                    .fill(Color.cdCardBackground)
            )
        }
    }

    private var noScanSection: some View {
        VStack(spacing: CDSpacing.medium) {
            ZStack {
                Circle()
                    .fill(Color.cdPrimary.opacity(0.1))
                    .frame(width: 60, height: 60)

                Image(systemName: "magnifyingglass")
                    .font(.system(size: 24))
                    .foregroundStyle(Color.cdTextTertiary)
            }

            VStack(spacing: CDSpacing.xs) {
                Text("No Scan Results")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Color.cdTextPrimary)

                Text("Run a diagnostic scan to see results")
                    .font(.system(size: 13))
                    .foregroundStyle(Color.cdTextSecondary)
            }
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CDSpacing.xlarge)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color.cdCardBackground)
        )
    }

    private var actionsSection: some View {
        VStack(spacing: CDSpacing.small) {
            if !isSelected {
                LuxuryButton("Select This Vehicle", icon: "checkmark.circle") {
                    onSelect()
                }
            }

            Button {
                onDelete()
            } label: {
                HStack {
                    Image(systemName: "trash")
                    Text("Remove Vehicle")
                }
                .font(.system(size: 15, weight: .medium))
                .foregroundStyle(Color.cdCritical)
                .frame(maxWidth: .infinity)
                .padding(.vertical, 14)
                .background(Color.cdCritical.opacity(0.1))
                .clipShape(RoundedRectangle(cornerRadius: 12))
            }
        }
    }

    // MARK: - Follow-up Questions

    private func followUpCard(_ result: ScanResult) -> some View {
        VStack(alignment: .leading, spacing: CDSpacing.medium) {
            HStack {
                HStack(spacing: CDSpacing.xs) {
                    Image(systemName: "bubble.left.and.bubble.right.fill")
                        .font(.system(size: 14))
                        .foregroundStyle(Color.cdPrimaryBright)

                    Text("Ask Follow-up Questions")
                        .font(.system(size: 14, weight: .semibold))
                        .foregroundStyle(Color.cdTextPrimary)
                }

                Spacer()

                Text("\(questionsRemaining) remaining")
                    .font(.system(size: 12))
                    .foregroundStyle(Color.cdTextTertiary)
            }

            // Quick questions
            ScrollView(.horizontal, showsIndicators: false) {
                HStack(spacing: CDSpacing.small) {
                    QuickQuestionButton(text: "Repair cost?") {
                        askQuestion("How much will this repair cost?", result: result)
                    }
                    QuickQuestionButton(text: "Safe to drive?") {
                        askQuestion("Can I drive to work tomorrow?", result: result)
                    }
                    QuickQuestionButton(text: "Parts needed?") {
                        askQuestion("What parts might need replacing?", result: result)
                    }
                    QuickQuestionButton(text: "DIY possible?") {
                        askQuestion("Can I fix this myself?", result: result)
                    }
                }
            }

            // Chat messages
            if !chatMessages.isEmpty {
                VStack(spacing: CDSpacing.small) {
                    ForEach(chatMessages) { message in
                        ChatBubble(message: message)
                    }

                    if isAskingQuestion {
                        HStack {
                            ProgressView()
                                .scaleEffect(0.8)
                            Text("Thinking...")
                                .font(.system(size: 12))
                                .foregroundStyle(Color.cdTextTertiary)
                            Spacer()
                        }
                        .padding(.leading, CDSpacing.small)
                    }
                }
            }

            // Input field
            if questionsRemaining > 0 {
                HStack(spacing: CDSpacing.small) {
                    TextField("Ask a question...", text: $currentQuestion)
                        .font(.system(size: 14))
                        .padding(.horizontal, 14)
                        .padding(.vertical, 12)
                        .background(Color.cdCardBackgroundLight)
                        .clipShape(RoundedRectangle(cornerRadius: 10))

                    Button {
                        askQuestion(currentQuestion, result: result)
                        currentQuestion = ""
                    } label: {
                        Image(systemName: "arrow.up.circle.fill")
                            .font(.system(size: 32))
                            .foregroundStyle(Color.cdPrimaryBright)
                    }
                    .disabled(currentQuestion.isEmpty || isAskingQuestion)
                    .opacity(currentQuestion.isEmpty ? 0.5 : 1)
                }
            }
        }
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(Color.cdCardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(Color.cdPrimary.opacity(0.15), lineWidth: 1)
                )
        )
    }

    private func askQuestion(_ question: String, result: ScanResult) {
        guard !question.isEmpty, questionsRemaining > 0 else { return }

        chatMessages.append(ChatMessage(role: .user, content: question))
        isAskingQuestion = true

        Task {
            let context: [String: Any] = [
                "vehicle": result.vehicle.displayName,
                "codes": result.codes.map { $0.code },
                "safety_level": result.safetyRating.rawValue,
                "engine": result.engine ?? "",
                "transmission": result.transmission ?? "",
                "drive": result.drive ?? "",
                "summary": result.dontPanic ?? "",
                "likely_causes": result.likelyCauses ?? ""
            ]

            let history = chatMessages.map { ["role": $0.role == .user ? "user" : "assistant", "content": $0.content] }

            do {
                let answer = try await apiClient.askFollowUp(
                    question: question,
                    context: context,
                    history: history
                )
                await MainActor.run {
                    chatMessages.append(ChatMessage(role: .assistant, content: answer))
                    questionsRemaining -= 1
                    isAskingQuestion = false
                }
            } catch {
                await MainActor.run {
                    chatMessages.append(ChatMessage(role: .assistant, content: "Sorry, couldn't get an answer. Please try again."))
                    isAskingQuestion = false
                }
            }
        }
    }
}

// MARK: - Vehicle Diagnostic Card

struct VehicleDiagnosticCard: View {
    let title: String
    let content: String
    let icon: String
    var isWarning: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: CDSpacing.small) {
            HStack(spacing: CDSpacing.small) {
                Image(systemName: icon)
                    .font(.system(size: 14))
                    .foregroundStyle(isWarning ? Color.cdWarning : Color.cdPrimaryBright)

                Text(title.uppercased())
                    .font(.system(size: 11, weight: .bold))
                    .foregroundStyle(isWarning ? Color.cdWarning : Color.cdPrimaryBright)
                    .tracking(0.5)
            }

            Text(content)
                .font(.system(size: 14))
                .foregroundStyle(Color.cdTextPrimary.opacity(0.9))
                .lineSpacing(4)
                .fixedSize(horizontal: false, vertical: true)
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 14)
                .fill(isWarning ? Color.cdWarning.opacity(0.08) : Color.cdCardBackground)
                .overlay(
                    RoundedRectangle(cornerRadius: 14)
                        .stroke(
                            isWarning ? Color.cdWarning.opacity(0.2) : Color.cdPrimary.opacity(0.1),
                            lineWidth: 1
                        )
                )
        )
    }
}

// MARK: - Stat Box

struct StatBox: View {
    let title: String
    let value: String
    let icon: String
    var valueColor: Color = .cdTextPrimary

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: icon)
                .font(.system(size: 14))
                .foregroundStyle(
                    LinearGradient(
                        colors: [Color.cdPrimaryBright.opacity(0.7), Color.cdTextTertiary],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )

            Text(value)
                .font(.system(size: 13, weight: .semibold))
                .foregroundStyle(valueColor)
                .lineLimit(1)
                .minimumScaleFactor(0.7)

            Text(title)
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(Color.cdTextTertiary)
                .textCase(.uppercase)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CDSpacing.small)
        .background(
            ZStack {
                RoundedRectangle(cornerRadius: 10)
                    .fill(LinearGradient.cdCardGradientElevated)
                RoundedRectangle(cornerRadius: 10)
                    .fill(LinearGradient.cdGlassGradient)
            }
        )
        .overlay(
            RoundedRectangle(cornerRadius: 10)
                .stroke(LinearGradient.cdGlassBorder, lineWidth: 0.5)
        )
    }
}

struct SpecWidget: View {
    let title: String
    let value: String
    let icon: String

    var body: some View {
        VStack(spacing: 4) {
            Image(systemName: icon)
                .font(.system(size: 16))
                .foregroundStyle(Color.cdPrimaryBright)

            Text(value)
                .font(.system(size: 12, weight: .semibold))
                .foregroundStyle(Color.cdTextPrimary)
                .lineLimit(2)
                .minimumScaleFactor(0.7)
                .multilineTextAlignment(.center)

            Text(title)
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(Color.cdTextTertiary)
                .textCase(.uppercase)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CDSpacing.medium)
        .background(
            RoundedRectangle(cornerRadius: 12)
                .fill(Color.cdCardBackground)
        )
    }
}

// MARK: - Mileage Entry Sheet

struct MileageEntrySheet: View {
    let savedVehicle: SavedVehicle
    let initialMileage: Double?
    let onSave: (Double) -> Void

    @Environment(\.dismiss) private var dismiss
    @AppStorage("useMetricUnits") private var useMetricUnits = false
    @State private var mileageText: String = ""
    @FocusState private var isFocused: Bool

    private var units: UnitConverter { UnitConverter(useMetric: useMetricUnits) }

    var body: some View {
        NavigationStack {
            ZStack {
                Color.cdBackground.ignoresSafeArea()

                VStack(spacing: CDSpacing.xlarge) {
                    // Vehicle info
                    VStack(spacing: CDSpacing.small) {
                        Image(systemName: "car.side.fill")
                            .font(.system(size: 40))
                            .foregroundStyle(Color.cdPrimaryBright)

                        Text(savedVehicle.vehicle.displayName)
                            .font(.system(size: 18, weight: .semibold))
                            .foregroundStyle(Color.cdTextPrimary)
                    }
                    .padding(.top, CDSpacing.large)

                    // Mileage input
                    VStack(spacing: CDSpacing.small) {
                        Text("Current Mileage")
                            .font(.system(size: 14, weight: .medium))
                            .foregroundStyle(Color.cdTextSecondary)

                        HStack(spacing: CDSpacing.small) {
                            TextField("0", text: $mileageText)
                                .keyboardType(.numberPad)
                                .font(.system(size: 36, weight: .bold, design: .rounded))
                                .foregroundStyle(Color.cdTextPrimary)
                                .multilineTextAlignment(.center)
                                .focused($isFocused)

                            Text(units.shortDistanceUnit())
                                .font(.system(size: 24, weight: .medium))
                                .foregroundStyle(Color.cdTextTertiary)
                        }
                        .padding(.horizontal, CDSpacing.large)
                        .padding(.vertical, CDSpacing.medium)
                        .background(Color.cdCardBackgroundLight)
                        .clipShape(RoundedRectangle(cornerRadius: 14))
                    }

                    if let initial = initialMileage {
                        Text("OBD detected: \(units.distance(initial))")
                            .font(.system(size: 13))
                            .foregroundStyle(Color.cdSuccess)
                    }

                    Spacer()

                    // Save button
                    Button {
                        if let enteredValue = Double(mileageText.replacingOccurrences(of: ",", with: "")) {
                            // If metric, user entered km - convert back to miles for storage
                            let mileage = useMetricUnits ? enteredValue / 1.60934 : enteredValue
                            onSave(mileage)
                            dismiss()
                        }
                    } label: {
                        Text("Save Mileage")
                            .font(.system(size: 16, weight: .semibold))
                            .foregroundStyle(.white)
                            .frame(maxWidth: .infinity)
                            .padding(.vertical, 16)
                            .background(
                                Group {
                                    if mileageText.isEmpty {
                                        Color.cdTextTertiary
                                    } else {
                                        LinearGradient.cdPrimaryGradient
                                    }
                                }
                            )
                            .clipShape(RoundedRectangle(cornerRadius: 14))
                    }
                    .disabled(mileageText.isEmpty)
                    .padding(.bottom, CDSpacing.large)
                }
                .padding(.horizontal, CDSpacing.large)
            }
            .navigationTitle("Set Mileage")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                    .foregroundStyle(Color.cdTextSecondary)
                }
            }
            .onAppear {
                if let initial = initialMileage {
                    // Convert to km if metric for display
                    let displayValue = useMetricUnits ? initial * 1.60934 : initial
                    mileageText = String(format: "%.0f", displayValue)
                }
                isFocused = true
            }
        }
    }
}

// MARK: - Service Log Sheet

struct ServiceLogSheet: View {
    let savedVehicle: SavedVehicle
    let currentMileage: Double?
    let onSave: (Date, Double) -> Void

    @Environment(\.dismiss) private var dismiss
    @AppStorage("useMetricUnits") private var useMetricUnits = false
    @State private var serviceDate: Date = Date()
    @State private var mileageText: String = ""
    @FocusState private var isFocused: Bool

    private var units: UnitConverter { UnitConverter(useMetric: useMetricUnits) }

    var body: some View {
        NavigationStack {
            ZStack {
                Color.cdBackground.ignoresSafeArea()

                ScrollView {
                    VStack(spacing: CDSpacing.xlarge) {
                        // Vehicle info
                        VStack(spacing: CDSpacing.small) {
                            Image(systemName: "wrench.and.screwdriver.fill")
                                .font(.system(size: 40))
                                .foregroundStyle(Color.cdPrimaryBright)

                            Text(savedVehicle.vehicle.displayName)
                                .font(.system(size: 18, weight: .semibold))
                                .foregroundStyle(Color.cdTextPrimary)
                        }
                        .padding(.top, CDSpacing.large)

                        // Service date
                        VStack(alignment: .leading, spacing: CDSpacing.small) {
                            Text("SERVICE DATE")
                                .font(.system(size: 11, weight: .bold))
                                .foregroundStyle(Color.cdTextTertiary)
                                .tracking(0.5)

                            DatePicker(
                                "Service Date",
                                selection: $serviceDate,
                                in: ...Date(),
                                displayedComponents: .date
                            )
                            .datePickerStyle(.compact)
                            .labelsHidden()
                            .tint(Color.cdPrimaryBright)
                            .padding(CDSpacing.medium)
                            .frame(maxWidth: .infinity)
                            .background(Color.cdCardBackgroundLight)
                            .clipShape(RoundedRectangle(cornerRadius: 12))
                        }

                        // Mileage at service
                        VStack(alignment: .leading, spacing: CDSpacing.small) {
                            Text("MILEAGE AT SERVICE")
                                .font(.system(size: 11, weight: .bold))
                                .foregroundStyle(Color.cdTextTertiary)
                                .tracking(0.5)

                            HStack(spacing: CDSpacing.small) {
                                TextField("0", text: $mileageText)
                                    .keyboardType(.numberPad)
                                    .font(.system(size: 24, weight: .semibold))
                                    .foregroundStyle(Color.cdTextPrimary)
                                    .focused($isFocused)

                                Text(units.distanceUnit())
                                    .font(.system(size: 16))
                                    .foregroundStyle(Color.cdTextTertiary)
                            }
                            .padding(CDSpacing.medium)
                            .background(Color.cdCardBackgroundLight)
                            .clipShape(RoundedRectangle(cornerRadius: 12))

                            if let current = currentMileage {
                                Text("Current: \(units.distance(current))")
                                    .font(.system(size: 12))
                                    .foregroundStyle(Color.cdTextSecondary)
                            }
                        }

                        // Info about intervals
                        VStack(alignment: .leading, spacing: CDSpacing.small) {
                            HStack(spacing: CDSpacing.xs) {
                                Image(systemName: "info.circle.fill")
                                    .font(.system(size: 12))
                                    .foregroundStyle(Color.cdPrimaryBright)
                                Text("Service Intervals")
                                    .font(.system(size: 12, weight: .semibold))
                                    .foregroundStyle(Color.cdTextSecondary)
                            }

                            Text("Next oil change will be calculated as \(useMetricUnits ? "8,000 km" : "5,000 miles") or 6 months from service date, whichever comes first.")
                                .font(.system(size: 12))
                                .foregroundStyle(Color.cdTextTertiary)
                                .lineSpacing(2)
                        }
                        .padding(CDSpacing.medium)
                        .background(Color.cdCardBackground)
                        .clipShape(RoundedRectangle(cornerRadius: 12))

                        Spacer(minLength: 40)

                        // Save button
                        Button {
                            if let enteredValue = Double(mileageText.replacingOccurrences(of: ",", with: "")) {
                                // If metric, user entered km - convert back to miles for storage
                                let mileage = useMetricUnits ? enteredValue / 1.60934 : enteredValue
                                onSave(serviceDate, mileage)
                                dismiss()
                            }
                        } label: {
                            Text("Log Service")
                                .font(.system(size: 16, weight: .semibold))
                                .foregroundStyle(.white)
                                .frame(maxWidth: .infinity)
                                .padding(.vertical, 16)
                                .background(
                                    Group {
                                        if mileageText.isEmpty {
                                            Color.cdTextTertiary
                                        } else {
                                            LinearGradient.cdPrimaryGradient
                                        }
                                    }
                                )
                                .clipShape(RoundedRectangle(cornerRadius: 14))
                        }
                        .disabled(mileageText.isEmpty)
                    }
                    .padding(.horizontal, CDSpacing.large)
                    .padding(.bottom, CDSpacing.large)
                }
            }
            .navigationTitle("Log Oil Change")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .topBarLeading) {
                    Button("Cancel") {
                        dismiss()
                    }
                    .foregroundStyle(Color.cdTextSecondary)
                }
            }
            .onAppear {
                if let current = currentMileage {
                    mileageText = String(format: "%.0f", current)
                }
            }
        }
    }
}

// MARK: - Legacy Support

struct VehicleCard: View {
    let saved: SavedVehicle
    let isSelected: Bool
    let onTap: () -> Void

    var body: some View {
        VehicleListCard(saved: saved, isSelected: isSelected, onTap: onTap)
    }
}

#Preview {
    VehiclesView(
        selectedVehicle: .constant(.preview),
        selectedVehicleImage: .constant(nil),
        refreshTrigger: .constant(UUID()),
        liveData: .constant(nil)
    )
    .environmentObject(APIClient())
    .environmentObject(VehicleStore())
    .preferredColorScheme(.dark)
}
