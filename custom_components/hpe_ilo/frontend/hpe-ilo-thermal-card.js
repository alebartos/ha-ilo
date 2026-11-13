/*
 * hpe-ilo-thermal-card
 * Mappa termica 3D / 2D dei sensori di temperatura di un server HP iLO,
 * fornita dall'integrazione hpe_ilo (https://github.com/alebartos/ha-ilo).
 *
 * Configurazione:
 *   type: custom:hpe-ilo-thermal-card
 *   server: OMV          # titolo del server nell'integrazione (opzionale: il primo)
 *   mode: 3d             # 3d | 2d
 *   title: Temperature   # opzionale
 *   refresh: 30          # secondi tra un aggiornamento e l'altro
 *   max_rows: 0          # righe dell'elenco (0 = tutte, con scorrimento)
 *   mobile_list: true    # su schermi stretti (telefono) mostra l'elenco al posto della mappa
 *   spin: false          # vista 3D che ruota da sola
 *   model: true          # vista 3D: modello stilizzato del server (false = colonnine)
 *
 * Vista 3D: trascina in orizzontale per ruotare, in verticale per inclinare,
 * doppio clic per tornare alla vista iniziale.
 */

const STOPS = [
  [0.0, [37, 99, 235]],
  [0.35, [6, 182, 212]],
  [0.55, [34, 197, 94]],
  [0.75, [234, 179, 8]],
  [0.9, [249, 115, 22]],
  [1.0, [239, 68, 68]],
];
const BASE_TEMP = 15; // °C a cui la scala parte da 0

// modello stilizzato (mm) di un ProLiant DL380p Gen8: 445 x 690 mm, 2U
const MW = 445;
const MD = 690;
const MH = 87;

// griglia iLO (y = 0 fronte) -> profondità in mm; davanti c'è spazio per gabbia dischi e ventole
function mapY(gy, N) {
  const K = [[-0.5, 0], [0.5, 150], [0.75, 222], [N - 0.5, MD]];
  let i = 1;
  while (i < K.length - 1 && gy > K[i][0]) i++;
  const [a0, b0] = K[i - 1];
  const [a1, b1] = K[i];
  return Math.max(0, Math.min(MD, b0 + ((b1 - b0) * (gy - a0)) / (a1 - a0)));
}

function inPoly(pts, x, y) {
  let ins = false;
  for (let i = 0, j = pts.length - 1; i < pts.length; j = i++) {
    const [xi, yi] = pts[i];
    const [xj, yj] = pts[j];
    if (yi > y !== yj > y && x < ((xj - xi) * (y - yi)) / (yj - yi) + xi) ins = !ins;
  }
  return ins;
}

function colorAt(t, alpha = 1, shade = 1) {
  t = Math.max(0, Math.min(1, t));
  for (let i = 1; i < STOPS.length; i++) {
    if (t <= STOPS[i][0]) {
      const [t0, c0] = STOPS[i - 1];
      const [t1, c1] = STOPS[i];
      const k = (t - t0) / (t1 - t0);
      const c = c0.map((v, j) => Math.round((v + (c1[j] - v) * k) * shade));
      return `rgba(${c[0]},${c[1]},${c[2]},${alpha})`;
    }
  }
  return `rgba(239,68,68,${alpha})`;
}

function heat(s) {
  if (typeof s.value !== "number") return null;
  const hi = s.caution || s.critical || s.value + 20;
  return (s.value - BASE_TEMP) / Math.max(1, hi - BASE_TEMP);
}

class HpeIloThermalCard extends HTMLElement {
  static getConfigForm() {
    return {
      schema: [
        { name: "server", selector: { text: {} } },
        {
          name: "mode",
          selector: { select: { mode: "dropdown", options: [{ value: "3d", label: "3D" }, { value: "2d", label: "2D" }] } },
        },
        { name: "title", selector: { text: {} } },
        { name: "refresh", selector: { number: { min: 10, max: 600, unit_of_measurement: "s" } } },
        { name: "max_rows", selector: { number: { min: 0, max: 60 } } },
        { name: "mobile_list", selector: { boolean: {} } },
        { name: "model", selector: { boolean: {} } },
      ],
      computeLabel: (s) =>
        ({
          server: "Server (nome nell'integrazione)",
          mode: "Vista",
          title: "Titolo",
          refresh: "Aggiornamento",
          max_rows: "Righe elenco (0 = tutte)",
          mobile_list: "Elenco su telefono",
          model: "Modello 3D del server",
        })[s.name],
    };
  }

  static getStubConfig() {
    return { mode: "3d" };
  }

  setConfig(config) {
    this._config = { mode: "3d", refresh: 30, ...config };
    this._mode = this._config.mode === "2d" ? "2d" : "3d";
    if (this._yaw === undefined) this._resetView();
    if (!this.shadowRoot) this._build();
    this._syncSpin();
    if (this._hass) this._restart();
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (first && this.isConnected) this._restart();
  }

  _resetView() {
    this._yaw = 0;
    this._tilt = 0.5;
  }

  _syncSpin() {
    const want = !!this._config.spin && this._mode === "3d" && this.isConnected;
    if (want && !this._raf) {
      const tick = () => {
        if (!this._drag) this._yaw += 0.004;
        this._draw();
        this._raf = requestAnimationFrame(tick);
      };
      this._raf = requestAnimationFrame(tick);
    } else if (!want && this._raf) {
      cancelAnimationFrame(this._raf);
      this._raf = null;
    }
  }

