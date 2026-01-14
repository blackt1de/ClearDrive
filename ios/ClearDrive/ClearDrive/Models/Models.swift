//
//  Models.swift
//  ClearDrive
//
//  Data models for the app
//

import Foundation
import SwiftUI

// MARK: - Vehicle Info

struct VehicleInfo: Codable, Identifiable, Equatable {
    var id: UUID = UUID()
    var vin: String?
    var year: String
    var make: String
    var model: String
    var trim: String?
    var engine: String?
    var fuelType: String?
    var driveType: String?
    var transmission: String?
    var bodyStyle: String?

    // Performance specs
    var horsepower: String?
    var torque: String?

    // Fuel economy
    var mpgCity: String?
    var mpgHighway: String?
    var mpgCombined: String?
    var tankCapacity: String?

    // Colors
    var colorsExterior: [VehicleColor]?
    var colorsInterior: [VehicleColor]?

    // Vehicle type flags
    var isTruck: Bool?
    var isElectric: Bool?
    var isPluginHybrid: Bool?

    var displayName: String {
        let trimStr = trim ?? ""
        return "\(year) \(make) \(model) \(trimStr)".trimmingCharacters(in: .whitespaces)
    }

    // Computed MPG display string
    var mpgDisplay: String? {
        if let city = mpgCity, let hwy = mpgHighway, !city.isEmpty, !hwy.isEmpty {
            return "\(city)/\(hwy)"
        }
        return mpgCombined
    }

    // Estimated range based on tank and MPG
    var estimatedRange: String? {
        guard let tank = tankCapacity, let tankVal = Double(tank),
              let combined = mpgCombined, let mpgVal = Double(combined) else {
            // Try city/highway average
            guard let tank = tankCapacity, let tankVal = Double(tank),
                  let city = mpgCity, let cityVal = Double(city),
                  let hwy = mpgHighway, let hwyVal = Double(hwy) else {
                return nil
            }
            let avgMpg = (cityVal + hwyVal) / 2
            return "\(Int(tankVal * avgMpg)) mi"
        }
        return "\(Int(tankVal * mpgVal)) mi"
    }

    static var empty: VehicleInfo {
        VehicleInfo(year: "", make: "", model: "")
    }

    static var preview: VehicleInfo {
        VehicleInfo(
            vin: "JTE7654321",
            year: "2014",
            make: "Toyota",
            model: "Land Cruiser",
            trim: "Base",
            engine: "5.7L V8 DOHC",
            fuelType: "Gasoline",
            driveType: "4WD",
            transmission: "6-Speed Automatic",
            horsepower: "381",
            torque: "401",
            mpgCity: "13",
            mpgHighway: "18",
            mpgCombined: "15",
            tankCapacity: "24.6"
        )
    }
}

// MARK: - Vehicle Color

struct VehicleColor: Codable, Equatable, Identifiable {
    var id: String { name }
    let name: String
    let rgb: String

    var color: Color {
        let components = rgb.split(separator: ",").compactMap { Double($0.trimmingCharacters(in: .whitespaces)) }
        guard components.count == 3 else { return .gray }
        return Color(red: components[0] / 255, green: components[1] / 255, blue: components[2] / 255)
    }
}

// MARK: - Trim

struct Trim: Identifiable, Codable {
    let id: String
    let name: String

    enum CodingKeys: String, CodingKey {
        case id, name
    }

    init(id: String, name: String) {
        self.id = id
        self.name = name
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        // Handle both string and int IDs from API
        if let intId = try? container.decode(Int.self, forKey: .id) {
            id = String(intId)
        } else {
            id = try container.decode(String.self, forKey: .id)
        }
        name = try container.decode(String.self, forKey: .name)
    }
}

// MARK: - DTC Code

struct DTCCode: Identifiable, Codable {
    var id: String { code }
    let code: String
    let description: String
    let severity: String?

    var severityRating: SafetyRating {
        guard let severity = severity else { return .safe }
        return SafetyRating(from: severity)
    }
}

// MARK: - Live OBD Data

struct LiveOBDData: Codable {
    let connected: Bool
    let rpm: Double?
    let speed: Double?
    let coolantTemp: Double?
    let odometer: Double?

    enum CodingKeys: String, CodingKey {
        case connected
        case rpm
        case speed
        case coolantTemp = "coolant_temp"
        case odometer
    }

    init(connected: Bool, rpm: Double?, speed: Double?, coolantTemp: Double?, odometer: Double? = nil) {
        self.connected = connected
        self.rpm = rpm
        self.speed = speed
        self.coolantTemp = coolantTemp
        self.odometer = odometer
    }
}

// MARK: - Scan Result

struct ScanResult: Identifiable, Codable {
    var id: UUID = UUID()
    let vehicle: VehicleInfo
    let codes: [DTCCode]
    let safetyRating: SafetyRating
    let timestamp: Date

