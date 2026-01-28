//
//  ContentView.swift
//  ClearDrive
//
//  Main tab navigation with luxury styling
//

import SwiftUI
import Combine

struct ContentView: View {
    @StateObject private var apiClient = APIClient()
    @StateObject private var vehicleStore = VehicleStore()
    @StateObject private var obdManager = OBDManager()

    @State private var selectedTab = 0
    @State private var selectedVehicle: VehicleInfo?
    @State private var selectedVehicleImage: String?
    @State private var obdStatus: OBDConnectionStatus = .disconnected
    @State private var lastScanResult: ScanResult?
    @State private var liveData: LiveOBDData?
    @State private var vehicleRefreshTrigger = UUID()  // Trigger to force VehiclesView refresh

    // Live data polling timer
    @State private var liveDataTimer: Timer?
    @State private var isPollingLiveData = false

    init() {
        // Style the tab bar
        let appearance = UITabBarAppearance()
        appearance.configureWithOpaqueBackground()
        appearance.backgroundColor = UIColor(Color.cdBackground)

        // Unselected state
        appearance.stackedLayoutAppearance.normal.iconColor = UIColor(Color.cdTextTertiary)
        appearance.stackedLayoutAppearance.normal.titleTextAttributes = [
            .foregroundColor: UIColor(Color.cdTextTertiary)
        ]

        // Selected state
        appearance.stackedLayoutAppearance.selected.iconColor = UIColor(Color.cdPrimaryBright)
        appearance.stackedLayoutAppearance.selected.titleTextAttributes = [
            .foregroundColor: UIColor(Color.cdPrimaryBright)
        ]

        UITabBar.appearance().standardAppearance = appearance
        UITabBar.appearance().scrollEdgeAppearance = appearance

        // Navigation bar styling
        let navAppearance = UINavigationBarAppearance()
        navAppearance.configureWithOpaqueBackground()
        navAppearance.backgroundColor = UIColor(Color.cdBackground)
        navAppearance.titleTextAttributes = [.foregroundColor: UIColor(Color.cdTextPrimary)]
        navAppearance.largeTitleTextAttributes = [.foregroundColor: UIColor(Color.cdTextPrimary)]

        UINavigationBar.appearance().standardAppearance = navAppearance
        UINavigationBar.appearance().scrollEdgeAppearance = navAppearance
    }

    var body: some View {
        TabView(selection: $selectedTab) {
            HomeView(
                selectedVehicle: $selectedVehicle,
                selectedVehicleImage: $selectedVehicleImage,
                obdStatus: $obdStatus,
                lastScanResult: $lastScanResult,
                liveData: $liveData,
                onScanTap: { selectedTab = 1 },
                onHistoryTap: { selectedTab = 3 }
            )
            .tabItem {
                Image(systemName: "house.fill")
                Text("Home")
            }
            .tag(0)

            ScanView(
                selectedVehicle: $selectedVehicle,
                selectedVehicleImage: $selectedVehicleImage,
                obdStatus: $obdStatus,
                lastScanResult: $lastScanResult,
                liveData: $liveData
            )
            .tabItem {
                Image(systemName: "magnifyingglass")
                Text("Scan")
            }
            .tag(1)

            VehiclesView(
                selectedVehicle: $selectedVehicle,
                selectedVehicleImage: $selectedVehicleImage,
                refreshTrigger: $vehicleRefreshTrigger,
                liveData: $liveData
            )
            .tabItem {
                Image(systemName: "car.2.fill")
                Text("Vehicles")
            }
            .tag(2)

            HistoryView()
                .tabItem {
                    Image(systemName: "clock.fill")
                    Text("History")
                }
                .tag(3)

            NavigationStack {
                SettingsView()
            }
            .tabItem {
                Image(systemName: "gearshape.fill")
                Text("Settings")
            }
            .tag(4)
        }
        .tint(.cdPrimaryBright)
        .environmentObject(apiClient)
        .environmentObject(vehicleStore)
        .environmentObject(obdManager)
        .preferredColorScheme(.dark)
        .onAppear {
            loadMostRecentVehicle()
        }
        .onChange(of: selectedVehicle) { _, newVehicle in
            loadScanResultForVehicle(newVehicle)
        }
        .onChange(of: lastScanResult?.id) { _, _ in
            // When a new scan completes, trigger VehiclesView refresh
            vehicleRefreshTrigger = UUID()
        }
        .onChange(of: obdManager.connectionState) { oldState, newState in
            handleOBDConnectionChange(from: oldState, to: newState)
        }
        .onDisappear {
            stopLiveDataPolling()
        }
    }

    // MARK: - Live Data Polling

