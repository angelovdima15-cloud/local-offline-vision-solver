from zeroconf import ServiceInfo
from local_vision_solver.discovery import SERVICE_TYPE


def test_bonjour_service_type_is_valid_and_within_dns_sd_limit():
    assert len(SERVICE_TYPE.split(".")[0].lstrip("_")) <= 15
    info = ServiceInfo(SERVICE_TYPE, "Local Vision Solver." + SERVICE_TYPE, port=8765)
    assert info.port == 8765

