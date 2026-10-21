"""
Parser de inventários XML gerados pelo GLPI Agent (formato FusionInventory).

Funções puras — sem I/O, sem dependência de banco/FastAPI — para facilitar teste
unitário isolado. Usa xml.etree.ElementTree (stdlib): o upload exige a permissão
`assets.write` (já é staff de TI autenticado, não entrada pública/anônima), então
o risco de XXE não justifica adicionar uma dependência nova (defusedxml) a uma
base de código que hoje só usa httpx para integrações externas.
"""

import xml.etree.ElementTree as ET
from typing import Any

_SERIAL_PLACEHOLDERS = {
    "",
    "none",
    "not specified",
    "to be filled by o.e.m.",
    "system serial number",
    "default string",
    "unknown",
    "n/a",
    "na",
    "0",
    "serial number",
}


class GlpiParseError(Exception):
    """Levantado quando o arquivo não é um inventário GLPI Agent / FusionInventory válido."""


def _text(elem: "ET.Element | None", tag: str) -> str | None:
    if elem is None:
        return None
    child = elem.find(tag)
    if child is None or child.text is None:
        return None
    value = child.text.strip()
    return value or None


def _clean_serial(value: str | None) -> str | None:
    if value is None:
        return None
    if value.strip().lower() in _SERIAL_PLACEHOLDERS:
        return None
    return value.strip()


def _extract_serial(bios: "ET.Element | None") -> str | None:
    if bios is None:
        return None
    return _clean_serial(_text(bios, "SSN")) or _clean_serial(_text(bios, "MSN"))


def _pick_primary_nic(networks: list[ET.Element]) -> dict[str, Any] | None:
    """Exclui adaptadores virtuais/VPN (VIRTUALDEV=1) e exige STATUS=Up; entre os
    restantes prefere o que tem IPADDRESS preenchido."""
    candidates = [n for n in networks if _text(n, "VIRTUALDEV") != "1" and _text(n, "STATUS") == "Up"]
    if not candidates:
        return None
    with_ip = [n for n in candidates if _text(n, "IPADDRESS")]
    best = with_ip[0] if with_ip else candidates[0]
    return {
        "mac": _text(best, "MACADDR"),
        "ip": _text(best, "IPADDRESS"),
        "type": _text(best, "TYPE"),
    }


def _sum_memory_mb(memories: list[ET.Element], hardware: "ET.Element | None") -> int | None:
    total = 0
    found = False
    for m in memories:
        cap = _text(m, "CAPACITY")
        if cap and cap.isdigit():
            total += int(cap)
            found = True
    if found:
        return total
    fallback = _text(hardware, "MEMORY") if hardware is not None else None
    if fallback and fallback.isdigit():
        return int(fallback)
    return None


def _parse_storages(storages: list[ET.Element]) -> list[dict[str, Any]]:
    disks = []
    for s in storages:
        size_text = _text(s, "DISKSIZE")
        disks.append(
            {
                "model": _text(s, "MODEL"),
                "serial": _text(s, "SERIAL") or _text(s, "SERIALNUMBER"),
                "size_mb": int(size_text) if size_text and size_text.isdigit() else None,
                "type": _text(s, "TYPE"),
                "interface": _text(s, "INTERFACE"),
            }
        )
    return disks


def _parse_monitors(monitors: list[ET.Element]) -> list[dict[str, Any]]:
    return [
        {
            "caption": _text(m, "CAPTION"),
            "manufacturer": _text(m, "MANUFACTURER"),
            "serial": _text(m, "SERIAL") or _text(m, "ALTSERIAL"),
        }
        for m in monitors
    ]


def _format_ram(ram_mb: int | None) -> str | None:
    if not ram_mb:
        return None
    gb = ram_mb / 1024
    return f"{gb:.0f} GB" if gb == int(gb) else f"{gb:.1f} GB"


def _format_storage(storage: list[dict[str, Any]]) -> str | None:
    parts = []
    for disk in storage:
        label = disk.get("model") or disk.get("type") or "Disco"
        size_mb = disk.get("size_mb")
        extra = []
        if size_mb:
            extra.append(f"{size_mb / 1024:.0f} GB")
        if disk.get("type"):
            extra.append(disk["type"])
        parts.append(f"{label} ({', '.join(extra)})" if extra else label)
    return "; ".join(parts) if parts else None


def _format_os(os_name: str | None, os_version: str | None) -> str | None:
    if not os_name:
        return None
    return f"{os_name} {os_version}" if os_version else os_name


