"""
Testes unitários do parser de inventário GLPI Agent (sem banco/FastAPI).
"""

import pytest

from app.assets.glpi_import_parser import GlpiParseError, build_display_specs, parse_inventory_xml


def _xml(content: str, device_id: str = "HOST-2026-01-01-00-00-00") -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<REQUEST>
  <CONTENT>
    {content}
  </CONTENT>
  <DEVICEID>{device_id}</DEVICEID>
  <QUERY>INVENTORY</QUERY>
</REQUEST>""".encode("utf-8")


_FULL_CONTENT = """
<ACCESSLOG><LOGDATE>2026-10-21 10:06:18</LOGDATE></ACCESSLOG>
<BIOS>
  <SSN>ABC123SERIAL</SSN>
  <MSN>BOARD-SERIAL</MSN>
  <SMANUFACTURER>LENOVO</SMANUFACTURER>
  <SMODEL>ThinkPad L14 Gen 2</SMODEL>
</BIOS>
<HARDWARE>
  <NAME>IV-1038</NAME>
  <CHASSIS_TYPE>Notebook</CHASSIS_TYPE>
  <MEMORY>24235</MEMORY>
  <LASTLOGGEDUSER>ti.rn</LASTLOGGEDUSER>
</HARDWARE>
<CPUS><NAME>11th Gen Intel Core i5-1135G7 @ 2.40GHz</NAME><CORE>4</CORE><THREAD>2</THREAD></CPUS>
<MEMORIES><CAPACITY>8192</CAPACITY></MEMORIES>
<MEMORIES><CAPACITY>16384</CAPACITY></MEMORIES>
<STORAGES><MODEL>SSSTC CL4-8D256-Q79</MODEL><SERIAL>SS1F28693L4BR3C653JT_0001</SERIAL><DISKSIZE>256060</DISKSIZE><TYPE>SSD</TYPE><INTERFACE>NVMe</INTERFACE></STORAGES>
<OPERATINGSYSTEM><FULL_NAME>Microsoft Windows 11 Pro</FULL_NAME><VERSION>25H2</VERSION><ARCH>64-bit</ARCH></OPERATINGSYSTEM>
<NETWORKS><DESCRIPTION>TAP-Windows Adapter V9</DESCRIPTION><MACADDR>00:FF:E6:A9:CE:ED</MACADDR><IPADDRESS>192.168.0.29</IPADDRESS><STATUS>Up</STATUS><VIRTUALDEV>1</VIRTUALDEV><TYPE>ethernet</TYPE></NETWORKS>
<NETWORKS><DESCRIPTION>Wi-Fi 6 AX200</DESCRIPTION><MACADDR>0C:91:92:B9:33:9A</MACADDR><STATUS>Down</STATUS><VIRTUALDEV>0</VIRTUALDEV><TYPE>wifi</TYPE></NETWORKS>
<NETWORKS><DESCRIPTION>Ethernet</DESCRIPTION><MACADDR>60:C7:27:0D:C5:16</MACADDR><IPADDRESS>10.10.10.53</IPADDRESS><STATUS>Up</STATUS><VIRTUALDEV>0</VIRTUALDEV><TYPE>ethernet</TYPE></NETWORKS>
<MONITORS><CAPTION>NV140FHM-N48</CAPTION><MANUFACTURER>Lenovo Group Limited</MANUFACTURER><SERIAL>00000000</SERIAL></MONITORS>
<SOFTWARES><NAME>7-Zip</NAME></SOFTWARES>
<SOFTWARES><NAME>Git</NAME></SOFTWARES>
<SOFTWARES><NAME>VLC</NAME></SOFTWARES>
"""


def test_parses_full_sample_happy_path():
    result = parse_inventory_xml(_xml(_FULL_CONTENT))

    assert result["serial_number"] == "ABC123SERIAL"
    # Nome sugerido é o MODELO do equipamento (SMODEL), não o hostname.
    assert result["suggested_name"] == "ThinkPad L14 Gen 2"

    inv = result["glpi_inventory"]
    assert inv["hostname"] == "IV-1038"
    assert inv["cpu_name"] == "11th Gen Intel Core i5-1135G7 @ 2.40GHz"
    assert inv["ram_mb"] == 8192 + 16384
    assert inv["storage"] == [
        {
            "model": "SSSTC CL4-8D256-Q79",
            "serial": "SS1F28693L4BR3C653JT_0001",
            "size_mb": 256060,
            "type": "SSD",
            "interface": "NVMe",
        }
    ]
    assert inv["os_name"] == "Microsoft Windows 11 Pro"
    assert inv["bios"] == {"manufacturer": "LENOVO", "model": "ThinkPad L14 Gen 2"}
    assert inv["software_count"] == 3
    assert inv["inventory_collected_at"] == "2026-10-21 10:06:18"
    assert inv["last_logged_user"] == "ti.rn"

    # NIC principal: exclui o adaptador virtual (VIRTUALDEV=1) e o que está Down,
    # escolhe o Ethernet Up com IP.
    assert inv["network"] == {"mac": "60:C7:27:0D:C5:16", "ip": "10.10.10.53", "type": "ethernet"}


def test_serial_falls_back_to_msn_when_ssn_missing():
    content = "<BIOS><MSN>BOARD-ONLY-SERIAL</MSN></BIOS><HARDWARE><NAME>HOST1</NAME></HARDWARE>"
    result = parse_inventory_xml(_xml(content))
    assert result["serial_number"] == "BOARD-ONLY-SERIAL"


@pytest.mark.parametrize(
    "placeholder",
    ["", "Not Specified", "To be filled by O.E.M.", "None", "  ", "System Serial Number"],
)
def test_placeholder_ssn_falls_back_to_msn(placeholder: str):
    content = f"<BIOS><SSN>{placeholder}</SSN><MSN>REAL-BOARD-SERIAL</MSN></BIOS><HARDWARE><NAME>HOST1</NAME></HARDWARE>"
    result = parse_inventory_xml(_xml(content))
    assert result["serial_number"] == "REAL-BOARD-SERIAL"


def test_placeholder_ssn_and_msn_yields_none_without_error():
    content = "<BIOS><SSN>Not Specified</SSN><MSN>None</MSN></BIOS><HARDWARE><NAME>HOST1</NAME></HARDWARE>"
    result = parse_inventory_xml(_xml(content))
    assert result["serial_number"] is None


def test_missing_bios_entirely_does_not_raise():
    content = "<HARDWARE><NAME>HOST1</NAME></HARDWARE>"
    result = parse_inventory_xml(_xml(content))
    assert result["serial_number"] is None
    assert result["glpi_inventory"]["bios"] == {"manufacturer": None, "model": None}


def test_missing_hardware_and_bios_does_not_raise():
    content = "<CPUS><NAME>Some CPU</NAME></CPUS>"
    result = parse_inventory_xml(_xml(content))
    assert result["serial_number"] is None
    assert result["suggested_name"] == "Ativo importado do GLPI"
    assert result["glpi_inventory"]["hostname"] is None


def test_all_nics_virtual_or_down_yields_none_network():
    content = (
        "<HARDWARE><NAME>HOST1</NAME></HARDWARE>"
        "<NETWORKS><VIRTUALDEV>1</VIRTUALDEV><STATUS>Up</STATUS><MACADDR>AA</MACADDR></NETWORKS>"
        "<NETWORKS><VIRTUALDEV>0</VIRTUALDEV><STATUS>Down</STATUS><MACADDR>BB</MACADDR></NETWORKS>"
    )
    result = parse_inventory_xml(_xml(content))
    assert result["glpi_inventory"]["network"] is None


def test_memory_falls_back_to_hardware_memory_when_no_memories_section():
    content = "<HARDWARE><NAME>HOST1</NAME><MEMORY>8192</MEMORY></HARDWARE>"
    result = parse_inventory_xml(_xml(content))
    assert result["glpi_inventory"]["ram_mb"] == 8192


def test_suggested_name_falls_back_to_board_model_when_no_system_model():
    content = "<BIOS><MMODEL>Placa-mãe X1</MMODEL></BIOS><HARDWARE><NAME>HOST1</NAME></HARDWARE>"
    result = parse_inventory_xml(_xml(content))
    assert result["suggested_name"] == "Placa-mãe X1"


def test_suggested_name_falls_back_to_hostname_when_no_model_at_all():
    content = "<HARDWARE><NAME>HOST1</NAME></HARDWARE>"
    result = parse_inventory_xml(_xml(content))
    assert result["suggested_name"] == "HOST1"


def test_build_display_specs_flattens_happy_path():
    result = parse_inventory_xml(_xml(_FULL_CONTENT))
    specs = build_display_specs(result["glpi_inventory"])

    assert specs == {
        "cpu": "11th Gen Intel Core i5-1135G7 @ 2.40GHz",
        "ram": "24 GB",
        "storage": "SSSTC CL4-8D256-Q79 (250 GB, SSD)",
        "os": "Microsoft Windows 11 Pro 25H2",
        "mac_address": "60:C7:27:0D:C5:16",
        "hostname": "IV-1038",
        "last_logged_user": "ti.rn",
    }


def test_build_display_specs_omits_empty_fields():
    content = "<HARDWARE><NAME>HOST1</NAME></HARDWARE>"
    result = parse_inventory_xml(_xml(content))
    specs = build_display_specs(result["glpi_inventory"])

    assert specs == {"hostname": "HOST1"}


def test_malformed_xml_raises_glpi_parse_error():
    with pytest.raises(GlpiParseError):
        parse_inventory_xml(b"<REQUEST><CONTENT>unclosed")


def test_non_request_root_raises_glpi_parse_error():
    with pytest.raises(GlpiParseError):
        parse_inventory_xml(b"<SOMETHING_ELSE></SOMETHING_ELSE>")


def test_missing_content_section_raises_glpi_parse_error():
    with pytest.raises(GlpiParseError):
        parse_inventory_xml(b"<REQUEST><DEVICEID>X</DEVICEID></REQUEST>")
