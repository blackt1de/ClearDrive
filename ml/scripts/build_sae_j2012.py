"""Generator for ml/data/sae_j2012.json — canonical OBD-II DTC lookup.

Source data assembled from training knowledge of SAE J2012, cross-checked
against the OBD-II Wikipedia DTC list and obd-codes.com. All entries with
`standardized=true` are the SAE J2012 standard P-codes (P00xx-P09xx range).
Manufacturer-specific codes (P1xxx and above, body B-, chassis C-, network U-)
are included only for the most-commonly-seen ones across major manufacturers.

The JSON output has one entry per code with the schema:
    {
        "code": "P0420",
        "description": "Catalyst System Efficiency Below Threshold (Bank 1)",
        "category": "powertrain",
        "subsystem": "emissions",
        "standardized": true,
        "manufacturer_specific": false
    }

Re-run with: py -3 ml/scripts/build_sae_j2012.py

Output: ml/data/sae_j2012.json (~400+ entries)
"""

import json
from pathlib import Path

# Schema: (code, description, subsystem)
# `category` is auto-derived from the first char of `code`. `standardized` and
# `manufacturer_specific` are auto-derived from the code's numeric range.

# --- POWERTRAIN: P00xx — Fuel and Air Metering, Auxiliary Emission Controls ---
P00XX = [
    ("P0000", "No DTCs Reported", "system"),
    ("P0010", "'A' Camshaft Position Actuator Circuit (Bank 1)", "fuel_air_metering"),
    ("P0011", "'A' Camshaft Position - Timing Over-Advanced or System Performance (Bank 1)", "fuel_air_metering"),
    ("P0012", "'A' Camshaft Position - Timing Over-Retarded (Bank 1)", "fuel_air_metering"),
    ("P0013", "'B' Camshaft Position - Actuator Circuit (Bank 1)", "fuel_air_metering"),
    ("P0014", "'B' Camshaft Position - Timing Over-Advanced or System Performance (Bank 1)", "fuel_air_metering"),
    ("P0015", "'B' Camshaft Position - Timing Over-Retarded (Bank 1)", "fuel_air_metering"),
    ("P0016", "Crankshaft Position - Camshaft Position Correlation (Bank 1 Sensor A)", "fuel_air_metering"),
    ("P0017", "Crankshaft Position - Camshaft Position Correlation (Bank 1 Sensor B)", "fuel_air_metering"),
    ("P0018", "Crankshaft Position - Camshaft Position Correlation (Bank 2 Sensor A)", "fuel_air_metering"),
    ("P0019", "Crankshaft Position - Camshaft Position Correlation (Bank 2 Sensor B)", "fuel_air_metering"),
    ("P0020", "'A' Camshaft Position Actuator Circuit (Bank 2)", "fuel_air_metering"),
    ("P0021", "'A' Camshaft Position - Timing Over-Advanced or System Performance (Bank 2)", "fuel_air_metering"),
    ("P0022", "'A' Camshaft Position - Timing Over-Retarded (Bank 2)", "fuel_air_metering"),
    ("P0023", "'B' Camshaft Position - Actuator Circuit (Bank 2)", "fuel_air_metering"),
    ("P0024", "'B' Camshaft Position - Timing Over-Advanced or System Performance (Bank 2)", "fuel_air_metering"),
    ("P0025", "'B' Camshaft Position - Timing Over-Retarded (Bank 2)", "fuel_air_metering"),
    ("P0030", "HO2S Heater Control Circuit (Bank 1 Sensor 1)", "fuel_air_metering"),
    ("P0031", "HO2S Heater Control Circuit Low (Bank 1 Sensor 1)", "fuel_air_metering"),
    ("P0032", "HO2S Heater Control Circuit High (Bank 1 Sensor 1)", "fuel_air_metering"),
    ("P0036", "HO2S Heater Control Circuit (Bank 1 Sensor 2)", "fuel_air_metering"),
    ("P0037", "HO2S Heater Control Circuit Low (Bank 1 Sensor 2)", "fuel_air_metering"),
    ("P0038", "HO2S Heater Control Circuit High (Bank 1 Sensor 2)", "fuel_air_metering"),
    ("P0050", "HO2S Heater Control Circuit (Bank 2 Sensor 1)", "fuel_air_metering"),
    ("P0051", "HO2S Heater Control Circuit Low (Bank 2 Sensor 1)", "fuel_air_metering"),
    ("P0052", "HO2S Heater Control Circuit High (Bank 2 Sensor 1)", "fuel_air_metering"),
    ("P0056", "HO2S Heater Control Circuit (Bank 2 Sensor 2)", "fuel_air_metering"),
    ("P0068", "MAP/MAF - Throttle Position Correlation", "fuel_air_metering"),
    ("P0070", "Ambient Air Temperature Sensor Circuit", "fuel_air_metering"),
    ("P0071", "Ambient Air Temperature Sensor Range/Performance", "fuel_air_metering"),
    ("P0087", "Fuel Rail/System Pressure - Too Low", "fuel_air_metering"),
    ("P0088", "Fuel Rail/System Pressure - Too High", "fuel_air_metering"),
    ("P0089", "Fuel Pressure Regulator 1 Performance", "fuel_air_metering"),
    ("P0090", "Fuel Pressure Regulator 1 Control Circuit", "fuel_air_metering"),
    ("P0091", "Fuel Pressure Regulator 1 Control Circuit Low", "fuel_air_metering"),
    ("P0092", "Fuel Pressure Regulator 1 Control Circuit High", "fuel_air_metering"),
]

