import re
import geopandas as gpd
from shapely.geometry import Point
try:
    from shapely import make_valid
except Exception:
    make_valid = None

import folium
from folium import GeoJson, FeatureGroup
from folium.plugins import MarkerCluster

# --- helpers ---
def fix_valid(gdf):
    if make_valid is not None:
        gdf["geometry"] = gdf.geometry.apply(make_valid)
    else:
        gdf["geometry"] = gdf.buffer(0)
    return gdf

def to_wgs84(gdf):
    if gdf.crs is None:
        raise ValueError("Layer has no CRS. Set the correct CRS before reprojecting.")
    return gdf.to_crs(epsg=4326) if gdf.crs.to_epsg() != 4326 else gdf

def read_fix(path):
    g = gpd.read_file(path)
    g = fix_valid(g)
    g = to_wgs84(g)
    return g

def year_from_path(path):
    m = re.search(r"(19|20)\d{2}", path)
    return int(m.group(0)) if m else None

# --- 1) Jundiaí (always on, drawn first) ---
poly_path = r"d:/Users/ivan.cavalcanti/Documents/Projects/mapeando_cep/data/SP_Municipios_2024/SP_Municipios_2024.shp"
poly = read_fix(poly_path)
mun = poly[poly["NM_MUN"] == "Jundiaí"].copy()
if mun.empty:
    raise ValueError("Municipality 'Jundiaí' not found in NM_MUN.")
mun = mun.dissolve()

# Correct center: total_bounds returns (minx, miny, maxx, maxy)
minx, miny, maxx, maxy = mun.total_bounds
center = [(miny + maxy) / 2, (minx + maxx) / 2]  # [lat, lon]

m = folium.Map(location=center, zoom_start=12, tiles=None)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="&copy; Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    name="Esri World Imagery",
    overlay=False,
    control=False,
).add_to(m)

# Jundiaí halo + outline (no group -> always visible)
folium.map.CustomPane("mun_halo", z_index=650).add_to(m)
folium.map.CustomPane("mun_line", z_index=651).add_to(m)

GeoJson(
    mun.__geo_interface__,
    name=None,
    pane="mun_halo",
    style_function=lambda f: {"color": "#000", "weight": 8, "opacity": 0.25, "fillOpacity": 0},
    tooltip="Município de Jundiaí",
).add_to(m)

GeoJson(
    mun.__geo_interface__,
    name=None,
    pane="mun_line",
    style_function=lambda f: {
        "color": "#FFD700",
        "weight": 3,
        "dashArray": "6,4",
        "fillColor": "#FFF59D",
        "fillOpacity": 0.15,
    },
    tooltip="Município de Jundiaí",
).add_to(m)

# --- 2) Urban layers by year (FeatureGroup per year) ---
files = ["./data/soil_use_2000.shp", "./data/soil_use_2010.shp", "./data/soil_use_2023.shp"]
YEAR_COLS = {"2000": "#e3d917", "2010": "#e32f17", "2023": "#62130a"}

year_groups = []
for path in files:
    try:
        g = read_fix(path)
    except Exception:
        continue
    # ensure columns
    if "soil_use" not in g.columns:
        g["soil_use"] = "urbano"
    if "year" not in g.columns or g["year"].isna().all():
        g["year"] = year_from_path(path)
    # keep only urbano
    g = g[g["soil_use"].astype(str).str.lower() == "urbano"].copy()
    if g.empty:
        continue

    year_str = str(int(g["year"].iloc[0]))
    color = YEAR_COLS.get(year_str, "#333333")

    fg = FeatureGroup(name=year_str, show=False)  # will show latest after loop
    GeoJson(
        g.__geo_interface__,
        name=None,  # inside the group; group has the name
        style_function=lambda f, c=color: {"color": c, "fillColor": c, "fillOpacity": 0.5, "weight": 1},
        highlight_function=lambda f: {"weight": 2},
        tooltip=folium.GeoJsonTooltip(fields=["year"], aliases=["Ano:"]),
    ).add_to(fg)
    fg.add_to(m)
    year_groups.append((year_str, g, fg))

# show only the latest year by default
if year_groups:
    latest = sorted(year_groups, key=lambda t: int(t[0]))[-1][2]
    latest.show = True

# --- 3) Parks as pins (FeatureGroup -> appears in control) ---
parks_path = r"d:/Users/ivan.cavalcanti/Documents/Projects/areas-verdes/data/Geojundiai/L_8683-2016_m13_parques-municipais.shp"
try:
    parques = read_fix(parks_path)
except Exception:
    parques = gpd.GeoDataFrame(geometry=[], crs="EPSG:4326")

if not parques.empty:
    if "nome" not in parques.columns:
        for cand in ["NOME", "Name", "nome", "NM_PARQUE", "NM", "TITULO"]:
            if cand in parques.columns:
                parques["nome"] = parques[cand]
                break
        if "nome" not in parques.columns:
            parques["nome"] = "Parque"

    fg_parks = FeatureGroup(name="Parques", show=True)
    mc = MarkerCluster().add_to(fg_parks)
    icon = folium.Icon(color="green", icon="tree", prefix="fa")
    for _, row in parques.iterrows():
        geom = row.geometry
        if geom is None or geom.is_empty:
            continue
        pt = geom if geom.geom_type == "Point" else geom.centroid
        folium.Marker(
            location=[pt.y, pt.x],
            tooltip=str(row.get("nome", "")),
            popup=str(row.get("nome", "")),
            icon=icon,
        ).add_to(mc)
    fg_parks.add_to(m)

# --- 4) Layer control & fit bounds ---
folium.LayerControl(collapsed=False).add_to(m)

# Fit to municipality (safe), or to union of urban layers if you prefer
m.fit_bounds([[miny, minx], [maxy, maxx]])

# Save where GitHub Pages expects (root or /docs)
m.save("./docs/index.html")
print("Saved index.html")