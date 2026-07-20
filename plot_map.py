# three_year_map.py
import re, json
import geopandas as gpd
import folium
from folium import FeatureGroup, GeoJson
from folium.plugins import MarkerCluster
from shapely.ops import unary_union

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
CRS_PROJ  = 31983  # SIRGAS 2000 UTM 23S

LBL_2000     = "Área urbana 2000 (Mapbiomas)"
LBL_EXP_0010 = "Espraiamento urbano 2000-2010 (Mapbiomas)"
LBL_EXP_1022 = "Espraiamento urbano 2010-2022 (Mapbiomas)"

EXP_COLS = {
    LBL_2000:     "#9ca3af",  # cinza – mancha base 2000
    LBL_EXP_0010: "#f59e0b",  # laranja – expansão 2000-2010
    LBL_EXP_1022: "#ef4444",  # vermelho – expansão 2010-2023
}

# -------- load layers --------
g2000, y2000 = load_urban_layer(PATH_2000)
g2010, _     = load_urban_layer(PATH_2010)
g2023, _     = load_urban_layer(PATH_2023)

# -------- expansão urbana (diferença geométrica) --------
def urban_diff(g_new: gpd.GeoDataFrame, g_old: gpd.GeoDataFrame, label: str) -> gpd.GeoDataFrame:
    new_u = unary_union(g_new.to_crs(CRS_PROJ).geometry)
    old_u = unary_union(g_old.to_crs(CRS_PROJ).geometry)
    diff  = new_u.difference(old_u)
    gdf   = gpd.GeoDataFrame(geometry=[diff], crs=CRS_PROJ).to_crs(4326)
    gdf   = gdf.explode(index_parts=False, ignore_index=True)
    gdf["periodo"] = label
    return gdf

exp_2000_2010 = urban_diff(g2010, g2000, LBL_EXP_0010)
exp_2010_2023 = urban_diff(g2023, g2010, LBL_EXP_1022)

# combined bounds (usando a mancha 2000 + expansões)
all_bounds = [g2000.total_bounds, exp_2000_2010.total_bounds, exp_2010_2023.total_bounds]
minx = min(b[0] for b in all_bounds)
miny = min(b[1] for b in all_bounds)
maxx = max(b[2] for b in all_bounds)
maxy = max(b[3] for b in all_bounds)
center = [(miny + maxy) / 2, (minx + maxx) / 2]  # [lat, lon]

# -------- map --------
m = folium.Map(location=center, zoom_start=12, tiles=None)

# base layers WITH names (so LayerControl shows)
folium.TileLayer("OpenStreetMap", name="OSM", overlay=False, control=True).add_to(m)
folium.TileLayer("CartoDB positron", name="Carto Positron", overlay=False, control=True).add_to(m)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri, Maxar, Earthstar Geographics",
    name="Satélite (Esri)",
    overlay=False, control=True
).add_to(m)


def add_layer(gdf: gpd.GeoDataFrame, label: str, tooltip_field: str, show: bool):
    color = EXP_COLS.get(label, "#333333")
    fg = FeatureGroup(name=label, show=show)
    GeoJson(
        data=json.loads(gdf.to_json()),
        name=None,
        style_function=lambda f, c=color: {
            "color": c, "fillColor": c, "fillOpacity": 0.5, "weight": 1
        },
        highlight_function=lambda f: {"weight": 2},
        tooltip=folium.GeoJsonTooltip(fields=[tooltip_field], aliases=["Período:"]),
    ).add_to(fg)
    fg.add_to(m)

# camada base: mancha urbana 2000
add_layer(g2000, LBL_2000, "year", show=True)
# variações de expansão
add_layer(exp_2000_2010, LBL_EXP_0010, "periodo", show=True)
add_layer(exp_2010_2023, LBL_EXP_1022, "periodo", show=True)

def add_polygon_layer(path: str, name: str, fill_color: str, line_color: str,
                      tooltip_col: str | None = None, show: bool = True):
    gdf = gpd.read_file(path)
    gdf = fix_valid(gdf)
    gdf = to_wgs84(gdf)
    fg  = FeatureGroup(name=name, show=show)
    tt  = folium.GeoJsonTooltip(fields=[tooltip_col]) if tooltip_col and tooltip_col in gdf.columns else None
    GeoJson(
        data=json.loads(gdf.to_json()),
        name=None,
        style_function=lambda f, fc=fill_color, lc=line_color: {
            "fillColor": fc, "color": lc, "weight": 1, "fillOpacity": 0.6
        },
        highlight_function=lambda f: {"weight": 2, "fillOpacity": 0.8},
        tooltip=tt,
    ).add_to(fg)
    fg.add_to(m)

BASE = "./data/green_jundiai"
GEO  = "./data/Geojundiai"

# -------- parques e praças (OSM) --------
add_polygon_layer(f"{BASE}/equipamentos_verdes_jundiai.shp", "Parques e praças (OSM)", "#16a34a", "#14532d", tooltip_col="name")

# -------- remanescente de vegetação (prefeitura) --------
add_polygon_layer(f"{GEO}/L_Remanescente_Vegetacao.shp",     "Remanescente Vegetação (prefeitura)",        "#a3e635", "#4d7c0f")
add_polygon_layer(f"{GEO}/L_8683-2016_m03_rem-veg-nat.shp", "Remanescente Vegetação Nativa (prefeitura)", "#65a30d", "#365314")

# -------- zoneamento municipal (prefeitura) --------
zon = gpd.read_file(f"{GEO}/L_7858-2012-zoneamento.shp")
zon = fix_valid(zon)
zon = to_wgs84(zon)

def add_zon_layer(macr_val: str, name: str, fill_color: str, line_color: str):
    gdf = zon[zon["l7858_macr"] == macr_val].copy()
    if gdf.empty:
        return
    fg = FeatureGroup(name=name, show=True)
    GeoJson(
        data=json.loads(gdf.to_json()),
        name=None,
        style_function=lambda f, fc=fill_color, lc=line_color: {
            "fillColor": fc, "color": lc, "weight": 1, "fillOpacity": 0.55
        },
        highlight_function=lambda f: {"weight": 2, "fillOpacity": 0.8},
        tooltip=folium.GeoJsonTooltip(fields=["l7858_macr"], aliases=["Categoria:"]),
    ).add_to(fg)
    fg.add_to(m)

add_zon_layer("Reserva Biológica",                    "Reserva Biológica (prefeitura)",          "#7c3aed", "#4c1d95")
add_zon_layer("Zona de Conservacao Rural",             "Zona de Conservação Rural (prefeitura)",  "#b45309", "#78350f")
add_zon_layer("Território de Gestão da Serra do Japi", "Território de Gestão da Serra do Japi (prefeitura)","#0891b2", "#164e63")

# -------- vegetação e hidrografia (Mapbiomas 2022) --------
add_polygon_layer(
    "./data/veg_urbana/formacao_florestal_2022.gpkg",
    "Vegetação (Mapbiomas)",
    fill_color="#1f8d49", line_color="#14532d"
)
add_polygon_layer(
    "./data/veg_urbana/rios_lagos_alagados_2022.gpkg",
    "Rios, lagos e alagados (Mapbiomas)",
    fill_color="#2532e4", line_color="#1e3a8a"
)



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