# --- P01xx — Fuel/Air metering ---
P01XX = [
    ("P0100", "Mass or Volume Air Flow 'A' Circuit", "fuel_air_metering"),
    ("P0101", "Mass or Volume Air Flow Sensor 'A' Circuit Range/Performance", "fuel_air_metering"),
    ("P0102", "Mass or Volume Air Flow Sensor 'A' Circuit Low Input", "fuel_air_metering"),
    ("P0103", "Mass or Volume Air Flow Sensor 'A' Circuit High Input", "fuel_air_metering"),
    ("P0104", "Mass or Volume Air Flow Sensor 'A' Circuit Intermittent", "fuel_air_metering"),
    ("P0105", "Manifold Absolute Pressure/Barometric Pressure Circuit", "fuel_air_metering"),
    ("P0106", "Manifold Absolute Pressure/Barometric Pressure Circuit Range/Performance", "fuel_air_metering"),
    ("P0107", "Manifold Absolute Pressure/Barometric Pressure Circuit Low Input", "fuel_air_metering"),
    ("P0108", "Manifold Absolute Pressure/Barometric Pressure Circuit High Input", "fuel_air_metering"),
    ("P0109", "Manifold Absolute Pressure/Barometric Pressure Circuit Intermittent", "fuel_air_metering"),
    ("P0110", "Intake Air Temperature Sensor 1 Circuit", "fuel_air_metering"),
    ("P0111", "Intake Air Temperature Sensor 1 Circuit Range/Performance", "fuel_air_metering"),
    ("P0112", "Intake Air Temperature Sensor 1 Circuit Low Input", "fuel_air_metering"),
    ("P0113", "Intake Air Temperature Sensor 1 Circuit High Input", "fuel_air_metering"),
    ("P0114", "Intake Air Temperature Sensor 1 Circuit Intermittent", "fuel_air_metering"),
    ("P0115", "Engine Coolant Temperature Circuit", "fuel_air_metering"),
    ("P0116", "Engine Coolant Temperature Circuit Range/Performance", "fuel_air_metering"),
    ("P0117", "Engine Coolant Temperature Sensor 1 Circuit Low Input", "fuel_air_metering"),
    ("P0118", "Engine Coolant Temperature Sensor 1 Circuit High Input", "fuel_air_metering"),
    ("P0119", "Engine Coolant Temperature Sensor 1 Circuit Intermittent", "fuel_air_metering"),
    ("P0120", "Throttle/Pedal Position Sensor/Switch 'A' Circuit", "fuel_air_metering"),
    ("P0121", "Throttle/Pedal Position Sensor/Switch 'A' Circuit Range/Performance", "fuel_air_metering"),
    ("P0122", "Throttle/Pedal Position Sensor/Switch 'A' Circuit Low Input", "fuel_air_metering"),
    ("P0123", "Throttle/Pedal Position Sensor/Switch 'A' Circuit High Input", "fuel_air_metering"),
    ("P0124", "Throttle/Pedal Position Sensor/Switch 'A' Circuit Intermittent", "fuel_air_metering"),
    ("P0125", "Insufficient Coolant Temperature for Closed Loop Fuel Control", "fuel_air_metering"),
    ("P0126", "Insufficient Coolant Temperature for Stable Operation", "fuel_air_metering"),
    ("P0127", "Intake Air Temperature Too High", "fuel_air_metering"),
    ("P0128", "Coolant Thermostat (Coolant Temperature Below Thermostat Regulating Temperature)", "fuel_air_metering"),
    ("P0130", "O2 Sensor Circuit (Bank 1, Sensor 1)", "fuel_air_metering"),
    ("P0131", "O2 Sensor Circuit Low Voltage (Bank 1, Sensor 1)", "fuel_air_metering"),
    ("P0132", "O2 Sensor Circuit High Voltage (Bank 1, Sensor 1)", "fuel_air_metering"),
    ("P0133", "O2 Sensor Circuit Slow Response (Bank 1, Sensor 1)", "fuel_air_metering"),
    ("P0134", "O2 Sensor Circuit No Activity Detected (Bank 1, Sensor 1)", "fuel_air_metering"),
    ("P0135", "O2 Sensor Heater Circuit Malfunction (Bank 1, Sensor 1)", "fuel_air_metering"),
    ("P0136", "O2 Sensor Circuit (Bank 1, Sensor 2)", "fuel_air_metering"),
    ("P0137", "O2 Sensor Circuit Low Voltage (Bank 1, Sensor 2)", "fuel_air_metering"),
    ("P0138", "O2 Sensor Circuit High Voltage (Bank 1, Sensor 2)", "fuel_air_metering"),
    ("P0139", "O2 Sensor Circuit Slow Response (Bank 1, Sensor 2)", "fuel_air_metering"),
    ("P0140", "O2 Sensor Circuit No Activity Detected (Bank 1, Sensor 2)", "fuel_air_metering"),
    ("P0141", "O2 Sensor Heater Circuit Malfunction (Bank 1, Sensor 2)", "fuel_air_metering"),
    ("P0150", "O2 Sensor Circuit (Bank 2, Sensor 1)", "fuel_air_metering"),
    ("P0151", "O2 Sensor Circuit Low Voltage (Bank 2, Sensor 1)", "fuel_air_metering"),
    ("P0152", "O2 Sensor Circuit High Voltage (Bank 2, Sensor 1)", "fuel_air_metering"),
    ("P0153", "O2 Sensor Circuit Slow Response (Bank 2, Sensor 1)", "fuel_air_metering"),
    ("P0154", "O2 Sensor Circuit No Activity Detected (Bank 2, Sensor 1)", "fuel_air_metering"),
    ("P0155", "O2 Sensor Heater Circuit Malfunction (Bank 2, Sensor 1)", "fuel_air_metering"),
    ("P0156", "O2 Sensor Circuit (Bank 2, Sensor 2)", "fuel_air_metering"),
    ("P0157", "O2 Sensor Circuit Low Voltage (Bank 2, Sensor 2)", "fuel_air_metering"),
    ("P0158", "O2 Sensor Circuit High Voltage (Bank 2, Sensor 2)", "fuel_air_metering"),
    ("P0159", "O2 Sensor Circuit Slow Response (Bank 2, Sensor 2)", "fuel_air_metering"),
    ("P0160", "O2 Sensor Circuit No Activity Detected (Bank 2, Sensor 2)", "fuel_air_metering"),
    ("P0161", "O2 Sensor Heater Circuit Malfunction (Bank 2, Sensor 2)", "fuel_air_metering"),
    ("P0170", "Fuel Trim Malfunction (Bank 1)", "fuel_air_metering"),
    ("P0171", "System Too Lean (Bank 1)", "fuel_air_metering"),
    ("P0172", "System Too Rich (Bank 1)", "fuel_air_metering"),
    ("P0173", "Fuel Trim Malfunction (Bank 2)", "fuel_air_metering"),
    ("P0174", "System Too Lean (Bank 2)", "fuel_air_metering"),
    ("P0175", "System Too Rich (Bank 2)", "fuel_air_metering"),
    ("P0190", "Fuel Rail Pressure Sensor Circuit", "fuel_air_metering"),
    ("P0191", "Fuel Rail Pressure Sensor Circuit Range/Performance", "fuel_air_metering"),
    ("P0192", "Fuel Rail Pressure Sensor Circuit Low Input", "fuel_air_metering"),
    ("P0193", "Fuel Rail Pressure Sensor Circuit High Input", "fuel_air_metering"),
    ("P0194", "Fuel Rail Pressure Sensor Circuit Intermittent", "fuel_air_metering"),
]

