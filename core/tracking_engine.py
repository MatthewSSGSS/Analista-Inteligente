"""Motor de Análisis de Seguimiento.

Cruza varios Excel -cada uno con su propia estructura, sin asumir columnas
fijas- por funcionario, usando el mismo motor semántico universal que el
resto de la app (detección de ID, nombre, fechas, conceptos). El resultado es
una tabla larga (tidy) que sirve como memoria portable: se puede exportar a
Excel, guardar, y volver a subir junto con archivos nuevos para seguir
acumulando historial sin depender del almacenamiento del servidor.
"""
from __future__ import annotations

import io
import re
import unicodedata
from datetime import datetime

import numpy as np
import pandas as pd

from core.loader import load_workbook

SUPERVISOR_RE = re.compile(r"(supervisor|jefe|l[ií]der|responsable|encargad[oa]|team\s*lead|coordinador)", re.I)
LOCATION_HEADER_RE = re.compile(r"(?:punto de venta|pdv|tienda|sucursal|puesto|sitio|local|agencia|estaci[oó]n|oficina)", re.I)
ID_PRIORITY_RE = re.compile(r"(cedula|cédula|documento|id.?empleado|id.?funcionario|dni|nit)", re.I)
LOCATION_CONCEPTS = {"city", "region", "country", "address"}
METRIC_CONCEPTS = {"revenue", "profit", "cost", "price", "quantity", "percentage", "rating"}

CONSOLIDATED_COLUMNS = [
    "person_key", "person_id", "person_name", "supervisor", "source_file",
    "source_sheet", "period", "column", "value", "concept", "upload_batch",
    "match_confidence",
]


def _norm_key(value) -> str:
    s = str(value or "").strip()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s+", " ", s).strip().lower()
    return s


def _looks_numeric(value) -> bool:
    try:
        float(str(value).replace(",", "").replace("%", "").strip())
        return True
    except (TypeError, ValueError):
        return False


def _pick_id_column(schema: dict):
    ids = schema.get("ids", []) or []
    if not ids:
        return None
    for c in ids:
        if ID_PRIORITY_RE.search(str(c)):
            return c
    return ids[0]


def _pick_name_column(df: pd.DataFrame, schema: dict):
    full = (schema.get("full_name") or {}).get("column")
    if full and full in df.columns:
        return full
    best = None
    for item in schema.get("semantic", {}).get("columns", []):
        if item.get("semantic_type") == "name" and item.get("column") in df.columns:
            conf = item.get("confidence", 0)
            if best is None or conf > best[1]:
                best = (item["column"], conf)
    return best[0] if best else None


def _pick_supervisor_column(df: pd.DataFrame):
    for c in df.columns:
        if SUPERVISOR_RE.search(str(c)):
            return c
    return None


def _pick_date_column(schema: dict):
    dates = schema.get("dates", []) or []
    return dates[0] if dates else None


def ingest_file(uploaded, batch_label: str | None = None) -> list[dict]:
    """Parsea un Excel/CSV subido y devuelve una lista de 'fuentes' (una por
    hoja usable). Reutiliza el mismo detector universal del resto de la app,
    así que no importa qué columnas traiga cada archivo.
    """
    wb = load_workbook(uploaded)
    sources = []
    for sheet_name, item in wb.get("sheets", {}).items():
        df = item.get("processed")
        schema = (item.get("profile") or {}).get("schema", {})
        if df is None or df.empty:
            continue
        id_col = _pick_id_column(schema)
        name_col = _pick_name_column(df, schema)
        if not id_col and not name_col:
            # Sin ID ni nombre no hay forma segura de identificar personas en
            # esta hoja: se omite del cruce (el resto del archivo se procesa igual).
            continue
        sources.append({
            "filename": wb.get("filename"),
            "sheet": sheet_name,
            "df": df,
            "schema": schema,
            "id_col": id_col,
            "name_col": name_col,
            "supervisor_col": _pick_supervisor_column(df),
            "date_col": _pick_date_column(schema),
            "batch_label": batch_label or wb.get("filename"),
        })
    return sources


