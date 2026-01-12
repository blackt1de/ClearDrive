import Foundation
import SwiftUI

// MARK: - Trim

struct Trim: Identifiable, Decodable {
    let id: String
    let name: String

    enum CodingKeys: String, CodingKey {
        case id
        case name
    }

    init(id: String, name: String) {
        self.id = id
        self.name = name
    }

    init(from decoder: Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        // Handle both string and int IDs
        if let intId = try? container.decode(Int.self, forKey: .id) {
            id = String(intId)
        } else {
            id = try container.decode(String.self, forKey: .id)
        }
        name = try container.decode(String.self, forKey: .name)
    }
}

// MARK: - DTC Code

struct DTCCode {
    let code: String
    let description: String
    let severity: String?
}

// MARK: - Scan Result

struct ScanResult {
    let vehicleDescription: String
    let vehicleImageURL: URL?
    let codes: [DTCCode]
    let diagnosis: String?
    let safetyRating: SafetyRating
    let estimatedCosts: EstimatedCosts?

    static var preview: ScanResult {
        ScanResult(
            vehicleDescription: "2020 Honda Civic EX",
            vehicleImageURL: nil,
            codes: [
                DTCCode(code: "P0420", description: "Catalyst System Efficiency Below Threshold", severity: "CAUTION"),
                DTCCode(code: "P0171", description: "System Too Lean (Bank 1)", severity: "CAUTION")
            ],
            diagnosis: "The P0420 code typically indicates a failing catalytic converter or oxygen sensor issue. Combined with P0171 (lean condition), this could indicate a vacuum leak or failing MAF sensor causing the catalyst to work harder.",
            safetyRating: .caution,
            estimatedCosts: EstimatedCosts(parts: "$150-400", labor: "$100-200", total: "$250-600")
        )
    }
}

// MARK: - Estimated Costs

struct EstimatedCosts {
    let parts: String
    let labor: String
    let total: String
}

// MARK: - Safety Rating

enum SafetyRating {
    case safe
    case caution
    case stop

    init(from string: String) {
        switch string.uppercased() {
        case "SAFE", "GREEN":
            self = .safe
        case "CAUTION", "YELLOW", "WARNING":
            self = .caution
        case "STOP", "RED", "CRITICAL":
            self = .stop
        default:
            self = .safe
        }
    }

    var label: String {
        switch self {
        case .safe: return "Safe to Drive"
        case .caution: return "Schedule Service"
        case .stop: return "Immediate Attention"
        }
    }

    var icon: String {
        switch self {
        case .safe: return "checkmark.circle.fill"
        case .caution: return "exclamationmark.triangle.fill"
        case .stop: return "xmark.octagon.fill"
        }
    }

    var color: Color {
        switch self {
        case .safe: return .green
        case .caution: return .orange
        case .stop: return .red
        }
    }
}

// MARK: - Scan History

struct ScanHistory: Identifiable {
    let id: String
    let vehicleDescription: String
    let date: Date
    let codeCount: Int
    let safetyRating: String

    var safetyColor: Color {
        switch safetyRating.uppercased() {
        case "SAFE", "GREEN": return .green
        case "CAUTION", "YELLOW": return .orange
        case "STOP", "RED": return .red
        default: return .gray
        }
    }
}