def build_display_specs(glpi_inventory: dict[str, Any]) -> dict[str, str]:
    """Converte o dicionário técnico (aninhado) extraído do XML em campos
    PLANOS e legíveis (string) a serem gravados diretamente em
    `Asset.technical_specs`, usando as mesmas chaves que a tela de detalhe do
    ativo já sabe exibir com rótulo e ícone amigáveis (`cpu`, `ram`, `storage`,
    `os`). Chaves com valor vazio/None são omitidas (não geram cartão vazio).
    """
    network = glpi_inventory.get("network") or {}
    candidates: dict[str, str | None] = {
        "cpu": glpi_inventory.get("cpu_name"),
        "ram": _format_ram(glpi_inventory.get("ram_mb")),
        "storage": _format_storage(glpi_inventory.get("storage") or []),
        "os": _format_os(glpi_inventory.get("os_name"), glpi_inventory.get("os_version")),
        "mac_address": network.get("mac"),
        "hostname": glpi_inventory.get("hostname"),
        "last_logged_user": glpi_inventory.get("last_logged_user"),
    }
    return {k: v for k, v in candidates.items() if v}


def parse_inventory_xml(xml_bytes: bytes) -> dict[str, Any]:
    """Faz o parse de um inventário GLPI Agent e retorna:
    `{"serial_number": str|None, "suggested_name": str, "glpi_inventory": dict}`.

    Levanta `GlpiParseError` só quando o XML é malformado ou não tem a estrutura
    mínima de um inventário GLPI (raiz <REQUEST>/<CONTENT>) — seções internas
    ausentes (BIOS, HARDWARE, etc.) resultam em campos vazios, não em exceção.
    """
    try:
        root = ET.fromstring(xml_bytes)
    except ET.ParseError as exc:
        raise GlpiParseError(f"XML malformado: {exc}") from exc

    if root.tag != "REQUEST":
        raise GlpiParseError("Arquivo não é um inventário GLPI Agent válido (raiz <REQUEST> ausente).")

    content = root.find("CONTENT")
    if content is None:
        raise GlpiParseError("Inventário sem a seção <CONTENT>.")

    device_id = _text(root, "DEVICEID")

    bios = content.find("BIOS")
    hardware = content.find("HARDWARE")
    cpus = content.findall("CPUS")
    memories = content.findall("MEMORIES")
    storages = content.findall("STORAGES")
    operating_system = content.find("OPERATINGSYSTEM")
    networks = content.findall("NETWORKS")
    monitors = content.findall("MONITORS")
    softwares = content.findall("SOFTWARES")
    accesslog = content.find("ACCESSLOG")

    serial_number = _extract_serial(bios)

    system_manufacturer = _text(bios, "SMANUFACTURER")
    system_model = _text(bios, "SMODEL")
    board_manufacturer = _text(bios, "MMANUFACTURER")
    board_model = _text(bios, "MMODEL")

    first_cpu = cpus[0] if cpus else None
    hostname = _text(hardware, "NAME")

    glpi_inventory: dict[str, Any] = {
        "device_id": device_id,
        "hostname": hostname,
        "chassis_type": _text(hardware, "CHASSIS_TYPE"),
        "cpu_name": _text(first_cpu, "NAME") if first_cpu is not None else None,
        "cpu_cores": _text(first_cpu, "CORE") if first_cpu is not None else None,
        "cpu_threads": _text(first_cpu, "THREAD") if first_cpu is not None else None,
        "ram_mb": _sum_memory_mb(memories, hardware),
        "storage": _parse_storages(storages),
        "os_name": _text(operating_system, "FULL_NAME"),
        "os_version": _text(operating_system, "VERSION"),
        "os_arch": _text(operating_system, "ARCH"),
        "bios": {
            "manufacturer": system_manufacturer or board_manufacturer,
            "model": system_model or board_model,
        },
        "network": _pick_primary_nic(networks),
        "monitors": _parse_monitors(monitors),
        "software_count": len(softwares),
        "inventory_collected_at": _text(accesslog, "LOGDATE") if accesslog is not None else None,
        "last_logged_user": _text(hardware, "LASTLOGGEDUSER"),
    }

    suggested_name = system_model or board_model or hostname or "Ativo importado do GLPI"

    return {
        "serial_number": serial_number,
        "suggested_name": suggested_name,
        "glpi_inventory": glpi_inventory,
    }