# --- P02xx — Fuel and Air Metering / Injector circuits ---
P02XX = [
    ("P0201", "Injector Circuit/Open - Cylinder 1", "fuel_air_metering"),
    ("P0202", "Injector Circuit/Open - Cylinder 2", "fuel_air_metering"),
    ("P0203", "Injector Circuit/Open - Cylinder 3", "fuel_air_metering"),
    ("P0204", "Injector Circuit/Open - Cylinder 4", "fuel_air_metering"),
    ("P0205", "Injector Circuit/Open - Cylinder 5", "fuel_air_metering"),
    ("P0206", "Injector Circuit/Open - Cylinder 6", "fuel_air_metering"),
    ("P0207", "Injector Circuit/Open - Cylinder 7", "fuel_air_metering"),
    ("P0208", "Injector Circuit/Open - Cylinder 8", "fuel_air_metering"),
    ("P0209", "Injector Circuit/Open - Cylinder 9", "fuel_air_metering"),
    ("P0210", "Injector Circuit/Open - Cylinder 10", "fuel_air_metering"),
    ("P0216", "Injection Timing Control Circuit", "fuel_air_metering"),
    ("P0217", "Engine Coolant Over Temperature Condition", "fuel_air_metering"),
    ("P0218", "Transmission Fluid Over Temperature Condition", "transmission"),
    ("P0219", "Engine Overspeed Condition", "fuel_air_metering"),
    ("P0221", "Throttle/Pedal Position Sensor/Switch 'B' Circuit Range/Performance", "fuel_air_metering"),
    ("P0222", "Throttle/Pedal Position Sensor/Switch 'B' Circuit Low Input", "fuel_air_metering"),
    ("P0223", "Throttle/Pedal Position Sensor/Switch 'B' Circuit High Input", "fuel_air_metering"),
    ("P0230", "Fuel Pump Primary Circuit", "fuel_air_metering"),
    ("P0231", "Fuel Pump Secondary Circuit Low", "fuel_air_metering"),
    ("P0232", "Fuel Pump Secondary Circuit High", "fuel_air_metering"),
    ("P0234", "Turbocharger/Supercharger 'A' Overboost Condition", "fuel_air_metering"),
    ("P0235", "Turbocharger/Supercharger Boost Sensor 'A' Circuit", "fuel_air_metering"),
    ("P0236", "Turbocharger/Supercharger Boost Sensor 'A' Circuit Range/Performance", "fuel_air_metering"),
    ("P0237", "Turbocharger/Supercharger Boost Sensor 'A' Circuit Low", "fuel_air_metering"),
    ("P0238", "Turbocharger/Supercharger Boost Sensor 'A' Circuit High", "fuel_air_metering"),
    ("P0299", "Turbocharger/Supercharger 'A' Underboost Condition", "fuel_air_metering"),
]

