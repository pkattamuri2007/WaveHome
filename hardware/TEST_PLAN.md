**Test Plan as of 10/31/2026**

# WaveHome – ESP32-S3 UDP & CSI Communication Test Plan

## Objective

Verify that the ESP32-S3 can collect Channel State Information (CSI) and transmit the resulting data over Wi-Fi to a laptop for reception and processing.

---

## 1. Test Equipment & Software

- ESP32-S3 development board
- Wi-Fi router (2.4 GHz Wi-Fi recommended for initial testing)
- Laptop connected to the same local network
- ESP-IDF development environment
- Python 3 UDP receiver (`udp_receiver.py`)
- ESP-CSI example project and custom UDP sender (`app_main.c`)

---

## 2. Testing Procedure

### Phase 1 – Local UDP Receiver Verification

**Procedure:**

1. Run the Python UDP receiver on the laptop using port `5005`.
2. Send a locally generated test packet to `127.0.0.1:5005`.
3. Verify that the receiver correctly prints the received message.

**Pass Criteria:**

The laptop successfully receives and displays the test packet.

**Testing Checklist:**

- [ ] Python UDP receiver running on port 5005
- [ ] Local test packet transmitted
- [ ] Test packet successfully received and displayed

---

### Phase 2 – ESP32-S3 UDP Communication

**Procedure:**

1. Connect the ESP32-S3 and laptop to the same Wi-Fi network.
2. Configure the ESP32 sender with the laptop's local IPv4 address.
3. Flash the UDP sender firmware to the ESP32-S3.
4. Transmit a test packet every second to the laptop.
5. Verify that the Python receiver displays the incoming packets.

**Pass Criteria:**

The laptop consistently receives the ESP32's UDP messages, with the expected contents and source address.

**Testing Checklist:**

- [ ] ESP32-S3 connected to Wi-Fi
- [ ] Laptop connected to the same network
- [ ] ESP32-S3 configured with laptop IPv4 address
- [ ] UDP sender firmware successfully flashed
- [ ] Test packets transmitted every second
- [ ] Laptop successfully receives incoming packets

---

### Phase 3 – CSI Data Acquisition

**Procedure:**

1. Configure the ESP32-S3 to collect CSI using the ESP-IDF ESP-CSI implementation.
2. Verify that CSI callbacks are triggered when suitable Wi-Fi packets are received.
3. Inspect the CSI output and confirm that metadata and CSI buffer values are being collected.
4. Record the CSI output format, including:
   - Timestamps
   - Received Signal Strength Indicator (RSSI)
   - CSI buffer length
   - Complex sample representation

**Pass Criteria:**

The ESP32-S3 successfully collects CSI data and produces valid, interpretable output.

**Testing Checklist:**

- [ ] CSI collection configured
- [ ] CSI callbacks successfully triggered
- [ ] CSI metadata collected
- [ ] CSI buffer values collected
- [ ] CSI output format documented
- [ ] CSI data verified as valid and interpretable

---

### Phase 4 – CSI Transmission Over UDP

**Procedure:**

1. Integrate the CSI callback with the UDP sender.
2. Package CSI metadata and sample values into UDP packets.
3. Transmit the packets to the laptop.
4. Verify that the Python receiver can parse and display the received CSI data.
5. Check:
   - Packet transmission frequency
   - Missing packets
   - Data integrity

**Pass Criteria:**

The laptop consistently receives CSI packets with correctly formatted metadata and sample values.

**Testing Checklist:**

- [ ] CSI callback integrated with UDP sender
- [ ] CSI data packaged into UDP packets
- [ ] CSI packets transmitted to laptop
- [ ] Python receiver successfully parses CSI data
- [ ] Packet frequency verified
- [ ] Missing packets checked
- [ ] Data integrity verified

---

## 3. Data to Record

Record the following measurements and observations during testing:

| Parameter | Description |
|---|---|
| Transmission Frequency | ESP32-S3 packet transmission frequency |
| Reception Frequency | Laptop packet reception frequency |
| Packet Loss | Missing packets or sequence numbers |
| Packet Size | UDP packet size and CSI buffer length |
| RSSI | Received Signal Strength Indicator |
| Timestamps | Local timestamps associated with CSI data |
| CSI Parsing | Successful parsing of received CSI values |
| Connection Stability | Connection interruptions or transmission errors |

### Test Results

| Test Phase | Expected Result | Status |
|---|---|---|
| Phase 1 – Local UDP | Laptop receives local test packets | Not Started |
| Phase 2 – ESP32-S3 UDP | Laptop receives wireless UDP packets | Not Started |
| Phase 3 – CSI Acquisition | ESP32-S3 collects valid CSI data | Not Started |
| Phase 4 – CSI over UDP | Laptop receives and parses CSI packets | Not Started |

---

## 4. Expected Outcome

Successful completion will establish an **end-to-end wireless data pipeline** between the ESP32-S3 and laptop.

The system will be capable of:

- Collecting CSI measurements
- Transmitting CSI data over UDP
- Receiving CSI packets on the laptop
- Processing and analyzing received CSI data

---

## 5. Implementation Priority

> [!IMPORTANT]
> **Complete and verify basic UDP communication before integrating CSI data.**

This separates networking issues from CSI acquisition and data-formatting issues, making debugging significantly easier.

### Recommended Implementation Order

1. **Local UDP Verification** – Confirm that the Python receiver works.
2. **Wireless UDP Communication** – Establish ESP32-S3 to laptop communication.
3. **CSI Acquisition** – Configure and validate CSI collection.
4. **CSI Transmission** – Integrate CSI data with the UDP communication pipeline.

> [!NOTE]
> Each phase should meet its pass criteria before proceeding to the next phase.
