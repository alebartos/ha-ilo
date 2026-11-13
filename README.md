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
max_rows: 0        # righe dell'elenco (0 = tutte, con scorrimento)
mobile_list: true  # su telefono mostra l'elenco al posto della mappa
spin: false        # vista 3D che ruota da sola
model: true        # vista 3D: modello stilizzato del server (false = colonnine)
```

Vista 3D: trascina in orizzontale per ruotare, in verticale per inclinare, doppio clic per tornare alla vista iniziale.

Nella vista 3D la card disegna un modello stilizzato del server (telaio 2U da 445 × 690 mm, gabbia dischi,
6 ventole, dissipatori CPU, banchi DIMM, schede PCI e alimentatori), con ogni componente colorato dalla
temperatura del suo sensore e la mappa di calore sul fondo. Il modello è disegnato da zero con forme
semplici (proporzioni di un ProLiant DL380p Gen8) e i componenti sono posizionati in base a nomi e
coordinate dei sensori iLO. Con `model: false` torna la vista a colonnine.

Le schede PCIe sono disegnate orizzontali nel riser (slot numerati dall'alto in basso), solo negli slot occupati (letti da Redfish
`PCISlots`/`PCIDevices`, iLO 4 e successivi), con il tipo di scheda nel tooltip. Se la scheda non
espone una sua temperatura (`PCI n`) si usa quella della zona dello slot (`PCI n Zone`) o della scheda
madre, indicata come stimata e con il bordo tratteggiato. Gli slot vuoti appaiono come connettori.

## Opzioni

Intervallo di aggiornamento (default 60 s Redfish, 120 s SSH, minimo 30 s).

## Licenza

MIT