# --- P03xx — Ignition / Misfire ---
P03XX = [
    ("P0300", "Random/Multiple Cylinder Misfire Detected", "ignition_misfire"),
    ("P0301", "Cylinder 1 Misfire Detected", "ignition_misfire"),
    ("P0302", "Cylinder 2 Misfire Detected", "ignition_misfire"),
    ("P0303", "Cylinder 3 Misfire Detected", "ignition_misfire"),
    ("P0304", "Cylinder 4 Misfire Detected", "ignition_misfire"),
    ("P0305", "Cylinder 5 Misfire Detected", "ignition_misfire"),
    ("P0306", "Cylinder 6 Misfire Detected", "ignition_misfire"),
    ("P0307", "Cylinder 7 Misfire Detected", "ignition_misfire"),
    ("P0308", "Cylinder 8 Misfire Detected", "ignition_misfire"),
    ("P0309", "Cylinder 9 Misfire Detected", "ignition_misfire"),
    ("P0310", "Cylinder 10 Misfire Detected", "ignition_misfire"),
    ("P0311", "Cylinder 11 Misfire Detected", "ignition_misfire"),
    ("P0312", "Cylinder 12 Misfire Detected", "ignition_misfire"),
    ("P0313", "Misfire Detected with Low Fuel", "ignition_misfire"),
    ("P0314", "Single Cylinder Misfire (Cylinder not Specified)", "ignition_misfire"),
    ("P0315", "Crankshaft Position System Variation Not Learned", "ignition_misfire"),
    ("P0316", "Misfire Detected on Startup (First 1000 Revolutions)", "ignition_misfire"),
    ("P0320", "Ignition/Distributor Engine Speed Input Circuit", "ignition_misfire"),
    ("P0321", "Ignition/Distributor Engine Speed Input Circuit Range/Performance", "ignition_misfire"),
    ("P0322", "Ignition/Distributor Engine Speed Input Circuit No Signal", "ignition_misfire"),
    ("P0325", "Knock Sensor 1 Circuit Malfunction (Bank 1 or Single Sensor)", "ignition_misfire"),
    ("P0326", "Knock Sensor 1 Circuit Range/Performance (Bank 1 or Single Sensor)", "ignition_misfire"),
    ("P0327", "Knock Sensor 1 Circuit Low Input (Bank 1 or Single Sensor)", "ignition_misfire"),
    ("P0328", "Knock Sensor 1 Circuit High Input (Bank 1 or Single Sensor)", "ignition_misfire"),
    ("P0330", "Knock Sensor 2 Circuit Malfunction (Bank 2)", "ignition_misfire"),
    ("P0335", "Crankshaft Position Sensor 'A' Circuit", "ignition_misfire"),
    ("P0336", "Crankshaft Position Sensor 'A' Circuit Range/Performance", "ignition_misfire"),
    ("P0337", "Crankshaft Position Sensor 'A' Circuit Low Input", "ignition_misfire"),
    ("P0338", "Crankshaft Position Sensor 'A' Circuit High Input", "ignition_misfire"),
    ("P0339", "Crankshaft Position Sensor 'A' Circuit Intermittent", "ignition_misfire"),
    ("P0340", "Camshaft Position Sensor 'A' Circuit (Bank 1 or Single Sensor)", "ignition_misfire"),
    ("P0341", "Camshaft Position Sensor 'A' Circuit Range/Performance (Bank 1 or Single Sensor)", "ignition_misfire"),
    ("P0342", "Camshaft Position Sensor 'A' Circuit Low Input (Bank 1 or Single Sensor)", "ignition_misfire"),
    ("P0343", "Camshaft Position Sensor 'A' Circuit High Input (Bank 1 or Single Sensor)", "ignition_misfire"),
    ("P0344", "Camshaft Position Sensor 'A' Circuit Intermittent (Bank 1 or Single Sensor)", "ignition_misfire"),
    ("P0345", "Camshaft Position Sensor 'A' Circuit (Bank 2)", "ignition_misfire"),
    ("P0350", "Ignition Coil Primary/Secondary Circuit Malfunction", "ignition_misfire"),
    ("P0351", "Ignition Coil 'A' Primary/Secondary Circuit Malfunction", "ignition_misfire"),
    ("P0352", "Ignition Coil 'B' Primary/Secondary Circuit Malfunction", "ignition_misfire"),
    ("P0353", "Ignition Coil 'C' Primary/Secondary Circuit Malfunction", "ignition_misfire"),
    ("P0354", "Ignition Coil 'D' Primary/Secondary Circuit Malfunction", "ignition_misfire"),
    ("P0355", "Ignition Coil 'E' Primary/Secondary Circuit Malfunction", "ignition_misfire"),
    ("P0356", "Ignition Coil 'F' Primary/Secondary Circuit Malfunction", "ignition_misfire"),
    ("P0357", "Ignition Coil 'G' Primary/Secondary Circuit Malfunction", "ignition_misfire"),
    ("P0358", "Ignition Coil 'H' Primary/Secondary Circuit Malfunction", "ignition_misfire"),
]

# --- P04xx — Auxiliary Emissions Controls (EGR, EVAP, Catalyst, Secondary Air) ---
P04XX = [
    ("P0400", "Exhaust Gas Recirculation 'A' Flow", "emissions"),
    ("P0401", "Exhaust Gas Recirculation Flow Insufficient Detected", "emissions"),
    ("P0402", "Exhaust Gas Recirculation Flow Excessive Detected", "emissions"),
    ("P0403", "Exhaust Gas Recirculation Control Circuit", "emissions"),
    ("P0404", "Exhaust Gas Recirculation Control Circuit Range/Performance", "emissions"),
    ("P0405", "Exhaust Gas Recirculation Sensor 'A' Circuit Low", "emissions"),
    ("P0406", "Exhaust Gas Recirculation Sensor 'A' Circuit High", "emissions"),
    ("P0410", "Secondary Air Injection System", "emissions"),
    ("P0411", "Secondary Air Injection System Incorrect Flow Detected", "emissions"),
    ("P0412", "Secondary Air Injection System Switching Valve 'A' Circuit", "emissions"),
    ("P0413", "Secondary Air Injection System Switching Valve 'A' Circuit Open", "emissions"),
    ("P0414", "Secondary Air Injection System Switching Valve 'A' Circuit Shorted", "emissions"),
    ("P0415", "Secondary Air Injection System Switching Valve 'B' Circuit", "emissions"),
    ("P0418", "Secondary Air Injection System Relay 'A' Circuit Malfunction", "emissions"),
    ("P0419", "Secondary Air Injection System Relay 'B' Circuit Malfunction", "emissions"),
    ("P0420", "Catalyst System Efficiency Below Threshold (Bank 1)", "emissions"),
    ("P0421", "Warm Up Catalyst Efficiency Below Threshold (Bank 1)", "emissions"),
    ("P0422", "Main Catalyst Efficiency Below Threshold (Bank 1)", "emissions"),
    ("P0423", "Heated Catalyst Efficiency Below Threshold (Bank 1)", "emissions"),
    ("P0424", "Heated Catalyst Temperature Below Threshold (Bank 1)", "emissions"),
    ("P0430", "Catalyst System Efficiency Below Threshold (Bank 2)", "emissions"),
    ("P0431", "Warm Up Catalyst Efficiency Below Threshold (Bank 2)", "emissions"),
    ("P0432", "Main Catalyst Efficiency Below Threshold (Bank 2)", "emissions"),
    ("P0440", "Evaporative Emission Control System Malfunction", "emissions"),
    ("P0441", "Evaporative Emission Control System Incorrect Purge Flow", "emissions"),
    ("P0442", "Evaporative Emission Control System Leak Detected (Small Leak)", "emissions"),
    ("P0443", "Evaporative Emission Control System Purge Control Valve Circuit", "emissions"),
    ("P0444", "Evaporative Emission Control System Purge Control Valve Circuit Open", "emissions"),
    ("P0445", "Evaporative Emission Control System Purge Control Valve Circuit Shorted", "emissions"),
    ("P0446", "Evaporative Emission Control System Vent Control Circuit Malfunction", "emissions"),
    ("P0447", "Evaporative Emission Control System Vent Control Circuit Open", "emissions"),
    ("P0448", "Evaporative Emission Control System Vent Control Circuit Shorted", "emissions"),
    ("P0449", "Evaporative Emission Control System Vent Valve/Solenoid Circuit", "emissions"),
    ("P0450", "Evaporative Emission Control System Pressure Sensor", "emissions"),
    ("P0451", "Evaporative Emission Control System Pressure Sensor Range/Performance", "emissions"),
    ("P0452", "Evaporative Emission Control System Pressure Sensor Low Input", "emissions"),
    ("P0453", "Evaporative Emission Control System Pressure Sensor High Input", "emissions"),
    ("P0454", "Evaporative Emission Control System Pressure Sensor Intermittent", "emissions"),
    ("P0455", "Evaporative Emission Control System Leak Detected (Large Leak)", "emissions"),
    ("P0456", "Evaporative Emission Control System Leak Detected (Very Small Leak)", "emissions"),
    ("P0457", "Evaporative Emission Control System Leak Detected (Fuel Cap Loose/Off)", "emissions"),
    ("P0460", "Fuel Level Sensor 'A' Circuit", "fuel_air_metering"),
    ("P0461", "Fuel Level Sensor 'A' Circuit Range/Performance", "fuel_air_metering"),
    ("P0462", "Fuel Level Sensor 'A' Circuit Low", "fuel_air_metering"),
    ("P0463", "Fuel Level Sensor 'A' Circuit High", "fuel_air_metering"),
    ("P0464", "Fuel Level Sensor 'A' Circuit Intermittent", "fuel_air_metering"),
    ("P0480", "Cooling Fan 1 Control Circuit", "fuel_air_metering"),
    ("P0481", "Cooling Fan 2 Control Circuit", "fuel_air_metering"),
    ("P0482", "Cooling Fan 3 Control Circuit", "fuel_air_metering"),
]

