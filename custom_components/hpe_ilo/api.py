"""Client per HP iLO.

- Redfish (iLO 4 con firmware >= 2.30, iLO 5+): API REST su HTTPS.
- SSH / SMASH CLP (iLO 2, iLO 3 e qualsiasi iLO senza Redfish): una sola sessione
  interattiva per ogni lettura, comandi "show" mirati per ogni target.

Entrambi i client restituiscono lo stesso modello dati (IloData), così le entità
di Home Assistant non dipendono dal protocollo.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import re
import threading
import time
from typing import Any
from xml.sax.saxutils import quoteattr

import aiohttp
import paramiko

from .const import (
    ACTION_FORCE_OFF,
    ACTION_ON,
    ACTION_RESET,
    ACTION_SHUTDOWN,
    HEALTH_OK,
    PROTOCOL_REDFISH,
    PROTOCOL_SSH,
)


class IloError(Exception):
    """Errore generico dell'iLO."""


class IloAuthError(IloError):
    """Credenziali rifiutate."""


class IloConnectionError(IloError):
    """iLO non raggiungibile o risposta non valida."""


@dataclass
class Measurement:
    """Una lettura: temperatura, tensione, ventola o alimentatore."""

    key: str
    name: str
    value: float | str | None
    health: str | None = None
    caution: float | None = None
    critical: float | None = None
    primary: bool = False  # entità attiva di default
    extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class IloData:
    """Stato completo di un server letto dall'iLO."""

    name: str | None = None
    model: str | None = None
    serial: str | None = None
    ilo_firmware: str | None = None
    bios: str | None = None
    power_on: bool | None = None
    health: str | None = None
    power_watts: float | None = None
    power_avg: float | None = None
    power_min: float | None = None
    power_max: float | None = None
    uid_led: str | None = None
    power_on_minutes: int | None = None  # tempo di accensione cumulativo (RIBCL, iLO 3+)
    temperatures: dict[str, Measurement] = field(default_factory=dict)
    voltages: dict[str, Measurement] = field(default_factory=dict)
    fans: dict[str, Measurement] = field(default_factory=dict)
    power_supplies: dict[str, Measurement] = field(default_factory=dict)


# --------------------------------------------------------------------------- utilità

_HEALTH_MAP = {
    "ok": HEALTH_OK,
    "good": HEALTH_OK,
    "warning": "warning",
    "degraded": "warning",
    "caution": "warning",
    "critical": "critical",
    "failed": "critical",
    "error": "critical",
    "non-recoverable": "critical",
}
_HEALTH_RANK = {HEALTH_OK: 0, "warning": 1, "critical": 2}


def normalize_health(value: Any) -> str | None:
    """Riduce i vari stati di salute a ok / warning / critical."""
    if value is None:
        return None
    text = str(value).strip().lower()
    if not text or text in ("n/a", "unknown", "other"):
        return None
    return _HEALTH_MAP.get(text, text)


def worst_health(values: list[str | None]) -> str | None:
    """Restituisce lo stato peggiore tra quelli noti."""
    known = [v for v in values if v in _HEALTH_RANK]
    if not known:
        return None
    return max(known, key=lambda v: _HEALTH_RANK[v])


def slugify(text: str) -> str:
    """Chiave stabile per unique_id."""
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def to_number(value: Any) -> float | None:
    """Converte '202 Watts', '13', 0 ... in numero; None se non disponibile."""
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value))
    return float(match.group(0)) if match else None


def _threshold(value: Any) -> float | None:
    num = to_number(value)
    return num if num else None  # 0 = soglia non impostata


