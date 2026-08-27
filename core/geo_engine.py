"""Geographic intelligence layer.

Turns city names into coordinates when latitude/longitude are not present,
then builds executive geographic indicators without changing source data.
Geocoding is cached in-process and ambiguous/unresolved places are surfaced
instead of being silently guessed.
"""
from __future__ import annotations
from .numeric import numeric_series

from functools import lru_cache
import re
from typing import Optional

import pandas as pd

try:
    from geopy.geocoders import ArcGIS
except Exception:  # pragma: no cover
    ArcGIS = None


def _norm(v) -> str:
    if pd.isna(v):
        return ""
    return re.sub(r"\s+", " ", str(v).strip())


def _pick_col(schema: dict, concept: str, df: pd.DataFrame) -> Optional[str]:
    for item in schema.get("semantic", {}).get("columns", []):
        if item.get("semantic_type") == concept and item.get("column") in df.columns:
            return item["column"]
    return None


def _header_pick(df: pd.DataFrame, aliases: set[str]) -> Optional[str]:
    normalized = {re.sub(r"[^a-z0-9]+", "", str(c).strip().lower()): c for c in df.columns}
    for alias in aliases:
        key = re.sub(r"[^a-z0-9]+", "", alias.lower())
        if key in normalized:
            return normalized[key]
    return None


def geo_columns(df: pd.DataFrame, schema: dict) -> dict:
    # Semantic detection has priority, but geography must also work with
    # ordinary Excel headers such as Ciudad, Región, País, Latitud and Longitud.
    # A semantic false-positive on a person field must never win over an exact
    # geographic header (e.g. "Apellido 1" must not become a city).
    name_field_re = re.compile(r"(^|\s)(nombre|nombres|apellido|apellidos|first name|last name|surname)(\s|$)", re.I)
    def safe_semantic(concept):
        candidate = _pick_col(schema, concept, df)
        return candidate if candidate and not name_field_re.search(str(candidate)) else None
    return {
        "city": safe_semantic("city") or _header_pick(df, {"ciudad", "city", "municipio", "localidad"}),
        "country": safe_semantic("country") or _header_pick(df, {"pais", "país", "country", "nacion", "nación"}),
        "region": safe_semantic("region") or _header_pick(df, {"region", "región", "departamento", "estado", "state", "zona"}),
        "lat": safe_semantic("latitude") or _header_pick(df, {"lat", "latitud", "latitude"}),
        "lon": safe_semantic("longitude") or _header_pick(df, {"lon", "lng", "long", "longitud", "longitude"}),
    }



def supports_georeferencing(df: pd.DataFrame, schema: dict) -> tuple[bool, dict]:
    """Decide whether the workbook deserves a georeferencing section.

    Geography is an optional capability: ordinary catalogs, plans, shopping
    lists and reference tables must not receive an empty/useless map. The
    decision is based on actual geographic columns *and* usable values.
    Coordinates are the strongest signal; city/region/country headers are
    accepted when they contain real values.
    """
    cols = geo_columns(df, schema)

    def usable(col):
        if not col or col not in df.columns:
            return False
        s = df[col]
        return bool(s.notna().sum() and s.astype(str).str.strip().replace({"nan": "", "None": ""}).ne("").sum())

    # Direct coordinates: require at least one valid pair, not merely the
    # presence of columns named Lat/Long.
    if cols["lat"] and cols["lon"]:
        lat = pd.to_numeric(df[cols["lat"]], errors="coerce")
        lon = pd.to_numeric(df[cols["lon"]], errors="coerce")
        valid = lat.between(-90, 90) & lon.between(-180, 180)
        if bool(valid.any()):
            return True, {"mode": "coordinates", "columns": cols}

    # A city is a strong geographic signal. Region/country are accepted too,
    # but only when the column actually has content.
    if usable(cols["city"]):
        return True, {"mode": "city", "columns": cols}
    if usable(cols["region"]):
        return True, {"mode": "region", "columns": cols}
    if usable(cols["country"]):
        return True, {"mode": "country", "columns": cols}

    return False, {"mode": "none", "columns": cols}

COLOMBIA_REGION_CENTROIDS = {
    "caribe": (10.3, -74.8), "andina": (5.7, -74.0),
    "pacifica": (4.2, -77.0), "pacífica": (4.2, -77.0),
    "orinoquia": (4.2, -71.5), "orinoquía": (4.2, -71.5),
    "amazonia": (0.8, -72.2), "amazonía": (0.8, -72.2),
    "amazonica": (0.8, -72.2), "amazónica": (0.8, -72.2),
}