# --- P05xx — Vehicle Speed Controls, Idle, Aux Inputs ---
P05XX = [
    ("P0500", "Vehicle Speed Sensor 'A' Malfunction", "vehicle_speed_idle"),
    ("P0501", "Vehicle Speed Sensor 'A' Range/Performance", "vehicle_speed_idle"),
    ("P0502", "Vehicle Speed Sensor 'A' Circuit Low Input", "vehicle_speed_idle"),
    ("P0503", "Vehicle Speed Sensor 'A' Circuit Intermittent/Erratic/High", "vehicle_speed_idle"),
    ("P0505", "Idle Air Control System Malfunction", "vehicle_speed_idle"),
    ("P0506", "Idle Air Control System RPM Lower Than Expected", "vehicle_speed_idle"),
    ("P0507", "Idle Air Control System RPM Higher Than Expected", "vehicle_speed_idle"),
    ("P0508", "Idle Air Control System Circuit Low", "vehicle_speed_idle"),
    ("P0509", "Idle Air Control System Circuit High", "vehicle_speed_idle"),
    ("P0510", "Closed Throttle Position Switch Malfunction", "vehicle_speed_idle"),
    ("P0511", "Idle Air Control Circuit Malfunction", "vehicle_speed_idle"),
    ("P0512", "Starter Request Circuit", "vehicle_speed_idle"),
    ("P0513", "Incorrect Immobilizer Key", "vehicle_speed_idle"),
    ("P0520", "Engine Oil Pressure Sensor/Switch Circuit", "vehicle_speed_idle"),
    ("P0521", "Engine Oil Pressure Sensor/Switch Range/Performance", "vehicle_speed_idle"),
    ("P0522", "Engine Oil Pressure Sensor/Switch Low Voltage", "vehicle_speed_idle"),
    ("P0523", "Engine Oil Pressure Sensor/Switch High Voltage", "vehicle_speed_idle"),
    ("P0530", "A/C Refrigerant Pressure Sensor 'A' Circuit", "vehicle_speed_idle"),
    ("P0532", "A/C Refrigerant Pressure Sensor 'A' Circuit Low Input", "vehicle_speed_idle"),
    ("P0533", "A/C Refrigerant Pressure Sensor 'A' Circuit High Input", "vehicle_speed_idle"),
    ("P0560", "System Voltage Malfunction", "vehicle_speed_idle"),
    ("P0561", "System Voltage Unstable", "vehicle_speed_idle"),
    ("P0562", "System Voltage Low", "vehicle_speed_idle"),
    ("P0563", "System Voltage High", "vehicle_speed_idle"),
    ("P0571", "Cruise Control/Brake Switch 'A' Circuit", "vehicle_speed_idle"),
]

