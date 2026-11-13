"""Windows System Intelligence Service using safe standard library and platform APIs.

Provides real metrics for CPU, RAM, Disk partitions, and Network adapters with zero
external dependencies, non-blocking execution, and deterministic structured outputs.
"""

from __future__ import annotations

import ctypes
import os
import platform
import shutil
import socket
import time
import winreg
from ctypes import wintypes
from typing import Any

from infrastructure.logging import get_logger

logger = get_logger("system_service")


# --- Win32 Ctypes Structures ---


class FILETIME(ctypes.Structure):
    _fields_ = [("dwLowDateTime", wintypes.DWORD), ("dwHighDateTime", wintypes.DWORD)]


def _filetime_to_int(ft: FILETIME) -> int:
    return (ft.dwHighDateTime << 32) | ft.dwLowDateTime


class MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", wintypes.DWORD),
        ("dwMemoryLoad", wintypes.DWORD),
        ("ullTotalPhys", ctypes.c_uint64),
        ("ullAvailPhys", ctypes.c_uint64),
        ("ullTotalPageFile", ctypes.c_uint64),
        ("ullAvailPageFile", ctypes.c_uint64),
        ("ullTotalVirtual", ctypes.c_uint64),
        ("ullAvailVirtual", ctypes.c_uint64),
        ("ullAvailExtendedVirtual", ctypes.c_uint64),
    ]


class SYSTEM_INFO(ctypes.Structure):
    class _DUMMYUNIONNAME(ctypes.Union):
        class _DUMMYSTRUCTNAME(ctypes.Structure):
            _fields_ = [("wProcessorArchitecture", wintypes.WORD), ("wReserved", wintypes.WORD)]

        _fields_ = [("dwOemId", wintypes.DWORD), ("s", _DUMMYSTRUCTNAME)]

    _anonymous_ = ("u",)
    _fields_ = [
        ("u", _DUMMYUNIONNAME),
        ("dwPageSize", wintypes.DWORD),
        ("lpMinimumApplicationAddress", ctypes.c_void_p),
        ("lpMaximumApplicationAddress", ctypes.c_void_p),
        ("dwActiveProcessorMask", ctypes.c_size_t),
        ("dwNumberOfProcessors", wintypes.DWORD),
        ("dwProcessorType", wintypes.DWORD),
        ("dwAllocationGranularity", wintypes.DWORD),
        ("wProcessorLevel", wintypes.WORD),
        ("wProcessorRevision", wintypes.WORD),
    ]


MAX_ADAPTER_NAME_LENGTH = 256
MAX_ADAPTER_DESCRIPTION_LENGTH = 128
MAX_ADAPTER_ADDRESS_LENGTH = 8


class IP_ADDR_STRING(ctypes.Structure):
    pass


IP_ADDR_STRING._fields_ = [
    ("Next", ctypes.POINTER(IP_ADDR_STRING)),
    ("IpAddress", ctypes.c_char * 16),
    ("IpMask", ctypes.c_char * 16),
    ("Context", wintypes.DWORD),
]


class IP_ADAPTER_INFO(ctypes.Structure):
    pass


IP_ADAPTER_INFO._fields_ = [
    ("Next", ctypes.POINTER(IP_ADAPTER_INFO)),
    ("ComboIndex", wintypes.DWORD),
    ("AdapterName", ctypes.c_char * (MAX_ADAPTER_NAME_LENGTH + 4)),
    ("Description", ctypes.c_char * (MAX_ADAPTER_DESCRIPTION_LENGTH + 4)),
    ("AddressLength", wintypes.UINT),
    ("Address", ctypes.c_ubyte * MAX_ADAPTER_ADDRESS_LENGTH),
    ("Index", wintypes.DWORD),
    ("Type", wintypes.UINT),
    ("DhcpEnabled", wintypes.UINT),
    ("CurrentIpAddress", ctypes.POINTER(IP_ADDR_STRING)),
    ("IpAddressList", IP_ADDR_STRING),
    ("GatewayList", IP_ADDR_STRING),
    ("DhcpServer", IP_ADDR_STRING),
    ("HaveWins", wintypes.BOOL),
    ("PrimaryWinsServer", IP_ADDR_STRING),
    ("SecondaryWinsServer", IP_ADDR_STRING),
    ("LeaseObtained", ctypes.c_long),
    ("LeaseExpires", ctypes.c_long),
]