  connectedCallback() {
    this._syncSpin();
    if (this._hass) this._restart();
    this._ro = new ResizeObserver(() => this._draw());
    this._onResize = () => this._update();
    window.addEventListener("resize", this._onResize);
    this._ro.observe(this._wrap);
  }

  disconnectedCallback() {
    clearInterval(this._timer);
    this._timer = null;
    if (this._ro) this._ro.disconnect();
    if (this._onResize) window.removeEventListener("resize", this._onResize);
    if (this._raf) cancelAnimationFrame(this._raf);
    this._raf = null;
  }

  getCardSize() {
    return 7;
  }

  getGridOptions() {
    return { columns: 12, rows: 7, min_columns: 6, min_rows: 5 };
  }

  _restart() {
    clearInterval(this._timer);
    this._fetch();
    this._timer = setInterval(() => this._fetch(), Math.max(10, Number(this._config.refresh) || 30) * 1000);
  }

  async _fetch() {
    try {
      const msg = { type: "hpe_ilo/thermal" };
      if (this._config.server) msg.server = String(this._config.server);
      this._data = await this._hass.callWS(msg);
      this._error = null;
    } catch (err) {
      this._error = err && err.message ? err.message : String(err);
    }
    this._update();
  }

  _build() {
    const root = this.attachShadow({ mode: "open" });
    root.innerHTML = `
      <style>
        ha-card { padding: 16px; position: relative; overflow: hidden; }
        .head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; }
        .title { font-size: 1.15rem; font-weight: 600; color: var(--primary-text-color); }
        .sub { font-size: 0.85rem; color: var(--secondary-text-color); margin-top: 2px; }
        .toggle { display: flex; border: 1px solid var(--divider-color); border-radius: 999px; overflow: hidden; flex-shrink: 0; }
        .toggle button { background: none; border: 0; padding: 4px 12px; font: inherit; font-size: 0.8rem;
          color: var(--secondary-text-color); cursor: pointer; }
        .toggle button.on { background: var(--primary-color); color: var(--text-primary-color, #fff); }
        .wrap { position: relative; width: 100%; margin-top: 8px; }
        canvas { display: block; width: 100%; touch-action: pan-y; }
        canvas.rot { cursor: grab; }
        canvas.rot.dragging { cursor: grabbing; }
        .tip { position: absolute; pointer-events: none; display: none; z-index: 2;
          background: var(--card-background-color, #222); color: var(--primary-text-color);
          border: 1px solid var(--divider-color); border-radius: 10px; padding: 8px 10px;
          font-size: 0.8rem; line-height: 1.35; box-shadow: 0 4px 16px rgba(0,0,0,.25); max-width: 240px; }
        .tip b { font-weight: 600; }
        .legend { display: flex; align-items: center; gap: 8px; margin-top: 8px; font-size: 0.75rem; color: var(--secondary-text-color); }
        .bar { flex: 1; height: 8px; border-radius: 4px;
          background: linear-gradient(90deg, ${STOPS.map(([t, c]) => `rgb(${c}) ${t * 100}%`).join(",")}); }
        .list { display: grid; gap: 6px; margin-top: 10px; max-height: min(60vh, 440px); overflow-y: auto;
          padding-right: 4px; overscroll-behavior: contain; }
        .row { display: grid; grid-template-columns: minmax(0, 1fr) 3.2em; gap: 8px; align-items: center; font-size: 0.85rem; }
        .row .name { color: var(--primary-text-color); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
        .row .track { grid-column: 1 / -1; height: 6px; border-radius: 3px; background: var(--divider-color); overflow: hidden; }
        .row .fill { height: 100%; border-radius: 3px; }
        .row .val { text-align: right; color: var(--primary-text-color); font-variant-numeric: tabular-nums; }
        .err { color: var(--error-color, #db4437); font-size: 0.9rem; margin-top: 8px; }
      </style>
      <ha-card>
        <div class="head">
          <div><div class="title"></div><div class="sub"></div></div>
          <div class="toggle"><button data-m="3d">3D</button><button data-m="2d">2D</button></div>
        </div>
        <div class="wrap"><canvas></canvas><div class="tip"></div></div>
        <div class="list"></div>
        <div class="legend"><span>freddo</span><div class="bar"></div><span>soglia</span></div>
        <div class="err"></div>
      </ha-card>`;
    this._card = root.querySelector("ha-card");
    this._titleEl = root.querySelector(".title");
    this._subEl = root.querySelector(".sub");
    this._wrap = root.querySelector(".wrap");
    this._canvas = root.querySelector("canvas");
    this._tip = root.querySelector(".tip");
    this._list = root.querySelector(".list");
    this._legend = root.querySelector(".legend");
    this._errEl = root.querySelector(".err");
    this._toggle = root.querySelector(".toggle");
    this._toggle.addEventListener("click", (ev) => {
      const m = ev.target && ev.target.dataset && ev.target.dataset.m;
      if (m) {
        this._mode = m;
        this._syncSpin();
        this._update();
      }
    });
    const cv = this._canvas;
    cv.addEventListener("pointerdown", (ev) => {
      if (this._mode !== "3d") return;
      this._drag = { x: ev.clientX, y: ev.clientY, moved: false };
      cv.setPointerCapture(ev.pointerId);
      cv.classList.add("dragging");
    });
    cv.addEventListener("pointermove", (ev) => {
      if (!this._drag) return this._hover(ev);
      const dx = ev.clientX - this._drag.x;
      const dy = ev.clientY - this._drag.y;
      if (Math.abs(dx) + Math.abs(dy) > 2) this._drag.moved = true;
      this._drag.x = ev.clientX;
      this._drag.y = ev.clientY;
      this._yaw -= dx * 0.01;
      if (ev.pointerType === "mouse") this._tilt = Math.max(0.22, Math.min(0.9, this._tilt + dy * 0.004));
      this._hintShown = true;
      this._tip.style.display = "none";
      if (!this._raf) this._draw();
    });
    const end = (ev) => {
      if (!this._drag) return;
      this._drag = null;
      cv.classList.remove("dragging");
      try {
        cv.releasePointerCapture(ev.pointerId);
      } catch (_e) {
        /* già rilasciato */
      }
    };
    cv.addEventListener("pointerup", end);
    cv.addEventListener("pointercancel", end);
    cv.addEventListener("dblclick", () => {
      this._resetView();
      this._draw();
    });
    cv.addEventListener("pointerleave", () => {
      if (!this._drag) this._tip.style.display = "none";
    });
  }