def _known_region_location(region: str, country: str = "") -> Optional[dict]:
    key = _norm(region).lower()
    c = _norm(country).lower()
    if key in COLOMBIA_REGION_CENTROIDS and ((not c) or "colombia" in c):
        lat, lon = COLOMBIA_REGION_CENTROIDS[key]
        return {"status":"ok","lat":lat,"lon":lon,"address":f"Región {region}, Colombia","score":100}
    return None


@lru_cache(maxsize=2000)
def geocode_place(city: str, country: str = "", region: str = "") -> dict:
    """Geocode a city using ArcGIS without requiring an API key.

    Returns status=ok/ambiguous/unresolved/offline. The raw source name is
    retained for transparency. Results are cached for the running process.
    """
    city, country, region = _norm(city), _norm(country), _norm(region)
    if not city:
        return {"status": "unresolved", "query": "", "reason": "Ciudad vacía"}
    if ArcGIS is None:
        return {"status": "offline", "query": city, "reason": "geopy no instalado"}
    query = ", ".join([x for x in [city, region, country] if x])
    try:
        geocoder = ArcGIS(timeout=4)
        locations = geocoder.geocode(query, exactly_one=False, maxRows=5)
        if not locations:
            return {"status": "unresolved", "query": query, "reason": "Sin coincidencias"}
        # Prefer city/locality matches and exact country matches when context exists.
        candidates = []
        for loc in locations:
            raw = getattr(loc, "raw", {}) or {}
            addr = str(getattr(loc, "address", "") or "")
            score = float(raw.get("Score", 0) or 0)
            if country and country.lower() in addr.lower():
                score += 5
            if region and region.lower() in addr.lower():
                score += 2
            candidates.append((score, loc))
        candidates.sort(key=lambda z: z[0], reverse=True)
        score, loc = candidates[0]
        raw = getattr(loc, "raw", {}) or {}
        if score < 80:
            return {"status": "ambiguous", "query": query, "reason": "Coincidencia débil", "candidates": [str(x[1].address) for x in candidates[:3]]}
        lat = pd.to_numeric(pd.Series([getattr(loc, "latitude", None)]), errors="coerce").iloc[0]
        lon = pd.to_numeric(pd.Series([getattr(loc, "longitude", None)]), errors="coerce").iloc[0]
        if pd.isna(lat) or pd.isna(lon) or not (-90 <= float(lat) <= 90 and -180 <= float(lon) <= 180):
            return {"status": "unresolved", "query": query, "reason": "Coordenadas inválidas"}
        return {
            "status": "ok",
            "query": query,
            "lat": float(lat),
            "lon": float(lon),
            "address": str(loc.address),
            "score": score,
            "country": raw.get("Country") or raw.get("CntryName") or "",
            "region": raw.get("Region") or raw.get("RegionAbbr") or "",
        }
    except Exception as exc:  # network/geocoder failures should never crash dashboard
        return {"status": "offline", "query": query, "reason": str(exc)[:160]}


