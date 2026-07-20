# plot_map_2.py
import re, json
import numpy as np
import geopandas as gpd
import rasterio
from rasterio.mask import mask as rio_mask
from rasterio.features import shapes
from shapely.geometry import shape
from shapely.ops import unary_union
import folium
from folium import FeatureGroup, GeoJson

try:
    from shapely import make_valid
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
        raise ValueError("CRS is missing.")
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
LIMITE    = "./data/green_jundiai/limite_municipal_jundiai.shp"
TIF_DIR   = r"D:\Arq-Azzoni\UrbanSprawl\Bases_dados\Vegetacao_mapbiomas"
MUN_SHP   = r"d:/Users/ivan.cavalcanti/Documents/Projects/mapeando_cep/data/SP_Municipios_2024/SP_Municipios_2024.shp"
CRS_PROJ  = 31983

# Mapbiomas class values used as vegetation proxy
# 3=Formação Florestal, 15=Pastagem, 21=Mosaico de Usos, 41=Outras Lavouras Temp.
VEG_VALORES = [3, 15, 21, 41]

# -------- load urban layers --------
print("Carregando manchas urbanas...")
g2000, _ = load_urban_layer(PATH_2000)
g2010, _ = load_urban_layer(PATH_2010)
g2023, _ = load_urban_layer(PATH_2023)

# -------- urban expansion diffs --------
def urban_diff(g_new: gpd.GeoDataFrame, g_old: gpd.GeoDataFrame, label: str) -> gpd.GeoDataFrame:
    new_u = unary_union(g_new.to_crs(CRS_PROJ).geometry)
    old_u = unary_union(g_old.to_crs(CRS_PROJ).geometry)
    diff  = new_u.difference(old_u)
    gdf   = gpd.GeoDataFrame(geometry=[diff], crs=CRS_PROJ).to_crs(4326)
    gdf   = gdf.explode(index_parts=False, ignore_index=True)
    gdf["periodo"] = label
    return gdf

LBL_URB_2000  = "Área urbana 2000 (Mapbiomas)"
LBL_ESP_0010  = "Espraiamento urbano 2000-2010 (Mapbiomas)"
LBL_ESP_1022  = "Espraiamento urbano 2010-2022 (Mapbiomas)"

print("Calculando espraiamento urbano...")
exp_2000_2010 = urban_diff(g2010, g2000, LBL_ESP_0010)
exp_2010_2023 = urban_diff(g2023, g2010, LBL_ESP_1022)

# -------- extract vegetation from raster --------
limite = gpd.read_file(LIMITE).to_crs(4326)

def extrair_vegetacao(ano: int) -> gpd.GeoDataFrame:
    tif = f"{TIF_DIR}/mapbiomas_urbano_sp_{ano}.tif"
    with rasterio.open(tif) as src:
        lim_proj  = limite.to_crs(src.crs)
        geom_mask = [lim_proj.union_all().__geo_interface__]
        arr, transform = rio_mask(src, geom_mask, crop=True, filled=True, nodata=0)
        arr = arr[0].astype(np.uint16)
        crs = src.crs

    mask_bin = np.isin(arr, VEG_VALORES).astype(np.uint8)
    if mask_bin.sum() == 0:
        return gpd.GeoDataFrame(geometry=[], crs=crs).to_crs(4326)

    geoms = [shape(g) for g, _ in shapes(mask_bin, mask=mask_bin, transform=transform)]
    gdf = gpd.GeoDataFrame(geometry=geoms, crs=crs).to_crs(4326)
    gdf = (
        gdf.to_crs(CRS_PROJ)
           .dissolve()
           .to_crs(4326)
           .explode(index_parts=False, ignore_index=True)
    )
    return gdf

print("Extraindo vegetação 2000...")
veg_2000 = extrair_vegetacao(2000)
print("Extraindo vegetação 2010...")
veg_2010 = extrair_vegetacao(2010)
print("Extraindo vegetação 2023 (base para 2022)...")
veg_2023 = extrair_vegetacao(2023)

# -------- vegetation variation (loss per period) --------
def veg_variacao(veg_old: gpd.GeoDataFrame, veg_new: gpd.GeoDataFrame, label: str) -> gpd.GeoDataFrame:
    """Areas with vegetation in veg_old that were lost by veg_new."""
    if veg_old.empty or veg_new.empty:
        return gpd.GeoDataFrame(geometry=[], crs=4326)
    old_u = unary_union(veg_old.to_crs(CRS_PROJ).geometry)
    new_u = unary_union(veg_new.to_crs(CRS_PROJ).geometry)
    loss  = old_u.difference(new_u)
    gdf   = gpd.GeoDataFrame(geometry=[loss], crs=CRS_PROJ).to_crs(4326)
    gdf   = gdf.explode(index_parts=False, ignore_index=True)
    gdf["periodo"] = label
    return gdf

