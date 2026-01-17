//
//  HomeView.swift
//  ClearDrive
//
//  Luxury home dashboard with vehicle hero and live widgets
//

import SwiftUI
import Combine

// MARK: - Cached Async Image (handles cancellations better than SwiftUI's AsyncImage)

struct CachedAsyncImage<Content: View, Placeholder: View>: View {
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
        print("[CachedAsyncImage] Loading: \(url.absoluteString)")

        // Use URLSession with caching
        let config = URLSessionConfiguration.default
        config.requestCachePolicy = .returnCacheDataElseLoad
        config.urlCache = URLCache.shared
        let session = URLSession(configuration: config)

        let task = session.dataTask(with: url) { data, response, error in
            DispatchQueue.main.async {
                isLoading = false

                if let error = error {
                    print("[CachedAsyncImage] Error: \(error.localizedDescription)")
                    // Retry on cancellation (up to 3 times)
                    if (error as NSError).code == -999 && loadAttempt < 3 {
                        loadAttempt += 1
                        print("[CachedAsyncImage] Retrying (attempt \(loadAttempt))...")
                        DispatchQueue.main.asyncAfter(deadline: .now() + 0.5) {
                            loadImage()
                        }
                    }
                    return
                }

                if let data = data, let uiImage = UIImage(data: data) {
                    print("[CachedAsyncImage] SUCCESS")
                    loadedImage = uiImage
                } else {
                    print("[CachedAsyncImage] Failed to decode image data")
                }
            }
        }
        task.resume()
    }
}

struct HomeView: View {
    @EnvironmentObject var apiClient: APIClient
    @EnvironmentObject var vehicleStore: VehicleStore
    @AppStorage("useMetricUnits") private var useMetricUnits = false

    @Binding var selectedVehicle: VehicleInfo?
    @Binding var selectedVehicleImage: String?
    @Binding var obdStatus: OBDConnectionStatus
    @Binding var lastScanResult: ScanResult?
    @Binding var liveData: LiveOBDData?

    private var units: UnitConverter { UnitConverter(useMetric: useMetricUnits) }

    let onScanTap: () -> Void
    let onHistoryTap: () -> Void

    @State private var showingResults = false
    @State private var displayedImageURL: String?

    var body: some View {
        ZStack {
            // Rich gradient background that blends up toward the car
            ZStack {
                // Base color
                Color.cdBackground

                // Main vertical gradient - smooth transition
                LinearGradient(
                    stops: [
                        .init(color: Color(hex: "0D1210"), location: 0),
                        .init(color: Color(hex: "0A0E0C"), location: 0.3),
                        .init(color: Color.cdBackground, location: 0.6),
                        .init(color: Color(hex: "080A09"), location: 1.0)
                    ],
                    startPoint: .top,
                    endPoint: .bottom
                )

                // Subtle green ambient glow from top center (behind car area)
                RadialGradient(
                    stops: [
                        .init(color: Color.cdPrimaryBright.opacity(0.12), location: 0),
                        .init(color: Color.cdPrimary.opacity(0.06), location: 0.3),
                        .init(color: Color.cdPrimary.opacity(0.02), location: 0.5),
                        .init(color: Color.clear, location: 0.8)
                    ],
                    center: .init(x: 0.5, y: 0.15),
                    startRadius: 20,
                    endRadius: 400
                )

                // Secondary subtle warm accent
                RadialGradient(
                    stops: [
                        .init(color: Color(hex: "1A2420").opacity(0.5), location: 0),
                        .init(color: Color.clear, location: 1)
                    ],
                    center: .init(x: 0.5, y: 0.5),
                    startRadius: 100,
                    endRadius: 600
                )
            }
            .ignoresSafeArea()

            ScrollView(showsIndicators: false) {
                VStack(spacing: 0) {
                    // Vehicle hero with image
                    vehicleHero

                    // Content
                    VStack(spacing: CDSpacing.large) {
                        // Live data widgets
                        if selectedVehicle != nil {
                            liveDataSection
                        }

                        // Vehicle stats row
                        if selectedVehicle != nil {
                            vehicleStatsRow
                        }

                        // Error codes banner
                        if let result = lastScanResult, !result.codes.isEmpty {
                            errorCodesBanner(result)
                        }

                        // Quick actions
                        quickActionsSection
                    }
                    .padding(.bottom, 120) // Extra space for tab bar
                    .padding(.horizontal, CDSpacing.medium)
                    .padding(.top, CDSpacing.large)
                }
            }
        }
        .sheet(isPresented: $showingResults) {
            if let result = lastScanResult {
                ResultsView(result: result)
            }
        }
        .onAppear {
            updateDisplayedImageURL()
        }
        .onChange(of: lastScanResult?.vehicleImageURL) { _, newValue in
            print("[HomeView] lastScanResult.vehicleImageURL changed to: \(newValue ?? "nil")")
            updateDisplayedImageURL()
        }
        .onChange(of: selectedVehicleImage) { _, newValue in
            print("[HomeView] selectedVehicleImage changed to: \(newValue ?? "nil")")
            updateDisplayedImageURL()
        }
    }