def enrich_geography(df: pd.DataFrame, schema: dict, max_places: int = 40) -> tuple[pd.DataFrame, dict]:
    """Return a copy with _geo_lat/_geo_lon/_geo_status.

    If coordinates already exist, they are used directly. If only city exists,
    city names are geocoded. Source columns are never modified.
    """
    cols = geo_columns(df, schema)
    out = df.copy()
    out["_geo_lat"] = pd.NA
    out["_geo_lon"] = pd.NA
    out["_geo_status"] = ""
    out["_geo_label"] = ""

    # Direct coordinates: fastest and most reliable path.
    if cols["lat"] and cols["lon"]:
        out["_geo_lat"] = pd.to_numeric(out[cols["lat"]], errors="coerce")
        out["_geo_lon"] = pd.to_numeric(out[cols["lon"]], errors="coerce")
        valid = out["_geo_lat"].between(-90, 90) & out["_geo_lon"].between(-180, 180)
        out.loc[valid, "_geo_status"] = "ok"
        # Cuando el Excel ya trae coordenadas, no debemos colapsar todos los
        # puntos bajo la etiqueta genérica "Ubicación". Usamos el mejor nombre
        # disponible para que cada punto sea identificable al hacer clic.
        label_col = cols["city"] or cols["region"] or cols["country"]
        if label_col:
            out.loc[valid, "_geo_label"] = out.loc[valid, label_col].map(_norm)
        else:
            out.loc[valid, "_geo_label"] = "Ubicación"
        meta = {
            "mode": "coordinates",
            "city_column": cols["city"],
            "country_column": cols["country"],
            "region_column": cols["region"],
            "dimension": label_col,
            "level": "Ciudad" if cols["city"] else "Región" if cols["region"] else "País" if cols["country"] else "Ubicación",
            "resolved_places": int(valid.sum()),
            "unresolved_places": int((~valid).sum()),
            "resolved": int(valid.sum()),
            "unresolved": int((~valid).sum()),
        }
        return out, meta

    if not cols["city"] and cols["region"]:
        region_col, country_col = cols["region"], cols["country"]
        base = out[[region_col] + ([country_col] if country_col else [])].copy()
        base[region_col] = base[region_col].map(_norm)
        base = base[base[region_col] != ""]
        unique = base.drop_duplicates().head(max_places)
        results = {}
        for _, row in unique.iterrows():
            region = row[region_col]; country = row[country_col] if country_col else ""
            known = _known_region_location(region, country)
            results[(_norm(region), _norm(country))] = known or geocode_place(region, _norm(country), "")
            if results[(_norm(region), _norm(country))].get("status") != "ok":
                results[(_norm(region), _norm(country))] = _fallback_place(region=region, country=_norm(country)) or results[(_norm(region), _norm(country))]
        for idx, row in out.iterrows():
            region = _norm(row.get(region_col, "")); country = _norm(row.get(country_col, "")) if country_col else ""
            if not region: continue
            r = results.get((region, country))
            if not r:
                out.at[idx, "_geo_status"] = "limit"; continue
            out.at[idx, "_geo_status"] = r.get("status", "unresolved")
            if r.get("status") == "ok":
                out.at[idx, "_geo_lat"] = r.get("lat"); out.at[idx, "_geo_lon"] = r.get("lon"); out.at[idx, "_geo_label"] = region
        status = out["_geo_status"].value_counts().to_dict()
        return out, {"mode":"region_geocoding","city_column":None,"country_column":country_col,"region_column":region_col,"dimension":region_col,"level":"Región","resolved_places":sum(r and r.get("status")=="ok" for r in results.values()),"ambiguous_places":sum(r and r.get("status")=="ambiguous" for r in results.values()),"unresolved_places":sum(r and r.get("status") in {"unresolved","offline"} for r in results.values()),"rows":status}

    if not cols["city"] and not cols["region"] and cols["country"]:
        country_col = cols["country"]
        base = out[[country_col]].copy()
        base[country_col] = base[country_col].map(_norm)
        base = base[base[country_col] != ""]
        unique = base.drop_duplicates().head(max_places)
        results = {}
        for _, row in unique.iterrows():
            country = row[country_col]
            results[country] = _fallback_place(country=country) or geocode_place(country, country, "")
        for idx, row in out.iterrows():
            country = _norm(row.get(country_col, ""))
            if not country:
                continue
            r = results.get(country)
            if not r:
                out.at[idx, "_geo_status"] = "limit"; continue
            out.at[idx, "_geo_status"] = r.get("status", "unresolved")
            if r.get("status") == "ok":
                out.at[idx, "_geo_lat"] = r.get("lat"); out.at[idx, "_geo_lon"] = r.get("lon"); out.at[idx, "_geo_label"] = country
        status = out["_geo_status"].value_counts().to_dict()
        return out, {"mode":"country_geocoding", "city_column":None, "country_column":country_col, "region_column":None, "dimension":country_col, "level":"País", "resolved_places":sum(r and r.get("status")=="ok" for r in results.values()), "ambiguous_places":sum(r and r.get("status")=="ambiguous" for r in results.values()), "unresolved_places":sum(r and r.get("status") in {"unresolved","offline"} for r in results.values()), "rows":status}

    if not cols["city"]:
        return out, {"mode": "none", "reason": "No se detectó una ciudad, región, país ni coordenadas utilizables."}

    city_col, country_col, region_col = cols["city"], cols["country"], cols["region"]
    base = out[[city_col] + ([country_col] if country_col else []) + ([region_col] if region_col else [])].copy()
    base[city_col] = base[city_col].map(_norm)
    base = base[base[city_col] != ""]
    unique = base.drop_duplicates().head(max_places)

    results = {}
    for _, row in unique.iterrows():
        city = row[city_col]
        country = row[country_col] if country_col else ""
        region = row[region_col] if region_col else ""
        results[(city, _norm(country), _norm(region))] = geocode_place(city, _norm(country), _norm(region))
        if results[(city, _norm(country), _norm(region))].get("status") != "ok":
            results[(city, _norm(country), _norm(region))] = _fallback_place(city=city, region=_norm(region), country=_norm(country)) or results[(city, _norm(country), _norm(region))]

    for idx, row in out.iterrows():
        city = _norm(row.get(city_col, ""))
        if not city:
            continue
        country = _norm(row.get(country_col, "")) if country_col else ""
        region = _norm(row.get(region_col, "")) if region_col else ""
        r = results.get((city, country, region))
        if not r:
            out.at[idx, "_geo_status"] = "limit"
            continue
        out.at[idx, "_geo_status"] = r.get("status", "unresolved")
        if r.get("status") == "ok":
            out.at[idx, "_geo_lat"] = r.get("lat")
            out.at[idx, "_geo_lon"] = r.get("lon")
            out.at[idx, "_geo_label"] = city

    status = out["_geo_status"].value_counts().to_dict()
    return out, {
        "mode": "city_geocoding",
        "city_column": city_col,
        "country_column": country_col,
        "region_column": region_col,
        "dimension": city_col,
        "level": "Ciudad",
        "resolved_places": len([r for r in results.values() if r.get("status") == "ok"]),
        "ambiguous_places": len([r for r in results.values() if r.get("status") == "ambiguous"]),
        "unresolved_places": len([r for r in results.values() if r.get("status") in {"unresolved", "offline"}]),
        "rows": status,
    }


