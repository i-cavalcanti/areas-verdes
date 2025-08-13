# -*- coding: utf-8 -*-
import re
import geopandas as gpd
from shapely.geometry import mapping
from shapely.ops import unary_union
try:
    from shapely import make_valid  # shapely >= 2.0
except Exception:
    make_valid = None

import folium
from folium import GeoJson
from folium.plugins import MarkerCluster

# ---------- helpers ----------

def to_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Ensure EPSG:4326 (WGS84 lon/lat)."""
    if gdf.crs is None:
        raise ValueError("Layer has no CRS set. Define it before reprojecting.")
    return gdf.to_crs(epsg=4326) if gdf.crs.to_epsg() != 4326 else gdf

def fix_valid(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Repair invalid geometries."""
    if make_valid is not None:
        gdf["geometry"] = gdf.geometry.apply(make_valid)
    else:
        # classic fallback: buffer(0)
        gdf["geometry"] = gdf.buffer(0)
    return gdf

def read_fix(path: str) -> gpd.GeoDataFrame:
    """Read a vector file and normalize: valid + WGS84 + drop Z/M."""
    gdf = gpd.read_file(path)
    gdf = fix_valid(gdf)
    gdf = to_wgs84(gdf)
    # drop Z/M by rewriting coords via GeoJSON mapping (works for most cases)
    gdf["geometry"] = gdf.geometry.apply(lambda geom: gpd.GeoSeries.from_wkt([geom.wkt])[0])
    return gdf

def year_from_path(path: str) -> int | None:
    m = re.search(r"(19|20)\d{2}", path)
    return int(m.group(0)) if m else None

def bounds_of_layers(layers: list[gpd.GeoDataFrame]) -> list[list[float]]:
    """Return [[min_lat, min_lon], [max_lat, max_lon]] for fit_bounds."""
    if not layers:
        raise ValueError("No layers to compute bounds.")
    xs, ys = [], []
    for g in layers:
        if g is None or g.empty:
            continue
        minx, miny, maxx, maxy = g.total_bounds
        xs += [minx, maxx]; ys += [miny, maxy]
    if not xs:
        # fallback to something sane
        return [[-23.3, -47.2], [-23.0, -46.7]]
    return [[min(ys), min(xs)], [max(ys), max(xs)]]  # lat, lon ordering

# ---------- 1) Jundiaí polygon (always on, drawn first) ----------

poly_path = r"d:/Users/ivan.cavalcanti/Documents/Projects/mapeando_cep/data/SP_Municipios_2024/SP_Municipios_2024.shp"
poly = read_fix(poly_path)

# Filter municipality by name
mun = poly[poly["NM_MUN"] == "Jundiaí"].copy()
if mun.empty:
    raise ValueError("Municipality 'Jundiaí' not found in NM_MUN.")

# Dissolve to a single footprint (optional, makes the halo cleaner)
mun = mun.dissolve()  # one row / multi-geom
miny, minx, maxy, maxx = mun.total_bounds
center = [(miny + maxy) / 2, (minx + maxx) / 2]

# Create map with satellite base
m = folium.Map(location=center, zoom_start=12, tiles=None)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="&copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    name="Esri World Imagery",
    overlay=False,
    control=False,
).add_to(m)

# Create custom panes to keep municipality highlight above other layers
folium.map.CustomPane("mun_halo", z_index=650).add_to(m)
folium.map.CustomPane("mun_line", z_index=651).add_to(m)

# Halo (thick dark outline, no fill)
GeoJson(
    data=mun.__geo_interface__,
    name=None,  # no LayerControl entry
    style_function=lambda f: {
        "color": "#000000",
        "weight": 8,
        "opacity": 0.25,
        "fillOpacity": 0.0,
    },
    pane="mun_halo",
    highlight_function=lambda f: {"weight": 8, "opacity": 0.35},
    tooltip="Município de Jundiaí",
).add_to(m)

# Line + light fill (gold dashed)
GeoJson(
    data=mun.__geo_interface__,
    name=None,
    style_function=lambda f: {
        "color": "#FFD700",
        "weight": 3,
        "dashArray": "6,4",
        "fillColor": "#FFF59D",
        "fillOpacity": 0.15,
    },
    pane="mun_line",
    highlight_function=lambda f: {"color": "#FFC107", "weight": 4},
    tooltip="Município de Jundiaí",
).add_to(m)

# ---------- 2) Urban layers by year (only soil_use == 'urbano') ----------

files = [
    "./data/soil_use_2000.shp",
    "./data/soil_use_2010.shp",
    "./data/soil_use_2023.shp",
]

