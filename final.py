# map_diff_urban_green_pcv.py
import geopandas as gpd
import pandas as pd
import folium
import json

# ============================================================
# --- CONFIGURAÇÕES GERAIS ---
# ============================================================

# --- caminhos ---
BASE_PATH = r"D:\Users\lucas.lopes\Documents\Projetos 2.0\datas"
BASE_PATH_GREEN = r"D:\Users\lucas.lopes\Documents\Projetos 2.0\datas 2.0"
BASE_PATH_3 = r"D:\Users\lucas.lopes\Documents\Projetos 2.0\datas 3.0"

PATH_2010 = f"{BASE_PATH}\\soil_use_2010.shp"
PATH_2023 = f"{BASE_PATH}\\soil_use_2023.shp"
MUN_PATH = f"{BASE_PATH}\\limite_municipal_jundiai.shp"

PARQUES_MUNICIPAIS_PATH = f"{BASE_PATH_GREEN}\\L_8683-2016_m13_parques-municipais.shp"
PARQUE_PATH = f"{BASE_PATH_GREEN}\\Parque.shp"
PRACA_PATH = f"{BASE_PATH_GREEN}\\Praça.shp"
OUTROS_PATH = f"{BASE_PATH_GREEN}\\Outros.shp"

CSV_PCV_PATH = f"{BASE_PATH_3}\\dif_cobertura.csv"
SHAPE_PCV_PATH = f"{BASE_PATH_3}\\SP_setores_CD2022.shp"

# ============================================================
# --- PARÂMETROS DE VISUALIZAÇÃO ---
# ============================================================

COLOR_CONFIG = {
    "urban": {
        "2010": "#f44336",  # vermelho claro (área urbana antiga)
        "2023": "#8b0000",  # vermelho escuro (urbano atual)
        "added": "#0077FF",  # azul (espraiamento urbano)
    },
    "greens": {
        "Parques": {"color": "#228B22", "geom": "polygon"},          # verde escuro
        "Praças": {"color": "#7CFC00", "geom": "polygon"},           # verde claro
        "Outros": {"color": "#66C2A5", "geom": "polygon"},           # verde-azulado
        "Parques Municipais": {"color": "#2E8B57", "geom": "point"}, # verde floresta
    },
    "pcv_layers": {
        "pcv_diff": {
            "label": "Diferença PCV (2023 - 2016)",
            "colormap": "RdYlGn",  # vermelho (queda) → verde (aumento)
        },
    },
}

# Parâmetros de limitação de PCV_diff
PCV_DIFF_PARAMS = {
    "use_std": True,        # usa desvio padrão (True) ou percentis (False)
    "n_std": 2,             # número de desvios padrão
    "clip_percentiles": (2.5, 97.5),  # se usar percentis
}

# ============================================================
# --- FUNÇÕES AUXILIARES ---
# ============================================================