  _update() {
    if (!this.shadowRoot) return;
    const d = this._data;
    this._errEl.textContent = this._error ? `Errore: ${this._error}` : "";
    if (!d) return;
    const temps = d.sensors.filter((s) => typeof s.value === "number");
    const hottest = temps.reduce((a, s) => (!a || s.value > a.value ? s : a), null);
    this._titleEl.textContent = this._config.title || `${d.title} · Temperature`;
    this._subEl.textContent = [
      d.model,
      d.power_on === true ? "acceso" : d.power_on === false ? "spento" : null,
      hottest ? `max ${hottest.value.toFixed(0)} °C (${hottest.name})` : null,
      d.last_update_success === false ? "iLO non raggiungibile" : null,
    ]
      .filter(Boolean)
      .join(" · ");
    for (const b of this._toggle.querySelectorAll("button")) b.classList.toggle("on", b.dataset.m === this._mode);
    this._canvas.classList.toggle("rot", this._mode === "3d");
    // telefono: elenco con scorrimento (la mappa 3D su schermi stretti è poco leggibile)
    const narrow = this._config.mobile_list !== false && window.matchMedia("(max-width: 640px)").matches;
    const map = d.has_map && !narrow;
    this._toggle.style.display = map ? "" : "none";
    this._wrap.style.display = map ? "" : "none";
    this._list.style.display = map ? "none" : "";
    this._legend.style.display = map ? "" : "none";
    if (map) this._draw();
    else this._drawList(temps);
  }

  _drawList(temps) {
    const max = Number(this._config.max_rows) || Infinity;
    const rows = [...temps].sort((a, b) => (heat(b) ?? 0) - (heat(a) ?? 0)).slice(0, max);
    this._list.innerHTML = rows
      .map((s) => {
        const t = Math.max(0, Math.min(1, heat(s) ?? 0));
        const lim = s.caution ? ` / ${s.caution.toFixed(0)}` : "";
        return `<div class="row" title="${s.name}: ${s.value} °C${lim ? ` (attenzione ${s.caution} °C)` : ""}">
          <span class="name">${s.name}</span><span class="val">${s.value.toFixed(0)}°</span>
          <div class="track"><div class="fill" style="width:${Math.max(4, t * 100)}%;background:${colorAt(t)}"></div></div>
        </div>`;
      })
      .join("");
  }

  _groups() {
    const map = new Map();
    for (const s of this._data.sensors) {
      if (s.x == null || s.y == null || typeof s.value !== "number") continue;
      const k = `${s.x},${s.y}`;
      if (!map.has(k)) map.set(k, { x: s.x, y: s.y, sensors: [] });
      map.get(k).sensors.push(s);
    }
    const groups = [...map.values()];
    for (const g of groups) {
      g.sensors.sort((a, b) => heat(b) - heat(a));
      g.t = heat(g.sensors[0]);
      g.value = g.sensors[0].value;
    }
    return groups;
  }

  _computeField(groups, N) {
    // campo di calore interpolato (IDW) sulla scheda, ricalcolato solo quando cambiano i dati
    const RES = 3; // sotto-celle per cella
    const M = N * RES;
    const field = [];
    for (let i = 0; i < M; i++) {
      field.push([]);
      for (let j = 0; j < M; j++) {
        const px = (i + 0.5) / RES - 0.5;
        const py = (j + 0.5) / RES - 0.5;
        let num = 0;
        let den = 0;
        for (const g of groups) {
          const d2 = (g.x - px) ** 2 + (g.y - py) ** 2;
          const w = 1 / Math.pow(d2 + 0.6, 1.6);
          num += w * g.t;
          den += w;
        }
        field[i].push(den ? num / den : 0);
      }
    }
    return { RES, M, field };
  }

  _draw() {
    if (!this._data || !this._data.has_map || !this._canvas) return;
    const width = this._wrap.clientWidth;
    if (!width) return;
    const is3d = this._mode === "3d";
    // tutta visibile senza scorrere: altezza limitata allo spazio della finestra
    // (intestazione, legenda e cornice del popup occupano circa 230 px)
    const maxH = Math.max(220, window.innerHeight - 230);
    const height = Math.round(Math.min(width * (is3d ? 0.66 : 0.72), maxH));
    const dpr = window.devicePixelRatio || 1;
    const cv = this._canvas;
    if (cv.width !== Math.round(width * dpr) || cv.height !== Math.round(height * dpr)) {
      cv.width = Math.round(width * dpr);
      cv.height = Math.round(height * dpr);
      cv.style.height = `${height}px`;
    }
    const ctx = cv.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, width, height);

