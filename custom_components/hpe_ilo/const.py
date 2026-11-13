"""Costanti per l'integrazione HP iLO."""

DOMAIN = "hpe_ilo"

CONF_PROTOCOL = "protocol"
PROTOCOL_REDFISH = "redfish"
PROTOCOL_SSH = "ssh"

CONF_SCAN_INTERVAL = "scan_interval"
DEFAULT_SCAN_INTERVAL = {
    PROTOCOL_REDFISH: 60,
    PROTOCOL_SSH: 120,
}
MIN_SCAN_INTERVAL = 30

# Azioni di alimentazione esposte dall'integrazione
ACTION_ON = "on"
ACTION_SHUTDOWN = "shutdown"  # pressione breve del tasto: spegnimento pulito del sistema operativo
ACTION_FORCE_OFF = "force_off"  # taglio immediato dell'alimentazione
ACTION_RESET = "reset"  # riavvio forzato

HEALTH_OK = "ok"