def sources_to_long(sources: list[dict], upload_batch: str | None = None) -> pd.DataFrame:
    """Convierte las fuentes parseadas en una tabla larga: una fila por
    (persona, columna, valor). Este formato absorbe cualquier estructura de
    Excel sin necesitar un esquema fijo.
    """
    upload_batch = upload_batch or datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for src in sources:
        df = src["df"]
        id_col, name_col, sup_col, date_col = src["id_col"], src["name_col"], src["supervisor_col"], src["date_col"]
        skip_cols = {c for c in [id_col, name_col, sup_col, date_col] if c}
        value_cols = [c for c in df.columns if c not in skip_cols]
        concepts = {x.get("column"): x.get("semantic_type") for x in src["schema"].get("semantic", {}).get("columns", [])}

        for idx, row in df.iterrows():
            raw_id = row.get(id_col) if id_col else None
            raw_name = row.get(name_col) if name_col else None
            has_id = id_col and pd.notna(raw_id) and str(raw_id).strip()
            has_name = name_col and pd.notna(raw_name) and str(raw_name).strip()
            if not has_id and not has_name:
                continue
            person_id = str(raw_id).strip() if has_id else None
            person_name = str(raw_name).strip() if has_name else None
            key = person_id if person_id else f"nombre:{_norm_key(person_name)}"
            match_confidence = "alta" if person_id else "media"
            period = row.get(date_col) if date_col else None
            supervisor = str(row.get(sup_col)).strip() if sup_col and pd.notna(row.get(sup_col)) else None

            for c in value_cols:
                v = row.get(c)
                if pd.isna(v) or str(v).strip() == "":
                    continue
                rows.append({
                    "person_key": key,
                    "person_id": person_id,
                    "person_name": person_name,
                    "supervisor": supervisor,
                    "source_file": src["filename"],
                    "source_sheet": src["sheet"],
                    "period": period,
                    "column": str(c),
                    "value": v,
                    "concept": concepts.get(c, ""),
                    "upload_batch": upload_batch,
                    "match_confidence": match_confidence,
                })
    return pd.DataFrame(rows, columns=CONSOLIDATED_COLUMNS)


def _clean_id_series(series: pd.Series) -> pd.Series:
    """Normaliza IDs releídos de Excel de vuelta a texto limpio.

    Al exportar/reimportar por Excel, pandas suele inferir columnas de ID
    como números (p. ej. "1001" -> 1001, o 1001.0 si hay vacíos), lo que
    rompe la comparación exacta usada para cruzar personas. Esto restaura
    el mismo texto que existía antes de pasar por Excel.
    """
    def fmt(v):
        if pd.isna(v):
            return None
        s = str(v).strip()
        if s.endswith(".0"):
            try:
                if float(v) == int(float(v)):
                    return str(int(float(v)))
            except (TypeError, ValueError):
                pass
        return s
    return series.map(fmt)