# --- P06xx — Computer / Output Circuits ---
P06XX = [
    ("P0600", "Serial Communication Link Malfunction", "computer_output"),
    ("P0601", "Internal Control Module Memory Check Sum Error", "computer_output"),
    ("P0602", "Control Module Programming Error", "computer_output"),
    ("P0603", "Internal Control Module Keep Alive Memory (KAM) Error", "computer_output"),
    ("P0604", "Internal Control Module Random Access Memory (RAM) Error", "computer_output"),
    ("P0605", "Internal Control Module Read Only Memory (ROM) Error", "computer_output"),
    ("P0606", "ECM/PCM Processor", "computer_output"),
    ("P0607", "Control Module Performance", "computer_output"),
    ("P0608", "Control Module VSS Output 'A' Malfunction", "computer_output"),
    ("P0610", "Control Module Vehicle Options Error", "computer_output"),
    ("P0615", "Starter Relay Circuit", "computer_output"),
    ("P0620", "Generator Control Circuit Malfunction", "computer_output"),
    ("P0625", "Generator Field Terminal Circuit Low", "computer_output"),
    ("P0626", "Generator Field Terminal Circuit High", "computer_output"),
    ("P0630", "VIN Not Programmed or Mismatch - ECM/PCM", "computer_output"),
    ("P0645", "A/C Clutch Relay Control Circuit", "computer_output"),
    ("P0646", "A/C Clutch Relay Control Circuit Low", "computer_output"),
    ("P0647", "A/C Clutch Relay Control Circuit High", "computer_output"),
    ("P0650", "Malfunction Indicator Lamp (MIL) Control Circuit", "computer_output"),
    ("P0660", "Intake Manifold Tuning Valve Control Circuit/Open (Bank 1)", "computer_output"),
    ("P0670", "Glow Plug Module Control Circuit", "computer_output"),
    ("P0685", "ECM/PCM Power Relay Control Circuit/Open", "computer_output"),
    ("P0686", "ECM/PCM Power Relay Control Circuit Low", "computer_output"),
    ("P0687", "ECM/PCM Power Relay Control Circuit High", "computer_output"),
    ("P0688", "ECM/PCM Power Relay Sense Circuit/Open", "computer_output"),
    ("P0691", "Fan 1 Control Circuit Low", "computer_output"),
    ("P0692", "Fan 1 Control Circuit High", "computer_output"),
]

# --- P07xx — Transmission ---
P07XX = [
    ("P0700", "Transmission Control System (MIL Request)", "transmission"),
    ("P0701", "Transmission Control System Range/Performance", "transmission"),
    ("P0702", "Transmission Control System Electrical", "transmission"),
    ("P0703", "Torque Converter/Brake Switch 'B' Circuit Malfunction", "transmission"),
    ("P0705", "Transmission Range Sensor Circuit Malfunction (PRNDL Input)", "transmission"),
    ("P0706", "Transmission Range Sensor Circuit Range/Performance", "transmission"),
    ("P0707", "Transmission Range Sensor Circuit Low Input", "transmission"),
    ("P0708", "Transmission Range Sensor Circuit High Input", "transmission"),
    ("P0709", "Transmission Range Sensor Circuit Intermittent", "transmission"),
    ("P0710", "Transmission Fluid Temperature Sensor Circuit", "transmission"),
    ("P0711", "Transmission Fluid Temperature Sensor Range/Performance", "transmission"),
    ("P0712", "Transmission Fluid Temperature Sensor Circuit Low Input", "transmission"),
    ("P0713", "Transmission Fluid Temperature Sensor Circuit High Input", "transmission"),
    ("P0714", "Transmission Fluid Temperature Sensor Circuit Intermittent", "transmission"),
    ("P0715", "Input/Turbine Speed Sensor Circuit Malfunction", "transmission"),
    ("P0716", "Input/Turbine Speed Sensor Circuit Range/Performance", "transmission"),
    ("P0717", "Input/Turbine Speed Sensor Circuit No Signal", "transmission"),
    ("P0720", "Output Speed Sensor Circuit Malfunction", "transmission"),
    ("P0721", "Output Speed Sensor Range/Performance", "transmission"),
    ("P0722", "Output Speed Sensor Circuit No Signal", "transmission"),
    ("P0725", "Engine Speed Input Circuit Malfunction", "transmission"),
    ("P0730", "Incorrect Gear Ratio", "transmission"),
    ("P0731", "Gear 1 Incorrect Ratio", "transmission"),
    ("P0732", "Gear 2 Incorrect Ratio", "transmission"),
    ("P0733", "Gear 3 Incorrect Ratio", "transmission"),
    ("P0734", "Gear 4 Incorrect Ratio", "transmission"),
    ("P0735", "Gear 5 Incorrect Ratio", "transmission"),
    ("P0736", "Reverse Incorrect Ratio", "transmission"),
    ("P0740", "Torque Converter Clutch Circuit Malfunction", "transmission"),
    ("P0741", "Torque Converter Clutch Circuit Performance or Stuck Off", "transmission"),
    ("P0742", "Torque Converter Clutch Circuit Stuck On", "transmission"),
    ("P0743", "Torque Converter Clutch Circuit Electrical", "transmission"),
    ("P0744", "Torque Converter Clutch Circuit Intermittent", "transmission"),
    ("P0750", "Shift Solenoid 'A' Malfunction", "transmission"),
    ("P0751", "Shift Solenoid 'A' Performance or Stuck Off", "transmission"),
    ("P0752", "Shift Solenoid 'A' Stuck On", "transmission"),
    ("P0753", "Shift Solenoid 'A' Electrical", "transmission"),
    ("P0754", "Shift Solenoid 'A' Intermittent", "transmission"),
    ("P0755", "Shift Solenoid 'B' Malfunction", "transmission"),
    ("P0756", "Shift Solenoid 'B' Performance or Stuck Off", "transmission"),
    ("P0760", "Shift Solenoid 'C' Malfunction", "transmission"),
    ("P0765", "Shift Solenoid 'D' Malfunction", "transmission"),
    ("P0770", "Shift Solenoid 'E' Malfunction", "transmission"),
]