class MIB_IF_ROW2(ctypes.Structure):
    _fields_ = [
        ("InterfaceLuid", ctypes.c_uint64),
        ("InterfaceIndex", wintypes.DWORD),
        ("InterfaceGuid", ctypes.c_byte * 16),
        ("Alias", wintypes.WCHAR * 257),
        ("Description", wintypes.WCHAR * 257),
        ("PhysicalAddressLength", wintypes.ULONG),
        ("PhysicalAddress", ctypes.c_ubyte * 32),
        ("PermanentPhysicalAddress", ctypes.c_ubyte * 32),
        ("Mtu", wintypes.ULONG),
        ("Type", wintypes.ULONG),
        ("TunnelType", wintypes.ULONG),
        ("MediaType", wintypes.ULONG),
        ("PhysicalMediumType", wintypes.ULONG),
        ("AccessType", wintypes.ULONG),
        ("DirectionType", wintypes.ULONG),
        ("InterfaceAndOperStatusFlags", ctypes.c_byte),
        ("OperStatus", wintypes.ULONG),
        ("AdminStatus", wintypes.ULONG),
        ("MediaConnectState", wintypes.ULONG),
        ("NetworkGuid", ctypes.c_byte * 16),
        ("ConnectionType", wintypes.ULONG),
        ("TransmitLinkSpeed", ctypes.c_uint64),
        ("ReceiveLinkSpeed", ctypes.c_uint64),
        ("InOctets", ctypes.c_uint64),
        ("InUcastPkts", ctypes.c_uint64),
        ("InNUcastPkts", ctypes.c_uint64),
        ("InDiscards", ctypes.c_uint64),
        ("InErrors", ctypes.c_uint64),
        ("InUnknownProtos", ctypes.c_uint64),
        ("InUcastOctets", ctypes.c_uint64),
        ("InMulticastOctets", ctypes.c_uint64),
        ("InBroadcastOctets", ctypes.c_uint64),
        ("OutOctets", ctypes.c_uint64),
        ("OutUcastPkts", ctypes.c_uint64),
        ("OutNUcastPkts", ctypes.c_uint64),
        ("OutDiscards", ctypes.c_uint64),
        ("OutErrors", ctypes.c_uint64),
        ("OutUcastOctets", ctypes.c_uint64),
        ("OutMulticastOctets", ctypes.c_uint64),
        ("OutBroadcastOctets", ctypes.c_uint64),
        ("OutQLen", ctypes.c_uint64),
    ]


# --- Windows System Intelligence Service ---