def geographic_summary(df: pd.DataFrame, schema: dict, metric: Optional[str] = None) -> dict:
    """Aggregate geographic indicators and return a Plotly-ready table."""
    from visualization.charts import metric_candidates

    enriched, meta = enrich_geography(df, schema)
    if meta.get("mode") == "none":
        return {"data": enriched, "meta": meta, "table": pd.DataFrame(), "kpis": {}}
    metrics = metric_candidates(df, schema)
    m = metric if metric in df.columns else (metrics[0] if metrics else None)
    valid = enriched[enriched["_geo_status"] == "ok"].copy()
    if valid.empty:
        return {"data": enriched, "meta": meta, "table": pd.DataFrame(), "kpis": {"metric": m}}

    if m:
        valid["_geo_metric"] = pd.to_numeric(valid[m], errors="coerce").fillna(0)
        grouped = valid.groupby(["_geo_label", "_geo_lat", "_geo_lon"], as_index=False)["_geo_metric"].sum()
        grouped = grouped.sort_values("_geo_metric", ascending=False)
        total = grouped["_geo_metric"].sum()
        grouped["share_pct"] = grouped["_geo_metric"] / total * 100 if total else 0
    else:
        grouped = valid.groupby(["_geo_label", "_geo_lat", "_geo_lon"], as_index=False).size().rename(columns={"size": "_geo_metric"})
        grouped["share_pct"] = grouped["_geo_metric"] / grouped["_geo_metric"].sum() * 100
        total = grouped["_geo_metric"].sum()

    top = grouped.iloc[0] if len(grouped) else None
    return {
        "data": enriched,
        "meta": meta,
        "table": grouped,
        "kpis": {
            "metric": m,
            "cities": int(grouped["_geo_label"].nunique()),
            "total": float(total),
            "leader": str(top["_geo_label"]) if top is not None else "—",
            "leader_value": float(top["_geo_metric"]) if top is not None else 0,
            "leader_share": float(top["share_pct"]) if top is not None else 0,
        },
    }

