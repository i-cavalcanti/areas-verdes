# three_year_map.py
import re, json
import geopandas as gpd
import folium
from folium import FeatureGroup, GeoJson
from folium.plugins import MarkerCluster

try:
    from shapely import make_valid  # shapely >= 2.0
except Exception:
    make_valid = None

# -------- helpers --------
def fix_valid(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if make_valid is not None:
        gdf["geometry"] = gdf.geometry.apply(make_valid)
    else:
        gdf["geometry"] = gdf.buffer(0)
    return gdf

def to_wgs84(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    if gdf.crs is None:
        raise ValueError("CRS is missing. Set it on the shapefile before reprojecting.")
    return gdf.to_crs(4326) if gdf.crs.to_epsg() != 4326 else gdf

def year_from_path(path: str):
    m = re.search(r"(19|20)\d{2}", path)
    return int(m.group(0)) if m else None

def load_urban_layer(path: str) -> tuple[gpd.GeoDataFrame, str]:
    g = gpd.read_file(path)
    g = fix_valid(g)
    g = to_wgs84(g)

    if "soil_use" not in g.columns:
        g["soil_use"] = "urbano"

    yr = None
    if "year" in g.columns and g["year"].notna().any():
        try:
            yr = int(g["year"].iloc[0])
        except Exception:
            pass
    if yr is None:
        yr = year_from_path(path)
    if yr is None:
        raise ValueError(f"Could not determine year for {path}")
    g["year"] = int(yr)

    g = g[g["soil_use"].astype(str).str.lower().eq("urbano")].copy()
    if g.empty:
        raise ValueError(f"No 'urbano' features in {path}")

    return g, str(yr)

# -------- config --------
PATH_2000 = "./data/soil_use_2000.shp"
PATH_2010 = "./data/soil_use_2010.shp"
PATH_2023 = "./data/soil_use_2023.shp"
YEAR_COLS = {"2000": "#e3d917", "2010": "#e32f17", "2023": "#62130a"}

# -------- load layers --------
g2000, y2000 = load_urban_layer(PATH_2000)
g2010, y2010 = load_urban_layer(PATH_2010)
g2023, y2023 = load_urban_layer(PATH_2023)

# combined bounds
minx = min(g2000.total_bounds[0], g2010.total_bounds[0], g2023.total_bounds[0])
miny = min(g2000.total_bounds[1], g2010.total_bounds[1], g2023.total_bounds[1])
maxx = max(g2000.total_bounds[2], g2010.total_bounds[2], g2023.total_bounds[2])
maxy = max(g2000.total_bounds[3], g2010.total_bounds[3], g2023.total_bounds[3])
center = [(miny + maxy) / 2, (minx + maxx) / 2]  # [lat, lon]

# -------- map --------
m = folium.Map(location=center, zoom_start=12, tiles=None)

# base layers WITH names (so LayerControl shows)
folium.TileLayer("OpenStreetMap", name="OSM", overlay=False, control=True).add_to(m)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri, Maxar, Earthstar Geographics",
    name="Satélite (Esri)",
    overlay=False, control=True
).add_to(m)


def add_year_layer(gdf: gpd.GeoDataFrame, year_str: str, show: bool):
    fg = FeatureGroup(name=year_str, show=show)
    GeoJson(
        data=json.loads(gdf.to_json()),
        name=None,
        style_function=lambda f, c=YEAR_COLS.get(year_str, "#333333"): {
            "color": c, "fillColor": c, "fillOpacity": 0.5, "weight": 1
        },
        highlight_function=lambda f: {"weight": 2},
        tooltip=folium.GeoJsonTooltip(fields=["year"], aliases=["Ano:"]),
    ).add_to(fg)
    fg.add_to(m)

# add overlays (show only latest by default)
add_year_layer(g2023, y2023, show=True)
add_year_layer(g2010, y2010, show=True)
add_year_layer(g2000, y2000, show=True)

PARKS_PATH = r"d:/Users/ivan.cavalcanti/Documents/Projects/areas-verdes/data/Geojundiai/L_8683-2016_m13_parques-municipais.shp"  # <-- change to your file

parques = gpd.read_file(PARKS_PATH)
parques = fix_valid(parques)
parques = to_wgs84(parques)

fg_parks = FeatureGroup(name="Parques", show=True)
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
    ).add_to(fg_parks)

fg_parks.add_to(m)



mun = gpd.read_file(r"d:/Users/ivan.cavalcanti/Documents/Projects/mapeando_cep/data/SP_Municipios_2024/SP_Municipios_2024.shp")
mun = fix_valid(mun)
mun = to_wgs84(mun)
mun = mun[mun["NM_MUN"] == "Jundiaí"].copy()
mun = mun.dissolve()  # single footprint
folium.map.CustomPane("mun_halo", z_index=580).add_to(m)
folium.map.CustomPane("mun_line", z_index=590).add_to(m)

# make panes non-interactive so they don't steal hover/clicks
m.get_root().html.add_child(folium.Element("""
<style>
.mun_halo-pane, .mun_line-pane { pointer-events: none; }
</style>
"""))

# halo (no control entry)
folium.GeoJson(
    data=json.loads(mun.to_json()),
    name=None,
    control=False,              # <-- keep OUT of LayerControl
    pane="mun_halo",
    style_function=lambda f: {"color": "#000000", "weight": 8, "opacity": 0.25, "fillOpacity": 0.0},
).add_to(m)

# outline + soft fill (no control entry)
folium.GeoJson(
    data=json.loads(mun.to_json()),
    name=None,
    control=False,              # <-- keep OUT of LayerControl
    pane="mun_line",
    style_function=lambda f: {
        "color": "#FFD700", "weight": 3, "dashArray": "6,4",
        "fillColor": "#FFF59D", "fillOpacity": 0.15
    },
).add_to(m)




# control + bounds
folium.LayerControl(position="topright", collapsed=False).add_to(m)
m.fit_bounds([[miny, minx], [maxy, maxx]])

# Save where GitHub Pages expects (root or /docs)
m.save("./docs/index.html")
print("Saved index.html")