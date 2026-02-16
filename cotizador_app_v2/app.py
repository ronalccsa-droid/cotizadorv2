
import streamlit as st
import pandas as pd
import numpy as np
from pathlib import Path
import datetime as dt
import json

st.set_page_config(page_title="Cotizador MAC/MAF (m³) — Transporte m3k", layout="wide")

APP_DIR = Path(__file__).resolve().parent
DEFAULT_EXCEL = APP_DIR / "Documento_Maestro_Costeo_2026.xlsx"
DATA_DIR = APP_DIR / "overrides"
DATA_DIR.mkdir(exist_ok=True)

CONFIG_PATH = DATA_DIR / "config_app.json"

DEFAULT_CONFIG = {
    "auth": {
        "admin_user": "admin",
        "admin_pass": "admin123",
        "user_user": "comercial",
        "user_pass": "user123"
    },
    "pricing": {
        "igv_pct": 18.0,
        "gg_pct": 10.0,
        "riesgo_pct": 3.0,
        "margen_base_pct": 15.0,
        "margen_competitivo_pct": 12.0,
        "descuento_max_pct": 5.0
    },
    "transporte_m3k": {
        "tarifa_mac": 0.0,
        "tarifa_maf": 0.0
    },
    "productos": {
        "MAC": {
            "partida_produccion": "",
            "partidas_colocacion": []
        },
        "MAF": {
            "partida_produccion": "",
            "partidas_colocacion": []
        }
    }
}

def load_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def save_config(cfg):
    CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")

def today_str():
    return dt.datetime.now().strftime("%Y-%m-%d")

@st.cache_data(show_spinner=False)
def load_master(excel_path: str):
    xls = pd.ExcelFile(excel_path)
    sheets = {s: pd.read_excel(excel_path, sheet_name=s) for s in xls.sheet_names}
    return sheets

def normalize_cols(df: pd.DataFrame):
    df = df.copy()
    df.columns = [str(c).strip() for c in df.columns]
    return df

def detect_ins_cols(df: pd.DataFrame):
    cols = {c.lower(): c for c in df.columns}
    def pick(*names):
        for n in names:
            if n in cols: return cols[n]
        return None
    return {
        "codigo": pick("codigo", "cod", "código"),
        "descripcion": pick("descripcion", "descripción", "insumo", "nombre"),
        "precio": pick("precio", "precio_unitario", "p_unit", "pu"),
    }

def detect_acu_cols(df: pd.DataFrame, fallback_codigo: str):
    cols = {c.lower(): c for c in df.columns}
    def pick(*names):
        for n in names:
            if n in cols: return cols[n]
        return None
    return {
        "partida": pick("partida", "codigo_partida", "cod_partida", "item", "id_partida") or df.columns[0],
        "insumo_codigo": pick("codigo", "cod", "código", "codigo_insumo", "cod_insumo") or fallback_codigo,
        "cantidad": pick("cantidad", "qty", "cant", "consumo", "coeficiente"),
        "precio": pick("precio", "precio_unitario", "pu", "p_unit")
    }

def load_overrides_price(list_name: str):
    p = DATA_DIR / f"insumos_overrides__{list_name}.csv"
    if p.exists():
        return pd.read_csv(p)
    return None

def apply_overrides(insumos: pd.DataFrame, ov: pd.DataFrame, key_col: str, price_col: str):
    ins = insumos.copy()
    if ov is None:
        ins["precio_base"] = ins[price_col]
        ins["precio_override"] = np.nan
        ins["precio_activo"] = ins[price_col]
        return ins

    ov = ov.copy()
    # ensure columns
    if price_col not in ov.columns:
        for c in ov.columns:
            if "precio" in c.lower():
                ov = ov.rename(columns={c: price_col})
                break
    if key_col not in ov.columns:
        for c in ov.columns:
            if "cod" in c.lower():
                ov = ov.rename(columns={c: key_col})
                break

    ov = ov.dropna(subset=[key_col])
    ov = ov.sort_values(by=[key_col]).drop_duplicates(subset=[key_col], keep="last")
    ins = ins.merge(ov[[key_col, price_col]].rename(columns={price_col:"precio_override"}), on=key_col, how="left")
    ins["precio_base"] = ins[price_col]
    ins["precio_activo"] = np.where(ins["precio_override"].notna(), ins["precio_override"], ins[price_col])
    return ins