# --- P08xx — Transmission (continued) ---
P08XX = [
    ("P0800", "Transfer Case Control System (MIL Request)", "transmission"),
    ("P0801", "Reverse Inhibit Control Circuit Malfunction", "transmission"),
    ("P0810", "Clutch Position Control Error", "transmission"),
    ("P0811", "Excessive Clutch Slippage", "transmission"),
    ("P0812", "Reverse Input Circuit", "transmission"),
    ("P0840", "Transmission Fluid Pressure Sensor/Switch 'A' Circuit", "transmission"),
    ("P0841", "Transmission Fluid Pressure Sensor/Switch 'A' Circuit Range/Performance", "transmission"),
    ("P0842", "Transmission Fluid Pressure Sensor/Switch 'A' Circuit Low", "transmission"),
    ("P0843", "Transmission Fluid Pressure Sensor/Switch 'A' Circuit High", "transmission"),
    ("P0850", "Park/Neutral Switch Input Circuit", "transmission"),
    ("P0868", "Transmission Fluid Pressure Low", "transmission"),
    ("P0869", "Transmission Fluid Pressure High", "transmission"),
    ("P0880", "TCM Power Input Signal", "transmission"),
    ("P0882", "TCM Power Input Signal Low", "transmission"),
    ("P0883", "TCM Power Input Signal High", "transmission"),
    ("P0890", "TCM Power Relay Sense Circuit Low", "transmission"),
    ("P0891", "TCM Power Relay Sense Circuit High", "transmission"),
]

# --- P2xxx — Standardized extended (selected commonly-encountered) ---
P2XXX = [
    ("P2002", "Diesel Particulate Filter Efficiency Below Threshold (Bank 1)", "emissions"),
    ("P2004", "Intake Manifold Runner Control Stuck Open (Bank 1)", "fuel_air_metering"),
    ("P2008", "Intake Manifold Runner Control Circuit/Open (Bank 1)", "fuel_air_metering"),
    ("P2010", "Intake Manifold Runner Control Circuit High (Bank 1)", "fuel_air_metering"),
    ("P2096", "Post Catalyst Fuel Trim System Too Lean (Bank 1)", "emissions"),
    ("P2097", "Post Catalyst Fuel Trim System Too Rich (Bank 1)", "emissions"),
    ("P2100", "Throttle Actuator Control Motor Circuit/Open", "fuel_air_metering"),
    ("P2101", "Throttle Actuator Control Motor Circuit Range/Performance", "fuel_air_metering"),
    ("P2118", "Throttle Actuator Control Motor Current Range/Performance", "fuel_air_metering"),
    ("P2122", "Throttle/Pedal Position Sensor/Switch 'D' Circuit Low Input", "fuel_air_metering"),
    ("P2127", "Throttle/Pedal Position Sensor/Switch 'E' Circuit Low Input", "fuel_air_metering"),
    ("P2135", "Throttle/Pedal Position Sensor/Switch 'A'/'B' Voltage Correlation", "fuel_air_metering"),
    ("P2138", "Throttle/Pedal Position Sensor/Switch 'D'/'E' Voltage Correlation", "fuel_air_metering"),
    ("P2187", "System Too Lean at Idle (Bank 1)", "fuel_air_metering"),
    ("P2188", "System Too Rich at Idle (Bank 1)", "fuel_air_metering"),
    ("P2189", "System Too Lean at Idle (Bank 2)", "fuel_air_metering"),
    ("P2190", "System Too Rich at Idle (Bank 2)", "fuel_air_metering"),
    ("P2195", "O2 Sensor Signal Stuck Lean (Bank 1, Sensor 1)", "fuel_air_metering"),
    ("P2196", "O2 Sensor Signal Stuck Rich (Bank 1, Sensor 1)", "fuel_air_metering"),
    ("P2270", "O2 Sensor Signal Stuck Lean (Bank 1, Sensor 2)", "fuel_air_metering"),
    ("P2279", "Intake Air System Leak", "fuel_air_metering"),
    ("P2336", "Cylinder 1 Above Knock Threshold", "ignition_misfire"),
    ("P2402", "Evaporative Emission System Leak Detection Pump Control Circuit Open", "emissions"),
    ("P2419", "Evaporative Emission System Switching Valve Control Circuit Low", "emissions"),
    ("P2440", "Secondary Air Injection System Switching Valve Stuck Open (Bank 1)", "emissions"),
    ("P2509", "ECM/PCM Power Input Signal Intermittent", "computer_output"),
]

# --- Body / Chassis / Network — common standardized ---
B_CODES = [
    ("B0001", "Driver Frontal Stage 1 Deployment Control", "airbag"),
    ("B0002", "Driver Frontal Stage 2 Deployment Control", "airbag"),
    ("B0010", "Passenger Frontal Stage 1 Deployment Control", "airbag"),
    ("B0011", "Passenger Frontal Stage 2 Deployment Control", "airbag"),
    ("B0020", "Left Side Deployment Loop", "airbag"),
    ("B0024", "Left Side Deployment Loop Stage 2", "airbag"),
    ("B0028", "Right Side Deployment Loop", "airbag"),
    ("B0050", "Passenger Frontal Deployment Loop Stage 1", "airbag"),
    ("B0080", "Left Side Air Bag Disposal", "airbag"),
    ("B0090", "Right Side Air Bag Disposal", "airbag"),
    ("B0100", "Driver Frontal Squib (Single Stage or Stage 1) Circuit Open", "airbag"),
    ("B0101", "Driver Frontal Squib (Single Stage or Stage 1) Circuit Short to Ground", "airbag"),
    ("B0102", "Driver Frontal Squib (Single Stage or Stage 1) Circuit Short to Battery", "airbag"),
    ("B1000", "ECU Malfunction (manufacturer-specific common)", "interior"),
]

C_CODES = [
    ("C0020", "ABS Pump Motor Circuit", "abs_brakes"),
    ("C0035", "Left Front Wheel Speed Sensor Circuit", "abs_brakes"),
    ("C0040", "Right Front Wheel Speed Sensor Circuit", "abs_brakes"),
    ("C0045", "Left Rear Wheel Speed Sensor Circuit", "abs_brakes"),
    ("C0050", "Right Rear Wheel Speed Sensor Circuit", "abs_brakes"),
    ("C0051", "Steering Wheel Position Sensor", "steering"),
    ("C0110", "Pump Motor Circuit Malfunction", "abs_brakes"),
    ("C0121", "Valve Relay Circuit Failure", "abs_brakes"),
    ("C0128", "Low Brake Fluid Indicator Circuit Malfunction", "abs_brakes"),
    ("C0131", "ABS Pressure Circuit", "abs_brakes"),
    ("C0265", "EBCM Relay Circuit", "abs_brakes"),
    ("C0561", "ABS Disabled - System Disable Information", "abs_brakes"),
    ("C0710", "Steering Position Signal", "steering"),
    ("C0800", "Powertrain Power Open Circuit", "abs_brakes"),
    ("C0900", "Tire Pressure Sensor Front Left Battery Low", "tpms"),
    ("C0905", "Tire Pressure Sensor Front Right Battery Low", "tpms"),
]

