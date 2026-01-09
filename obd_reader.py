"""
Real OBD-II Reader
Uses python-obd library to connect to ELM327 Bluetooth adapter.
This file is NOT active yet - will be connected when adapter is available.
"""

import obd
from typing import Optional
from schemas import DTCCode, OBDSnapshot
from datetime import datetime


class OBDReader:
    def __init__(self, port: Optional[str] = None):
        """
        Initialize OBD connection.
        port: COM port like "COM3" - leave None to auto-detect
        """
        self.connection = None
        self.port = port
    
    def connect(self) -> bool:
        """Connect to the OBD adapter. Returns True if successful."""
        try:
            if self.port:
                self.connection = obd.OBD(self.port)
            else:
                self.connection = obd.OBD()  # Auto-detect
            
            if self.connection.is_connected():
                print(f"[OBD] Connected to {self.connection.port_name()}")
                return True
            else:
                print("[OBD] Failed to connect")
                return False
        except Exception as e:
            print(f"[OBD] Connection error: {e}")
            return False
    
    def disconnect(self):
        """Close the OBD connection."""
        if self.connection:
            self.connection.close()
            print("[OBD] Disconnected")
    
    def is_connected(self) -> bool:
        """Check if connected to adapter."""
        return self.connection is not None and self.connection.is_connected()
    
    def read_dtc_codes(self) -> list[DTCCode]:
        """Read diagnostic trouble codes from the vehicle."""
        if not self.is_connected():
            print("[OBD] Not connected")
            return []
        
        try:
            response = self.connection.query(obd.commands.GET_DTC)
            if response.is_null():
                return []
            
            codes = []
            for code, description in response.value:
                codes.append(DTCCode(
                    code=code,
                    description=description if description else "No description available"
                ))
            return codes
        except Exception as e:
            print(f"[OBD] Error reading DTCs: {e}")
            return []
    
    def read_snapshot(self) -> OBDSnapshot:
        """Read full vehicle snapshot including codes and live data."""
        if not self.is_connected():
            return OBDSnapshot(
                timestamp=datetime.now(),
                dtc_codes=[],
                is_mock=False
            )
        
        snapshot = OBDSnapshot(
            timestamp=datetime.now(),
            dtc_codes=self.read_dtc_codes(),
            is_mock=False
        )
        
        # Read live data
        try:
            # RPM
            rpm_response = self.connection.query(obd.commands.RPM)
            if not rpm_response.is_null():
                snapshot.rpm = rpm_response.value.magnitude
            
            # Speed (comes in km/h, convert to mph)
            speed_response = self.connection.query(obd.commands.SPEED)
            if not speed_response.is_null():
                snapshot.speed_mph = speed_response.value.magnitude * 0.621371
            
            # Coolant temp (comes in Celsius, convert to Fahrenheit)
            coolant_response = self.connection.query(obd.commands.COOLANT_TEMP)
            if not coolant_response.is_null():
                celsius = coolant_response.value.magnitude
                snapshot.coolant_temp_f = (celsius * 9/5) + 32
        
        except Exception as e:
            print(f"[OBD] Error reading live data: {e}")
        
        return snapshot
    
    def clear_codes(self) -> bool:
        """Clear diagnostic trouble codes. Use with caution!"""
        if not self.is_connected():
            return False
        
        try:
            self.connection.query(obd.commands.CLEAR_DTC)
            print("[OBD] Codes cleared")
            return True
        except Exception as e:
            print(f"[OBD] Error clearing codes: {e}")
            return False
    
    def get_vehicle_info(self) -> dict:
        """Get vehicle identification info if available."""
        info = {}
        
        if not self.is_connected():
            return info
        
        try:
            # VIN (not all vehicles support this)
            vin_response = self.connection.query(obd.commands.VIN)
            if not vin_response.is_null():
                info["vin"] = vin_response.value
        except:
            pass
        
        return info


# Global reader instance
_reader: Optional[OBDReader] = None


def get_reader() -> OBDReader:
    """Get or create the global OBD reader."""
    global _reader
    if _reader is None:
        _reader = OBDReader()
    return _reader


def connect_obd(port: Optional[str] = None) -> bool:
    """Connect to OBD adapter. Call this once at startup."""
    reader = get_reader()
    if port:
        reader.port = port
    return reader.connect()


def read_vehicle() -> OBDSnapshot:
    """Read current vehicle data."""
    return get_reader().read_snapshot()


def disconnect_obd():
    """Disconnect from OBD adapter."""
    get_reader().disconnect()