    enum CodingKeys: String, CodingKey {
        case id, vehicle, codes, safetyRating, timestamp
        case dontPanic, likelyCauses, symptoms, ifIgnored
        case quickChecks, diyFix, urgency, repairCost
        case knownIssues, ownerReports
        case engine, drive, fuelType, transmission
        case isTurbo, isSupercharged, isHybrid, isElectric
        case dataSources, obdSource
        case rpm, speed, coolantTemp
        case vehicleImageURL
    }

    // Custom decoder to handle optional/default values
    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)

        id = try container.decodeIfPresent(UUID.self, forKey: .id) ?? UUID()
        vehicle = try container.decode(VehicleInfo.self, forKey: .vehicle)
        codes = try container.decode([DTCCode].self, forKey: .codes)
        safetyRating = try container.decode(SafetyRating.self, forKey: .safetyRating)
        timestamp = try container.decode(Date.self, forKey: .timestamp)

        dontPanic = try container.decodeIfPresent(String.self, forKey: .dontPanic)
        likelyCauses = try container.decodeIfPresent(String.self, forKey: .likelyCauses)
        symptoms = try container.decodeIfPresent(String.self, forKey: .symptoms)
        ifIgnored = try container.decodeIfPresent(String.self, forKey: .ifIgnored)
        quickChecks = try container.decodeIfPresent(String.self, forKey: .quickChecks)
        diyFix = try container.decodeIfPresent(String.self, forKey: .diyFix)
        urgency = try container.decodeIfPresent(String.self, forKey: .urgency)
        repairCost = try container.decodeIfPresent(String.self, forKey: .repairCost)
        knownIssues = try container.decodeIfPresent(String.self, forKey: .knownIssues)
        ownerReports = try container.decodeIfPresent(String.self, forKey: .ownerReports)

        engine = try container.decodeIfPresent(String.self, forKey: .engine)
        drive = try container.decodeIfPresent(String.self, forKey: .drive)
        fuelType = try container.decodeIfPresent(String.self, forKey: .fuelType)
        transmission = try container.decodeIfPresent(String.self, forKey: .transmission)
        isTurbo = try container.decodeIfPresent(Bool.self, forKey: .isTurbo) ?? false
        isSupercharged = try container.decodeIfPresent(Bool.self, forKey: .isSupercharged) ?? false
        isHybrid = try container.decodeIfPresent(Bool.self, forKey: .isHybrid) ?? false
        isElectric = try container.decodeIfPresent(Bool.self, forKey: .isElectric) ?? false

        dataSources = try container.decodeIfPresent([String].self, forKey: .dataSources) ?? []
        obdSource = try container.decodeIfPresent(String.self, forKey: .obdSource)

        rpm = try container.decodeIfPresent(Int.self, forKey: .rpm)
        speed = try container.decodeIfPresent(Int.self, forKey: .speed)
        coolantTemp = try container.decodeIfPresent(Int.self, forKey: .coolantTemp)

        vehicleImageURL = try container.decodeIfPresent(String.self, forKey: .vehicleImageURL)
    }

    // Custom encoder to ensure all properties are saved
    func encode(to encoder: Encoder) throws {
        var container = encoder.container(keyedBy: CodingKeys.self)

        try container.encode(id, forKey: .id)
        try container.encode(vehicle, forKey: .vehicle)
        try container.encode(codes, forKey: .codes)
        try container.encode(safetyRating, forKey: .safetyRating)
        try container.encode(timestamp, forKey: .timestamp)

        try container.encodeIfPresent(dontPanic, forKey: .dontPanic)
        try container.encodeIfPresent(likelyCauses, forKey: .likelyCauses)
        try container.encodeIfPresent(symptoms, forKey: .symptoms)
        try container.encodeIfPresent(ifIgnored, forKey: .ifIgnored)
        try container.encodeIfPresent(quickChecks, forKey: .quickChecks)
        try container.encodeIfPresent(diyFix, forKey: .diyFix)
        try container.encodeIfPresent(urgency, forKey: .urgency)
        try container.encodeIfPresent(repairCost, forKey: .repairCost)
        try container.encodeIfPresent(knownIssues, forKey: .knownIssues)
        try container.encodeIfPresent(ownerReports, forKey: .ownerReports)

        try container.encodeIfPresent(engine, forKey: .engine)
        try container.encodeIfPresent(drive, forKey: .drive)
        try container.encodeIfPresent(fuelType, forKey: .fuelType)
        try container.encodeIfPresent(transmission, forKey: .transmission)
        try container.encode(isTurbo, forKey: .isTurbo)
        try container.encode(isSupercharged, forKey: .isSupercharged)
        try container.encode(isHybrid, forKey: .isHybrid)
        try container.encode(isElectric, forKey: .isElectric)

        try container.encode(dataSources, forKey: .dataSources)
        try container.encodeIfPresent(obdSource, forKey: .obdSource)

        try container.encodeIfPresent(rpm, forKey: .rpm)
        try container.encodeIfPresent(speed, forKey: .speed)
        try container.encodeIfPresent(coolantTemp, forKey: .coolantTemp)

        try container.encodeIfPresent(vehicleImageURL, forKey: .vehicleImageURL)
    }

    // Standard initializer
    init(vehicle: VehicleInfo, codes: [DTCCode], safetyRating: SafetyRating, timestamp: Date) {
        self.vehicle = vehicle
        self.codes = codes
        self.safetyRating = safetyRating
        self.timestamp = timestamp
    }

    // All diagnostic sections from the AI
    var dontPanic: String?           // What's Happening
    var likelyCauses: String?        // Likely Causes
    var symptoms: String?            // What You Might Notice
    var ifIgnored: String?           // If You Ignore This
    var quickChecks: String?         // Quick Checks
    var diyFix: String?              // DIY Fix
    var urgency: String?             // When To See A Mechanic
    var repairCost: String?          // Estimated Repair Cost
    var knownIssues: String?         // Known Issues For This Engine
    var ownerReports: String?        // Other Owners Report

    // Vehicle details
    var engine: String?
    var drive: String?
    var fuelType: String?
    var transmission: String?
    var isTurbo: Bool = false
    var isSupercharged: Bool = false
    var isHybrid: Bool = false
    var isElectric: Bool = false

    // Data sources used
    var dataSources: [String] = []
    var obdSource: String?

    // Live data at time of scan
    var rpm: Int?
    var speed: Int?
    var coolantTemp: Int?

    // Vehicle image URL
    var vehicleImageURL: String?

    // Legacy property for backwards compatibility
    var diagnosis: String? { dontPanic }
    var estimatedCosts: EstimatedCosts? {
        guard let cost = repairCost, !cost.isEmpty else { return nil }
        return EstimatedCosts(parts: "See details", labor: "See details", total: cost)
    }

    static var preview: ScanResult {
        var result = ScanResult(
            vehicle: .preview,
            codes: [
                DTCCode(code: "P0420", description: "Catalyst System Efficiency Below Threshold", severity: "CAUTION"),
                DTCCode(code: "P0171", description: "System Too Lean (Bank 1)", severity: "CAUTION")
            ],
            safetyRating: .caution,
            timestamp: Date()
        )
        result.dontPanic = "Your 2014 Toyota Land Cruiser is showing a catalytic converter efficiency issue combined with a lean fuel condition. This is commonly caused by a failing oxygen sensor or vacuum leak."
        result.likelyCauses = "1. Failing upstream O2 sensor\n2. Vacuum leak in intake manifold\n3. Worn catalytic converter\n4. Exhaust leak before sensors\n5. Fuel injector issues"
        result.symptoms = "1. Slight decrease in fuel economy\n2. Rough idle when cold\n3. Occasional hesitation on acceleration\n4. Check engine light on"
        result.ifIgnored = "The catalytic converter may fail completely, leading to a repair cost of $1500-3000. The lean condition could cause engine damage over time."
        result.quickChecks = "1. Check for loose gas cap\n2. Listen for vacuum hissing sounds\n3. Check exhaust for visible damage"
        result.diyFix = "Difficulty: Intermediate\n\nIf it's a vacuum leak, you can spray carburetor cleaner around intake connections while the engine is running - RPM changes indicate a leak location."
        result.urgency = "Schedule service within 1-2 weeks. Safe for normal driving in the meantime."
        result.repairCost = "Parts: $150-400\nLabor: $100-200\nTotal: $250-600 at independent shop"
        result.knownIssues = "The 5.7L V8 in Land Cruisers is known for O2 sensor failures around 80-100k miles."
        result.ownerReports = "Several owners on forums report this combination of codes was resolved by replacing the upstream O2 sensors."
        result.engine = "5.7L V8 DOHC"
        result.drive = "4WD"
        result.fuelType = "Premium"
        result.dataSources = ["CarsXE", "OBD-Codes.com", "Community Forums"]
        result.obdSource = "Demo Mode"
        result.rpm = 750
        result.coolantTemp = 195
        return result
    }
}

// MARK: - Estimated Costs

struct EstimatedCosts: Codable {
    let parts: String
    let labor: String
    let total: String
}

// MARK: - OBD Connection Status

enum OBDConnectionStatus {
    case disconnected
    case connecting
    case connected
    case error(String)

    var isConnected: Bool {
        if case .connected = self { return true }
        return false
    }

    var label: String {
        switch self {
        case .disconnected: return "Disconnected"
        case .connecting: return "Connecting..."
        case .connected: return "Connected"
        case .error(let msg): return "Error: \(msg)"
        }
    }

    var color: Color {
        switch self {
        case .disconnected: return .cdTextSecondary
        case .connecting: return .cdWarning
        case .connected: return .cdSuccess
        case .error: return .cdCritical
        }
    }
}
