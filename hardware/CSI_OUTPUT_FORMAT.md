**Output Format as of 10/31/2026**

# ESP32-S3 CSI Output Format Documentation

**Project:** WaveHome  
**Example:** Espressif ESP-CSI `csi_recv_router`  
**Hardware Target:** ESP32-S3  
**ESP-IDF Version:** v5.5.6  
**Output Format:** CSV (Comma-Separated Values)

---

## 1. Overview

The `csi_recv_router` example collects **Channel State Information (CSI)** from received Wi-Fi packets and prints each measurement as a CSV record.

Each record contains:

- Wi-Fi packet metadata
- CSI buffer length and validity information
- An array of CSI measurements

The example connects to a Wi-Fi access point, periodically pings the router, and collects CSI from matching received packets.

---

## 2. CSV Record Structure

The ESP32-S3 example prints the following CSV header:

```csv
type,id,mac,rssi,rate,sig_mode,mcs,bandwidth,smoothing,not_sounding,aggregation,stbc,fec_coding,sgi,noise_floor,ampdu_cnt,channel,secondary_channel,local_timestamp,ant,sig_len,rx_format,len,first_word,data
```

Each subsequent line represents one CSI measurement.

### Example CSV Record

The following illustrates the record structure using example values:

```text
CSI_DATA,0,AA:BB:CC:DD:EE:FF,-30,11,1,6,1,0,1,0,1,0,0,-93,0,13,0,2751923,0,67,1,128,0,"[12,-7,3,9,...]"
```

> [!NOTE]
> This is an illustrative record. Actual CSI values, buffer lengths, and metadata depend on the received Wi-Fi packet and CSI configuration.

### 2.1 Metadata Fields

| Field | Description |
|---|---|
| `type` | Record identifier. Printed as `CSI_DATA`. |
| `id` | Incrementing packet counter (`s_count`). |
| `mac` | Source MAC address of the received packet. |
| `rssi` | Received Signal Strength Indicator. |
| `rate` | Wi-Fi packet rate field. |
| `sig_mode` | Signal mode reported by the Wi-Fi driver. |
| `mcs` | Modulation and Coding Scheme index. |
| `bandwidth` | Channel bandwidth field (`rx_ctrl.cwb`). |
| `smoothing` | Smoothing flag. |
| `not_sounding` | Not-sounding flag. |
| `aggregation` | Aggregation flag. |
| `stbc` | Space-Time Block Coding field. |
| `fec_coding` | Forward Error Correction coding field. |
| `sgi` | Short Guard Interval flag. |
| `noise_floor` | Received noise-floor measurement. |
| `ampdu_cnt` | AMPDU count field. |
| `channel` | Primary Wi-Fi channel. |
| `secondary_channel` | Secondary-channel information. |
| `local_timestamp` | Local packet-reception timestamp in microseconds. |
| `ant` | Antenna field reported by the driver. |
| `sig_len` | Signal length reported by the receive control structure. |
| `rx_format` | Receive-format field. In this example, the source prints `rx_ctrl.sig_mode` again. |
| `len` | Number of valid CSI buffer bytes (`info->len`). |
| `first_word` | First-word validity flag (`info->first_word_invalid`). |
| `data` | Array of gain-compensated CSI values. |

### 2.2 Timestamp Information

> [!IMPORTANT]
> The `local_timestamp` field represents **local device time**, not Unix epoch time.

ESP-IDF documents the timestamp as precise only when modem sleep and light sleep are disabled.

This distinction is important when synchronizing CSI measurements with other devices or external data sources.

---

## 3. CSI Buffer Structure

The ESP-IDF v5.5.6 definition of `wifi_csi_info_t` includes the following fields:

```c
bool first_word_invalid;
int8_t *buf;
uint16_t len;
```

### 3.1 Buffer Field Definitions

| Field | Data Type | Description |
|---|---|---|
| `buf` | `int8_t *` | Pointer to the CSI buffer containing signed 8-bit values. |
| `len` | `uint16_t` | Number of valid bytes in the CSI buffer. |
| `first_word_invalid` | `bool` | Indicates whether the first four bytes of CSI data are invalid due to a hardware limitation. |

### 3.2 CSI Array Printing Implementation

The example prints the CSI array using the following C code:

```c
ets_printf(",%d,%d,\"[%d",
           info->len,
           info->first_word_invalid,
           (int16_t)(compensate_gain * info->buf[0]));

for (int i = 1; i < info->len; i++) {
    ets_printf(",%d",
               (int16_t)(compensate_gain * info->buf[i]));
}
```

### 3.3 Important Data Distinction

The original CSI buffer contains **signed 8-bit integers**.

However, the example multiplies each value by `compensate_gain` and casts the result to `int16_t` before printing.

Therefore:

- The original buffer values are signed 8-bit values.
- The printed CSV values are gain-compensated integers.
- The CSV array length is determined by `len`.
- `len` represents the number of buffer bytes/elements, not directly the number of complex subcarriers.

> [!WARNING]
> Do not assume that the gain-compensated integers printed in the CSV are identical to the original signed 8-bit buffer values.

---

## 4. Complex CSI Representation

Espressif documents each CSI subcarrier measurement as two values:

1. **Imaginary component**
2. **Real component**

These values are interleaved in the CSI buffer.

### 4.1 Example CSI Array

Consider the following CSI values:

```text
[12, -7, 3, 9]
```

This represents two complex CSI measurements:

| Subcarrier | Imaginary Component | Real Component |
|---|---|---|
| 1 | 12 | -7 |
| 2 | 3 | 9 |

