import Foundation
import CoreBluetooth
import Combine

/// Manages Bluetooth connection to ELM327-based OBD adapters
class OBDManager: NSObject, ObservableObject {
    @Published var isConnected = false
    @Published var isScanning = false
    @Published var connectedDeviceName: String?
    @Published var discoveredDevices: [CBPeripheral] = []

    private var centralManager: CBCentralManager!
    private var connectedPeripheral: CBPeripheral?
    private var writeCharacteristic: CBCharacteristic?
    private var readCharacteristic: CBCharacteristic?

    // ELM327 BLE Service and Characteristic UUIDs (common ones)
    private let elmServiceUUIDs = [
        CBUUID(string: "FFF0"),           // Common ELM327 BLE service
        CBUUID(string: "E7810A71-73AE-499D-8C15-FAA9AEF0C3F2"), // OBDLink
        CBUUID(string: "0000FFE0-0000-1000-8000-00805F9B34FB"), // Generic
    ]

    private let elmWriteCharUUIDs = [
        CBUUID(string: "FFF2"),
        CBUUID(string: "BEF8D6C9-9C21-4C9E-B632-BD58C1009F9F"),
        CBUUID(string: "0000FFE1-0000-1000-8000-00805F9B34FB"),
    ]

    private let elmReadCharUUIDs = [
        CBUUID(string: "FFF1"),
        CBUUID(string: "BEF8D6C9-9C21-4C9E-B632-BD58C1009F9F"),
        CBUUID(string: "0000FFE1-0000-1000-8000-00805F9B34FB"),
    ]

    private var responseBuffer = ""
    private var responseCompletion: ((Result<String, OBDError>) -> Void)?
    private var responseTimer: Timer?

    override init() {
        super.init()
        centralManager = CBCentralManager(delegate: self, queue: nil)
    }

    // MARK: - Public Methods

    func startScanning() {
        guard centralManager.state == .poweredOn else {
            print("[OBD] Bluetooth not ready")
            return
        }

        isScanning = true
        discoveredDevices = []

        // Scan for devices with ELM327 service UUIDs, or nil for all devices
        centralManager.scanForPeripherals(withServices: nil, options: [
            CBCentralManagerScanOptionAllowDuplicatesKey: false
        ])

        // Stop scanning after 10 seconds
        DispatchQueue.main.asyncAfter(deadline: .now() + 10) { [weak self] in
            self?.stopScanning()
        }
    }

    func stopScanning() {
        centralManager.stopScan()
        isScanning = false
    }

    func connect(to peripheral: CBPeripheral) {
        stopScanning()
        connectedPeripheral = peripheral
        centralManager.connect(peripheral, options: nil)
    }

    func disconnect() {
        if let peripheral = connectedPeripheral {
            centralManager.cancelPeripheralConnection(peripheral)
        }
        cleanup()
    }

    /// Read DTC codes from the vehicle
    func readDTCCodes() async throws -> [String] {
        guard isConnected else {
            throw OBDError.notConnected
        }

        // Initialize ELM327
        _ = try await sendCommand("ATZ")      // Reset
        _ = try await sendCommand("ATE0")     // Echo off
        _ = try await sendCommand("ATL0")     // Linefeeds off
        _ = try await sendCommand("ATSP0")    // Auto protocol

        // Request stored DTCs (Mode 03)
        let response = try await sendCommand("03")

        return parseDTCResponse(response)
    }

    /// Clear DTC codes
    func clearDTCCodes() async throws {
        guard isConnected else {
            throw OBDError.notConnected
        }

        _ = try await sendCommand("04")
    }

    // MARK: - Private Methods

    private func sendCommand(_ command: String) async throws -> String {
        return try await withCheckedThrowingContinuation { continuation in
            sendCommand(command) { result in
                continuation.resume(with: result)
            }
        }
    }

    private func sendCommand(_ command: String, completion: @escaping (Result<String, OBDError>) -> Void) {
        guard let characteristic = writeCharacteristic,
              let peripheral = connectedPeripheral else {
            completion(.failure(.notConnected))
            return
        }

        responseBuffer = ""
        responseCompletion = completion

        // Start timeout timer
        responseTimer?.invalidate()
        responseTimer = Timer.scheduledTimer(withTimeInterval: 5.0, repeats: false) { [weak self] _ in
            self?.responseCompletion?(.failure(.timeout))
            self?.responseCompletion = nil
        }

        let commandWithTerminator = command + "\r"
        if let data = commandWithTerminator.data(using: .utf8) {
            peripheral.writeValue(data, for: characteristic, type: .withResponse)
        }
    }

    private func parseDTCResponse(_ response: String) -> [String] {
        var codes: [String] = []

        // Response format: 43 XX XX YY YY ...
        // Where each XX XX is a DTC
        let cleanResponse = response
            .replacingOccurrences(of: " ", with: "")
            .replacingOccurrences(of: "\r", with: "")
            .replacingOccurrences(of: "\n", with: "")
            .replacingOccurrences(of: ">", with: "")

        // Check for valid response (starts with 43)
        guard cleanResponse.hasPrefix("43") else {
            return codes
        }

        // Remove the 43 prefix
        let dataString = String(cleanResponse.dropFirst(2))

        // Parse each 4-character DTC
        var index = dataString.startIndex
        while index < dataString.endIndex {
            let endIndex = dataString.index(index, offsetBy: 4, limitedBy: dataString.endIndex) ?? dataString.endIndex
            let dtcHex = String(dataString[index..<endIndex])

            if dtcHex.count == 4, let code = decodeDTC(dtcHex) {
                codes.append(code)
            }

            index = endIndex
        }

        return codes
    }