def read_consolidated(uploaded) -> pd.DataFrame:
    """Lee un historial consolidado exportado previamente por esta misma
    herramienta. Lanza un error claro si el archivo no tiene ese formato,
    para no confundirlo silenciosamente con un Excel de datos nuevo.
    """
    data = uploaded.getvalue()
    df = pd.read_excel(io.BytesIO(data))
    missing = [c for c in CONSOLIDATED_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(
            "Este archivo no tiene el formato del historial consolidado "
            f"(faltan columnas: {', '.join(missing)}). Súbelo solo si es el "
            "archivo que esta misma herramienta te entregó para descargar."
        )
    df = df[CONSOLIDATED_COLUMNS].copy()
    df["period"] = pd.to_datetime(df["period"], errors="coerce")
    df["person_key"] = _clean_id_series(df["person_key"])
    df["person_id"] = _clean_id_series(df["person_id"])
    return df


def merge_long(existing: pd.DataFrame | None, new: pd.DataFrame) -> pd.DataFrame:
    if existing is None or existing.empty:
        combined = new.copy()
    else:
        combined = pd.concat([existing, new], ignore_index=True)
    if combined.empty:
        return combined
    dedup_key = combined.copy()
    dedup_key["_period_key"] = dedup_key["period"].astype(str)
    dedup_key["_value_key"] = dedup_key["value"].astype(str)
    combined = combined.loc[
        ~dedup_key.duplicated(
            subset=["person_key", "source_file", "source_sheet", "_period_key", "column", "_value_key"],
            keep="last",
        )
    ].reset_index(drop=True)
    return combined


def export_consolidated(long_df: pd.DataFrame) -> bytes:
    buf = io.BytesIO()
    out = long_df.copy()
    out["period"] = out["period"].astype(str).replace("NaT", "")
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        out.to_excel(writer, sheet_name="Historial consolidado", index=False)
    return buf.getvalue()


def person_directory(long_df: pd.DataFrame) -> pd.DataFrame:
    cols = ["person_key", "person_id", "person_name", "supervisor", "sources", "match_confidence"]
    if long_df is None or long_df.empty:
        return pd.DataFrame(columns=cols)
    rows = []
    for key, sub in long_df.groupby("person_key"):
        names = sub["person_name"].dropna()
        name = names.mode().iloc[0] if len(names) else key
        ids = sub["person_id"].dropna()
        pid = ids.mode().iloc[0] if len(ids) else None
        sups = sub["supervisor"].dropna()
        sup = sups.mode().iloc[0] if len(sups) else None
        conf = sub["match_confidence"].mode()
        rows.append({
            "person_key": key,
            "person_id": pid,
            "person_name": name,
            "supervisor": sup,
            "sources": sorted(sub["source_file"].dropna().unique().tolist()),
            "match_confidence": conf.iloc[0] if len(conf) else "media",
        })
    return pd.DataFrame(rows, columns=cols).sort_values("person_name", na_position="last").reset_index(drop=True)


def supervisor_directory(long_df: pd.DataFrame) -> list[str]:
    if long_df is None or long_df.empty:
        return []
    sups = long_df["supervisor"].dropna().astype(str).str.strip()
    return sorted({s for s in sups if s})


def team_roster(long_df: pd.DataFrame, supervisor_name: str) -> pd.DataFrame:
    if long_df is None or long_df.empty:
        return person_directory(long_df)
    target = _norm_key(supervisor_name)
    sub = long_df[long_df["supervisor"].apply(lambda s: _norm_key(s) == target if pd.notna(s) else False)]
    return person_directory(sub)


def person_profile(long_df: pd.DataFrame, person_key: str) -> dict | None:
    sub = long_df[long_df["person_key"] == person_key].copy()
    if sub.empty:
        return None

    names = sub["person_name"].dropna()
    ids = sub["person_id"].dropna()
    sups = sub["supervisor"].dropna()
    identity = {
        "key": person_key,
        "name": names.mode().iloc[0] if len(names) else person_key,
        "id": ids.mode().iloc[0] if len(ids) else None,
        "supervisor": sups.mode().iloc[0] if len(sups) else None,
        "match_confidence": sub["match_confidence"].mode().iloc[0] if len(sub) else "media",
        "sources": sorted(sub["source_file"].dropna().unique().tolist()),
    }

    location_mask = sub["concept"].isin(LOCATION_CONCEPTS) | sub["column"].str.contains(LOCATION_HEADER_RE, na=False)
    locations = {}
    for col, grp in sub[location_mask].groupby("column"):
        vals = sorted({str(v).strip() for v in grp["value"] if str(v).strip()})
        if vals:
            locations[col] = vals

    numeric_mask = sub["concept"].isin(METRIC_CONCEPTS) | sub["value"].apply(_looks_numeric)
    metrics = {}
    for col, grp in sub[numeric_mask & ~location_mask].groupby("column"):
        num = pd.to_numeric(grp["value"], errors="coerce")
        grp = grp.assign(_num=num).dropna(subset=["_num"])
        if grp.empty:
            continue
        with_period = grp.dropna(subset=["period"]).sort_values("period")
        timeline = with_period[["period", "_num"]].reset_index(drop=True) if not with_period.empty else pd.DataFrame(columns=["period", "_num"])
        latest_row = with_period.iloc[-1] if not with_period.empty else grp.iloc[-1]
        metrics[col] = {
            "latest": float(latest_row["_num"]),
            "avg": float(grp["_num"].mean()),
            "count": int(len(grp)),
            "timeline": timeline,
        }

    used_cols = set(locations.keys()) | set(metrics.keys())
    other = {}
    for col, grp in sub[~sub["column"].isin(used_cols)].groupby("column"):
        vals = sorted({str(v).strip() for v in grp["value"] if str(v).strip()})
        if vals:
            other[col] = vals

    return {"identity": identity, "locations": locations, "metrics": metrics, "other": other, "raw": sub}


def project_metric(timeline: pd.DataFrame, target_date) -> dict:
    """Proyección profesional por regresión lineal sobre el histórico real:
    si el desempeño sigue la misma tendencia, ¿a cuánto llegaría en la fecha
    de corte? Con menos de 3 puntos no hay tendencia confiable que calcular,
    así que se informa en vez de inventar un número.
    """
    d = timeline.dropna()
    if len(d) < 3:
        return {"status": "insuficiente", "points": int(len(d))}
    d = d.sort_values("period")
    # "period" ya llega parseado desde sources_to_long/merge_long, pero se
    # vuelve a forzar con errors="coerce" (igual que el resto del proyecto)
    # para no romper la proyección si alguna vez llega un valor sucio.
    periods = pd.to_datetime(d["period"], errors="coerce")
    t0 = periods.min()
    x = (periods - t0).dt.days.to_numpy(dtype=float)
    y = d["_num"].to_numpy(dtype=float)
    if np.ptp(x) == 0:
        return {"status": "insuficiente", "points": int(len(d))}
    slope, intercept = np.polyfit(x, y, 1)
    target_ts = pd.to_datetime(target_date, errors="coerce")
    if pd.isna(t0) or pd.isna(target_ts):
        return {"status": "insuficiente", "points": int(len(d))}
    target_days = (target_ts - t0).days
    projected = slope * target_days + intercept
    y_pred = slope * x + intercept
    ss_res = float(np.sum((y - y_pred) ** 2))
    ss_tot = float(np.sum((y - y.mean()) ** 2)) or 1e-9
    r2 = max(0.0, min(1.0, 1 - ss_res / ss_tot))
    return {
        "status": "ok",
        "points": int(len(d)),
        "current": float(y[-1]),
        "projected": float(projected),
        "target_date": target_ts,
        "r2": r2,
        "trend": "creciente" if slope > 1e-9 else ("decreciente" if slope < -1e-9 else "estable"),
    }