def load_urban_layer(path: str) -> tuple[str, gpd.GeoDataFrame] | None:
    g = read_fix(path)
    # Ensure attributes
    if "soil_use" not in g.columns:
        g["soil_use"] = "urbano"
    yr = g["year"].iloc[0] if "year" in g.columns and g["year"].notna().any() else year_from_path(path)
    g["year"] = int(yr) if yr is not None else None
    # Keep only urban
    g = g[g["soil_use"].astype(str).str.lower() == "urbano"].copy()
    if g.empty:
        return None
    return str(g["year"].iloc[0]), g

loaded = [load_urban_layer(p) for p in files]
loaded = [x for x in loaded if x is not None]

# Order by year (old -> new)
loaded.sort(key=lambda t: int(t[0]))

# Colors by year (customize freely)
YEAR_COLS = {
    "2000": "#e3d917",
    "2010": "#e32f17",
    "2023": "#62130a",
}

urban_layers = []
for yr, g in loaded:
    color = YEAR_COLS.get(yr, "#333333")
    # Show only the latest by default
    show_flag = (yr == loaded[-1][0])
    gj = GeoJson(
        data=g.__geo_interface__,
        name=yr,           # appears in LayerControl
        overlay=True,
        show=show_flag,
        style_function=lambda f, c=color: {
            "color": c,
            "fillColor": c,
            "fillOpacity": 0.5,
            "weight": 1,
        },
        highlight_function=lambda f: {"weight": 2},
        tooltip=folium.GeoJsonTooltip(
            fields=["year"],
            aliases=["Ano:"],
            sticky=False,
        ),
    )
    gj.add_to(m)
    urban_layers.append(g)

# Legend (simple HTML block)
legend_html = """
<div style="
  position: fixed; bottom: 20px; right: 20px; z-index: 9999;
  background: rgba(255,255,255,0.9); padding: 8px 10px; border-radius: 6px;
  box-shadow: 0 0 8px rgba(0,0,0,0.2); font-size: 13px;
">
  <div style="font-weight:600; margin-bottom:4px;">Urbano por ano</div>
  <div><span style="display:inline-block;width:12px;height:12px;background:#e3d917;margin-right:6px;border:1px solid #666"></span>2000</div>
  <div><span style="display:inline-block;width:12px;height:12px;background:#e32f17;margin-right:6px;border:1px solid #666"></span>2010</div>
  <div><span style="display:inline-block;width:12px;height:12px;background:#62130a;margin-right:6px;border:1px solid #666"></span>2023</div>
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

# Layer control
folium.LayerControl(collapsed=False).add_to(m)

# Fit bounds to all urban layers (fallback to municipality)
all_for_bounds = [g for g in urban_layers if not g.empty] or [mun]
m.fit_bounds(bounds_of_layers(all_for_bounds))

# ---------- 3) Parks as pins (clustered) ----------

# Read parks (adjust path). If you need Latin-1 to UTF-8 fix, uncomment the encoding block below.
parks_path = r"d:/Users/ivan.cavalcanti/Documents/Projects/areas-verdes/data/Geojundiai/L_8683-2016_m13_parques-municipais.shp"
parques = read_fix(parks_path)

# Ensure 'nome' exists; if not, pick a best-effort name column
if "nome" not in parques.columns:
    for cand in ["NOME", "Name", "name", "NM_PARQUE", "NM", "TITULO"]:
        if cand in parques.columns:
            parques["nome"] = parques[cand]
            break
    if "nome" not in parques.columns:
        parques["nome"] = "Parque"

# (Optional) Fix Latin-1 -> UTF-8 for labels
try:
    parques["nome"] = (
        parques["nome"]
        .astype(str)
        .str.encode("latin1", errors="ignore")
        .str.decode("utf-8", errors="ignore")
    )
except Exception:
    pass

# FeatureGroup + MarkerCluster so we can toggle the whole "Parques" layer
fg_parks = folium.FeatureGroup(name="Parques", show=True)
mc = MarkerCluster().add_to(fg_parks)

icon = folium.Icon(color="green", icon="tree", prefix="fa")  # FA "tree" pin
for _, row in parques.iterrows():
    geom = row.geometry
    if geom is None or geom.is_empty:
        continue
    # Handle POINT or centroid of non-points just in case
    pt = geom
    if geom.geom_type != "Point":
        pt = geom.centroid
    folium.Marker(
        location=[pt.y, pt.x],
        tooltip=str(row.get("nome", "")),
        popup=str(row.get("nome", "")),
        icon=icon,
    ).add_to(mc)

fg_parks.add_to(m)

# ---------- 4) Save (works on GitHub Pages) ----------
m.save("index.html")
print("Saved: index.html")