def calc_unit_cost_per_partida(acu: pd.DataFrame, ins_active: pd.DataFrame, col_partida: str, col_insumo: str, col_qty: str, col_price: str):
    a = acu.copy()
    ins_map = ins_active[[col_insumo, "precio_activo"]].dropna().drop_duplicates(subset=[col_insumo])
    a = a.merge(ins_map, on=col_insumo, how="left")
    a["precio_usado"] = np.where(a["precio_activo"].notna(), a["precio_activo"], a[col_price])
    a["parcial_calc"] = a[col_qty] * a["precio_usado"]
    unit = a.groupby(col_partida, dropna=False)["parcial_calc"].sum().reset_index().rename(columns={"parcial_calc":"costo_unitario_m3"})
    return unit, a

# -----------------------------
# Auth
# -----------------------------
cfg = load_config()
st.sidebar.header("Acceso")
user = st.sidebar.text_input("Usuario", value=cfg["auth"]["user_user"])
pwd = st.sidebar.text_input("Clave", type="password", value="")
role = None
if user == cfg["auth"]["admin_user"] and pwd == cfg["auth"]["admin_pass"]:
    role = "admin"
elif user == cfg["auth"]["user_user"] and pwd == cfg["auth"]["user_pass"]:
    role = "user"

if role is None:
    st.sidebar.info("Ingresa usuario/clave. (Admin o Comercial)")
    st.stop()

st.sidebar.success(f"Rol activo: {role.upper()}")

# -----------------------------
# Data source
# -----------------------------
st.sidebar.header("Datos")
uploaded = st.sidebar.file_uploader("Excel maestro (opcional)", type=["xlsx"])
if uploaded:
    excel_path = str(APP_DIR / f"_upload_{today_str()}.xlsx")
    with open(excel_path, "wb") as f:
        f.write(uploaded.getbuffer())
else:
    excel_path = str(DEFAULT_EXCEL)

sheets = load_master(excel_path)
sheets = {k: normalize_cols(v) for k, v in sheets.items()}

ins_sheet = "Insumos_Limpio"
acu_sheet = "ACU_Detalle_Limpio"
if ins_sheet not in sheets or acu_sheet not in sheets:
    st.error("Faltan hojas: 'Insumos_Limpio' y/o 'ACU_Detalle_Limpio' en el Excel maestro.")
    st.stop()

insumos = sheets[ins_sheet]
acu = sheets[acu_sheet]

ins_cols = detect_ins_cols(insumos)
if not ins_cols["codigo"] or not ins_cols["precio"]:
    st.error("No se detectó 'Código' y 'Precio' en Insumos_Limpio.")
    st.stop()

codigo_col = ins_cols["codigo"]
desc_col = ins_cols["descripcion"] or codigo_col
precio_col = ins_cols["precio"]

acu_cols = detect_acu_cols(acu, codigo_col)
if acu_cols["cantidad"] is None or acu_cols["precio"] is None:
    st.error("No se detectó 'Cantidad' y 'Precio' en ACU_Detalle_Limpio.")
    st.stop()

partida_col = acu_cols["partida"]
acu_insumo_col = acu_cols["insumo_codigo"]
acu_qty_col = acu_cols["cantidad"]
acu_price_col = acu_cols["precio"]

# price list (editable only by admin)
st.sidebar.header("Lista de precios")
list_name = st.sidebar.text_input("Nombre de lista", value="Base_2026")
ov = load_overrides_price(list_name)
ins_active = apply_overrides(insumos, ov, codigo_col, precio_col)

unit_cost, acu_enriched = calc_unit_cost_per_partida(
    acu=acu,
    ins_active=ins_active,
    col_partida=partida_col,
    col_insumo=acu_insumo_col,
    col_qty=acu_qty_col,
    col_price=acu_price_col
)

partidas = unit_cost[partida_col].astype(str).sort_values().unique().tolist()

# -----------------------------
# UI
# -----------------------------
st.title("Cotizador MAC/MAF (m³) — Transporte m3k")
st.caption("Cliente NO ve ACU. Solo Admin puede editar precios/ACU y parametrizar productos.")

tab_cot, tab_admin = st.tabs(["Cotizar", "Admin (solo tú)"])