U_CODES = [
    ("U0001", "High Speed CAN Communication Bus", "network"),
    ("U0002", "High Speed CAN Communication Bus Performance", "network"),
    ("U0073", "Control Module Communication Bus 'A' Off", "network"),
    ("U0100", "Lost Communication With ECM/PCM 'A'", "network"),
    ("U0101", "Lost Communication With TCM", "network"),
    ("U0102", "Lost Communication With Transfer Case Control Module", "network"),
    ("U0103", "Lost Communication With Gear Shift Control Module", "network"),
    ("U0121", "Lost Communication With Anti-Lock Brake System (ABS) Control Module", "network"),
    ("U0125", "Lost Communication With Multi-axis Acceleration Sensor Module", "network"),
    ("U0126", "Lost Communication With Steering Angle Sensor Module", "network"),
    ("U0140", "Lost Communication With Body Control Module", "network"),
    ("U0151", "Lost Communication With Restraints Control Module", "network"),
    ("U0155", "Lost Communication With Instrument Panel Cluster Control Module", "network"),
    ("U0184", "Lost Communication With Radio", "network"),
    ("U0300", "Internal Control Module Software Incompatibility", "network"),
    ("U0401", "Invalid Data Received From ECM/PCM 'A'", "network"),
    ("U0402", "Invalid Data Received From TCM", "network"),
    ("U0415", "Invalid Data Received From Vehicle Security Control Module", "network"),
]

# --- Manufacturer-specific commonly-encountered (P1xxx) ---
# Selected very common P1xxx codes across major manufacturers.
# These are NOT standardized — meaning the same code can mean different things
# on different makes. Marked manufacturer_specific=true.
MFR_SPECIFIC = [
    ("P1000", "OBD-II Monitor Testing Not Complete (Ford / Mazda / Jaguar)", "diagnostic"),
    ("P1101", "Mass Air Flow Sensor Out of Self Test Range (Ford / Lincoln)", "fuel_air_metering"),
    ("P1131", "Lack of HO2S Switch - Sensor Indicates Lean (Ford / Mazda)", "fuel_air_metering"),
    ("P1135", "HO2S Heater Circuit Bank 1 Sensor 1 Performance (Ford / Mercury)", "fuel_air_metering"),
    ("P1151", "Lack of HO2S Switch - Sensor Indicates Lean (Ford / Mazda, Bank 2)", "fuel_air_metering"),
    ("P1320", "Ignition Failure Sensor Circuit (Nissan / Infiniti)", "ignition_misfire"),
    ("P1336", "Crankshaft Position System Variation Not Learned (GM)", "ignition_misfire"),
    ("P1399", "Random Misfire Detected (Honda / Acura)", "ignition_misfire"),
    ("P1457", "EVAP Control System Leakage - Canister System (Honda / Acura)", "emissions"),
    ("P1604", "Startability Malfunction (Toyota / Lexus)", "computer_output"),
    ("P1684", "Battery Was Disconnected Within Last 50 Starts (Chrysler / Dodge / Jeep)", "computer_output"),
    ("P1800", "Manufacturer-Specific Transmission Code (various)", "transmission"),
    ("P2509", "ECM/PCM Power Input Signal Intermittent (standardized but commonly mfr-specific use)", "computer_output"),
    # GM-specific common ones
    ("P0014", "Camshaft Position 'B' - Timing Over-Advanced (Bank 1) - GM AFM trigger", "fuel_air_metering"),
]


def category_for(code: str) -> str:
    """First char of code maps to category."""
    return {
        "P": "powertrain",
        "B": "body",
        "C": "chassis",
        "U": "network",
    }[code[0].upper()]


def is_standardized(code: str) -> bool:
    """Standardized: P00xx-P09xx, B00xx, C00xx, U00xx. P1xxx is mfr-specific."""
    first_digit = code[1]
    return first_digit == "0"


def build():
    all_entries: dict[str, tuple[str, str]] = {}
    # Order matters for deduplication: later overrides earlier.
    for group in [P00XX, P01XX, P02XX, P03XX, P04XX, P05XX, P06XX, P07XX, P08XX, P2XXX,
                  B_CODES, C_CODES, U_CODES, MFR_SPECIFIC]:
        for code, desc, subsystem in group:
            # If we have a MFR_SPECIFIC entry for a code already in standardized
            # set, the MFR note is a comment overlay; keep the SAE definition.
            if code in all_entries:
                continue
            all_entries[code] = (desc, subsystem)

    records = []
    for code in sorted(all_entries):
        desc, subsystem = all_entries[code]
        std = is_standardized(code)
        records.append({
            "code": code,
            "description": desc,
            "category": category_for(code),
            "subsystem": subsystem,
            "standardized": std,
            "manufacturer_specific": not std,
        })
    return records


def main():
    records = build()
    out = Path(__file__).resolve().parent.parent / "data" / "sae_j2012.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(records, fh, indent=2, ensure_ascii=False)
        fh.write("\n")
    print(f"wrote {len(records)} entries to {out}")
    # Counts by category for sanity
    from collections import Counter
    cat = Counter(r["category"] for r in records)
    std = Counter(r["standardized"] for r in records)
    print(f"  by category: {dict(cat)}")
    print(f"  standardized: {std[True]} / mfr-specific: {std[False]}")


if __name__ == "__main__":
    main()