    private func handleOBDConnectionChange(from oldState: OBDConnectionState, to newState: OBDConnectionState) {
        // Update OBD status
        switch newState {
        case .disconnected:
            obdStatus = .disconnected
            stopLiveDataPolling()
        case .connecting:
            obdStatus = .connecting
        case .connected, .ready:
            obdStatus = .connected
            if newState == .ready {
                startLiveDataPolling()
            }
        case .scanning:
            obdStatus = .connecting
        case .error(let msg):
            obdStatus = .error(msg)
            stopLiveDataPolling()
        }
    }

    private func startLiveDataPolling() {
        guard !isPollingLiveData else { return }
        isPollingLiveData = true
        slowPollCounter = 0  // Reset counter so fuel/odometer read immediately

        print("[ContentView] Starting live data polling (500ms interval)")

        // Set connected state immediately so UI shows LIVE indicator
        liveData = LiveOBDData(
            connected: true,
            rpm: nil,
            speed: nil,
            coolantTemp: nil,
            odometer: nil,
            fuelLevel: nil
        )

        // Poll immediately to get data
        pollLiveData()

        // Set up timer to poll every 500ms
        liveDataTimer = Timer.scheduledTimer(withTimeInterval: 0.5, repeats: true) { _ in
            pollLiveData()
        }
    }

    private func stopLiveDataPolling() {
        guard isPollingLiveData else { return }
        isPollingLiveData = false

        print("[ContentView] Stopping live data polling")

        liveDataTimer?.invalidate()
        liveDataTimer = nil
        liveData = nil
    }

    @State private var slowPollCounter: Int = 0

    private func pollLiveData() {
        guard obdManager.connectionState == .ready else { return }

        Task {
            // Use fast read (only RPM, speed, coolant) for responsive real-time display
            let data = await obdManager.readLiveDataFast()

            // Every 10th poll (~5 seconds), also read fuel level and odometer
            var fuelLevel = liveData?.fuelLevel
            var odometer = liveData?.odometer

            await MainActor.run {
                slowPollCounter += 1
            }

            // On first poll (counter=1) or every 10th poll (~5 seconds), read fuel & odometer
            if slowPollCounter <= 1 || slowPollCounter % 10 == 0 {
                // Read slower-changing values less frequently
                if let fuel = await obdManager.readFuelLevel() {
                    fuelLevel = fuel
                }
                if let odo = await obdManager.readOdometer() {
                    odometer = odo
                }
            }

            await MainActor.run {
                liveData = LiveOBDData(
                    connected: true,
                    rpm: data.rpm != nil ? Double(data.rpm!) : nil,
                    speed: data.speed != nil ? Double(data.speed!) : nil,
                    coolantTemp: data.coolant != nil ? Double(data.coolant!) : nil,
                    odometer: odometer,
                    fuelLevel: fuelLevel
                )
            }
        }
    }

    private func loadMostRecentVehicle() {
        // Load the most recently scanned vehicle on app launch
        if let mostRecent = vehicleStore.savedVehicles.first {
            selectedVehicle = mostRecent.vehicle
            // Try saved imageURL first, then fall back to scan result's imageURL
            selectedVehicleImage = mostRecent.imageURL ?? mostRecent.lastScanResult?.vehicleImageURL
            lastScanResult = mostRecent.lastScanResult
            print("[ContentView] Loaded most recent: \(mostRecent.vehicle.displayName), imageURL: \(selectedVehicleImage ?? "nil")")
        }
    }

    private func loadScanResultForVehicle(_ vehicle: VehicleInfo?) {
        guard let vehicle = vehicle else {
            lastScanResult = nil
            selectedVehicleImage = nil
            return
        }

        // Find the saved vehicle and load its scan result
        if let saved = vehicleStore.savedVehicles.first(where: {
            $0.vehicle.year == vehicle.year &&
            $0.vehicle.make == vehicle.make &&
            $0.vehicle.model == vehicle.model
        }) {
            lastScanResult = saved.lastScanResult
            // Only update image if we have one saved (don't overwrite with nil)
            if let savedImageURL = saved.imageURL {
                selectedVehicleImage = savedImageURL
            }
            // Also check the scan result for image URL
            if selectedVehicleImage == nil, let resultImageURL = saved.lastScanResult?.vehicleImageURL {
                selectedVehicleImage = resultImageURL
            }
            print("[ContentView] Loaded vehicle: \(vehicle.displayName), imageURL: \(selectedVehicleImage ?? "nil")")
        } else {
            // New vehicle not yet scanned - clear stale data from previous vehicle
            lastScanResult = nil
            selectedVehicleImage = nil
            print("[ContentView] New vehicle \(vehicle.displayName) - cleared stale scan data")
        }
    }
}

#Preview {
    ContentView()
}