def fix_valid(gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    gdf["geometry"] = gdf.buffer(0)
    return gdf

def to_wgs84(gdf: gpd.GeoDataFrame, default_crs_epsg=None) -> gpd.GeoDataFrame:
    if gdf.crs is None and default_crs_epsg:
        gdf = gdf.set_crs(default_crs_epsg)
    if gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(4326)
    return gdf

def load_urban(path: str) -> gpd.GeoDataFrame:
    g = gpd.read_file(path)
    g = fix_valid(g)
    g = to_wgs84(g)
    if "soil_use" in g.columns:
        g = g[g["soil_use"].astype(str).str.lower() == "urbano"].copy()
    return g

def load_green(path: str, default_crs_epsg=None, fix_points=True) -> gpd.GeoDataFrame:
    g = gpd.read_file(path)
    if fix_points:
        g = fix_valid(g)
    g = to_wgs84(g, default_crs_epsg)
    return g

# ============================================================
# --- CARREGAMENTO DE DADOS ---
# ============================================================

g2010 = load_urban(PATH_2010)
g2023 = load_urban(PATH_2023)
mun = gpd.read_file(MUN_PATH)
mun = fix_valid(mun)
mun = to_wgs84(mun)
mun = mun.dissolve()

# Diferenças urbanas
added = gpd.overlay(g2023, g2010, how="difference")
removed = gpd.overlay(g2010, g2023, how="difference")

# Áreas verdes
greens = {
    "Parques": load_green(PARQUE_PATH),
    "Praças": load_green(PRACA_PATH),
    "Outros": load_green(OUTROS_PATH),
    "Parques Municipais": load_green(PARQUES_MUNICIPAIS_PATH, default_crs_epsg=31983, fix_points=False),
}

# Shapefile e CSV de PCV
setores = gpd.read_file(SHAPE_PCV_PATH)
csv = pd.read_csv(CSV_PCV_PATH)
csv.columns = [c.upper() for c in csv.columns]

setores["CD_SETOR"] = setores["CD_SETOR"].astype(str)
csv["CD_SETOR"] = csv["CD_SETOR"].astype(str)

setores = setores.merge(csv, on="CD_SETOR", how="inner")
setores = to_wgs84(setores, default_crs_epsg=31983)

# ============================================================
# --- MAPA ---
# ============================================================

minx, miny, maxx, maxy = mun.total_bounds
center = [(miny + maxy)/2, (minx + maxx)/2]
m = folium.Map(location=center, zoom_start=12, control_scale=True, tiles="CartoDB positron")

# Basemaps
folium.TileLayer("OpenStreetMap", name="Mapa padrão", overlay=False).add_to(m)
folium.TileLayer(
    tiles="https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
    attr="Esri Satellite", name="Satélite (Esri)", overlay=False
).add_to(m)

# ============================================================
# --- CAMADAS URBANAS ---
# ============================================================

def add_layer(gdf, color, name, fill_opacity=0.5, show=True):
    if gdf.empty:
        return
    fg = folium.FeatureGroup(name=name, show=show)
    folium.GeoJson(
        data=json.loads(gdf.to_json()),
        style_function=lambda f: {"color": color, "fillColor": color, "fillOpacity": fill_opacity, "weight": 1}
    ).add_to(fg)
    fg.add_to(m)

for label, color in COLOR_CONFIG["urban"].items():
    if label == "2010":
        add_layer(g2010, color, "Urbano 2010", fill_opacity=0.4, show=False)
    elif label == "2023":
        add_layer(g2023, color, "Urbano 2023", fill_opacity=0.5, show=True)
    elif label == "added":
        add_layer(added, color, "Espraiamento urbano", fill_opacity=0.8, show=True)

# Limite municipal (renomeado)
folium.GeoJson(
    data=json.loads(mun.to_json()),
    name="Limite Municipal de Jundiaí",
    style_function=lambda f: {"color": "#000", "weight": 3, "fillOpacity": 0}
).add_to(m)

# ============================================================
# --- CAMADAS VERDES ---
# ============================================================

for label, conf in COLOR_CONFIG["greens"].items():
    gdf = greens[label]
    color = conf["color"]
    geom_type = conf["geom"]

    fg = folium.FeatureGroup(name=label, show=True)
    if gdf.empty:
        continue

    if geom_type == "polygon":
        folium.GeoJson(
            data=json.loads(gdf.to_json()),
            style_function=lambda f, c=color: {"color": c, "fillColor": c, "fillOpacity": 0.5, "weight": 1}
        ).add_to(fg)
    else:
        icon = folium.Icon(color="green", icon="tree", prefix="fa")
        for _, row in gdf.iterrows():
            geom = row.geometry
            if geom is None or geom.is_empty:
                continue
            pt = geom if geom.geom_type == "Point" else geom.centroid
            folium.Marker(
                location=[pt.y, pt.x],
                tooltip=str(row.get("nome", label)),
                icon=icon
            ).add_to(fg)
    fg.add_to(m)

# ============================================================
# --- PCV ---
# ============================================================

setores["pcv_diff"] = setores["PCV_2023"] - setores["PCV_2016"]

if PCV_DIFF_PARAMS["use_std"]:
    mean_diff = setores["pcv_diff"].mean()
    std_diff = setores["pcv_diff"].std()
    lim_inf = mean_diff - PCV_DIFF_PARAMS["n_std"] * std_diff
    lim_sup = mean_diff + PCV_DIFF_PARAMS["n_std"] * std_diff
else:
    lim_inf, lim_sup = setores["pcv_diff"].quantile([p/100 for p in PCV_DIFF_PARAMS["clip_percentiles"]])

setores["pcv_diff"] = setores["pcv_diff"].clip(lim_inf, lim_sup)

def add_pcv_layer(gdf, column, label, colormap):
    if gdf.empty:
        return
    folium.Choropleth(
        geo_data=json.loads(gdf.to_json()),
        name=label,
        data=gdf,
        columns=["CD_SETOR", column],
        key_on="feature.properties.CD_SETOR",
        fill_color=colormap,
        fill_opacity=0.55,  # opacidade reduzida
        line_opacity=0.2,
        legend_name=label
    ).add_to(m)

for col, conf in COLOR_CONFIG["pcv_layers"].items():
    add_pcv_layer(setores, col, conf["label"], conf["colormap"])

# ============================================================
# --- FINALIZAÇÃO ---
# ============================================================

folium.LayerControl(collapsed=False).add_to(m)
m.save("./docs/Final.html")
print("Mapa salvo em ./docs/Final.html")