# -------- Cotizar --------
with tab_cot:
    st.subheader("Nueva cotización")
    c1, c2, c3, c4 = st.columns([2,2,2,2])
    cliente = c1.text_input("Cliente", value="")
    producto = c2.selectbox("Producto", ["MAC", "MAF"])
    cantidad_m3 = c3.number_input("Cantidad (m³)", min_value=0.0, value=720.0, step=10.0)
    modalidad = c4.selectbox("Modalidad", ["Planta (solo mezcla)", "Entregado (Transporte m3k)", "Colocado (Completo)"])

    d1, d2, d3, d4 = st.columns([2,2,2,2])
    distancia_km = d1.number_input("Distancia (km) — para transporte m3k", min_value=0.0, value=0.0, step=1.0)
    moneda = d2.selectbox("Moneda", ["PEN (S/)", "USD ($)"])
    incluir_igv = d3.checkbox("Mostrar con IGV", value=True)
    notas = d4.text_input("Notas", value="")

    # pricing parameters (fixed for user; editable by admin)
    igv = cfg["pricing"]["igv_pct"]/100
    gg = cfg["pricing"]["gg_pct"]/100
    riesgo = cfg["pricing"]["riesgo_pct"]/100

    if producto == "MAC":
        tarifa_m3k = cfg["transporte_m3k"]["tarifa_mac"]
    else:
        tarifa_m3k = cfg["transporte_m3k"]["tarifa_maf"]

    # product mapping
    prod_cfg = cfg["productos"][producto]
    partida_prod = str(prod_cfg.get("partida_produccion", "")).strip()
    partidas_col = [str(x) for x in prod_cfg.get("partidas_colocacion", [])]

    if not partida_prod:
        st.warning("⚠️ Este producto no tiene 'Partida de Producción' configurada. Pide al Admin que la configure en la pestaña Admin.")
        st.stop()

    # Get unit costs
    uc_map = dict(zip(unit_cost[partida_col].astype(str), unit_cost["costo_unitario_m3"].astype(float)))
    costo_prod_unit = uc_map.get(partida_prod, np.nan)
    if not np.isfinite(costo_prod_unit):
        st.error(f"No se encontró costo unitario para la partida de producción: {partida_prod}")
        st.stop()

    costo_prod_total = costo_prod_unit * cantidad_m3

    costo_coloc_total = 0.0
    if modalidad == "Colocado (Completo)":
        missing = [p for p in partidas_col if p not in uc_map]
        if missing:
            st.error(f"Partidas de colocación sin costo unitario (no encontradas en ACU): {missing}")
            st.stop()
        costo_coloc_unit = sum(uc_map[p] for p in partidas_col)
        costo_coloc_total = costo_coloc_unit * cantidad_m3

    costo_transporte = 0.0
    if modalidad in ["Entregado (Transporte m3k)", "Colocado (Completo)"]:
        costo_transporte = cantidad_m3 * distancia_km * float(tarifa_m3k)

    costo_directo = costo_prod_total + costo_coloc_total + costo_transporte
    costo_indirecto = costo_directo * gg
    costo_base = costo_directo + costo_indirecto
    costo_con_riesgo = costo_base * (1 + riesgo)

    def escenario(margen_pct: float, descuento_pct: float = 0.0):
        margen = margen_pct/100.0
        precio_sin_igv = costo_con_riesgo * (1 + margen)
        # descuento sobre precio sin IGV
        precio_sin_igv = precio_sin_igv * (1 - descuento_pct/100.0)
        igv_val = precio_sin_igv * igv
        precio_con_igv = precio_sin_igv + igv_val
        return {
            "margen_pct": margen_pct,
            "descuento_pct": descuento_pct,
            "precio_sin_igv": precio_sin_igv,
            "precio_con_igv": precio_con_igv
        }

    base = escenario(cfg["pricing"]["margen_base_pct"])
    competitivo = escenario(cfg["pricing"]["margen_competitivo_pct"])

    st.divider()
    st.subheader("Resumen de costos (interno)")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Costo producción", f"{costo_prod_total:,.2f}")
    r2.metric("Costo transporte (m3k)", f"{costo_transporte:,.2f}")
    r3.metric("Costo colocación", f"{costo_coloc_total:,.2f}")
    r4.metric("Costo total con riesgo", f"{costo_con_riesgo:,.2f}")

    st.subheader("Alternativas de cotización")
    out = pd.DataFrame([
        {"Alternativa":"Base", "Margen %": base["margen_pct"], "Descuento %": 0.0,
         "Precio": base["precio_con_igv"] if incluir_igv else base["precio_sin_igv"]},
        {"Alternativa":"Competitiva", "Margen %": competitivo["margen_pct"], "Descuento %": 0.0,
         "Precio": competitivo["precio_con_igv"] if incluir_igv else competitivo["precio_sin_igv"]},
    ])

    # Especial (user can propose within limit)
    max_desc = float(cfg["pricing"]["descuento_max_pct"])
    desc = st.number_input(f"Precio especial — Descuento % (máx {max_desc:.1f}%)", min_value=0.0, max_value=50.0, value=0.0, step=0.5)
    if desc <= max_desc:
        especial = escenario(cfg["pricing"]["margen_base_pct"], descuento_pct=desc)
        out = pd.concat([out, pd.DataFrame([{
            "Alternativa":"Especial (aprobado)", "Margen %": especial["margen_pct"], "Descuento %": desc,
            "Precio": especial["precio_con_igv"] if incluir_igv else especial["precio_sin_igv"]
        }])], ignore_index=True)
    else:
        out = pd.concat([out, pd.DataFrame([{
            "Alternativa":"Especial (requiere Admin)", "Margen %": cfg["pricing"]["margen_base_pct"], "Descuento %": desc,
            "Precio": np.nan
        }])], ignore_index=True)

    st.dataframe(out, use_container_width=True)

    st.info("ACU y estructura interna NO se muestran a usuarios. El Admin puede ver trazabilidad en la pestaña Admin.")