    if (!this._cache || this._cache.data !== this._data) {
      const style = getComputedStyle(this._card);
      const groups = this._groups();
      const N = Math.max(16, ...groups.map((g) => Math.max(g.x, g.y) + 1));
      this._cache = {
        data: this._data,
        groups,
        N,
        ...this._computeField(groups, N),
        textColor: style.getPropertyValue("--primary-text-color").trim() || "#ddd",
        subColor: style.getPropertyValue("--secondary-text-color").trim() || "#999",
      };
    }
    const c = this._cache;
    this._hits = [];
    if (is3d && this._config.model !== false) this._drawModel(ctx, width, height, c);
    else if (is3d) this._draw3d(ctx, width, height, c.N, c.RES, c.M, c.field, c.groups, c.textColor, c.subColor);
    else this._draw2d(ctx, width, height, c.N, c.RES, c.M, c.field, c.groups, c.textColor, c.subColor);
  }

  _draw3d(ctx, W, H, N, RES, M, field, groups, textColor, subColor) {
    // vista 3D girevole: yaw = rotazione attorno all'asse verticale, k = inclinazione
    const yaw = this._yaw;
    const k = this._tilt;
    const hz = Math.sqrt(1 - k * k) / 0.866;
    const cos = Math.cos(yaw);
    const sin = Math.sin(yaw);
    const ctr = (N - 1) / 2;
    const BAR_MAX = 4.8;
    const s = Math.min(W / (2 * N * 0.866 + 2), H / (2 * N * k + BAR_MAX * hz + 3));
    const cx = W / 2;
    const cy = H / 2 + (BAR_MAX * hz * s) / 2;
    const uv = (gx, gy) => {
      const a = gx - ctr;
      const b = N - 1 - gy - ctr; // fronte (y = 0) verso chi guarda
      return [a * cos - b * sin, a * sin + b * cos];
    };
    const P = (gx, gy, h = 0) => {
      const [u, v] = uv(gx, gy);
      return [cx + (u - v) * 0.866 * s, cy + (u + v) * k * s - h * hz * s];
    };
    const depth = (gx, gy) => {
      const [u, v] = uv(gx, gy);
      return u + v;
    };
    const quad = (pts, fill, stroke) => {
      ctx.beginPath();
      ctx.moveTo(...pts[0]);
      for (const p of pts.slice(1)) ctx.lineTo(...p);
      ctx.closePath();
      if (fill) {
        ctx.fillStyle = fill;
        ctx.fill();
      }
      if (stroke) {
        ctx.strokeStyle = stroke;
        ctx.lineWidth = 1;
        ctx.stroke();
      }
    };
    // luce: facce rivolte verso chi guarda/sinistra più chiare
    const shadeOf = (nx, ny) => {
      const [u, v] = [nx * cos - ny * sin, nx * sin + ny * cos];
      return 0.55 + 0.3 * Math.max(-1, Math.min(1, (u + v) / 1.414)) * 0.5 + 0.15 * Math.max(0, -(u - v) / 1.414);
    };

    // spessore della scheda (tutte le facce, dalla più lontana)
    const e = -0.5;
    const f = N - 0.5;
    const T = 0.45;
    const edges = [
      [[e, e], [f, e]],
      [[f, e], [f, f]],
      [[f, f], [e, f]],
      [[e, f], [e, e]],
    ]
      .map(([p0, p1]) => ({ p0, p1, d: depth((p0[0] + p1[0]) / 2, (p0[1] + p1[1]) / 2) }))
      .sort((a, b) => a.d - b.d);
    for (const { p0, p1 } of edges) {
      quad([P(...p0), P(...p1), P(...p1, -T), P(...p0, -T)], "rgba(45,55,65,0.7)");
    }

    // mappa di calore
    const step = 1 / RES;
    for (let i = 0; i < M; i++) {
      for (let j = 0; j < M; j++) {
        const x0 = i / RES - 0.5;
        const y0 = j / RES - 0.5;
        quad([P(x0, y0), P(x0 + step, y0), P(x0 + step, y0 + step), P(x0, y0 + step)], colorAt(field[i][j], 0.85));
      }
    }
    quad([P(e, e), P(f, e), P(f, f), P(e, f)], null, "rgba(255,255,255,0.35)");

    // colonnine, dalla più lontana alla più vicina
    const sorted = [...groups].sort((a, b) => depth(a.x, a.y) - depth(b.x, b.y));
    const r = 0.28;
    for (const g of sorted) {
      const h = 0.4 + Math.max(0, Math.min(1.2, g.t)) * 3.6;
      const x0 = g.x - r;
      const x1 = g.x + r;
      const y0 = g.y - r;
      const y1 = g.y + r;
      const faces = [
        { pts: [[x0, y0], [x1, y0]], n: [0, 1] }, // fronte (y minore = verso chi guarda)
        { pts: [[x1, y0], [x1, y1]], n: [1, 0] },
        { pts: [[x1, y1], [x0, y1]], n: [0, -1] },
        { pts: [[x0, y1], [x0, y0]], n: [-1, 0] },
      ]
        .map((fc) => ({ ...fc, d: depth((fc.pts[0][0] + fc.pts[1][0]) / 2, (fc.pts[0][1] + fc.pts[1][1]) / 2) }))
        .sort((a, b) => a.d - b.d);
      for (const fc of faces) {
        const [a, b] = fc.pts;
        quad([P(...a), P(...b), P(...b, h), P(...a, h)], colorAt(g.t, 1, shadeOf(fc.n[0], fc.n[1])));
      }
      quad([P(x0, y0, h), P(x1, y0, h), P(x1, y1, h), P(x0, y1, h)], colorAt(g.t, 1, 1.08), "rgba(255,255,255,0.5)");
      const [tx, ty] = P(g.x, g.y, h);
      this._hits.push({ x: tx, y: ty, r: Math.max(10, s * 0.6), g });
    }

    // etichette sulle 4 colonnine più calde
    ctx.font = `600 ${Math.max(10, Math.round(s * 0.62))}px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    for (const hit of [...this._hits].sort((a, b) => b.g.t - a.g.t).slice(0, 4)) {
      ctx.fillStyle = textColor;
      ctx.fillText(`${hit.g.value.toFixed(0)}°`, hit.x, hit.y - 4);
    }

    // orientamento: etichette sul bordo anteriore e posteriore
    ctx.font = `${Math.max(9, Math.round(s * 0.5))}px system-ui, sans-serif`;
    ctx.fillStyle = subColor;
    ctx.textBaseline = "middle";
    const [fx, fy] = P(ctr, -1.6);
    ctx.fillText("fronte · ingresso aria", fx, fy);
    const [bx, by] = P(ctr, N + 0.6);
    ctx.fillText("retro · scarico", bx, by);
    if (!this._hintShown) {
      ctx.textAlign = "right";
      ctx.textBaseline = "top";
      ctx.fillText("trascina per ruotare · doppio clic per tornare", W - 4, 4);
    }
  }

  _buildModel(N) {
    // componenti (box in mm) ricavati da nomi e coordinate dei sensori; calcolato solo al cambio dati
    const X = (gx) => ((gx + 0.5) / N) * MW;
    const Y = (gy) => mapY(gy, N);
    const clamp = (v, a, b) => Math.max(a, Math.min(b, v));
    const num = (s) => parseInt(s.name.replace(/^\D+/, ""), 10) || 0;
    const free = this._data.sensors.filter((s) => typeof s.value === "number" && s.x != null && s.y != null);
    const take = (re) => {
      const out = free.filter((s) => re.test(s.name));
      for (const s of out) free.splice(free.indexOf(s), 1);
      return out;
    };
    const B = (x0, x1, y0, y1, z0, z1, kind) => ({ x0, x1, y0, y1, z0, z1, kind });
    const comps = [];
    const boxes = [];
    const add = (title, sensors, bxs, opt = {}) => {
      const c = { title, sensors, extra: [], boxes: bxs, ...opt };
      const hot = sensors.reduce((a, s) => (!a || heat(s) > heat(a) ? s : a), null);
      c.t = hot ? heat(hot) : null;
      c.value = hot ? hot.value : null;
      for (const b of bxs) {
        Object.assign(b, { c, a0: b.x0 - MW / 2, a1: b.x1 - MW / 2, b0: MD / 2 - b.y1, b1: MD / 2 - b.y0 });
        boxes.push(b);
      }
      comps.push(c);
      return c;
    };

    // telaio aperto: pareti laterali e pannello posteriore (trasparenti)
    add(null, [], [B(0, 2, 0, MD, 0, MH, "wall"), B(MW - 2, MW, 0, MD, 0, MH, "wall"), B(2, MW - 2, MD - 2, MD, 0, MH, "wall")], {
      ghost: true,
    });
    // fronte: orecchie del pannello (sensore aria in ingresso a sinistra) e gabbia dischi
    add("Pannello frontale", take(/^Inlet Ambient/i), [B(2, 30, 0, 36, 2, 84, "ear")]);
    add(null, [], [B(MW - 30, MW - 2, 0, 36, 2, 84, "ear")]);
    add("Gabbia dischi", take(/^HD Max|^HDD|Drive/i), [B(30, MW - 30, 0, 150, 2, 84, "cage")]);
    // 6 ventole
    const fw = (MW - 12 - 5 * 4) / 6;
    add(null, [], [0, 1, 2, 3, 4, 5].map((i) => B(6 + i * (fw + 4), 6 + i * (fw + 4) + fw, 158, 212, 2, 80, "fan")));
    // dissipatori CPU
    const cpuY = {};
    for (const s of take(/^CPU \d+$/)) {
      const cx = clamp(X(s.x), 44, MW - 44);
      const cy = (cpuY[num(s)] = clamp(Y(s.y), 270, MD - 270));
      add(s.name, [s], [B(cx - 40, cx + 40, cy - 50, cy + 50, 4, 66, "sink")]);
    }
    // banchi DIMM: 3 moduli per sensore, paralleli al flusso d'aria, accanto alla CPU
    for (const s of take(/^P\d+ DIMM/)) {
      const cx = clamp(X(s.x), 12, MW - 12);
      const cy = cpuY[num(s)] ?? clamp(Y(s.y), 290, MD - 290);
      add(s.name, [s], [-8, 0, 8].map((o) => B(cx + o - 2, cx + o + 2, cy - 66, cy + 66, 4, 36, "dimm")));
    }
    // alimentatori sul retro
    const ps = take(/^P\/S \d+$/).sort((a, b) => num(a) - num(b));
    if (ps.length) {
      const st = clamp(X(ps.reduce((a, s) => a + s.x, 0) / ps.length) - ps.length * 28, 4, MW - 4 - ps.length * 56);
      ps.forEach((s, i) => add(`Alimentatore ${num(s)}`, [s], [B(st + i * 56, st + i * 56 + 54, MD - 214, MD - 4, 4, 44, "psu")]));
    }
    // schede PCI sul riser (una per numero di slot)
    const pci = take(/^PCI \d+/);
    if (pci.length) {
      const slots = [...new Set(pci.map(num))].sort((a, b) => a - b);
      const xr = clamp(X(pci.reduce((a, s) => a + s.x, 0) / pci.length) - 20, 30 + slots.length * 11, MW - 30 - slots.length * 11);
      slots.forEach((n, i) => {
        const cx = xr + (i - (slots.length - 1) / 2) * 22;
        add(`Slot PCI ${n}`, pci.filter((s) => num(s) === n), [B(cx - 2.5, cx + 2.5, MD - 190, MD - 12, 10, 76, "card")]);
      });
    }
    // altri sensori: dentro un componente -> nel suo tooltip, altrimenti un chip sulla scheda
    const hosts = comps.filter((c) => c.sensors.length);
    const chips = new Map();
    for (const s of free) {
      const x = X(s.x);
      const y = Y(s.y);
      const host = hosts.find((c) => c.boxes.some((b) => x >= b.x0 - 4 && x <= b.x1 + 4 && y >= b.y0 - 4 && y <= b.y1 + 4));
      if (host) host.extra.push(s);
      else {
        const key = `${s.x},${s.y}`;
        if (!chips.has(key)) chips.set(key, { x, y, list: [] });
        chips.get(key).list.push(s);
      }
    }
    for (const g of chips.values()) {
      const n = g.list[0].name;
      const [w, d, h] = /LOM/.test(n)
        ? [40, 70, 8]
        : /HD Controller|I\/O Board|Chipset$/.test(n)
          ? [30, 30, 8]
          : /^VR/.test(n) && !/Zone/.test(n)
            ? [26, 16, 10]
            : [16, 16, 4];
      const x0 = clamp(g.x - w / 2, 3, MW - 3 - w);
      const y0 = clamp(g.y - d / 2, 3, MD - 3 - d);
      add(g.list.map((s) => s.name).join(", "), g.list, [B(x0, x0 + w, y0, y0 + d, 2, 2 + h, "chip")]);
    }
    for (const c of comps) {
      const all = [...c.sensors, ...c.extra].sort((a, b) => heat(b) - heat(a));
      const solo = c.sensors.length === 1 && !c.extra.length && c.sensors[0].name === c.title;
      c.g = all.length ? { title: solo ? null : c.title, sensors: all } : null;
      const b = c.boxes;
      c.top = [(Math.min(...b.map((q) => q.x0)) + Math.max(...b.map((q) => q.x1))) / 2,
        (Math.min(...b.map((q) => q.y0)) + Math.max(...b.map((q) => q.y1))) / 2, Math.max(...b.map((q) => q.z1))];
    }
    // bordi della mappa di calore in mm
    const RES = this._cache.RES;
    const M = this._cache.M;
    const ex = [];
    const ey = [];
    for (let i = 0; i <= M; i++) {
      ex.push(X(i / RES - 0.5));
      ey.push(Y(i / RES - 0.5));
    }
    return { comps, boxes, ex, ey, orders: {} };
  }

  _order(m, ga, gb) {
    // ordine del pittore tra box allineati agli assi: piano separatore, poi altezza; dipende solo
    // dal quadrante di vista, quindi è calcolato al più 4 volte
    const key = `${ga >= 0 ? 1 : 0}${gb >= 0 ? 1 : 0}`;
    if (m.orders[key]) return m.orders[key];
    const bx = m.boxes;
    const n = bx.length;
    const sep = (A, B) => {
      if (A.a1 <= B.a0) return ga >= 0 ? -1 : 1;
      if (B.a1 <= A.a0) return ga >= 0 ? 1 : -1;
      if (A.b1 <= B.b0) return gb >= 0 ? -1 : 1;
      if (B.b1 <= A.b0) return gb >= 0 ? 1 : -1;
      if (A.z1 <= B.z0) return -1;
      if (B.z1 <= A.z0) return 1;
      return 0;
    };
    const indeg = new Array(n).fill(0);
    const out = bx.map(() => []);
    for (let i = 0; i < n; i++) {
      for (let j = i + 1; j < n; j++) {
        const r = sep(bx[i], bx[j]);
        if (r < 0) {
          out[i].push(j);
          indeg[j]++;
        } else if (r > 0) {
          out[j].push(i);
          indeg[i]++;
        }
      }
    }
    const dep = bx.map((b) => ((b.a0 + b.a1) / 2) * ga + ((b.b0 + b.b1) / 2) * gb);
    const done = new Array(n).fill(false);
    const order = [];
    while (order.length < n) {
      let best = -1;
      for (let i = 0; i < n; i++) {
        if (done[i]) continue;
        if (best < 0 || indeg[i] < indeg[best] || (indeg[i] === indeg[best] && dep[i] < dep[best])) best = i;
      }
      done[best] = true;
      order.push(bx[best]);
      for (const j of out[best]) indeg[j]--;
    }
    return (m.orders[key] = order);
  }

  _drawModel(ctx, W, H, c) {
    const m = c.model || (c.model = this._buildModel(c.N));
    const k = this._tilt;
    const hz = Math.sqrt(1 - k * k) / 0.866;
    const cos = Math.cos(this._yaw);
    const sin = Math.sin(this._yaw);
    const ga = cos + sin; // crescita della profondità (verso chi guarda) lungo a = x
    const gb = cos - sin; // ... lungo b = verso il fronte
    const R = Math.hypot(MW, MD) / 2 + 50;
    const s = Math.min(W / (2 * 1.2247 * R), H / (2 * 1.4142 * R * k + MH * hz + 24));
    const su = (s * MW) / c.N; // pixel per cella della griglia iLO (per i caratteri)
    const cx = W / 2;
    const cy = H / 2 + (MH * hz * s) / 2;
    const P = (x, y, z = 0) => {
      const a = x - MW / 2;
      const b = MD / 2 - y;
      const u = a * cos - b * sin;
      const v = a * sin + b * cos;
      return [cx + (u - v) * 0.866 * s, cy + (u + v) * k * s - z * hz * s];
    };
    const poly = (pts, fill, stroke, lw = 1) => {
      ctx.beginPath();
      ctx.moveTo(pts[0][0], pts[0][1]);
      for (let i = 1; i < pts.length; i++) ctx.lineTo(pts[i][0], pts[i][1]);
      ctx.closePath();
      if (fill) {
        ctx.fillStyle = fill;
        ctx.fill();
      }
      if (stroke) {
        ctx.strokeStyle = stroke;
        ctx.lineWidth = lw;
        ctx.stroke();
      }
    };
    const shadeOf = (na, nb) => {
      const u = na * cos - nb * sin;
      const v = na * sin + nb * cos;
      return 0.55 + 0.3 * Math.max(-1, Math.min(1, (u + v) / 1.414)) * 0.5 + 0.15 * Math.max(0, -(u - v) / 1.414);
    };
    const col = (t, a, sh) => {
      if (t != null) return colorAt(t, a, sh);
      const g = Math.round(105 * sh);
      return `rgba(${g},${g + 6},${g + 14},${a})`;
    };
    const lines = (segs, stroke, lw = 1) => {
      ctx.beginPath();
      for (const [p, q] of segs) {
        ctx.moveTo(p[0], p[1]);
        ctx.lineTo(q[0], q[1]);
      }
      ctx.strokeStyle = stroke;
      ctx.lineWidth = lw;
      ctx.stroke();
    };

    // spessore del fondo
    const T = 12;
    const sides = [
      [[0, 0], [0, MD], ga < 0],
      [[MW, 0], [MW, MD], ga > 0],
      [[0, 0], [MW, 0], gb > 0],
      [[0, MD], [MW, MD], gb < 0],
    ];
    for (const [p0, p1, vis] of sides) {
      if (vis) poly([P(...p0), P(...p1), P(...p1, -T), P(...p0, -T)], "rgba(45,55,65,0.85)");
    }
    // mappa di calore sul fondo
    const { ex, ey } = m;
    const M = c.M;
    const pts = [];
    for (let i = 0; i <= M; i++) {
      const row = [];
      for (let j = 0; j <= M; j++) row.push(P(ex[i], ey[j]));
      pts.push(row);
    }
    for (let i = 0; i < M; i++) {
      for (let j = 0; j < M; j++) {
        poly([pts[i][j], pts[i + 1][j], pts[i + 1][j + 1], pts[i][j + 1]], colorAt(c.field[i][j], 0.7));
      }
    }
    poly([P(0, 0), P(MW, 0), P(MW, MD), P(0, MD)], null, "rgba(255,255,255,0.3)");

    // componenti, dal più lontano al più vicino
    for (const b of this._order(m, ga, gb)) {
      const cp = b.c;
      const { x0, x1, y0, y1, z0, z1 } = b;
      const alpha = cp.ghost ? 0.1 : 1;
      const edge = cp.ghost ? "rgba(255,255,255,0.18)" : "rgba(0,0,0,0.35)";
      const faces = [];
      if (ga < 0) faces.push([[x0, y0], [x0, y1], -1, 0]);
      if (ga > 0) faces.push([[x1, y0], [x1, y1], 1, 0]);
      if (gb > 0) faces.push([[x0, y0], [x1, y0], 0, 1]);
      if (gb < 0) faces.push([[x0, y1], [x1, y1], 0, -1]);
      for (const [p0, p1, na, nb] of faces) {
        const q = [P(...p0, z0), P(...p1, z0), P(...p1, z1), P(...p0, z1)];
        poly(q, col(cp.t, alpha, shadeOf(na, nb) * (b.kind === "fan" ? 0.75 : 1)), edge, 0.6);
        if (cp.g) this._hits.push({ poly: q, g: cp.g });
      }
      const top = [P(x0, y0, z1), P(x1, y0, z1), P(x1, y1, z1), P(x0, y1, z1)];
      poly(top, col(cp.t, alpha, b.kind === "fan" ? 0.8 : 1.08), cp.ghost ? edge : "rgba(255,255,255,0.4)", 0.8);
      if (cp.g) this._hits.push({ poly: top, g: cp.g });

      if (b.kind === "sink") {
        const segs = [];
        for (let x = x0 + 5; x < x1 - 2; x += 7) segs.push([P(x, y0, z1), P(x, y1, z1)]);
        lines(segs, "rgba(0,0,0,0.28)");
      } else if (b.kind === "cage" && gb > 0) {
        const segs = [];
        for (let i = 1; i < 8; i++) {
          const x = x0 + ((x1 - x0) * i) / 8;
          segs.push([P(x, y0, z0 + 5), P(x, y0, z1 - 5)]);
        }
        lines(segs, "rgba(0,0,0,0.4)");
      } else if (b.kind === "fan") {
        const yf = gb > 0 ? y0 : y1;
        const fx = (x0 + x1) / 2;
        const fz = (z0 + z1) / 2;
        const r = Math.min(x1 - x0, z1 - z0) * 0.42;
        const ring = (rr) => Array.from({ length: 20 }, (_, i) => P(fx + rr * Math.cos((i * Math.PI) / 10), yf, fz + rr * Math.sin((i * Math.PI) / 10)));
        poly(ring(r), "rgba(0,0,0,0.4)", "rgba(255,255,255,0.25)");
        poly(ring(r * 0.3), "rgba(120,128,140,1)");
      }
    }

    // valori sui 4 componenti più caldi
    ctx.font = `600 ${Math.max(10, Math.round(su * 0.62))}px system-ui, sans-serif`;
    ctx.textAlign = "center";
    ctx.textBaseline = "bottom";
    ctx.fillStyle = c.textColor;
    for (const cp of m.comps.filter((q) => q.t != null).sort((a, b) => b.t - a.t).slice(0, 4)) {
      const [tx, ty] = P(...cp.top);
      ctx.fillText(`${cp.value.toFixed(0)}°`, tx, ty - 4);
    }

    ctx.font = `${Math.max(9, Math.round(su * 0.5))}px system-ui, sans-serif`;
    ctx.fillStyle = c.subColor;
    ctx.textBaseline = "middle";
    // lato verso chi guarda: a terra; lato lontano: sopra i componenti, per non sovrapporsi
    const [fx, fy] = gb > -0.5 ? P(MW / 2, -110) : P(MW / 2, -30, MH + 20);
    ctx.fillText("fronte · ingresso aria", fx, fy);
    const [bx, by] = gb < 0.5 ? P(MW / 2, MD + 80) : P(MW / 2, MD + 20, MH + 20);
    ctx.fillText("retro · scarico", bx, by);
    if (!this._hintShown) {
      ctx.textAlign = "right";
      ctx.textBaseline = "top";
      ctx.fillText("trascina per ruotare · doppio clic per tornare", W - 4, 4);
    }
  }

  _draw2d(ctx, W, H, N, RES, M, field, groups, textColor, subColor) {
    const pad = 22;
    const s = Math.min((W - 2 * pad) / N, (H - 2 * pad) / N);
    const ox = (W - s * N) / 2;
    const oy = (H - s * N) / 2;
    // fronte in basso
    const X = (gx) => ox + (gx + 0.5) * s;
    const Y = (gy) => oy + (N - 1 - gy + 0.5) * s;
    const cs = s / RES;
    for (let i = 0; i < M; i++) {
      for (let j = 0; j < M; j++) {
        ctx.fillStyle = colorAt(field[i][j], 0.85);
        ctx.fillRect(ox + i * cs, oy + (M - 1 - j) * cs, cs + 0.5, cs + 0.5);
      }
    }
    ctx.strokeStyle = "rgba(255,255,255,0.35)";
    ctx.strokeRect(ox, oy, s * N, s * N);
    const rad = Math.max(8, s * 0.42);
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.font = `600 ${Math.max(8, Math.round(rad * 0.85))}px system-ui, sans-serif`;
    for (const g of groups) {
      const x = X(g.x);
      const y = Y(g.y);
      ctx.beginPath();
      ctx.arc(x, y, rad, 0, Math.PI * 2);
      ctx.fillStyle = colorAt(g.t, 1, 0.9);
      ctx.fill();
      ctx.strokeStyle = "rgba(255,255,255,0.8)";
      ctx.lineWidth = 1.5;
      ctx.stroke();
      ctx.fillStyle = "#fff";
      ctx.fillText(g.value.toFixed(0), x, y + 0.5);
      this._hits.push({ x, y, r: rad + 2, g });
    }
    ctx.font = `${Math.max(9, Math.round(s * 0.5))}px system-ui, sans-serif`;
    ctx.fillStyle = subColor;
    ctx.fillText("▼ fronte · aria in ingresso", W / 2, H - pad / 2);
    ctx.fillText("retro · scarico ▲", W / 2, pad / 2);
  }

  _hover(ev) {
    if (!this._hits || !this._hits.length) return;
    const rect = this._canvas.getBoundingClientRect();
    const mx = ev.clientX - rect.left;
    const my = ev.clientY - rect.top;
    let best = null;
    let bd = Infinity;
    // modello: poligoni delle facce, dall'ultima disegnata (in primo piano)
    for (let i = this._hits.length - 1; i >= 0 && !best; i--) {
      if (this._hits[i].poly && inPoly(this._hits[i].poly, mx, my)) best = this._hits[i];
    }
    for (const h of best ? [] : this._hits) {
      if (h.poly) continue;
      const d = Math.hypot(h.x - mx, h.y - my);
      if (d < h.r * 1.4 && d < bd) {
        best = h;
        bd = d;
      }
    }
    if (!best) {
      this._tip.style.display = "none";
      return;
    }
    this._tip.innerHTML =
      (best.g.title ? `<div style="opacity:.7;margin-bottom:2px">${best.g.title}</div>` : "") +
      best.g.sensors
      .map((s) => {
        const lim = [s.caution ? `attenzione ${s.caution.toFixed(0)}°` : null, s.critical ? `critica ${s.critical.toFixed(0)}°` : null]
          .filter(Boolean)
          .join(" · ");
        return `<div><b>${s.name}</b>: ${s.value.toFixed(0)} °C${lim ? `<br><span style="opacity:.7">${lim}</span>` : ""}</div>`;
      })
      .join('<div style="height:4px"></div>');
    this._tip.style.display = "block";
    const tw = this._tip.offsetWidth;
    const left = Math.min(Math.max(4, mx + 12), rect.width - tw - 4);
    this._tip.style.left = `${left}px`;
    this._tip.style.top = `${Math.max(4, my - this._tip.offsetHeight - 10)}px`;
  }
}

if (!customElements.get("hpe-ilo-thermal-card")) {
  customElements.define("hpe-ilo-thermal-card", HpeIloThermalCard);
  window.customCards = window.customCards || [];
  window.customCards.push({
    type: "hpe-ilo-thermal-card",
    name: "HP iLO – Mappa termica",
    description: "Temperature del server HP iLO sulla scheda madre, in 3D o 2D.",
    documentationURL: "https://github.com/alebartos/ha-ilo",
  });
}