def _strip(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


# --------------------------------------------------------------------------- Redfish

REDFISH_RESET_TYPES = {
    ACTION_ON: "On",
    ACTION_SHUTDOWN: "PushPowerButton",
    ACTION_FORCE_OFF: "ForceOff",
    ACTION_RESET: "ForceRestart",
}

_PRIMARY_TEMP_RE = re.compile(r"inlet|ambient|cpu", re.I)


def parse_redfish(
    system: dict[str, Any],
    thermal: dict[str, Any],
    power: dict[str, Any],
    manager: dict[str, Any],
) -> IloData:
    """Converte le risposte Redfish nel modello IloData."""
    data = IloData(
        name=_strip(system.get("HostName")) or _strip(system.get("Name")),
        model=_strip(system.get("Model")),
        serial=_strip(system.get("SerialNumber")),
        ilo_firmware=_strip(manager.get("FirmwareVersion")),
        bios=_strip(system.get("BiosVersion")),
        power_on=(system.get("PowerState") == "On") if system.get("PowerState") else None,
        health=normalize_health((system.get("Status") or {}).get("Health")),
        uid_led=_strip(system.get("IndicatorLED")),
    )

    for item in thermal.get("Temperatures") or []:
        if (item.get("Status") or {}).get("State") != "Enabled":
            continue
        raw_name = _strip(item.get("Name")) or f"Sensor {item.get('Number')}"
        name = re.sub(r"^\d+-", "", raw_name)
        key = slugify(raw_name)
        hp = (item.get("Oem") or {}).get("Hp") or {}
        data.temperatures[key] = Measurement(
            key=key,
            name=name,
            value=to_number(item.get("ReadingCelsius", item.get("CurrentReading"))),
            health=normalize_health((item.get("Status") or {}).get("Health")),
            caution=_threshold(item.get("UpperThresholdCritical")),
            critical=_threshold(item.get("UpperThresholdFatal")),
            primary=bool(_PRIMARY_TEMP_RE.search(name)),
            # posizione sulla scheda (griglia 16x16 dell'iLO 4, usata dalla card termica)
            extra={
                "posizione": item.get("PhysicalContext"),
                "x": hp.get("LocationXmm"),
                "y": hp.get("LocationYmm"),
            },
        )

    for item in thermal.get("Fans") or []:
        if (item.get("Status") or {}).get("State") == "Absent":
            continue
        name = _strip(item.get("FanName")) or _strip(item.get("Name")) or "Fan"
        key = slugify(name)
        data.fans[key] = Measurement(
            key=key,
            name=name,
            value=to_number(item.get("CurrentReading", item.get("Reading"))),
            health=normalize_health((item.get("Status") or {}).get("Health")),
            primary=True,
        )

    for index, item in enumerate(power.get("PowerSupplies") or [], start=1):
        status = item.get("Status") or {}
        if status.get("State") == "Absent":
            continue
        oem = (item.get("Oem") or {}).get("Hp") or {}
        bay = oem.get("BayNumber") or index
        key = f"psu_{bay}"
        data.power_supplies[key] = Measurement(
            key=key,
            name=f"Alimentatore {bay}",
            value=to_number(item.get("LastPowerOutputWatts")),
            health=normalize_health(status.get("Health")),
            primary=True,
            extra={
                "modello": _strip(item.get("Model")),
                "tensione_ingresso": to_number(item.get("LineInputVoltage")),
                "capacita_w": to_number(item.get("PowerCapacityWatts")),
                "stato": ((oem.get("PowerSupplyStatus") or {}).get("State")),
            },
        )

    control = (power.get("PowerControl") or [{}])[0]
    metrics = control.get("PowerMetrics") or power.get("PowerMetrics") or {}
    data.power_watts = to_number(control.get("PowerConsumedWatts", power.get("PowerConsumedWatts")))
    data.power_avg = to_number(metrics.get("AverageConsumedWatts"))
    data.power_min = to_number(metrics.get("MinConsumedWatts"))
    data.power_max = to_number(metrics.get("MaxConsumedWatts"))
    return data


class RedfishClient:
    """Client Redfish asincrono."""

    protocol = PROTOCOL_REDFISH

    def __init__(
        self, session: aiohttp.ClientSession, host: str, username: str, password: str
    ) -> None:
        self._session = session
        self._base = f"https://{host}"
        self._auth = aiohttp.BasicAuth(username, password)
        self._username = username
        self._password = password

    async def _request(
        self, method: str, path: str, payload: dict[str, Any] | None = None
    ) -> Any:
        try:
            async with self._session.request(
                method,
                self._base + path,
                json=payload,
                auth=self._auth,
                ssl=False,  # certificato iLO autofirmato
                timeout=aiohttp.ClientTimeout(total=30),
            ) as resp:
                if resp.status in (401, 403):
                    raise IloAuthError(f"Credenziali rifiutate (HTTP {resp.status})")
                if resp.status >= 400:
                    text = await resp.text()
                    raise IloError(f"HTTP {resp.status}: {text[:300]}")
                if method == "GET":
                    return await resp.json(content_type=None)
                return None
        except IloError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError, ValueError) as err:
            raise IloConnectionError(f"{type(err).__name__}: {err}") from err

    async def async_probe(self) -> bool:
        """True se l'host espone Redfish."""
        root = await self._request("GET", "/redfish/v1/")
        return isinstance(root, dict) and "Systems" in root

    async def async_fetch(self) -> IloData:
        system, thermal, power, manager, minutes = await asyncio.gather(
            self._request("GET", "/redfish/v1/Systems/1/"),
            self._request("GET", "/redfish/v1/Chassis/1/Thermal/"),
            self._request("GET", "/redfish/v1/Chassis/1/Power/"),
            self._request("GET", "/redfish/v1/Managers/1/"),
            self._power_on_minutes(),
        )
        data = parse_redfish(system, thermal, power, manager)
        data.power_on_minutes = minutes
        return data

    async def _power_on_minutes(self) -> int | None:
        """Tempo di accensione cumulativo: Redfish non lo espone, si legge via RIBCL."""
        xml = (
            '<?xml version="1.0"?>\r\n<RIBCL VERSION="2.0">'
            f"<LOGIN USER_LOGIN={quoteattr(self._username)} PASSWORD={quoteattr(self._password)}>"
            '<SERVER_INFO MODE="read"><GET_SERVER_POWER_ON_TIME/></SERVER_INFO>'
            "</LOGIN></RIBCL>\r\n"
        )
        try:
            async with self._session.post(
                self._base + "/ribcl",
                data=xml,
                headers={"Content-Type": "text/xml"},
                ssl=False,
                timeout=aiohttp.ClientTimeout(total=20),
            ) as resp:
                text = await resp.text()
        except (aiohttp.ClientError, asyncio.TimeoutError):
            return None
        match = re.search(r'SERVER_POWER_ON_MINUTES VALUE="(\d+)"', text)
        return int(match.group(1)) if match else None

    async def async_power(self, action: str) -> None:
        await self._request(
            "POST",
            "/redfish/v1/Systems/1/Actions/ComputerSystem.Reset/",
            {"ResetType": REDFISH_RESET_TYPES[action]},
        )


