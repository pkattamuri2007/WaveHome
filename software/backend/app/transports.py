"""Device-facing transports. Each UDP datagram or MQTT message carries one JSON packet."""

import asyncio
import logging
import socket

from .ingest import Ingestor

log = logging.getLogger("wavehome")


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, ingestor: Ingestor):
        self.ingestor = ingestor

    def datagram_received(self, data: bytes, addr) -> None:
        self.ingestor.handle_raw(data, "udp")


async def start_udp(ingestor: Ingestor, host: str, port: int) -> asyncio.DatagramTransport:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    # A bigger receive buffer stops the OS dropping bursts from several nodes.
    for size in (4 << 20, 1 << 20):
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, size)
            break
        except OSError:
            continue
    sock.bind((host, port))
    loop = asyncio.get_running_loop()
    transport, _ = await loop.create_datagram_endpoint(lambda: _UdpProtocol(ingestor), sock=sock)
    log.info("UDP listening on %s:%d", host, transport.get_extra_info("sockname")[1])
    return transport


def start_mqtt(ingestor: Ingestor, host: str, port: int, topic: str):
    """Subscribe to topic on the broker. Reconnects in the background if the broker is down."""
    import paho.mqtt.client as mqtt

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)

    def on_connect(client, userdata, flags, reason_code, properties):
        if reason_code.is_failure:
            log.warning("MQTT connect to %s:%d failed: %s", host, port, reason_code)
            return
        client.subscribe(topic, qos=0)
        log.info("MQTT subscribed to %s on %s:%d", topic, host, port)

    def on_message(client, userdata, msg):
        ingestor.handle_raw(msg.payload, "mqtt")

    client.on_connect = on_connect
    client.on_message = on_message
    client.connect_async(host, port)
    client.loop_start()
    return client
