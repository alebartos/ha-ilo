# HP iLO per Home Assistant

Integrazione custom per i server HP/HPE ProLiant: stato, sensori hardware e
controllo dell'alimentazione tramite l'iLO.

| iLO | Protocollo | Note |
|---|---|---|
| iLO 4 (firmware ≥ 2.30), iLO 5+ | Redfish (HTTPS) | rilevato automaticamente |
| iLO 2, iLO 3, iLO 4 vecchi | SSH (SMASH CLP) | una sessione per lettura, ~30 s su iLO 2 |

## Entità per server

- **Interruttore** `Alimentazione`: acceso = accensione, spento = spegnimento pulito (pressione breve del tasto).
- **Pulsanti**: `Accendi`, `Spegni`, `Spegnimento forzato`, `Riavvio forzato`.
- **Sensori binari**: `Acceso`, `Problema hardware`.
- **Sensori**: `Consumo` (W), `Consumo medio`, `Consumo minimo/massimo` (disattivati),
  `Ventole (media)`, `Tempo di accensione` (iLO 4+, via RIBCL), `Stato hardware`, una entità per ogni ventola, temperatura,
  tensione e alimentatore con soglie di attenzione/critiche come attributi.
  Le temperature secondarie e le tensioni sono create disattivate: attivale dalla pagina del dispositivo.

## Installazione

1. Marketplace / HACS → repository personalizzato `https://github.com/alebartos/ha-ilo` (categoria *Integration*),
   oppure copia `custom_components/hpe_ilo` in `config/custom_components/`.
2. Riavvia Home Assistant.
3. *Impostazioni → Dispositivi e servizi → Aggiungi integrazione → HP iLO*: indirizzo, utente, password.

Consiglio: crea sull'iLO un utente dedicato con i soli privilegi *Login* e *Virtual Power and Reset*.

## Card mappa termica

L'integrazione carica da sola la card `custom:hpe-ilo-thermal-card` (nessuna risorsa da aggiungere):
mostra i sensori di temperatura sulla scheda madre in **3D** o **2D**, colorati in base alla distanza
dalla soglia di attenzione. Passando sopra a un sensore compaiono nome, valore e soglie.
Su iLO senza coordinate dei sensori (iLO 2) mostra un elenco a barre.

```yaml
type: custom:hpe-ilo-thermal-card
server: OMV        # nome del server nell'integrazione (opzionale: il primo)
mode: 3d           # 3d | 2d
refresh: 30        # secondi
max_rows: 12       # solo elenco (iLO senza mappa)
```

## Opzioni

Intervallo di aggiornamento (default 60 s Redfish, 120 s SSH, minimo 30 s).

## Licenza

MIT