# --------------------------------------------------------------------------- SSH (SMASH CLP)

SSH_COMMANDS = {
    ACTION_ON: "power on",
    ACTION_SHUTDOWN: "power off",
    ACTION_FORCE_OFF: "power off hard",
    ACTION_RESET: "power reset",
}

_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]|\[D")
_TARGET_RE = re.compile(r"^(fan|sensor|powersupply)\d+$")


def clean_output(text: str) -> str:
    """Rimuove sequenze ANSI e ritorni a capo spuri dell'iLO."""
    return _ANSI_RE.sub("", text).replace("\r", "")


def parse_props(text: str) -> dict[str, str]:
    """Estrae le coppie chiave=valore della sezione Properties."""
    props: dict[str, str] = {}
    section = None
    for line in clean_output(text).splitlines():
        stripped = line.strip()
        if stripped in ("Targets", "Properties", "Verbs"):
            section = stripped
            continue
        if section == "Properties" and "=" in stripped:
            key, _, value = stripped.partition("=")
            props[key.strip()] = value.strip()
    return props


def parse_targets(text: str) -> list[str]:
    """Elenca i target figli (fan1, sensor3, ...) dall'output di 'show'."""
    targets: list[str] = []
    section = None
    for line in clean_output(text).splitlines():
        stripped = line.strip()
        if stripped in ("Targets", "Properties", "Verbs"):
            section = stripped
            continue
        if section == "Targets" and stripped and "=" not in stripped:
            targets.extend(stripped.split())
    return targets


def command_ok(text: str) -> bool:
    return "status=0" in clean_output(text)


def parse_ssh(
    system: dict[str, str],
    firmware: dict[str, str],
    bios: dict[str, str],
    items: dict[str, dict[str, str]],
) -> IloData:
    """Converte le proprietà SMASH CLP nel modello IloData."""
    state = (system.get("enabledstate") or "").lower()
    data = IloData(
        name=_strip(system.get("oemhp_server_name")) or _strip(system.get("name")),
        model=_strip(system.get("name")),
        serial=_strip(system.get("number")),
        ilo_firmware=" ".join(
            p for p in (_strip(firmware.get("name")), _strip(firmware.get("version"))) if p
        )
        or None,
        bios=" ".join(p for p in (_strip(bios.get("version")), _strip(bios.get("date"))) if p)
        or None,
        power_on=(state == "enabled") if state else None,
        power_watts=to_number(system.get("oemhp_PresentPower")),
        power_avg=to_number(system.get("oemhp_AveragePower")),
        power_min=to_number(system.get("oemhp_MinPower")),
        power_max=to_number(system.get("oemhp_MaxPower")),
    )

    healths: list[str | None] = []
    for target, props in items.items():
        health = normalize_health(props.get("HealthState") or props.get("OperationalStatus"))
        healths.append(health)
        if target.startswith("fan"):
            name = _strip(props.get("DeviceID")) or target
            data.fans[target] = Measurement(
                key=target,
                name=name,
                value=to_number(props.get("DesiredSpeed")),
                health=health,
                primary=True,
                extra={"velocita_variabile": props.get("VariableSpeed")},
            )
        elif target.startswith("powersupply"):
            name = _strip(props.get("ElementName")) or target
            data.power_supplies[target] = Measurement(
                key=target,
                name=name.replace("Power Supply", "Alimentatore"),
                value=_strip(props.get("OperationalStatus")),
                health=health,
                primary=True,
            )
        elif target.startswith("sensor"):
            kind = (props.get("SensorType") or "").lower()
            device = _strip(props.get("DeviceID")) or target
            element = _strip(props.get("ElementName"))
            name = f"{element} ({device})" if element else device
            meas = Measurement(
                key=target,
                name=name,
                value=to_number(props.get("CurrentReading")),
                health=health,
                caution=_threshold(props.get("oemhp_CautionValue")),
                critical=_threshold(props.get("oemhp_CriticalValue")),
                extra={"unita": props.get("RateUnits")},
            )
            if kind == "temperature":
                # attive di default: CPU, ambiente e Temp 1 (aria in ingresso su iLO 2)
                meas.primary = bool(_PRIMARY_TEMP_RE.search(name)) or device == "Temp 1"
                data.temperatures[target] = meas
            elif kind == "voltage":
                data.voltages[target] = meas

    data.health = worst_health(healths)
    return data


class _SshShell:
    """Sessione interattiva sincrona verso la CLI dell'iLO."""

    PROMPT = "hpiLO->"

    def __init__(self, host: str, port: int, username: str, password: str) -> None:
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        try:
            self._client.connect(
                host,
                port=port,
                username=username,
                password=password,
                look_for_keys=False,
                allow_agent=False,
                timeout=20,
                banner_timeout=30,
                auth_timeout=30,
            )
        except paramiko.AuthenticationException as err:
            self._client.close()
            raise IloAuthError("Credenziali rifiutate") from err
        except (paramiko.SSHException, OSError) as err:
            self._client.close()
            raise IloConnectionError(f"{type(err).__name__}: {err}") from err
        try:
            self._chan = self._client.invoke_shell(width=250, height=2000)
            self._read_until_prompt()
        except Exception:
            self._client.close()
            raise

    def _read_until_prompt(self, timeout: float = 45) -> str:
        buf = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._chan.recv_ready():
                buf += self._chan.recv(65535).decode("utf-8", errors="replace")
                if clean_output(buf).rstrip().endswith(self.PROMPT):
                    return buf
            elif self._chan.closed or self._chan.exit_status_ready():
                break
            else:
                time.sleep(0.05)
        raise IloConnectionError("Timeout in attesa del prompt dell'iLO")

    def run(self, command: str) -> str:
        self._chan.send(command + "\r\n")
        return self._read_until_prompt()

    def close(self) -> None:
        try:
            self._chan.send("exit\r\n")
        except Exception:  # noqa: BLE001
            pass
        self._client.close()


class SshClient:
    """Client SSH: le chiamate bloccanti girano nell'executor di Home Assistant."""

    protocol = PROTOCOL_SSH

    def __init__(self, executor, host: str, username: str, password: str, port: int = 22) -> None:
        self._executor = executor  # hass.async_add_executor_job
        self._args = (host, port, username, password)
        self._lock = threading.Lock()  # l'iLO 2 accetta poche sessioni contemporanee

    def _fetch(self) -> IloData:
        with self._lock:
            shell = _SshShell(*self._args)
            try:
                out = shell.run("show /system1")
                if not command_ok(out):
                    raise IloConnectionError("Risposta inattesa a 'show /system1'")
                system = parse_props(out)
                targets = [t for t in parse_targets(out) if _TARGET_RE.match(t)]
                firmware = parse_props(shell.run("show /map1/firmware1"))
                bios = parse_props(shell.run("show /system1/firmware1"))
                items: dict[str, dict[str, str]] = {}
                for target in targets:
                    out = shell.run(f"show /system1/{target}")
                    if command_ok(out):
                        items[target] = parse_props(out)
            finally:
                shell.close()
        return parse_ssh(system, firmware, bios, items)

    def _power(self, action: str) -> None:
        with self._lock:
            shell = _SshShell(*self._args)
            try:
                out = shell.run(SSH_COMMANDS[action])
            finally:
                shell.close()
        text = clean_output(out)
        if "status=0" not in text and "status_tag=COMMAND COMPLETED" not in text:
            raise IloError(f"Comando '{SSH_COMMANDS[action]}' rifiutato: {text.strip()[-200:]}")

    async def async_probe(self) -> bool:
        data = await self.async_fetch()
        return data.power_on is not None

    async def async_fetch(self) -> IloData:
        return await self._executor(self._fetch)

    async def async_power(self, action: str) -> None:
        await self._executor(self._power, action)