class WindowsSystemService:
    """Provides safe, real system metrics on Windows platforms."""

    @classmethod
    def get_cpu_info(cls, sample_duration: float = 0.1) -> dict[str, Any]:
        """Collect CPU hardware model, cores, frequency, and current load percentage."""
        # 1. Architecture and Cores
        logical_cores = os.cpu_count() or 1
        model_name = platform.processor() or "Unknown CPU"
        current_mhz = 0.0

        # Query Windows Registry for exact model and nominal clock speed
        try:
            key = winreg.OpenKey(
                winreg.HKEY_LOCAL_MACHINE,
                r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
            )
            name_val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            if isinstance(name_val, str) and name_val.strip():
                model_name = name_val.strip()
            mhz_val, _ = winreg.QueryValueEx(key, "~MHz")
            if isinstance(mhz_val, (int, float)):
                current_mhz = float(mhz_val)
            winreg.CloseKey(key)
        except Exception as exc:
            logger.debug(f"Could not read CentralProcessor registry key: {exc}")

        # Physical Architecture
        arch = platform.machine()
        try:
            si = SYSTEM_INFO()
            ctypes.windll.kernel32.GetNativeSystemInfo(ctypes.byref(si))
            arch_map = {9: "x64 (AMD64)", 5: "ARM", 12: "ARM64", 0: "x86 (IA32)"}
            arch = arch_map.get(si.u.s.wProcessorArchitecture, arch)
        except Exception:
            pass

        # 2. Utilization Sampling via GetSystemTimes
        utilization_percent = 0.0
        try:
            idle1, kern1, user1 = FILETIME(), FILETIME(), FILETIME()
            idle2, kern2, user2 = FILETIME(), FILETIME(), FILETIME()
            if ctypes.windll.kernel32.GetSystemTimes(
                ctypes.byref(idle1), ctypes.byref(kern1), ctypes.byref(user1)
            ):
                # Bounded brief sample sleep
                sleep_sec = max(0.05, min(sample_duration, 0.5))
                time.sleep(sleep_sec)
                if ctypes.windll.kernel32.GetSystemTimes(
                    ctypes.byref(idle2), ctypes.byref(kern2), ctypes.byref(user2)
                ):
                    d_idle = _filetime_to_int(idle2) - _filetime_to_int(idle1)
                    d_kern = _filetime_to_int(kern2) - _filetime_to_int(kern1)
                    d_user = _filetime_to_int(user2) - _filetime_to_int(user1)
                    total_sys = d_kern + d_user
                    if total_sys > 0:
                        total_busy = total_sys - d_idle
                        utilization_percent = max(0.0, min(100.0, (total_busy / total_sys) * 100.0))
        except Exception as exc:
            logger.debug(f"Error calculating CPU utilization: {exc}")

        return {
            "model": model_name,
            "architecture": arch,
            "logical_cores": logical_cores,
            "physical_cores": max(1, logical_cores // 2)
            if "x86" in arch or "x64" in arch
            else logical_cores,
            "clock_speed_mhz": current_mhz,
            "utilization_percent": round(utilization_percent, 1),
            "platform": platform.platform(),
        }

    @classmethod
    def get_memory_info(cls) -> dict[str, Any]:
        """Collect physical and virtual memory statistics via GlobalMemoryStatusEx."""
        try:
            stat = MEMORYSTATUSEX()
            stat.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
            if not ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
                raise ctypes.WinError()

            total_phys = stat.ullTotalPhys
            avail_phys = stat.ullAvailPhys
            used_phys = total_phys - avail_phys
            phys_percent = float(stat.dwMemoryLoad)

            total_page = stat.ullTotalPageFile
            avail_page = stat.ullAvailPageFile
            used_page = total_page - avail_page
            page_percent = round((used_page / total_page) * 100.0, 1) if total_page > 0 else 0.0

            return {
                "total_bytes": total_phys,
                "available_bytes": avail_phys,
                "used_bytes": used_phys,
                "utilization_percent": phys_percent,
                "total_gb": round(total_phys / (1024**3), 2),
                "available_gb": round(avail_phys / (1024**3), 2),
                "used_gb": round(used_phys / (1024**3), 2),
                "page_file_total_bytes": total_page,
                "page_file_used_bytes": used_page,
                "page_file_utilization_percent": page_percent,
            }
        except Exception as exc:
            logger.error(f"Failed to read memory status: {exc}")
            return {
                "error": str(exc),
                "total_bytes": 0,
                "available_bytes": 0,
                "used_bytes": 0,
                "utilization_percent": 0.0,
            }

    @classmethod
    def get_disk_info(cls) -> dict[str, Any]:
        """Collect mounted local logical drives and usage statistics."""
        partitions: list[dict[str, Any]] = []
        total_all = 0
        used_all = 0
        free_all = 0

        try:
            bitmask = ctypes.windll.kernel32.GetLogicalDrives()
            for letter in "ABCDEFGHIJKLMNOPQRSTUVWXYZ":
                if bitmask & 1:
                    drive_path = f"{letter}:\\"
                    try:
                        # DRIVE_FIXED = 3, DRIVE_REMOVABLE = 2, DRIVE_REMOTE = 4, DRIVE_CDROM = 5
                        drive_type_code = ctypes.windll.kernel32.GetDriveTypeW(drive_path)
                        # We only inspect fixed or removable local drives
                        if drive_type_code in (2, 3):
                            tot, used, free = shutil.disk_usage(drive_path)
                            pct = round((used / tot) * 100.0, 1) if tot > 0 else 0.0
                            total_all += tot
                            used_all += used
                            free_all += free

                            # Filesystem name
                            fs_buf = ctypes.create_unicode_buffer(261)
                            ctypes.windll.kernel32.GetVolumeInformationW(
                                drive_path, None, 0, None, None, None, fs_buf, 260
                            )
                            fs_type = fs_buf.value or "NTFS"

                            partitions.append(
                                {
                                    "mount_point": drive_path,
                                    "filesystem": fs_type,
                                    "total_bytes": tot,
                                    "used_bytes": used,
                                    "free_bytes": free,
                                    "total_gb": round(tot / (1024**3), 2),
                                    "used_gb": round(used / (1024**3), 2),
                                    "free_gb": round(free / (1024**3), 2),
                                    "utilization_percent": pct,
                                }
                            )
                    except Exception as drive_err:
                        logger.debug(f"Could not read usage for drive {drive_path}: {drive_err}")
                bitmask >>= 1
        except Exception as exc:
            logger.error(f"Error enumerating disks: {exc}")

        total_pct = round((used_all / total_all) * 100.0, 1) if total_all > 0 else 0.0
        return {
            "partitions": partitions,
            "aggregate": {
                "total_bytes": total_all,
                "used_bytes": used_all,
                "free_bytes": free_all,
                "total_gb": round(total_all / (1024**3), 2),
                "used_gb": round(used_all / (1024**3), 2),
                "free_gb": round(free_all / (1024**3), 2),
                "utilization_percent": total_pct,
            },
        }

    @classmethod
    def get_network_info(cls, expose_mac: bool = False) -> dict[str, Any]:
        """Inspect network interfaces, IP addresses, operational status, and throughput counters."""
        hostname = socket.gethostname()
        adapters: list[dict[str, Any]] = []

        try:
            buflen = wintypes.ULONG(0)
            ctypes.windll.iphlpapi.GetAdaptersInfo(None, ctypes.byref(buflen))
            if buflen.value > 0:
                buf = ctypes.create_string_buffer(buflen.value)
                res = ctypes.windll.iphlpapi.GetAdaptersInfo(
                    ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_INFO)),
                    ctypes.byref(buflen),
                )
                if res == 0:
                    curr = ctypes.cast(buf, ctypes.POINTER(IP_ADAPTER_INFO))
                    while curr:
                        info = curr.contents
                        desc = info.Description.decode("ascii", errors="ignore").strip()
                        ip = info.IpAddressList.IpAddress.decode("ascii", errors="ignore").strip()
                        mask = info.IpAddressList.IpMask.decode("ascii", errors="ignore").strip()
                        gw = info.GatewayList.IpAddress.decode("ascii", errors="ignore").strip()
                        idx = int(info.Index)

                        mac_addr = (
                            ":".join(f"{b:02x}" for b in info.Address[: info.AddressLength])
                            if expose_mac and info.AddressLength > 0
                            else "[Redacted for Privacy]"
                        )

                        # Detailed stats via GetIfEntry2
                        in_octets = 0
                        out_octets = 0
                        speed_bps = 0
                        oper_status = "active" if ip and ip != "0.0.0.0" else "inactive"
                        alias_name = desc

                        try:
                            row = MIB_IF_ROW2()
                            row.InterfaceIndex = idx
                            if ctypes.windll.iphlpapi.GetIfEntry2(ctypes.byref(row)) == 0:
                                in_octets = int(row.InOctets)
                                out_octets = int(row.OutOctets)
                                speed_bps = int(row.ReceiveLinkSpeed)
                                if row.Alias:
                                    alias_name = row.Alias
                        except Exception:
                            pass

                        # Filter out disabled virtual adapters with no traffic and no IP to keep output concise
                        if ip != "0.0.0.0" or in_octets > 0 or out_octets > 0:
                            adapters.append(
                                {
                                    "name": alias_name,
                                    "description": desc,
                                    "ipv4_address": ip if ip != "0.0.0.0" else None,
                                    "subnet_mask": mask if mask != "0.0.0.0" else None,
                                    "gateway": gw if gw != "0.0.0.0" else None,
                                    "mac_address": mac_addr,
                                    "status": oper_status,
                                    "speed_mbps": round(speed_bps / 1_000_000, 1)
                                    if speed_bps > 0
                                    else 0.0,
                                    "bytes_received": in_octets,
                                    "bytes_sent": out_octets,
                                }
                            )

                        curr = info.Next
        except Exception as exc:
            logger.error(f"Error querying network adapters: {exc}")

        return {
            "hostname": hostname,
            "adapters": adapters,
            "adapter_count": len(adapters),
        }

    @classmethod
    def get_system_overview(cls, expose_mac: bool = False) -> dict[str, Any]:
        """Generate a structured consolidated summary of the machine specifications."""
        cpu = cls.get_cpu_info(sample_duration=0.05)
        mem = cls.get_memory_info()
        disk = cls.get_disk_info()
        net = cls.get_network_info(expose_mac=expose_mac)

        return {
            "os": f"Windows {platform.release()} ({platform.version()})",
            "python_runtime": platform.python_version(),
            "machine_architecture": cpu.get("architecture"),
            "cpu_summary": {
                "model": cpu.get("model"),
                "logical_cores": cpu.get("logical_cores"),
                "physical_cores": cpu.get("physical_cores"),
                "utilization_percent": cpu.get("utilization_percent"),
            },
            "memory_summary": {
                "total_gb": mem.get("total_gb"),
                "available_gb": mem.get("available_gb"),
                "used_gb": mem.get("used_gb"),
                "utilization_percent": mem.get("utilization_percent"),
            },
            "disk_summary": disk.get("aggregate"),
            "primary_network": {
                "hostname": net.get("hostname"),
                "active_adapters": len(
                    [a for a in net.get("adapters", []) if a.get("ipv4_address")]
                ),
            },
        }
