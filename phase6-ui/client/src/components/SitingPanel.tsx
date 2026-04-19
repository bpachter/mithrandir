import { useEffect, useMemo, useRef, useState, useCallback } from 'react'
import maplibregl, { Map as MLMap } from 'maplibre-gl'
import type { LngLatBoundsLike } from 'maplibre-gl'
import 'maplibre-gl/dist/maplibre-gl.css'
import {
  fetchSitingFactors,
  fetchSitingSample,
  fetchSitingLayers,
  fetchSitingLayerGeoJSON,
  scoreSites,
  type Archetype,
  type SiteResultDTO,
  type SitingFactorsResponse,
  type SitingLayer,
} from '../api'
import './SitingPanel.css'

// Free MapLibre style — CARTO dark matter (no API key)
const STYLE_URL =
  'https://basemaps.cartocdn.com/gl/dark-matter-gl-style/style.json'

// Map UI layer key -> color/visual config for overlays
const LAYER_VISUALS: Record<string, {
  color: string
  width?: number
  radius?: number
  type: 'line' | 'circle'
}> = {
  transmission: { color: '#ff9500', width: 1.4, type: 'line' },
  pipelines:    { color: '#ff1a40', width: 1.0, type: 'line' },
  fiber:        { color: '#00e5ff', width: 0.9, type: 'line' },
  substations:  { color: '#ff9500', radius: 2.5, type: 'circle' },
  ixp:          { color: '#39d353', radius: 4.0, type: 'circle' },
}

function colorForScore(score: number, killed: boolean): string {
  if (killed) return '#3a1018'
  // 0..10 → red..amber..green
  const t = Math.max(0, Math.min(1, score / 10))
  if (t < 0.5) {
    const k = t / 0.5
    // red -> amber
    const r = Math.round(255)
    const g = Math.round(26 + (149 - 26) * k)
    const b = Math.round(64 - 64 * k)
    return `rgb(${r},${g},${b})`
  } else {
    const k = (t - 0.5) / 0.5
    // amber -> green
    const r = Math.round(255 - (255 - 57) * k)
    const g = Math.round(149 + (211 - 149) * k)
    const b = Math.round(0 + 83 * k)
    return `rgb(${r},${g},${b})`
  }
}

const ARCHETYPES: Archetype[] = ['training', 'inference', 'mixed']

const FALLBACK_SAMPLE_SITES: Array<{ site_id: string; lat: number; lon: number; state: string }> = [
  { site_id: 'TX-ABL-001', lat: 32.4487, lon: -99.7331, state: 'TX' },
  { site_id: 'VA-LDN-001', lat: 39.0840, lon: -77.6555, state: 'VA' },
  { site_id: 'GA-DGL-001', lat: 33.9526, lon: -84.5499, state: 'GA' },
  { site_id: 'AZ-PHX-001', lat: 33.4484, lon: -112.0740, state: 'AZ' },
  { site_id: 'IA-DSM-001', lat: 41.5868, lon: -93.6250, state: 'IA' },
  { site_id: 'WI-MTP-001', lat: 42.7228, lon: -87.7829, state: 'WI' },
  { site_id: 'WA-QCY-001', lat: 47.2343, lon: -119.8521, state: 'WA' },
  { site_id: 'NE-OMA-001', lat: 41.2565, lon: -95.9345, state: 'NE' },
  { site_id: 'TN-CLA-001', lat: 36.5298, lon: -87.3595, state: 'TN' },
  { site_id: 'TX-TMP-001', lat: 31.0982, lon: -97.3428, state: 'TX' },
]

type SiteInput = { site_id: string; lat: number; lon: number; [k: string]: unknown }

const FALLBACK_BY_ID: Record<string, SiteInput> = Object.fromEntries(
  FALLBACK_SAMPLE_SITES.map((s) => [s.site_id, s]),
)

function isFiniteNumber(v: unknown): v is number {
  return typeof v === 'number' && Number.isFinite(v)
}

function toSiteInputsFromResults(results: SiteResultDTO[]): SiteInput[] {
  const out: SiteInput[] = []
  for (const r of results as Array<SiteResultDTO & { extras?: Record<string, unknown> }>) {
    const lat = isFiniteNumber(r.lat) ? r.lat : FALLBACK_BY_ID[r.site_id]?.lat
    const lon = isFiniteNumber(r.lon) ? r.lon : FALLBACK_BY_ID[r.site_id]?.lon
    if (!isFiniteNumber(lat) || !isFiniteNumber(lon)) continue
    out.push({ site_id: r.site_id, lat, lon, ...(r.extras ?? {}) })
  }
  return out
}

