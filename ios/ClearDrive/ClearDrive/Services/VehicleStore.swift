//
//  VehicleStore.swift
//  ClearDrive
//
//  Manages saved vehicles and scan history
//

import Foundation
import SwiftUI
import Combine

@MainActor
class VehicleStore: ObservableObject {
    @Published var savedVehicles: [SavedVehicle] = []
    @Published var scanHistory: [ScanResult] = []

    private let vehiclesKey = "savedVehicles"
    private let historyKey = "scanHistory"

    init() {
        loadVehicles()
        loadScanHistory()
    }

    // MARK: - Vehicle Management

    func saveVehicle(_ vehicle: VehicleInfo, imageURL: String? = nil, trimId: String? = nil, scanResult: ScanResult? = nil) {
        // Determine the effective image URL - use provided one or fall back to scan result
        let effectiveImageURL = imageURL ?? scanResult?.vehicleImageURL

        print("[VehicleStore] Saving vehicle: \(vehicle.displayName)")
        print("  - imageURL param: \(imageURL ?? "nil")")
        print("  - effectiveImageURL: \(effectiveImageURL ?? "nil")")
        print("  - hasScanResult: \(scanResult != nil)")
        if let result = scanResult {
            print("  - scanResult.vehicleImageURL: \(result.vehicleImageURL ?? "nil")")
            print("  - scanResult.dontPanic: \(result.dontPanic?.prefix(50) ?? "nil")...")
        }

        // Check if already saved
        if let index = savedVehicles.firstIndex(where: { $0.vehicle.year == vehicle.year && $0.vehicle.make == vehicle.make && $0.vehicle.model == vehicle.model && $0.vehicle.trim == vehicle.trim }) {
            // Update existing - create new ID to force SwiftUI view refresh
            print("[VehicleStore] Updating existing vehicle at index \(index)")
            let existing = savedVehicles[index]
            let updated = SavedVehicle(
                id: UUID(),  // New ID forces SwiftUI to recreate the view
                vehicle: vehicle,
                imageURL: effectiveImageURL ?? existing.imageURL,
                trimId: existing.trimId,
                dateAdded: existing.dateAdded,
                lastScanned: Date(),
                lastScanResult: scanResult ?? existing.lastScanResult
            )
            print("[VehicleStore] Updated vehicle lastScanResult.vehicleImageURL: \(updated.lastScanResult?.vehicleImageURL ?? "nil")")
            // Force SwiftUI to recognize change
            objectWillChange.send()
            savedVehicles.remove(at: index)
            savedVehicles.insert(updated, at: 0)  // Move to top of list
            print("[VehicleStore] Updated imageURL: \(updated.imageURL ?? "nil")")
        } else {
            // Add new
            print("[VehicleStore] Adding new vehicle")
            let saved = SavedVehicle(
                vehicle: vehicle,
                imageURL: effectiveImageURL,
                trimId: trimId,
                dateAdded: Date(),
                lastScanned: Date(),
                lastScanResult: scanResult
            )
            savedVehicles.insert(saved, at: 0)
            print("[VehicleStore] Saved new vehicle with imageURL: \(effectiveImageURL ?? "nil")")
        }
        persistVehicles()
    }

    func updateVehicleScanResult(_ vehicle: VehicleInfo, scanResult: ScanResult) {
        if let index = savedVehicles.firstIndex(where: { $0.vehicle.year == vehicle.year && $0.vehicle.make == vehicle.make && $0.vehicle.model == vehicle.model && $0.vehicle.trim == vehicle.trim }) {
            savedVehicles[index].lastScanned = Date()
            savedVehicles[index].lastScanResult = scanResult
            persistVehicles()
        }
    }

    func removeVehicle(_ saved: SavedVehicle) {
        savedVehicles.removeAll { $0.id == saved.id }
        persistVehicles()
    }

    func updateMileage(for vehicleId: UUID, mileage: Double) {
        if let index = savedVehicles.firstIndex(where: { $0.id == vehicleId }) {
            savedVehicles[index].currentMileage = mileage
            persistVehicles()
            print("[VehicleStore] Updated mileage for \(savedVehicles[index].vehicle.displayName): \(mileage)")
        }
    }

    func updateServiceInfo(for vehicleId: UUID, date: Date, mileage: Double) {
        if let index = savedVehicles.firstIndex(where: { $0.id == vehicleId }) {
            savedVehicles[index].lastOilChangeDate = date
            savedVehicles[index].lastOilChangeMileage = mileage
            persistVehicles()
            print("[VehicleStore] Updated service info for \(savedVehicles[index].vehicle.displayName): date=\(date), mileage=\(mileage)")
        }
    }

    // MARK: - Scan History

    func addScanResult(_ result: ScanResult) {
        scanHistory.insert(result, at: 0)
        // Keep last 50 scans
        if scanHistory.count > 50 {
            scanHistory = Array(scanHistory.prefix(50))
        }
        persistScanHistory()
    }

    private func loadScanHistory() {
        if let data = UserDefaults.standard.data(forKey: historyKey) {
            do {
                let decoded = try JSONDecoder().decode([ScanResult].self, from: data)
                scanHistory = decoded
                print("[VehicleStore] Loaded \(decoded.count) scan history items")
            } catch {
                print("[VehicleStore] Failed to decode scan history: \(error)")
                UserDefaults.standard.removeObject(forKey: historyKey)
                scanHistory = []
            }
        }
    }