### 4.2 Complex Number Representation

The corresponding complex values are:

```text
H₁ = -7 + 12j
H₂ =  9 +  3j
```

In general:

```math
H_k = \text{Real}_k + j\text{Imaginary}_k
```

When parsing the CSI array:

- The **first value** in each pair is the imaginary component.
- The **second value** in each pair is the real component.

For example:

```text
CSI Array: [12, -7, 3, 9]
             |   |  |  |
             Im  Re Im Re
```

### 4.3 CSI Data Validity

> [!WARNING]
> If `first_word` is `1`, the first four bytes of the CSI buffer are invalid.

A parser must account for this rather than blindly treating every pair as valid CSI data.

This is especially important when converting the raw CSI array into complex-valued subcarrier measurements.

---

## 5. ESP32-S3 CSI Configuration

The example configures CSI collection using the following structure:

```c
wifi_csi_config_t csi_config = {
    .lltf_en           = true,
    .htltf_en          = false,
    .stbc_htltf2_en    = false,
    .ltf_merge_en      = true,
    .channel_filter_en = true,
    .manu_scale        = true,
    .shift             = true,
};
```

### 5.1 Configuration Parameters

| Configuration | Value | Purpose |
|---|---|---|
| `lltf_en` | `true` | Enables Legacy Long Training Field CSI. |
| `htltf_en` | `false` | Disables HT-LTF CSI collection. |
| `stbc_htltf2_en` | `false` | Disables STBC HT-LTF CSI collection. |
| `ltf_merge_en` | `true` | Enables LTF merging. |
| `channel_filter_en` | `true` | Enables channel filtering. |
| `manu_scale` | `true` | Enables manual CSI scaling. |
| `shift` | `true` | Configures the scaling shift field. |

### 5.2 Configuration Implications

This configuration determines which CSI measurements are collected.

> [!NOTE]
> The resulting CSI buffer should not be assumed to contain every possible Wi-Fi training field.

The available CSI measurements depend on the enabled training fields and the format of the received Wi-Fi packets.

---

## 6. CSI Collection and Output Flow

The `csi_recv_router` example follows the sequence below.

### Step 1 – Network Initialization

`app_main()` initializes networking and connects the ESP32-S3 to Wi-Fi.

### Step 2 – CSI Configuration

`wifi_csi_init()` configures CSI collection.

### Step 3 – Callback Registration

`esp_wifi_set_csi_rx_cb()` registers the CSI receive callback.

### Step 4 – Router Communication

`wifi_ping_router_start()` periodically pings the router.

### Step 5 – CSI Packet Processing

`wifi_csi_rx_cb()` processes matching received packets.

### Step 6 – CSV Output

The callback prints:

- Packet metadata
- CSI buffer length
- First-word validity information
- Gain-compensated CSI array values

The callback filters packets by comparing the packet's source MAC address with the router's BSSID.

### Collection Flow Summary

```text
ESP32-S3 Initialization
          |
          v
Connect to Wi-Fi Router
          |
          v
Configure CSI Collection
          |
          v
Register CSI Receive Callback
          |
          v
Periodically Ping Router
          |
          v
Receive Matching Wi-Fi Packets
          |
          v
Execute CSI Callback
          |
          v
Extract Metadata and CSI Buffer
          |
          v
Apply Gain Compensation
          |
          v
Print CSI Record as CSV
```

---

## 7. Important Implementation Considerations

### 7.1 Serial Output vs. UDP Transmission

The `csi_recv_router` example prints CSI data to the **serial output**.

It does **not** transmit CSI over UDP.

For WaveHome, a separate UDP transmission implementation is required.

### 7.2 Router-Based CSI Collection

The example is configured to collect CSI from the connected router.

Its callback filters packets using the router's BSSID.

### 7.3 Gain-Compensated CSI Values

The CSI array contains gain-compensated values, not necessarily the original buffer values.

### 7.4 Invalid First-Word Data

The first four bytes may be invalid when `first_word_invalid` is true.

### 7.5 Timestamp Interpretation

The timestamp is a local microsecond timestamp, not a Unix timestamp.

### 7.6 Variable CSI Buffer Length

The number of CSI values and subcarriers can vary depending on:

- Packet format
- Training-field configuration
- CSI collection settings

### 7.7 CSV Receive-Format Field

The CSV `rx_format` column is populated with `rx_ctrl.sig_mode` in this particular source file.

---

## 8. Source References

### 8.1 Espressif ESP-CSI Repository

[Espressif ESP-CSI GitHub Repository](https://github.com/espressif/esp-csi)

### 8.2 ESP-CSI Example Source

**Example:** `csi_recv_router`

**Source File:**

```text
examples/get-started/csi_recv_router/main/app_main.c
```

### 8.3 ESP-IDF v5.5.6 Structure Definitions

**Source File:**

```text
components/esp_wifi/include/local/esp_wifi_types_native.h
```

### 8.4 Official Wi-Fi CSI Documentation

[Espressif ESP32-S3 Wi-Fi CSI Documentation](https://docs.espressif.com/projects/esp-idf/en/latest/esp32s3/api-guides/wifi-driver/wifi-vendor-features.html)

---

## 9. Documentation Scope

> [!IMPORTANT]
> This document describes the ESP32-S3 CSI output generated by the `csi_recv_router` example.

It does **not** define the separate WaveHome application or network schema.

The WaveHome implementation will require additional design decisions regarding UDP packet structure, CSI serialization, packet sequencing, and data processing.