function mergeCoordsIntoResults(results: SiteResultDTO[], inputs: SiteInput[]): SiteResultDTO[] {
  const byId = new Map(inputs.map((s) => [s.site_id, s]))
  return results
    .map((r) => {
      const src = byId.get(r.site_id)
      if (!src) return r
      return { ...r, lat: src.lat, lon: src.lon, extras: { ...(r.extras ?? {}), ...src } }
    })
    .filter((r) => isFiniteNumber(r.lat) && isFiniteNumber(r.lon))
}

export default function SitingPanel() {
  const mapDivRef = useRef<HTMLDivElement | null>(null)
  const mapRef = useRef<MLMap | null>(null)
  const [mapReady, setMapReady] = useState(false)
  const [bbox, setBbox] = useState<[number, number, number, number] | null>(null)

  const [factorsCatalog, setFactorsCatalog] = useState<SitingFactorsResponse | null>(null)
  const [layers, setLayers] = useState<SitingLayer[]>([])
  const [enabledLayers, setEnabledLayers] = useState<Record<string, boolean>>({})

  const [archetype, setArchetype] = useState<Archetype>('training')
  const [weightOverrides, setWeightOverrides] = useState<Record<string, number>>({})

  const [sites, setSites] = useState<SiteResultDTO[]>([])
  const [siteInputs, setSiteInputs] = useState<SiteInput[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [scoring, setScoring] = useState(false)
  const [layerStatus, setLayerStatus] = useState<Record<string, 'idle' | 'loading' | 'ok' | 'missing' | 'error'>>({})
  const [error, setError] = useState<string | null>(null)

  // ── init: catalog + layer list + sample sites ─────────────────────────
  useEffect(() => {
    fetchSitingFactors().then(setFactorsCatalog).catch(e => setError(String(e)))
    fetchSitingLayers().then(r => {
      setLayers(r.layers)
      const enabled: Record<string, boolean> = {}
      for (const l of r.layers) enabled[l.key] = false
      setEnabledLayers(enabled)
    }).catch(e => setError(String(e)))
    fetchSitingSample()
      .then(async (r) => {
        if (Array.isArray(r.results)) {
          const inputs = toSiteInputsFromResults(r.results)
          if (inputs.length > 0) {
            setSiteInputs(inputs)
            setSites(mergeCoordsIntoResults(r.results, inputs))
            return
          }
          const scored = await scoreSites({ sites: FALLBACK_SAMPLE_SITES, archetype })
          setSiteInputs(FALLBACK_SAMPLE_SITES)
          setSites(mergeCoordsIntoResults(scored.results, FALLBACK_SAMPLE_SITES))
          return
        }
        if (Array.isArray(r.sites) && r.sites.length > 0) {
          const scored = await scoreSites({ sites: r.sites, archetype })
          setSiteInputs(r.sites)
          setSites(mergeCoordsIntoResults(scored.results, r.sites))
        }
      })
      .catch(async () => {
        try {
          const scored = await scoreSites({
            sites: FALLBACK_SAMPLE_SITES,
            archetype,
          })
          setSiteInputs(FALLBACK_SAMPLE_SITES)
          setSites(mergeCoordsIntoResults(scored.results, FALLBACK_SAMPLE_SITES))
        } catch (e) {
          setError(String(e))
        }
      })
  }, [])

  // ── init MapLibre ─────────────────────────────────────────────────────
  useEffect(() => {
    if (!mapDivRef.current || mapRef.current) return
    const map = new maplibregl.Map({
      container: mapDivRef.current,
      style: STYLE_URL,
      center: [-96, 38.5],
      zoom: 3.6,
      attributionControl: { compact: true },
    })
    map.addControl(new maplibregl.NavigationControl({ visualizePitch: true }), 'top-right')
    map.addControl(new maplibregl.ScaleControl({ unit: 'imperial' }), 'bottom-left')

    const updateBbox = () => {
      const b = map.getBounds()
      setBbox([b.getWest(), b.getSouth(), b.getEast(), b.getNorth()])
    }
    map.on('load', () => {
      mapRef.current = map
      setMapReady(true)
      updateBbox()
    })
    map.on('moveend', updateBbox)
    return () => { map.remove(); mapRef.current = null }
  }, [])

  // ── candidate site source/layer (re-render when sites change) ─────────
  useEffect(() => {
    const map = mapRef.current
    if (!map || !mapReady) return
    const fc: GeoJSON.FeatureCollection = {
      type: 'FeatureCollection',
      features: sites.map(s => ({
        type: 'Feature',
        id: s.site_id,
        geometry: { type: 'Point', coordinates: [s.lon, s.lat] },
        properties: {
          site_id: s.site_id,
          composite: s.composite,
          killed: Object.values(s.kill_flags).some(Boolean),
          color: colorForScore(s.composite, Object.values(s.kill_flags).some(Boolean)),
        },
      })),
    }
    const SRC = 'sites-src'
    const LYR = 'sites-lyr'
    const LBL = 'sites-lbl'
    const HALO = 'sites-halo'

    if (map.getSource(SRC)) {
      ;(map.getSource(SRC) as maplibregl.GeoJSONSource).setData(fc)
    } else {
      map.addSource(SRC, { type: 'geojson', data: fc })
      map.addLayer({
        id: HALO, type: 'circle', source: SRC,
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 3, 8, 8, 22],
          'circle-color': ['get', 'color'],
          'circle-opacity': 0.18,
          'circle-blur': 0.6,
        },
      })
      map.addLayer({
        id: LYR, type: 'circle', source: SRC,
        paint: {
          'circle-radius': ['interpolate', ['linear'], ['zoom'], 3, 5, 8, 12],
          'circle-color': ['get', 'color'],
          'circle-stroke-color': '#000',
          'circle-stroke-width': 1.2,
        },
      })
      map.addLayer({
        id: LBL, type: 'symbol', source: SRC,
        layout: {
          'text-field': [
            'concat',
            ['to-string', ['round', ['*', ['get', 'composite'], 10]]],
            '',
          ],
          'text-size': 11,
          'text-offset': [0, -1.4],
          'text-font': ['Open Sans Bold', 'Arial Unicode MS Bold'],
          'text-allow-overlap': true,
        },
        paint: {
          'text-color': '#fff',
          'text-halo-color': '#000',
          'text-halo-width': 1.4,
        },
      })
      map.on('click', LYR, (e) => {
        const f = e.features?.[0]
        if (f) setSelectedId(String(f.properties?.site_id))
      })
      map.on('mouseenter', LYR, () => { map.getCanvas().style.cursor = 'pointer' })
      map.on('mouseleave', LYR, () => { map.getCanvas().style.cursor = '' })
    }
  }, [sites, mapReady])

  // ── overlay layers: load on toggle / bbox change ──────────────────────
  const reloadOverlay = useCallback(async (key: string) => {
    const map = mapRef.current
    if (!map) return
    const vis = LAYER_VISUALS[key]
    if (!vis) return
    setLayerStatus(s => ({ ...s, [key]: 'loading' }))
    const data = await fetchSitingLayerGeoJSON(key, bbox ?? undefined, 4000)
    if ('error' in data) {
      setLayerStatus(s => ({ ...s, [key]: 'missing' }))
      return
    }
    const SRC = `ovl-${key}-src`
    const LYR = `ovl-${key}-lyr`
    if (map.getSource(SRC)) {
      ;(map.getSource(SRC) as maplibregl.GeoJSONSource).setData(data as any)
    } else {
      map.addSource(SRC, { type: 'geojson', data: data as any })
      if (vis.type === 'line') {
        map.addLayer({
          id: LYR, type: 'line', source: SRC,
          layout: { 'line-cap': 'round', 'line-join': 'round' },
          paint: { 'line-color': vis.color, 'line-width': vis.width ?? 1, 'line-opacity': 0.85 },
        }, 'sites-halo')
      } else {
        map.addLayer({
          id: LYR, type: 'circle', source: SRC,
          paint: {
            'circle-radius': vis.radius ?? 3,
            'circle-color': vis.color,
            'circle-stroke-color': '#000',
            'circle-stroke-width': 0.6,
            'circle-opacity': 0.9,
          },
        }, 'sites-halo')
      }
    }
    setLayerStatus(s => ({ ...s, [key]: 'ok' }))
  }, [bbox])

  const removeOverlay = useCallback((key: string) => {
    const map = mapRef.current
    if (!map) return
    const SRC = `ovl-${key}-src`
    const LYR = `ovl-${key}-lyr`
    if (map.getLayer(LYR)) map.removeLayer(LYR)
    if (map.getSource(SRC)) map.removeSource(SRC)
    setLayerStatus(s => ({ ...s, [key]: 'idle' }))
  }, [])

  // toggle handler
  function toggleLayer(key: string) {
    setEnabledLayers(prev => {
      const next = { ...prev, [key]: !prev[key] }
      if (next[key]) reloadOverlay(key)
      else removeOverlay(key)
      return next
    })
  }

  // refetch enabled overlays when bbox changes (debounced via dependency)
  useEffect(() => {
    if (!mapReady || !bbox) return
    for (const [key, on] of Object.entries(enabledLayers)) {
      if (on) reloadOverlay(key)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bbox?.[0], bbox?.[1], bbox?.[2], bbox?.[3], mapReady])

  // ── re-score on archetype / weight changes ────────────────────────────
  async function rescoreAll() {
    if (siteInputs.length === 0) return
    setScoring(true)
    setError(null)
    try {
      const r = await scoreSites({
        sites: siteInputs,
        archetype,
        weight_overrides: Object.keys(weightOverrides).length ? weightOverrides : undefined,
      })
      setSites(mergeCoordsIntoResults(r.results, siteInputs))
    } catch (e) {
      setError(String(e))
    } finally {
      setScoring(false)
    }
  }

  useEffect(() => { rescoreAll() /* eslint-disable-next-line react-hooks/exhaustive-deps */ }, [archetype])

  const selected = useMemo(
    () => sites.find(s => s.site_id === selectedId) ?? null,
    [selectedId, sites],
  )

  function flyTo(s: SiteResultDTO) {
    const map = mapRef.current
    if (!map) return
    map.flyTo({ center: [s.lon, s.lat], zoom: 8.5, speed: 1.4 })
    setSelectedId(s.site_id)
  }

  function fitToSites() {
    const map = mapRef.current
    if (!map || sites.length === 0) return
    let xmin = 180, ymin = 90, xmax = -180, ymax = -90
    for (const s of sites) {
      if (s.lon < xmin) xmin = s.lon
      if (s.lon > xmax) xmax = s.lon
      if (s.lat < ymin) ymin = s.lat
      if (s.lat > ymax) ymax = s.lat
    }
    const bounds: LngLatBoundsLike = [[xmin, ymin], [xmax, ymax]]
    map.fitBounds(bounds, { padding: 80, duration: 800 })
  }

  const ranked = useMemo(
    () => [...sites].sort((a, b) => b.composite - a.composite),
    [sites],
  )

  const factorList = factorsCatalog?.factors ?? []
  const baseWeights = factorsCatalog?.weights[archetype] ?? {}

  function setWeight(factor: string, val: number) {
    setWeightOverrides(w => ({ ...w, [factor]: val }))
  }

  function resetWeights() {
    setWeightOverrides({})
  }

  return (
    <div className="siting-root">
      {/* ── Sidebar ── */}
      <aside className="siting-side">
        <div className="siting-side-head">
          <span className="siting-title">SITING.MAP</span>
          <span className="siting-sub">14-factor composite · public data</span>
        </div>

        <section className="siting-block">
          <div className="siting-block-head">ARCHETYPE</div>
          <div className="archetype-row">
            {ARCHETYPES.map(a => (
              <button
                key={a}
                className={`arch-btn ${archetype === a ? 'active' : ''}`}
                onClick={() => setArchetype(a)}
              >{a.toUpperCase()}</button>
            ))}
          </div>
        </section>

        <section className="siting-block">
          <div className="siting-block-head">
            <span>OVERLAYS</span>
            <span className="siting-block-meta">{bbox ? 'bbox-clipped' : ''}</span>
          </div>
          <ul className="layer-list">
            {layers.map(l => {
              const st = layerStatus[l.key] ?? 'idle'
              const dotColor = LAYER_VISUALS[l.key]?.color ?? '#888'
              const note =
                st === 'loading' ? '…' :
                st === 'missing' ? 'not cached' :
                st === 'error'   ? 'err' :
                !l.cached        ? 'not cached' : ''
              return (
                <li key={l.key} className={`layer-row ${enabledLayers[l.key] ? 'on' : ''}`}>
                  <label>
                    <input
                      type="checkbox"
                      checked={!!enabledLayers[l.key]}
                      onChange={() => toggleLayer(l.key)}
                      disabled={!l.cached}
                    />
                    <span className="layer-dot" style={{ background: dotColor }} />
                    <span className="layer-name">{l.name}</span>
                  </label>
                  <span className="layer-note">{note}</span>
                </li>
              )
            })}
          </ul>
          {layers.some(l => !l.cached) && (
            <div className="ingest-hint">
              Run <code>python -m src.cli ingest --all</code> in
              <br/><code>phase7-datacenter-siting/</code> to enable overlays.
            </div>
          )}
        </section>

        <section className="siting-block">
          <div className="siting-block-head">
            <span>WEIGHTS · {archetype}</span>
            <button className="link-btn" onClick={resetWeights}>reset</button>
          </div>
          <div className="weight-list">
            {factorList.map(f => {
              const base = baseWeights[f] ?? 0
              const cur = weightOverrides[f] ?? base
              return (
                <div key={f} className="weight-row">
                  <div className="weight-row-head">
                    <span className="factor-name">{f}</span>
                    <span className="factor-val">{(cur * 100).toFixed(0)}</span>
                  </div>
                  <input
                    type="range" min={0} max={0.30} step={0.01}
                    value={cur}
                    onChange={(e) => setWeight(f, parseFloat(e.target.value))}
                  />
                </div>
              )
            })}
          </div>
          <button className="primary-btn" onClick={rescoreAll} disabled={scoring}>
            {scoring ? 'SCORING…' : 'RESCORE'}
          </button>
        </section>

        {error && <div className="siting-err">{error}</div>}
      </aside>

      {/* ── Map ── */}
      <div className="siting-mapwrap">
        <div ref={mapDivRef} className="siting-map" />
        <div className="map-toolbar">
          <button onClick={fitToSites}>FIT</button>
          <span className="bbox-readout">
            {bbox && `${bbox[1].toFixed(2)}°N ${bbox[0].toFixed(2)}°E → ${bbox[3].toFixed(2)}°N ${bbox[2].toFixed(2)}°E`}
          </span>
        </div>
        {selected && (
          <div className="site-detail">
            <div className="detail-head">
              <span className="detail-id">{selected.site_id}</span>
              <span
                className="detail-score"
                style={{ color: colorForScore(selected.composite, Object.values(selected.kill_flags).some(Boolean)) }}
              >{selected.composite.toFixed(2)}</span>
              <button className="link-btn" onClick={() => setSelectedId(null)}>×</button>
            </div>
            <div className="detail-meta">
              {selected.lat.toFixed(4)}°, {selected.lon.toFixed(4)}°
              {Object.entries(selected.kill_flags).filter(([, v]) => v).map(([k]) => (
                <span key={k} className="kill-tag">KILL: {k}</span>
              ))}
            </div>
            <table className="detail-tbl">
              <thead><tr><th>factor</th><th>raw</th><th>norm</th><th>w</th><th>·w</th></tr></thead>
              <tbody>
                {Object.entries(selected.factors)
                  .sort((a, b) => b[1].weighted - a[1].weighted)
                  .map(([k, f]) => (
                    <tr key={k} className={f.killed ? 'killed' : ''}>
                      <td>{k}</td>
                      <td>{f.raw_value == null ? '—' : Number(f.raw_value).toFixed(2)}</td>
                      <td>{(f.normalized * 100).toFixed(0)}</td>
                      <td>{(f.weight * 100).toFixed(0)}</td>
                      <td>{(f.weighted * 100).toFixed(1)}</td>
                    </tr>
                  ))}
              </tbody>
            </table>
            {selected.imputed.length > 0 && (
              <div className="imputed-note">imputed (cohort median): {selected.imputed.join(', ')}</div>
            )}
          </div>
        )}
      </div>

      {/* ── Right rail: ranked list ── */}
      <aside className="siting-rank">
        <div className="siting-side-head">
          <span className="siting-title">RANKED · {ranked.length}</span>
          <span className="siting-sub">{archetype}</span>
        </div>
        <ol className="rank-list">
          {ranked.map((s, i) => {
            const killed = Object.values(s.kill_flags).some(Boolean)
            return (
              <li
                key={s.site_id}
                className={`rank-row ${selectedId === s.site_id ? 'sel' : ''} ${killed ? 'killed' : ''}`}
                onClick={() => flyTo(s)}
              >
                <span className="rank-idx">{i + 1}</span>
                <span className="rank-id">{s.site_id}</span>
                <span
                  className="rank-score"
                  style={{ color: colorForScore(s.composite, killed) }}
                >{s.composite.toFixed(2)}</span>
              </li>
            )
          })}
        </ol>
      </aside>
    </div>
  )
}