LBL_VEG_2000   = "Vegetação 2000 (Mapbiomas)"
LBL_VEGV_0010  = "Variação vegetação 2000-2010 (Mapbiomas)"
LBL_VEGV_1022  = "Variação vegetação 2010-2022 (Mapbiomas)"

print("Calculando variação vegetação 2000-2010...")
veg_var_0010 = veg_variacao(veg_2000, veg_2010, LBL_VEGV_0010)
print("Calculando variação vegetação 2010-2022...")
veg_var_1022 = veg_variacao(veg_2010, veg_2023, LBL_VEGV_1022)

# -------- bounds (from urban layers) --------
all_bounds = [g2000.total_bounds, exp_2000_2010.total_bounds, exp_2010_2023.total_bounds]
minx = min(b[0] for b in all_bounds)
miny = min(b[1] for b in all_bounds)
maxx = max(b[2] for b in all_bounds)
maxy = max(b[3] for b in all_bounds)

# -------- build map --------
centro = limite.geometry.union_all().centroid
m = folium.Map(location=[centro.y, centro.x], zoom_start=12, tiles=None)

# base tiles
folium.TileLayer("OpenStreetMap", name="OSM", overlay=False, control=True).add_to(m)
folium.TileLayer("CartoDB positron", name="Carto Positron", overlay=False, control=True).add_to(m)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri, Maxar, Earthstar Geographics",
    name="Satélite (Esri)",
    overlay=False, control=True,
).add_to(m)

# -------- layer styles --------
URBAN_STYLE = {
    LBL_URB_2000: "#9ca3af",   # cinza
    LBL_ESP_0010: "#f59e0b",   # laranja
    LBL_ESP_1022: "#ef4444",   # vermelho
}

VEG_STYLE = {
    LBL_VEG_2000:  {"fill": "#86efac", "line": "#166534"},  # verde claro – baseline
    LBL_VEGV_0010: {"fill": "#fde68a", "line": "#b45309"},  # âmbar – perda 2000-2010
    LBL_VEGV_1022: {"fill": "#fca5a5", "line": "#991b1b"},  # rosa/vermelho – perda 2010-2022
}

def add_urban_layer(gdf: gpd.GeoDataFrame, label: str, tooltip_field: str, show: bool = True):
    color = URBAN_STYLE[label]
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

def add_veg_layer(gdf: gpd.GeoDataFrame, label: str, tooltip_field: str | None = None, show: bool = True):
    if gdf.empty:
        print(f"  [aviso] camada vazia: {label}")
        return
    cv = VEG_STYLE[label]
    fg = FeatureGroup(name=label, show=show)
    tt = (
        folium.GeoJsonTooltip(fields=[tooltip_field], aliases=["Período:"])
        if tooltip_field and tooltip_field in gdf.columns else None
    )
    GeoJson(
        data=json.loads(gdf.to_json()),
        name=None,
        style_function=lambda f, c=cv: {
            "fillColor": c["fill"], "color": c["line"],
            "weight": 0.5, "fillOpacity": 0.75,
        },
        tooltip=tt,
    ).add_to(fg)
    fg.add_to(m)

# urban layers
add_urban_layer(g2000,        LBL_URB_2000, "year",    show=True)
add_urban_layer(exp_2000_2010, LBL_ESP_0010, "periodo", show=True)
add_urban_layer(exp_2010_2023, LBL_ESP_1022, "periodo", show=True)

# vegetation layers
add_veg_layer(veg_2000,    LBL_VEG_2000,  show=True)
add_veg_layer(veg_var_0010, LBL_VEGV_0010, "periodo", show=True)
add_veg_layer(veg_var_1022, LBL_VEGV_1022, "periodo", show=True)

# -------- municipality boundary --------
mun = gpd.read_file(MUN_SHP)
mun = fix_valid(mun)
mun = to_wgs84(mun)
mun = mun[mun["NM_MUN"] == "Jundiaí"].copy()
mun = mun.dissolve()

folium.map.CustomPane("mun_halo", z_index=580).add_to(m)
folium.map.CustomPane("mun_line", z_index=590).add_to(m)
m.get_root().html.add_child(folium.Element("""
<style>
.mun_halo-pane, .mun_line-pane { pointer-events: none; }
</style>
"""))

folium.GeoJson(
    data=json.loads(mun.to_json()),
    name=None, control=False, pane="mun_halo",
    style_function=lambda f: {"color": "#000000", "weight": 8, "opacity": 0.25, "fillOpacity": 0.0},
).add_to(m)
folium.GeoJson(
    data=json.loads(mun.to_json()),
    name=None, control=False, pane="mun_line",
    style_function=lambda f: {
        "color": "#FFD700", "weight": 3, "dashArray": "6,4",
        "fillColor": "#FFF59D", "fillOpacity": 0.15,
    },
).add_to(m)

folium.LayerControl(position="topright", collapsed=False).add_to(m)
m.fit_bounds([[miny, minx], [maxy, maxx]])

m.save("./docs/mapa_vegetacao.html")
print("Salvo: ./docs/mapa_vegetacao.html")