# Conservative offline fallbacks for common Colombian locations and countries.
COLOMBIA_PLACE_CENTROIDS = {
    "antioquia": (6.2476, -75.5658), "bogota": (4.7110, -74.0721), "bogotá": (4.7110, -74.0721),
    "atlantico": (10.9685, -74.7813), "atlántico": (10.9685, -74.7813), "bolivar": (10.3910, -75.4794), "bolívar": (10.3910, -75.4794),
    "boyaca": (5.5353, -73.3678), "boyacá": (5.5353, -73.3678), "caldas": (5.0689, -75.5174),
    "caqueta": (1.6144, -75.6062), "caquetá": (1.6144, -75.6062), "casanare": (5.3378, -72.3959),
    "cauca": (2.4448, -76.6147), "cesar": (10.4631, -73.2532), "cordoba": (8.7479, -75.8814), "córdoba": (8.7479, -75.8814),
    "cundinamarca": (4.5709, -74.2973), "guainia": (2.5854, -68.5247), "guainía": (2.5854, -68.5247),
    "guaviare": (2.5729, -72.6459), "huila": (2.5359, -75.5277), "la guajira": (11.5444, -72.9072),
    "magdalena": (10.4113, -74.4057), "meta": (3.4547, -73.2877), "narino": (1.2892, -77.3579), "nariño": (1.2892, -77.3579),
    "norte de santander": (7.9463, -72.8988), "putumayo": (1.1523, -76.6526), "quindio": (4.5339, -75.6811), "quindío": (4.5339, -75.6811),
    "risaralda": (4.8143, -75.6946), "santander": (7.1254, -73.1198), "sucre": (9.3047, -75.3978),
    "tolima": (4.4389, -75.2322), "valle del cauca": (3.4516, -76.5320), "arauca": (7.0903, -70.7617),
    "vaupes": (0.8554, -70.8110), "vaupés": (0.8554, -70.8110), "vichada": (4.4234, -69.2878),
    "medellin": (6.2442, -75.5812), "medellín": (6.2442, -75.5812), "cali": (3.4516, -76.5320),
    "barranquilla": (10.9685, -74.7813), "cartagena": (10.3910, -75.4794), "bucaramanga": (7.1193, -73.1227),
    "pereira": (4.8087, -75.6906), "manizales": (5.0703, -75.5138), "ibague": (4.4389, -75.2322), "ibagué": (4.4389, -75.2322),
    "santa marta": (11.2408, -74.1990), "villavicencio": (4.1420, -73.6266), "neiva": (2.9345, -75.2809),
    "armenia": (4.5339, -75.6811), "pasto": (1.2136, -77.2811), "monteria": (8.7479, -75.8814), "montería": (8.7479, -75.8814),
    "valledupar": (10.4631, -73.2532), "sincelejo": (9.3047, -75.3978), "popayan": (2.4448, -76.6147), "popayán": (2.4448, -76.6147),
}
COUNTRY_CENTROIDS = {
    "colombia": (4.5709, -74.2973), "ecuador": (-1.8312, -78.1834), "peru": (-9.1900, -75.0152), "perú": (-9.1900, -75.0152),
    "argentina": (-38.4161, -63.6167), "chile": (-35.6751, -71.5430), "brasil": (-14.2350, -51.9253), "brazil": (-14.2350, -51.9253),
    "mexico": (23.6345, -102.5528), "méxico": (23.6345, -102.5528), "panama": (8.5380, -80.7821), "panamá": (8.5380, -80.7821),
    "venezuela": (6.4238, -66.5897), "estados unidos": (37.0902, -95.7129), "united states": (37.0902, -95.7129),
    "españa": (40.4637, -3.7492), "spain": (40.4637, -3.7492), "francia": (46.2276, 2.2137), "france": (46.2276, 2.2137),
    "alemania": (51.1657, 10.4515), "germany": (51.1657, 10.4515), "italia": (41.8719, 12.5674), "italy": (41.8719, 12.5674),
    "reino unido": (55.3781, -3.4360), "united kingdom": (55.3781, -3.4360), "canada": (56.1304, -106.3468), "canadá": (56.1304, -106.3468),
}
def _fallback_place(city: str = "", region: str = "", country: str = "") -> Optional[dict]:
    for value in (city, region):
        key = _norm(value).lower()
        if key in COLOMBIA_PLACE_CENTROIDS:
            lat, lon = COLOMBIA_PLACE_CENTROIDS[key]
            return {"status":"ok", "lat":lat, "lon":lon, "address":str(value), "score":88, "fallback":True}
    key = _norm(country).lower()
    if key in COUNTRY_CENTROIDS:
        lat, lon = COUNTRY_CENTROIDS[key]
        return {"status":"ok", "lat":lat, "lon":lon, "address":str(country), "score":85, "fallback":True}
    return None
