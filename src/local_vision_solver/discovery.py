import ipaddress
import socket

from zeroconf import IPVersion, ServiceInfo, Zeroconf
import ifaddr

from .config import ServerConfig

SERVICE_TYPE = "_visionsolver._tcp.local."


def lan_addresses() -> list[str]:
    # Enumerate interfaces directly: no DNS resolution or Internet connectivity probe.
    candidates = [ip.ip for adapter in ifaddr.get_adapters() for ip in adapter.ips if isinstance(ip.ip, str)]
    return sorted({address for address in candidates
                   if not ipaddress.ip_address(address).is_loopback
                   and ipaddress.ip_address(address).is_private})


class Advertisement:
    def __init__(self, config: ServerConfig):
        addresses = [config.advertise_address] if config.advertise_address else lan_addresses()
        if not addresses:
            raise RuntimeError("No LAN IPv4 address found; connect Wi-Fi or configure server.advertise_address")
        for address in addresses:
            value = ipaddress.ip_address(address)
            if value.version != 4 or not value.is_private or value.is_loopback:
                raise ValueError("Bonjour advertisement needs a local LAN IPv4 address")
        self.zeroconf = Zeroconf(ip_version=IPVersion.V4Only)
        self.info = ServiceInfo(SERVICE_TYPE, f"{config.service_name}.{SERVICE_TYPE}",
                                addresses=[socket.inet_aton(a) for a in addresses], port=config.port,
                                properties={"api_version": "1", "path": "/health"},
                                server=f"{socket.gethostname().split('.')[0]}.local.")
        try:
            self.zeroconf.register_service(self.info, allow_name_change=True)
        except Exception:
            self.zeroconf.close()
            raise

    def close(self):
        self.zeroconf.unregister_service(self.info)
        self.zeroconf.close()
