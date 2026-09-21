from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional


def get_mock_available_slots(service_address: str, preferred_date: str, preferred_time_range: str) -> List[str]:
    if not preferred_date:
        preferred_date = (datetime.now().date() + timedelta(days=1)).isoformat()

    mapping = {
        "morning": [
            f"{preferred_date} 09:00-11:00",
            f"{preferred_date} 10:00-12:00",
        ],
        "afternoon": [
            f"{preferred_date} 14:00-16:00",
            f"{preferred_date} 15:00-17:00",
        ],
        "evening": [
            f"{preferred_date} 18:00-20:00",
        ],
    }
    return mapping.get(preferred_time_range, [])


def evaluate_dispatch_need(memory: Dict[str, Any]) -> Optional[bool]:
    service = memory.get("service")
    issue_type = memory.get("issue_type")
    info = memory.get("known_info", {})

    if service != "network" or not issue_type:
        return None

    if issue_type == "no_internet":
        if info.get("affected_scope") == "all_devices":
            if info.get("modem_light_status") in ["red", "off"]:
                return True
            if info.get("modem_reboot_done") == "yes":
                if info.get("router_exists") == "yes":
                    return info.get("router_reboot_done") == "yes"
                return True

    if issue_type == "slow_speed":
        if info.get("speedtest_done") == "yes":
            down = info.get("download_speed")
            up = info.get("upload_speed")
            if isinstance(down, (int, float)) and down < 100:
                return True
            if isinstance(up, (int, float)) and up < 20:
                return True

    return False


def has_contact_info(memory: Dict[str, Any]) -> bool:
    info = memory.get("known_info", {})
    return all(k in info for k in ["customer_name", "contact_phone", "service_address"])


def has_schedule_pref(memory: Dict[str, Any]) -> bool:
    info = memory.get("known_info", {})
    return all(k in info for k in ["preferred_date", "preferred_time_range"])


def maybe_schedule(memory: Dict[str, Any]) -> Dict[str, Any]:
    info = memory.get("known_info", {})

    if (
        memory.get("need_dispatch") is True
        and has_contact_info(memory)
        and has_schedule_pref(memory)
        and "appointment_slot" not in info
    ):
        slots = get_mock_available_slots(
            info.get("service_address", ""),
            info.get("preferred_date", ""),
            info.get("preferred_time_range", ""),
        )
        memory["available_slots"] = slots
        if slots:
            info["appointment_slot"] = slots[0]
            memory["known_info"] = info

    return memory