    private func updateDisplayedImageURL() {
        let newURL = lastScanResult?.vehicleImageURL ?? selectedVehicleImage
        if displayedImageURL != newURL {
            print("[HomeView] URL changed: \(newURL ?? "nil")")
            displayedImageURL = newURL
        }
    }

    // MARK: - Vehicle Hero

    private var vehicleHero: some View {
        ZStack(alignment: .bottom) {
            // Smooth background gradient with multiple stops to prevent banding
            LinearGradient(
                stops: [
                    .init(color: Color.cdPrimary.opacity(0.18), location: 0),
                    .init(color: Color.cdPrimary.opacity(0.12), location: 0.2),
                    .init(color: Color.cdPrimary.opacity(0.06), location: 0.4),
                    .init(color: Color.cdPrimary.opacity(0.02), location: 0.6),
                    .init(color: Color.clear, location: 0.85),
                    .init(color: Color.clear, location: 1.0)
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            .frame(height: 400)

            VStack(spacing: CDSpacing.medium) {
                // Header
                HStack {
                    HStack(spacing: CDSpacing.small) {
                        Image("Logo")
                            .resizable()
                            .aspectRatio(contentMode: .fit)
                            .frame(width: 40, height: 40)
                            .clipShape(RoundedRectangle(cornerRadius: 10))

                        VStack(alignment: .leading, spacing: 2) {
                            Text("ClearDrive")
                                .font(.system(size: 22, weight: .bold))
                                .foregroundStyle(Color.cdTextPrimary)

                            Text(apiClient.isDemoMode ? "Demo Mode" : (obdStatus.isConnected ? "Connected" : "Ready"))
                                .font(.system(size: 11, weight: .medium))
                                .foregroundStyle(Color.cdTextTertiary)
                        }
                    }

                    Spacer()

                    // Connection status pill
                    HStack(spacing: 6) {
                        Circle()
                            .fill(obdStatus.isConnected ? Color.cdSuccess : Color.cdTextTertiary)
                            .frame(width: 8, height: 8)

                        Text(obdStatus.isConnected ? "Live" : "Offline")
                            .font(.system(size: 12, weight: .medium))
                            .foregroundStyle(Color.cdTextSecondary)
                    }
                    .padding(.horizontal, 12)
                    .padding(.vertical, 8)
                    .background(Color.cdCardBackground)
                    .clipShape(Capsule())
                }
                .padding(.horizontal, CDSpacing.medium)
                .padding(.top, CDSpacing.medium)

                Spacer()

                // Vehicle image
                if let vehicle = selectedVehicle {
                    // Logging moved to onChange handlers to prevent spam

                    VStack(spacing: CDSpacing.small) {
                        if let imageURL = displayedImageURL, let url = URL(string: imageURL) {
                            CachedAsyncImage(url: url) { image in
                                image
                                    .resizable()
                                    .aspectRatio(contentMode: .fit)
                                    .frame(width: 320, height: 200)
                                    .shadow(color: Color.black.opacity(0.5), radius: 20, y: 10)
                            } placeholder: {
                                ProgressView()
                                    .frame(width: 320, height: 200)
                            }
                            .frame(width: 320, height: 200)
                        } else {
                            carPlaceholder
                        }

                        Text(vehicle.displayName)
                            .font(.system(size: 20, weight: .semibold))
                            .foregroundStyle(Color.cdTextPrimary)

                        if let engine = vehicle.engine {
                            Text(engine)
                                .font(.system(size: 14))
                                .foregroundStyle(Color.cdTextSecondary)
                        }

                        // Vehicle type badges (Turbo, Supercharged, Hybrid, Electric)
                        if hasVehicleTypeBadges {
                            vehicleTypeBadges
                        }

                        // Health status badge
                        healthStatusBadge
                    }
                    // Stable ID based on vehicle only - image has its own ID
                    .id(vehicle.displayName)
                } else {
                    VStack(spacing: CDSpacing.medium) {
                        carPlaceholder

                        Text("No Vehicle Selected")
                            .font(.system(size: 20, weight: .semibold))
                            .foregroundStyle(Color.cdTextSecondary)

                        Text("Add your vehicle to get started")
                            .font(.system(size: 14))
                            .foregroundStyle(Color.cdTextTertiary)
                    }
                }

                Spacer().frame(height: CDSpacing.medium)
            }
        }
        .frame(height: 400)
    }

    private var carPlaceholder: some View {
        ZStack {
            Ellipse()
                .fill(
                    RadialGradient(
                        colors: [Color.cdPrimaryBright.opacity(0.2), Color.clear],
                        center: .center,
                        startRadius: 30,
                        endRadius: 120
                    )
                )
                .frame(width: 260, height: 130)
                .blur(radius: 25)

            Image(systemName: "car.side.fill")
                .font(.system(size: 100))
                .foregroundStyle(
                    LinearGradient(
                        colors: [Color.cdTextSecondary.opacity(0.6), Color.cdTextTertiary.opacity(0.3)],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )
        }
        .frame(width: 320, height: 200)
    }

    // MARK: - Health Status Badge

    private var healthStatusBadge: some View {
        Group {
            if let result = lastScanResult {
                Button {
                    showingResults = true
                } label: {
                    HStack(spacing: CDSpacing.small) {
                        Image(systemName: result.safetyRating.icon)
                            .font(.system(size: 14, weight: .semibold))
                            .shadow(color: result.safetyRating.color.opacity(0.5), radius: 4)

                        Text(healthStatusText(result.safetyRating))
                            .font(.system(size: 13, weight: .bold))
                    }
                    .foregroundStyle(
                        LinearGradient(
                            colors: [result.safetyRating.color, result.safetyRating.color.opacity(0.8)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
                    .padding(.horizontal, 16)
                    .padding(.vertical, 10)
                    .background(
                        ZStack {
                            RoundedRectangle(cornerRadius: 20)
                                .fill(result.safetyRating.color.opacity(0.12))
                            RoundedRectangle(cornerRadius: 20)
                                .fill(
                                    LinearGradient(
                                        colors: [Color.white.opacity(0.1), Color.clear],
                                        startPoint: .top,
                                        endPoint: .bottom
                                    )
                                )
                        }
                    )
                    .overlay(
                        RoundedRectangle(cornerRadius: 20)
                            .stroke(
                                LinearGradient(
                                    colors: [result.safetyRating.color.opacity(0.5), result.safetyRating.color.opacity(0.2)],
                                    startPoint: .topLeading,
                                    endPoint: .bottomTrailing
                                ),
                                lineWidth: 1
                            )
                    )
                    .shadow(color: result.safetyRating.color.opacity(0.3), radius: 8, y: 2)
                }
            } else {
                HStack(spacing: CDSpacing.small) {
                    Image(systemName: "questionmark.circle")
                        .font(.system(size: 14, weight: .medium))

                    Text("No Scan Yet")
                        .font(.system(size: 13, weight: .medium))
                }
                .foregroundStyle(Color.cdTextTertiary)
                .padding(.horizontal, 16)
                .padding(.vertical, 10)
                .background(
                    ZStack {
                        RoundedRectangle(cornerRadius: 20)
                            .fill(LinearGradient.cdCardGradientElevated)
                        RoundedRectangle(cornerRadius: 20)
                            .fill(LinearGradient.cdGlassGradient)
                    }
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 20)
                        .stroke(LinearGradient.cdGlassBorder, lineWidth: 0.5)
                )
            }
        }
    }

    private func healthStatusText(_ rating: SafetyRating) -> String {
        switch rating {
        case .safe: return "SAFE TO DRIVE"
        case .caution: return "CAUTION"
        case .critical: return "STOP - CHECK NOW"
        }
    }

    // MARK: - Vehicle Type Badges

    private var hasVehicleTypeBadges: Bool {
        guard let result = lastScanResult else {
            print("[HomeView] No lastScanResult - no badges")
            return false
        }
        print("[HomeView] Badge check: turbo=\(result.isTurbo) super=\(result.isSupercharged) hybrid=\(result.isHybrid) electric=\(result.isElectric)")
        return result.isTurbo || result.isSupercharged || result.isHybrid || result.isElectric
    }

    private var vehicleTypeBadges: some View {
        HStack(spacing: CDSpacing.small) {
            if lastScanResult?.isTurbo == true {
                VehicleTypeBadge(text: "TURBO", icon: "wind", color: .cdAccent)
            }
            if lastScanResult?.isSupercharged == true {
                VehicleTypeBadge(text: "SUPERCHARGED", icon: "bolt.fill", color: .cdWarning)
            }
            if lastScanResult?.isHybrid == true {
                VehicleTypeBadge(text: "HYBRID", icon: "leaf.fill", color: .cdSuccess)
            }
            if lastScanResult?.isElectric == true {
                VehicleTypeBadge(text: "ELECTRIC", icon: "bolt.car.fill", color: .cdPrimaryBright)
            }
        }
    }

    // MARK: - Demo Data (for screenshots)

    private var demoMileage: Double { 47832 }
    private var demoRPM: Double { 750 }
    private var demoSpeed: Double { 0 }
    private var demoCoolantTemp: Double { 192 }

    private var effectiveLiveData: LiveOBDData? {
        if apiClient.isDemoMode {
            return LiveOBDData(
                connected: true,
                rpm: demoRPM,
                speed: demoSpeed,
                coolantTemp: demoCoolantTemp,
                odometer: demoMileage,
                fuelLevel: 72  // Demo fuel level at 72%
            )
        }
        return liveData
    }

    // MARK: - Live Data Section

    private var liveDataSection: some View {
        VStack(spacing: CDSpacing.small) {
            HStack {
                SectionHeader(title: "Live Data")
                Spacer()
                if effectiveLiveData != nil {
                    HStack(spacing: 4) {
                        Circle()
                            .fill(Color.cdSuccess)
                            .frame(width: 6, height: 6)
                        Text(apiClient.isDemoMode ? "Demo" : "Live")
                            .font(.system(size: 11, weight: .medium))
                            .foregroundStyle(Color.cdSuccess)
                    }
                }
            }

            HStack(spacing: CDSpacing.small) {
                LiveDataWidget(
                    value: effectiveLiveData?.rpm != nil ? "\(Int(effectiveLiveData!.rpm!))" : "--",
                    label: "RPM",
                    icon: "gauge.high",
                    color: .cdPrimaryBright
                )
                LiveDataWidget(
                    value: effectiveLiveData?.speed != nil ? "\(Int(effectiveLiveData!.speed!))" : "--",
                    label: "MPH",
                    icon: "speedometer",
                    color: .cdAccent
                )
                LiveDataWidget(
                    value: effectiveLiveData?.coolantTemp != nil ? "\(Int(effectiveLiveData!.coolantTemp!))°" : "--",
                    label: "TEMP",
                    icon: "thermometer.medium",
                    color: demoTemperatureColor
                )
            }
        }
    }

    private var temperatureColor: Color {
        guard let temp = liveData?.coolantTemp else { return .cdPrimaryBright }
        if temp > 220 { return .cdCritical }
        if temp > 200 { return .cdWarning }
        return .cdSuccess
    }

    private var demoTemperatureColor: Color {
        guard let temp = effectiveLiveData?.coolantTemp else { return .cdPrimaryBright }
        if temp > 220 { return .cdCritical }
        if temp > 200 { return .cdWarning }
        return .cdSuccess
    }

    // MARK: - Vehicle Stats Row

    private var vehicleStatsRow: some View {
        VStack(spacing: CDSpacing.small) {
            // Top row: Mileage and Next Service (from OBD or demo)
            HStack(spacing: CDSpacing.small) {
                // Mileage - from live OBD data or demo
                InfoWidget(
                    title: "Mileage",
                    value: formatMileage(effectiveLiveData?.odometer),
                    subtitle: effectiveLiveData?.odometer != nil ? units.distanceUnit() : "",
                    icon: "road.lanes"
                )

                // Next Service - calculated or from OBD/demo
                InfoWidget(
                    title: "Next Service",
                    value: formatNextService(effectiveLiveData?.odometer),
                    subtitle: effectiveLiveData?.odometer != nil ? "\(units.shortDistanceUnit()) away" : "",
                    icon: "wrench.and.screwdriver"
                )
            }

            // Middle row: Engine, Transmission
            HStack(spacing: CDSpacing.small) {
                // Engine - show displacement + type (e.g., "5.0L V8")
                InfoWidget(
                    title: "Engine",
                    value: formatEngineDisplay(lastScanResult?.engine ?? selectedVehicle?.engine),
                    subtitle: enginePowerSubtitle,
                    icon: "engine.combustion"
                )

                // Transmission
                InfoWidget(
                    title: "Trans",
                    value: formatTransmission(lastScanResult?.transmission ?? selectedVehicle?.transmission),
                    subtitle: transmissionSubtitle,
                    icon: "gearshape.2.fill"
                )
            }

            // Third row: Drive, Gas Type
            HStack(spacing: CDSpacing.small) {
                // Drive Type
                InfoWidget(
                    title: "Drive",
                    value: formatDrive(lastScanResult?.drive ?? selectedVehicle?.driveType),
                    subtitle: "",
                    icon: "car.fill"
                )

                // Gas Type (Regular, Premium, Diesel)
                InfoWidget(
                    title: "Gas",
                    value: formatFuelType(lastScanResult?.fuelType ?? selectedVehicle?.fuelType),
                    subtitle: fuelSubtitle,
                    icon: "drop.fill"
                )
            }

            // Fourth row: MPG/L per 100km, Fuel Level
            HStack(spacing: CDSpacing.small) {
                // Fuel Economy - prefer scan result, fallback to vehicle info
                InfoWidget(
                    title: units.fuelEconomyUnit(),
                    value: mpgDisplayValue,
                    subtitle: mpgSubtitle,
                    icon: "gauge.with.dots.needle.33percent"
                )

                // Fuel Level % from OBD
                InfoWidget(
                    title: "Fuel %",
                    value: fuelLevelDisplay,
                    subtitle: fuelLevelSubtitle,
                    icon: "fuelpump.fill"
                )
            }

            // Fifth row: Mileage, Range
            HStack(spacing: CDSpacing.small) {
                // Mileage from OBD or saved
                InfoWidget(
                    title: "Mileage",
                    value: mileageDisplayValue,
                    subtitle: mileageSubtitle,
                    icon: "speedometer"
                )

                // Calculated Range (fuel % × tank × MPG)
                InfoWidget(
                    title: "Range",
                    value: calculatedRangeDisplay,
                    subtitle: rangeSubtitle,
                    icon: "road.lanes"
                )
            }
        }
    }

    // MARK: - Live Data Display Properties

    private var mpgDisplayValue: String {
        // Get city and highway values
        let city = lastScanResult?.mpgCity ?? selectedVehicle?.mpgCity
        let hwy = lastScanResult?.mpgHighway ?? selectedVehicle?.mpgHighway

        // Use unit converter to format based on metric setting
        return units.fuelEconomy(cityMpg: city, highwayMpg: hwy)
    }

    private var mpgSubtitle: String {
        if let city = lastScanResult?.mpgCity ?? selectedVehicle?.mpgCity,
           let hwy = lastScanResult?.mpgHighway ?? selectedVehicle?.mpgHighway,
           !city.isEmpty, !hwy.isEmpty {
            return "City/Hwy"
        }
        return ""
    }

    private var fuelLevelDisplay: String {
        if let fuel = liveData?.fuelLevel {
            return "\(fuel)%"
        }
        return "--"
    }

    private var fuelLevelSubtitle: String {
        if liveData?.fuelLevel != nil {
            return "LIVE"
        }
        return "Connect OBD"
    }

    private var mileageDisplayValue: String {
        // Prefer live OBD odometer, fallback to saved vehicle mileage
        if let odometer = liveData?.odometer {
            return formatMileage(odometer)
        }
        // Check if there's a saved vehicle with mileage
        if let saved = vehicleStore.savedVehicles.first(where: {
            $0.vehicle.year == selectedVehicle?.year &&
            $0.vehicle.make == selectedVehicle?.make &&
            $0.vehicle.model == selectedVehicle?.model
        }), let mileage = saved.currentMileage {
            return formatMileage(mileage)
        }
        return "--"
    }

    private var mileageSubtitle: String {
        if liveData?.odometer != nil {
            return "LIVE"
        }
        return units.distanceUnit()
    }

    private var calculatedRangeDisplay: String {
        // Calculate range from fuel % and MPG
        guard let fuelPercent = liveData?.fuelLevel else {
            // No live fuel data - show static estimate if available
            if let range = selectedVehicle?.estimatedRange {
                // Parse and convert if metric
                if useMetricUnits, let mi = Int(range.replacingOccurrences(of: " mi", with: "")) {
                    let km = Int(Double(mi) * 1.60934)
                    return "\(km) km"
                }
                return range
            }
            return "--"
        }

        // Get tank capacity and MPG
        let tankStr = lastScanResult?.tankCapacity ?? selectedVehicle?.tankCapacity ?? ""
        let mpgStr = lastScanResult?.mpgCombined ?? selectedVehicle?.mpgCombined ?? ""

        // Try to calculate from city/hwy average if combined not available
        var mpgValue: Double?
        if let mpg = Double(mpgStr), mpg > 0 {
            mpgValue = mpg
        } else if let city = Double(lastScanResult?.mpgCity ?? selectedVehicle?.mpgCity ?? ""),
                  let hwy = Double(lastScanResult?.mpgHighway ?? selectedVehicle?.mpgHighway ?? "") {
            mpgValue = (city + hwy) / 2
        }

        guard let tank = Double(tankStr), tank > 0,
              let mpg = mpgValue, mpg > 0 else {
            return "--"
        }

        let gallonsRemaining = tank * (Double(fuelPercent) / 100.0)
        let rangeMiles = Int(gallonsRemaining * mpg)
        return units.range(rangeMiles)
    }

    private var rangeSubtitle: String {
        if liveData?.fuelLevel != nil {
            return "LIVE"
        }
        if let tank = lastScanResult?.tankCapacity ?? selectedVehicle?.tankCapacity, !tank.isEmpty,
           let tankVal = Double(tank) {
            let converted = units.volume(tankVal)
            return String(format: "%.1f %@ tank", converted, units.volumeUnit())
        }
        return ""
    }

    private func formatMileage(_ odometer: Double?) -> String {
        guard let miles = odometer else { return "--" }
        // Convert to km if metric, and format with commas
        return units.distance(miles, includeUnit: false)
    }

    private func formatNextService(_ odometer: Double?) -> String {
        // Can't calculate without user entering their last service date/mileage
        // Returns "--" until service tracking is set up
        // TODO: Integrate with VehicleStore.serviceSchedule once user enters last service
        return "--"
    }

    private func formatEngineDisplay(_ engine: String?) -> String {
        guard let engine = engine, !engine.isEmpty else { return "--" }

        // Remove HP info in parentheses - just show displacement + type (e.g., "5.0L V8")
        var display = engine
        if let parenRange = display.range(of: #"\s*\([^)]*hp[^)]*\)"#, options: [.regularExpression, .caseInsensitive]) {
            display.removeSubrange(parenRange)
        }
        display = display.trimmingCharacters(in: .whitespaces)

        // Trim if still too long
        if display.count <= 14 {
            return display
        }
        return String(display.prefix(12)) + ".."
    }

    private var enginePowerSubtitle: String {
        guard let engine = lastScanResult?.engine ?? selectedVehicle?.engine else { return "" }
        // Extract horsepower if in the CarsXE data
        if let hpMatch = engine.range(of: #"\d+\s*hp"#, options: [.regularExpression, .caseInsensitive]) {
            return String(engine[hpMatch])
        }
        return ""
    }

    private func formatTransmission(_ transmission: String?) -> String {
        guard let trans = transmission, !trans.isEmpty else { return "--" }
        // Display CarsXE transmission data, trimmed if too long
        if trans.count <= 14 {
            return trans
        }
        return String(trans.prefix(12)) + ".."
    }

    private var transmissionSubtitle: String {
        return ""
    }

    private func formatDrive(_ drive: String?) -> String {
        guard let drive = drive?.lowercased() else { return "--" }
        if drive.contains("rear") { return "RWD" }
        if drive.contains("front") { return "FWD" }
        if drive.contains("all") || drive.contains("awd") { return "AWD" }
        if drive.contains("4") { return "4WD" }
        return drive.prefix(3).uppercased()
    }

    private func formatFuelType(_ fuel: String?) -> String {
        guard let fuel = fuel?.lowercased() else { return "--" }
        if fuel.contains("premium") { return "Premium" }
        if fuel.contains("diesel") { return "Diesel" }
        if fuel.contains("electric") { return "Electric" }
        if fuel.contains("e85") || fuel.contains("flex") { return "Flex" }
        return "Regular"
    }

    private var fuelSubtitle: String {
        if let fuel = lastScanResult?.fuelType ?? selectedVehicle?.fuelType {
            if fuel.lowercased().contains("premium") { return "91+ octane" }
            if fuel.lowercased().contains("diesel") { return "diesel" }
            if fuel.lowercased().contains("electric") { return "EV" }
            return "87 octane"
        }
        return ""
    }

    // MARK: - Error Codes Banner

    private func errorCodesBanner(_ result: ScanResult) -> some View {
        Button {
            showingResults = true
        } label: {
            HStack(spacing: CDSpacing.medium) {
                ZStack {
                    Circle()
                        .fill(Color.cdWarning.opacity(0.15))
                        .frame(width: 44, height: 44)

                    Image(systemName: "exclamationmark.triangle.fill")
                        .font(.system(size: 20))
                        .foregroundStyle(Color.cdWarning)
                }

                VStack(alignment: .leading, spacing: 2) {
                    Text("\(result.codes.count) Active Code\(result.codes.count == 1 ? "" : "s")")
                        .font(.system(size: 15, weight: .semibold))
                        .foregroundStyle(Color.cdTextPrimary)

                    Text(result.codes.map { $0.code }.joined(separator: ", "))
                        .font(.system(size: 13, design: .monospaced))
                        .foregroundStyle(Color.cdWarning)
                }

                Spacer()

                Text("View")
                    .font(.system(size: 13, weight: .semibold))
                    .foregroundStyle(Color.cdPrimaryBright)

                Image(systemName: "chevron.right")
                    .font(.system(size: 12, weight: .semibold))
                    .foregroundStyle(Color.cdTextTertiary)
            }
            .padding(CDSpacing.medium)
            .background(
                RoundedRectangle(cornerRadius: 16)
                    .fill(Color.cdCardBackground)
                    .overlay(
                        RoundedRectangle(cornerRadius: 16)
                            .stroke(Color.cdWarning.opacity(0.3), lineWidth: 1)
                    )
            )
        }
    }

    // MARK: - Quick Actions

    private var quickActionsSection: some View {
        VStack(spacing: CDSpacing.small) {
            SectionHeader(title: "Quick Actions")

            HStack(spacing: CDSpacing.small) {
                QuickActionButton(
                    title: "Run Scan",
                    icon: "magnifyingglass",
                    color: .cdPrimaryBright
                ) {
                    onScanTap()
                }

                QuickActionButton(
                    title: "History",
                    icon: "clock.fill",
                    color: .cdTextSecondary
                ) {
                    onHistoryTap()
                }

                if lastScanResult != nil {
                    QuickActionButton(
                        title: "Last Scan",
                        icon: "doc.text.fill",
                        color: .cdTextSecondary
                    ) {
                        showingResults = true
                    }
                }
            }
        }
    }
}

// MARK: - Live Data Widget

struct LiveDataWidget: View {
    let value: String
    let label: String
    let icon: String
    let color: Color

    var body: some View {
        VStack(spacing: CDSpacing.small) {
            ZStack {
                // Subtle glow behind icon
                Circle()
                    .fill(
                        RadialGradient(
                            colors: [color.opacity(0.3), Color.clear],
                            center: .center,
                            startRadius: 2,
                            endRadius: 20
                        )
                    )
                    .frame(width: 40, height: 40)

                Image(systemName: icon)
                    .font(.system(size: 20))
                    .foregroundStyle(
                        LinearGradient(
                            colors: [color, color.opacity(0.7)],
                            startPoint: .top,
                            endPoint: .bottom
                        )
                    )
            }

            Text(value)
                .font(.system(size: 28, weight: .bold, design: .rounded))
                .foregroundStyle(Color.cdTextPrimary)

            Text(label)
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(Color.cdTextTertiary)
                .tracking(1)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CDSpacing.medium)
        .background(
            ZStack {
                RoundedRectangle(cornerRadius: 16)
                    .fill(LinearGradient.cdCardGradientElevated)
                RoundedRectangle(cornerRadius: 16)
                    .fill(LinearGradient.cdGlassGradient)
                // Color tint at top
                RoundedRectangle(cornerRadius: 16)
                    .fill(
                        LinearGradient(
                            colors: [color.opacity(0.08), Color.clear],
                            startPoint: .top,
                            endPoint: .center
                        )
                    )
            }
        )
        .overlay(
            RoundedRectangle(cornerRadius: 16)
                .stroke(
                    LinearGradient(
                        colors: [color.opacity(0.3), color.opacity(0.1), Color.white.opacity(0.05)],
                        startPoint: .topLeading,
                        endPoint: .bottomTrailing
                    ),
                    lineWidth: 1
                )
        )
    }
}

// MARK: - Info Widget

struct InfoWidget: View {
    let title: String
    let value: String
    let subtitle: String
    let icon: String
    var valueColor: Color = .cdTextPrimary

    var body: some View {
        VStack(spacing: CDSpacing.xs) {
            Image(systemName: icon)
                .font(.system(size: 16))
                .foregroundStyle(
                    LinearGradient(
                        colors: [Color.cdPrimaryBright.opacity(0.8), Color.cdTextTertiary],
                        startPoint: .top,
                        endPoint: .bottom
                    )
                )

            Text(value)
                .font(.system(size: 16, weight: .bold, design: .rounded))
                .foregroundStyle(valueColor)
                .lineLimit(2)
                .minimumScaleFactor(0.7)
                .multilineTextAlignment(.center)

            if !subtitle.isEmpty {
                Text(subtitle)
                    .font(.system(size: 10))
                    .foregroundStyle(Color.cdTextTertiary)
                    .lineLimit(1)
            }

            Text(title)
                .font(.system(size: 9, weight: .medium))
                .foregroundStyle(Color.cdTextTertiary)
                .textCase(.uppercase)
                .tracking(0.5)
        }
        .frame(maxWidth: .infinity)
        .padding(.vertical, CDSpacing.medium)
        .padding(.horizontal, CDSpacing.xs)
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

// MARK: - Quick Action Button

struct QuickActionButton: View {
    let title: String
    let icon: String
    let color: Color
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            VStack(spacing: CDSpacing.small) {
                ZStack {
                    // Glow behind icon
                    Circle()
                        .fill(
                            RadialGradient(
                                colors: [color.opacity(0.3), color.opacity(0.1), Color.clear],
                                center: .center,
                                startRadius: 5,
                                endRadius: 30
                            )
                        )
                        .frame(width: 56, height: 56)

                    Circle()
                        .fill(
                            LinearGradient(
                                colors: [color.opacity(0.25), color.opacity(0.1)],
                                startPoint: .topLeading,
                                endPoint: .bottomTrailing
                            )
                        )
                        .frame(width: 50, height: 50)
                        .overlay(
                            Circle()
                                .stroke(color.opacity(0.3), lineWidth: 1)
                        )

                    Image(systemName: icon)
                        .font(.system(size: 20, weight: .medium))
                        .foregroundStyle(
                            LinearGradient(
                                colors: [color, color.opacity(0.8)],
                                startPoint: .top,
                                endPoint: .bottom
                            )
                        )
                }

                Text(title)
                    .font(.system(size: 12, weight: .medium))
                    .foregroundStyle(Color.cdTextSecondary)
            }
            .frame(maxWidth: .infinity)
            .padding(.vertical, CDSpacing.medium)
            .background(
                ZStack {
                    RoundedRectangle(cornerRadius: 16)
                        .fill(LinearGradient.cdCardGradientElevated)
                    RoundedRectangle(cornerRadius: 16)
                        .fill(LinearGradient.cdGlassGradient)
                }
            )
            .overlay(
                RoundedRectangle(cornerRadius: 16)
                    .stroke(LinearGradient.cdGlassBorder, lineWidth: 0.5)
            )
        }
    }
}

// MARK: - Vehicle Type Badge

struct VehicleTypeBadge: View {
    let text: String
    let icon: String
    let color: Color

    var body: some View {
        HStack(spacing: 4) {
            Image(systemName: icon)
                .font(.system(size: 10, weight: .bold))
            Text(text)
                .font(.system(size: 9, weight: .bold))
                .tracking(0.5)
        }
        .foregroundStyle(color)
        .padding(.horizontal, 8)
        .padding(.vertical, 5)
        .background(
            Capsule()
                .fill(color.opacity(0.15))
        )
        .overlay(
            Capsule()
                .stroke(color.opacity(0.3), lineWidth: 0.5)
        )
    }
}

// MARK: - Legacy Support

struct StatCard: View {
    let value: String
    let label: String
    let icon: String

    var body: some View {
        LiveDataWidget(value: value, label: label, icon: icon, color: .cdPrimaryBright)
    }
}

#Preview {
    HomeView(
        selectedVehicle: .constant(.preview),
        selectedVehicleImage: .constant(nil),
        obdStatus: .constant(.connected),
        lastScanResult: .constant(.preview),
        liveData: .constant(nil),
        onScanTap: {},
        onHistoryTap: {}
    )
    .environmentObject(APIClient())
    .environmentObject(VehicleStore())
    .preferredColorScheme(.dark)
}
