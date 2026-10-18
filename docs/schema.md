# WaveHome Packet Schema (v0.1)

This is the contract between hardware and software. Hardware sends packets in this format; software accepts and validates them. Do not change fields without telling both teams, and bump the version number when you do.

## Packet format

Each packet is one JSON object representing one CSI sample from one receiver.

```json
{
  "schema_version": "0.1",
  "node_id": "rx1",
  "seq": 12345,
  "ts_device_us": 1729280000123456,
  "rssi": -45,
  "channel": 6,
  "bandwidth_mhz": 20,
  "csi_len": 128,
  "csi": [12, -7, 3, 9]
}
```

## Fields

| Field | Type | Description |
|---|---|---|
| schema_version | string | Schema version, currently "0.1" |
| node_id | string | Unique ID of the receiver that captured the sample (e.g., "rx1") |
| seq | integer | Counter that increments by 1 per packet, per node. Used to detect dropped packets |
| ts_device_us | integer | Device timestamp in microseconds. Server also records its own arrival time |
| rssi | integer | Received signal strength in dBm (negative number) |
| channel | integer | WiFi channel in use |
| bandwidth_mhz | integer | Channel bandwidth in MHz (20 or 40) |
| csi_len | integer | Number of values in the csi array. Must equal the array length |
| csi | array of integers | Raw CSI values, signed integers from -128 to 127 |

## Notes

- The csi array is interleaved pairs per subcarrier. Per Espressif's esp-csi docs this is imaginary then real, but **hardware team: confirm this against real output** and update this file.
- Software computes amplitude and phase from the pairs.
- The server adds its own arrival timestamp when it receives a packet. Devices do not need to send it.
- Rejected packets: wrong types, missing fields, csi_len not matching the array length, or csi values out of range.

## JSON Schema (for validation)

```json
{
  "$schema": "http://json-schema.org/draft-07/schema#",
  "title": "WaveHomeCSIPacket",
  "type": "object",
  "required": ["schema_version", "node_id", "seq", "ts_device_us", "rssi", "channel", "bandwidth_mhz", "csi_len", "csi"],
  "properties": {
    "schema_version": { "type": "string" },
    "node_id": { "type": "string" },
    "seq": { "type": "integer", "minimum": 0 },
    "ts_device_us": { "type": "integer", "minimum": 0 },
    "rssi": { "type": "integer", "maximum": 0 },
    "channel": { "type": "integer", "minimum": 1 },
    "bandwidth_mhz": { "type": "integer", "enum": [20, 40] },
    "csi_len": { "type": "integer", "minimum": 1 },
    "csi": {
      "type": "array",
      "items": { "type": "integer", "minimum": -128, "maximum": 127 }
    }
  }
}
```

## Changelog

- v0.1: initial draft