# -------- Admin --------
with tab_admin:
    if role != "admin":
        st.warning("Solo el Admin puede ver y modificar esta sección.")
        st.stop()

    st.subheader("Configuración de seguridad")
    cfg2 = cfg.copy()

    a1, a2 = st.columns(2)
    cfg2["auth"]["admin_user"] = a1.text_input("Usuario Admin", value=cfg["auth"]["admin_user"])
    cfg2["auth"]["admin_pass"] = a2.text_input("Clave Admin", value=cfg["auth"]["admin_pass"])
    b1, b2 = st.columns(2)
    cfg2["auth"]["user_user"] = b1.text_input("Usuario Comercial", value=cfg["auth"]["user_user"])
    cfg2["auth"]["user_pass"] = b2.text_input("Clave Comercial", value=cfg["auth"]["user_pass"])

    st.subheader("Parámetros de pricing")
    p1, p2, p3, p4, p5 = st.columns(5)
    cfg2["pricing"]["igv_pct"] = p1.number_input("IGV %", min_value=0.0, max_value=30.0, value=float(cfg["pricing"]["igv_pct"]), step=0.5)
    cfg2["pricing"]["gg_pct"] = p2.number_input("GG %", min_value=0.0, max_value=200.0, value=float(cfg["pricing"]["gg_pct"]), step=1.0)
    cfg2["pricing"]["riesgo_pct"] = p3.number_input("Riesgo %", min_value=0.0, max_value=200.0, value=float(cfg["pricing"]["riesgo_pct"]), step=0.5)
    cfg2["pricing"]["margen_base_pct"] = p4.number_input("Margen Base %", min_value=0.0, max_value=300.0, value=float(cfg["pricing"]["margen_base_pct"]), step=1.0)
    cfg2["pricing"]["margen_competitivo_pct"] = p5.number_input("Margen Competitivo %", min_value=0.0, max_value=300.0, value=float(cfg["pricing"]["margen_competitivo_pct"]), step=1.0)

    cfg2["pricing"]["descuento_max_pct"] = st.number_input("Descuento máx permitido al comercial (%)", min_value=0.0, max_value=50.0, value=float(cfg["pricing"]["descuento_max_pct"]), step=0.5)

    st.subheader("Transporte m3k (solo Admin)")
    t1, t2 = st.columns(2)
    cfg2["transporte_m3k"]["tarifa_mac"] = t1.number_input("Tarifa m3k MAC (S/ por m³·km)", min_value=0.0, value=float(cfg["transporte_m3k"]["tarifa_mac"]), step=0.01)
    cfg2["transporte_m3k"]["tarifa_maf"] = t2.number_input("Tarifa m3k MAF (S/ por m³·km)", min_value=0.0, value=float(cfg["transporte_m3k"]["tarifa_maf"]), step=0.01)

    st.subheader("Mapeo de productos a partidas (ACU) — oculto para comercial")
    st.caption("Define qué partida representa el costo unitario de producción por m³ y qué partidas componen la colocación por m³.")

    for prod in ["MAC", "MAF"]:
        st.markdown(f"### {prod}")
        c1, c2 = st.columns([2,3])
        cfg2["productos"][prod]["partida_produccion"] = c1.selectbox(
            f"Partida de producción ({prod})",
            options=[""] + partidas,
            index=([""] + partidas).index(cfg["productos"][prod].get("partida_produccion","")) if cfg["productos"][prod].get("partida_produccion","") in partidas else 0
        )
        cfg2["productos"][prod]["partidas_colocacion"] = c2.multiselect(
            f"Partidas de colocación ({prod})",
            options=partidas,
            default=[p for p in cfg["productos"][prod].get("partidas_colocacion", []) if p in partidas]
        )

    st.divider()
    st.subheader("Editar lista de precios de insumos (solo Admin)")
    st.caption("Edita y guarda una lista. El cotizador usará estos precios activos para recalcular el costo unitario de las partidas.")

    # Load override frame (or initialize)
    override_path = DATA_DIR / f"insumos_overrides__{list_name}.csv"
    if ov is None:
        ov_edit = insumos[[codigo_col, desc_col, precio_col]].copy().rename(columns={precio_col: "precio"})
    else:
        ov_edit = ov.copy()
        if "precio" not in ov_edit.columns:
            for c in ov_edit.columns:
                if "precio" in c.lower():
                    ov_edit = ov_edit.rename(columns={c:"precio"})
                    break
        if codigo_col not in ov_edit.columns:
            for c in ov_edit.columns:
                if "cod" in c.lower():
                    ov_edit = ov_edit.rename(columns={c: codigo_col})
                    break

    filt = st.text_input("Buscar insumo (código o descripción)", value="")
    show_n = st.number_input("Máx filas", min_value=100, max_value=5000, value=500, step=100)
    view = insumos[[codigo_col, desc_col, precio_col]].copy()
    view = view.merge(ov_edit[[codigo_col, "precio"]], on=codigo_col, how="left", suffixes=("", "_ov"))
    view["precio_override"] = view["precio"]
    view = view.drop(columns=["precio"])
    if filt.strip():
        m = view[codigo_col].astype(str).str.contains(filt, case=False, na=False) | view[desc_col].astype(str).str.contains(filt, case=False, na=False)
        view = view[m]
    view = view.head(int(show_n))

    edited = st.data_editor(
        view.rename(columns={precio_col:"precio_base"}),
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "precio_override": st.column_config.NumberColumn("precio_override", format="%.4f"),
            "precio_base": st.column_config.NumberColumn("precio_base", disabled=True, format="%.4f"),
        }
    )

    s1, s2 = st.columns([1,1])
    if s1.button("Guardar configuración + precios", type="primary"):
        # save config
        save_config(cfg2)

        # save overrides
        base = insumos[[codigo_col, desc_col]].copy()
        base = base.merge(edited[[codigo_col, "precio_override"]], on=codigo_col, how="left")
        out_ov = base.rename(columns={"precio_override":"precio"})
        out_ov = out_ov.dropna(subset=["precio"])
        out_ov.to_csv(override_path, index=False, encoding="utf-8")

        st.success("Guardado. Recarga para aplicar cambios.")
        st.cache_data.clear()
        st.rerun()

    if s2.button("Resetear config"):
        if CONFIG_PATH.exists():
            CONFIG_PATH.unlink()
        st.warning("Configuración reseteada a valores por defecto.")
        st.cache_data.clear()
        st.rerun()

    st.subheader("Trazabilidad ACU (solo Admin)")
    if st.checkbox("Ver detalle ACU de una partida", value=False):
        p = st.selectbox("Partida", options=partidas)
        det = acu_enriched[acu_enriched[partida_col].astype(str)==str(p)].copy()
        ins_small = insumos[[codigo_col, desc_col]].drop_duplicates(subset=[codigo_col])
        det = det.merge(ins_small.rename(columns={codigo_col: acu_insumo_col, desc_col:"insumo_desc"}), on=acu_insumo_col, how="left")
        st.dataframe(det[[partida_col, acu_insumo_col, "insumo_desc", acu_qty_col, "precio_usado", "parcial_calc"]], use_container_width=True)