    private func decodeDTC(_ hex: String) -> String? {
        guard hex.count == 4, hex != "0000" else { return nil }

        let firstChar = hex.first!
        let prefix: String

        switch firstChar {
        case "0": prefix = "P0"
        case "1": prefix = "P1"
        case "2": prefix = "P2"
        case "3": prefix = "P3"
        case "4": prefix = "C0"
        case "5": prefix = "C1"
        case "6": prefix = "C2"
        case "7": prefix = "C3"
        case "8": prefix = "B0"
        case "9": prefix = "B1"
        case "A", "a": prefix = "B2"
        case "B", "b": prefix = "B3"
        case "C", "c": prefix = "U0"
        case "D", "d": prefix = "U1"
        case "E", "e": prefix = "U2"
        case "F", "f": prefix = "U3"
        default: return nil
        }

        let suffix = String(hex.dropFirst())
        return prefix + suffix
    }

    private func cleanup() {
        connectedPeripheral = nil
        writeCharacteristic = nil
        readCharacteristic = nil
        connectedDeviceName = nil
        isConnected = false
        responseTimer?.invalidate()
        responseTimer = nil
    }
}

// MARK: - CBCentralManagerDelegate

extension OBDManager: CBCentralManagerDelegate {
    func centralManagerDidUpdateState(_ central: CBCentralManager) {
        switch central.state {
        case .poweredOn:
            print("[OBD] Bluetooth powered on")
        case .poweredOff:
            print("[OBD] Bluetooth powered off")
            cleanup()
        case .unauthorized:
            print("[OBD] Bluetooth unauthorized")
        case .unsupported:
            print("[OBD] Bluetooth unsupported")
        default:
            break
        }
    }

    func centralManager(_ central: CBCentralManager, didDiscover peripheral: CBPeripheral, advertisementData: [String: Any], rssi RSSI: NSNumber) {
        // Filter for likely OBD adapters
        let name = peripheral.name ?? ""
        let isLikelyOBD = name.lowercased().contains("obd") ||
                          name.lowercased().contains("elm") ||
                          name.lowercased().contains("vlink") ||
                          name.lowercased().contains("veepeak") ||
                          name.lowercased().contains("carista")

        if isLikelyOBD || !name.isEmpty {
            if !discoveredDevices.contains(where: { $0.identifier == peripheral.identifier }) {
                DispatchQueue.main.async {
                    self.discoveredDevices.append(peripheral)
                }
                print("[OBD] Discovered: \(name) (\(peripheral.identifier))")
            }
        }
    }

    func centralManager(_ central: CBCentralManager, didConnect peripheral: CBPeripheral) {
        print("[OBD] Connected to \(peripheral.name ?? "Unknown")")
        connectedDeviceName = peripheral.name
        peripheral.delegate = self
        peripheral.discoverServices(nil)
    }

    func centralManager(_ central: CBCentralManager, didDisconnectPeripheral peripheral: CBPeripheral, error: Error?) {
        print("[OBD] Disconnected from \(peripheral.name ?? "Unknown")")
        cleanup()
    }

    func centralManager(_ central: CBCentralManager, didFailToConnect peripheral: CBPeripheral, error: Error?) {
        print("[OBD] Failed to connect: \(error?.localizedDescription ?? "Unknown error")")
        cleanup()
    }
}

// MARK: - CBPeripheralDelegate

extension OBDManager: CBPeripheralDelegate {
    func peripheral(_ peripheral: CBPeripheral, didDiscoverServices error: Error?) {
        guard let services = peripheral.services else { return }

        for service in services {
            print("[OBD] Discovered service: \(service.uuid)")
            peripheral.discoverCharacteristics(nil, for: service)
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didDiscoverCharacteristicsFor service: CBService, error: Error?) {
        guard let characteristics = service.characteristics else { return }

        for characteristic in characteristics {
            print("[OBD] Discovered characteristic: \(characteristic.uuid)")

            // Check if this is a write characteristic
            if characteristic.properties.contains(.write) || characteristic.properties.contains(.writeWithoutResponse) {
                writeCharacteristic = characteristic
                print("[OBD] Found write characteristic")
            }

            // Check if this is a read/notify characteristic
            if characteristic.properties.contains(.notify) {
                readCharacteristic = characteristic
                peripheral.setNotifyValue(true, for: characteristic)
                print("[OBD] Found notify characteristic")
            }
        }

        // Mark as connected when we have both characteristics
        if writeCharacteristic != nil {
            DispatchQueue.main.async {
                self.isConnected = true
            }
        }
    }

    func peripheral(_ peripheral: CBPeripheral, didUpdateValueFor characteristic: CBCharacteristic, error: Error?) {
        guard let data = characteristic.value,
              let response = String(data: data, encoding: .utf8) else {
            return
        }

        responseBuffer += response

        // Check if response is complete (ends with > prompt)
        if responseBuffer.contains(">") {
            responseTimer?.invalidate()
            responseCompletion?(.success(responseBuffer))
            responseCompletion = nil
        }
    }
}

// MARK: - OBD Errors

enum OBDError: LocalizedError {
    case notConnected
    case timeout
    case invalidResponse
    case bluetoothDisabled

    var errorDescription: String? {
        switch self {
        case .notConnected:
            return "Not connected to OBD adapter"
        case .timeout:
            return "OBD command timed out"
        case .invalidResponse:
            return "Invalid response from vehicle"
        case .bluetoothDisabled:
            return "Bluetooth is disabled"
        }
    }
}