    private func persistScanHistory() {
        do {
            let encoded = try JSONEncoder().encode(scanHistory)
            UserDefaults.standard.set(encoded, forKey: historyKey)
            print("[VehicleStore] Saved \(scanHistory.count) scan history items")
        } catch {
            print("[VehicleStore] Failed to encode scan history: \(error)")
        }
    }

    // MARK: - Persistence

    private func loadVehicles() {
        if let data = UserDefaults.standard.data(forKey: vehiclesKey) {
            do {
                let decoded = try JSONDecoder().decode([SavedVehicle].self, from: data)
                savedVehicles = decoded
                print("[VehicleStore] Loaded \(decoded.count) vehicles")
                for vehicle in decoded {
                    print("  - \(vehicle.vehicle.displayName)")
                    print("    imageURL: \(vehicle.imageURL ?? "nil")")
                    print("    scanResult.imageURL: \(vehicle.lastScanResult?.vehicleImageURL ?? "nil")")
                    print("    hasScanResult: \(vehicle.lastScanResult != nil)")
                }
            } catch {
                print("[VehicleStore] Failed to decode vehicles: \(error)")
                // Clear corrupted data
                UserDefaults.standard.removeObject(forKey: vehiclesKey)
                savedVehicles = []
            }
        } else {
            print("[VehicleStore] No saved vehicles found in UserDefaults")
        }
    }

    private func persistVehicles() {
        do {
            let encoded = try JSONEncoder().encode(savedVehicles)
            UserDefaults.standard.set(encoded, forKey: vehiclesKey)
            print("[VehicleStore] Saved \(savedVehicles.count) vehicles")
        } catch {
            print("[VehicleStore] Failed to encode vehicles: \(error)")
        }
    }

    /// Clear all saved vehicles
    func clearAllVehicles() {
        savedVehicles = []
        UserDefaults.standard.removeObject(forKey: vehiclesKey)
        print("[VehicleStore] Cleared all vehicles")
    }

    /// Clear all scan history
    func clearAllHistory() {
        scanHistory = []
        UserDefaults.standard.removeObject(forKey: historyKey)
        print("[VehicleStore] Cleared all scan history")
    }

    /// Clear everything (vehicles and history)
    func clearAllData() {
        clearAllVehicles()
        clearAllHistory()
        print("[VehicleStore] Cleared all data")
    }
}

// MARK: - Saved Vehicle Model

struct SavedVehicle: Identifiable, Codable {
    let id: UUID
    var vehicle: VehicleInfo
    var imageURL: String?
    var trimId: String?
    var dateAdded: Date
    var lastScanned: Date
    var lastScanResult: ScanResult?

    // Service tracking
    var currentMileage: Double?
    var lastOilChangeDate: Date?
    var lastOilChangeMileage: Double?

    init(id: UUID = UUID(), vehicle: VehicleInfo, imageURL: String? = nil, trimId: String? = nil, dateAdded: Date = Date(), lastScanned: Date = Date(), lastScanResult: ScanResult? = nil, currentMileage: Double? = nil, lastOilChangeDate: Date? = nil, lastOilChangeMileage: Double? = nil) {
        self.id = id
        self.vehicle = vehicle
        self.imageURL = imageURL
        self.trimId = trimId
        self.dateAdded = dateAdded
        self.lastScanned = lastScanned
        self.lastScanResult = lastScanResult
        self.currentMileage = currentMileage
        self.lastOilChangeDate = lastOilChangeDate
        self.lastOilChangeMileage = lastOilChangeMileage
    }

    // Custom decoder to handle missing fields in old data
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        vehicle = try container.decode(VehicleInfo.self, forKey: .vehicle)
        imageURL = try container.decodeIfPresent(String.self, forKey: .imageURL)
        trimId = try container.decodeIfPresent(String.self, forKey: .trimId)
        dateAdded = try container.decodeIfPresent(Date.self, forKey: .dateAdded) ?? Date()
        lastScanned = try container.decodeIfPresent(Date.self, forKey: .lastScanned) ?? Date()
        lastScanResult = try container.decodeIfPresent(ScanResult.self, forKey: .lastScanResult)
        currentMileage = try container.decodeIfPresent(Double.self, forKey: .currentMileage)
        lastOilChangeDate = try container.decodeIfPresent(Date.self, forKey: .lastOilChangeDate)
        lastOilChangeMileage = try container.decodeIfPresent(Double.self, forKey: .lastOilChangeMileage)
    }

    enum CodingKeys: String, CodingKey {
        case id, vehicle, imageURL, trimId, dateAdded, lastScanned, lastScanResult
        case currentMileage, lastOilChangeDate, lastOilChangeMileage
    }

    // Calculate next oil change
    var nextOilChangeMileage: Double? {
        guard let lastMileage = lastOilChangeMileage else { return nil }
        // Standard interval: 5,000 miles for conventional, 7,500 for synthetic
        let interval: Double = 5000
        return lastMileage + interval
    }

    var nextOilChangeDate: Date? {
        guard let lastDate = lastOilChangeDate else { return nil }
        // Standard interval: 6 months
        return Calendar.current.date(byAdding: .month, value: 6, to: lastDate)
    }

    var milesUntilOilChange: Int? {
        guard let nextMileage = nextOilChangeMileage, let current = currentMileage else { return nil }
        return max(0, Int(nextMileage - current))
    }

    var isOilChangeOverdue: Bool {
        if let milesLeft = milesUntilOilChange, milesLeft <= 0 { return true }
        if let nextDate = nextOilChangeDate, nextDate < Date() { return true }
        return false
    }
}
