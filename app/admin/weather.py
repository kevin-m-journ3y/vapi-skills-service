# app/admin/weather.py - Weather data via Open-Meteo (free, no API key)
import httpx
import logging
import os
from typing import List, Dict, Any, Optional
from datetime import date, timedelta

logger = logging.getLogger(__name__)

# WMO Weather Codes → human-readable descriptions + emoji
WMO_CODES = {
    0: ("Clear sky", "sun"),
    1: ("Mainly clear", "sun"),
    2: ("Partly cloudy", "cloud-sun"),
    3: ("Overcast", "cloud"),
    45: ("Fog", "fog"),
    48: ("Depositing rime fog", "fog"),
    51: ("Light drizzle", "cloud-drizzle"),
    53: ("Moderate drizzle", "cloud-drizzle"),
    55: ("Dense drizzle", "cloud-drizzle"),
    56: ("Light freezing drizzle", "cloud-drizzle"),
    57: ("Dense freezing drizzle", "cloud-drizzle"),
    61: ("Slight rain", "cloud-rain"),
    63: ("Moderate rain", "cloud-rain"),
    65: ("Heavy rain", "cloud-rain"),
    66: ("Light freezing rain", "cloud-rain"),
    67: ("Heavy freezing rain", "cloud-rain"),
    71: ("Slight snow", "cloud-snow"),
    73: ("Moderate snow", "cloud-snow"),
    75: ("Heavy snow", "cloud-snow"),
    77: ("Snow grains", "cloud-snow"),
    80: ("Slight rain showers", "cloud-rain"),
    81: ("Moderate rain showers", "cloud-rain"),
    82: ("Violent rain showers", "cloud-rain"),
    85: ("Slight snow showers", "cloud-snow"),
    86: ("Heavy snow showers", "cloud-snow"),
    95: ("Thunderstorm", "cloud-lightning"),
    96: ("Thunderstorm with slight hail", "cloud-lightning"),
    99: ("Thunderstorm with heavy hail", "cloud-lightning"),
}


def _extract_search_terms(address: str) -> List[str]:
    """
    Extract candidate city/town names from an address string.
    Open-Meteo geocoding works best with just a city name.
    Try progressively simpler queries.
    """
    if not address:
        return []

    # Remove common noise: unit numbers, street numbers, postcodes
    import re
    clean = address.strip()

    # Split by comma and try parts (addresses often have "Street, Suburb, State")
    parts = [p.strip() for p in clean.split(",")]

    # Common Australian state abbreviations to skip as standalone searches
    state_abbrevs = {"VIC", "NSW", "QLD", "SA", "WA", "TAS", "NT", "ACT"}

    candidates = []

    # For "Street, Suburb, State" pattern: try suburb first (most reliable)
    if len(parts) >= 2:
        # Second part is usually the suburb/city - best candidate
        suburb = parts[1].strip()
        if suburb.upper() not in state_abbrevs and len(suburb) > 2:
            candidates.append(suburb)

    # Try each non-street, non-state part
    for i, p in enumerate(parts):
        stripped = re.sub(r'\d+\s*', '', p).strip()
        if stripped and len(stripped) > 2 and stripped.upper() not in state_abbrevs and stripped not in candidates:
            candidates.append(stripped)

    # Full address as last resort
    candidates.append(clean)

    return candidates


# Map timezone prefix to ISO country code
TIMEZONE_TO_COUNTRY = {
    "Australia": "AU",
    "Pacific/Auckland": "NZ",
    "Pacific/Fiji": "FJ",
    "Asia/Singapore": "SG",
    "Europe/London": "GB",
    "America/New_York": "US",
    "America/Chicago": "US",
    "America/Denver": "US",
    "America/Los_Angeles": "US",
}


def _country_from_timezone(timezone: str) -> Optional[str]:
    """Derive ISO country code from IANA timezone."""
    if not timezone:
        return None
    # Direct match
    if timezone in TIMEZONE_TO_COUNTRY:
        return TIMEZONE_TO_COUNTRY[timezone]
    # Match on prefix (e.g. "Australia/Sydney" → "Australia")
    prefix = timezone.split("/")[0]
    return TIMEZONE_TO_COUNTRY.get(prefix)


async def _geocode_address(address: str, country_code: str = None) -> Optional[Dict[str, float]]:
    """Geocode an address to lat/lon using Open-Meteo's geocoding API."""
    if not address or not address.strip():
        return None

    candidates = _extract_search_terms(address)

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Map country code to country name for filtering results
            country_names = {
                "AU": "Australia", "NZ": "New Zealand", "US": "United States",
                "GB": "United Kingdom", "SG": "Singapore", "FJ": "Fiji",
            }
            target_country = country_names.get(country_code, "") if country_code else ""

            for query in candidates:
                params = {"name": query, "count": 10, "language": "en", "format": "json"}

                response = await client.get(
                    "https://geocoding-api.open-meteo.com/v1/search",
                    params=params
                )
                if response.status_code == 200:
                    data = response.json()
                    results = data.get("results", [])
                    if not results:
                        continue

                    # Filter by country if we have one
                    best = None
                    if target_country:
                        for r in results:
                            if r.get("country", "").lower() == target_country.lower():
                                best = r
                                break

                    # Fall back to first result if no country match
                    if not best:
                        best = results[0]

                    # Build a full location string: "Randwick, New South Wales, Australia"
                    name_parts = [best.get("name", "")]
                    if best.get("admin1"):
                        name_parts.append(best["admin1"])
                    if best.get("country"):
                        name_parts.append(best["country"])
                    full_name = ", ".join(name_parts)

                    logger.info(f"Geocoded '{query}' (country={country_code}) → {full_name}")
                    return {
                        "latitude": best["latitude"],
                        "longitude": best["longitude"],
                        "name": full_name,
                    }
    except Exception as e:
        logger.warning(f"Geocoding failed for '{address}': {e}")
    return None


def _dominant_weather(codes_list):
    """Pick the most severe weather code from a list of hourly codes."""
    if not codes_list:
        return 0
    # Higher codes are generally more severe — take the max
    return max(codes_list)


async def _fetch_weather_from_api(
    latitude: float, longitude: float, start_date: date, end_date: date
) -> List[Dict[str, Any]]:
    """Fetch daily + hourly weather from Open-Meteo, split into AM/PM."""
    try:
        today = date.today()

        if end_date < today - timedelta(days=5):
            base_url = "https://archive-api.open-meteo.com/v1/archive"
        else:
            base_url = "https://api.open-meteo.com/v1/forecast"

        async with httpx.AsyncClient(timeout=15.0) as client:
            response = await client.get(
                base_url,
                params={
                    "latitude": latitude,
                    "longitude": longitude,
                    "start_date": start_date.isoformat(),
                    "end_date": end_date.isoformat(),
                    "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code,wind_speed_10m_max",
                    "hourly": "temperature_2m,weather_code,precipitation",
                    "timezone": "auto",
                }
            )

            if response.status_code != 200:
                logger.error(f"Open-Meteo API error: {response.status_code} - {response.text}")
                return []

            data = response.json()
            daily = data.get("daily", {})
            hourly = data.get("hourly", {})

            # Parse daily data
            dates = daily.get("time", [])
            temp_max = daily.get("temperature_2m_max", [])
            temp_min = daily.get("temperature_2m_min", [])
            precip = daily.get("precipitation_sum", [])
            codes = daily.get("weather_code", [])
            wind = daily.get("wind_speed_10m_max", [])

            # Parse hourly data into per-day AM/PM buckets
            hourly_times = hourly.get("time", [])          # "2026-03-23T00:00", etc.
            hourly_temps = hourly.get("temperature_2m", [])
            hourly_codes = hourly.get("weather_code", [])
            hourly_precip = hourly.get("precipitation", [])

            # Group hourly data by date
            # Morning = 6:00-10:59 (hours 6-10), Afternoon = 11:00-16:59 (hours 11-16)
            # Matches builder working hours: 6am-5pm
            day_hourly = {}
            for idx, time_str in enumerate(hourly_times):
                date_part = time_str[:10]
                hour = int(time_str[11:13])

                if date_part not in day_hourly:
                    day_hourly[date_part] = {
                        "am_temps": [], "am_codes": [], "am_precip": 0,
                        "pm_temps": [], "pm_codes": [], "pm_precip": 0,
                    }

                temp = hourly_temps[idx] if idx < len(hourly_temps) else None
                code = hourly_codes[idx] if idx < len(hourly_codes) else 0
                prec = hourly_precip[idx] if idx < len(hourly_precip) else 0

                if 6 <= hour <= 10:
                    if temp is not None:
                        day_hourly[date_part]["am_temps"].append(temp)
                    day_hourly[date_part]["am_codes"].append(code)
                    day_hourly[date_part]["am_precip"] += prec or 0
                elif 11 <= hour <= 16:
                    if temp is not None:
                        day_hourly[date_part]["pm_temps"].append(temp)
                    day_hourly[date_part]["pm_codes"].append(code)
                    day_hourly[date_part]["pm_precip"] += prec or 0

            results = []
            for i, d in enumerate(dates):
                code = codes[i] if i < len(codes) else 0
                desc, icon = WMO_CODES.get(code, ("Unknown", "cloud"))

                result = {
                    "date": d,
                    "temperature_max": temp_max[i] if i < len(temp_max) else None,
                    "temperature_min": temp_min[i] if i < len(temp_min) else None,
                    "precipitation_mm": precip[i] if i < len(precip) else 0,
                    "weather_code": code,
                    "weather_description": desc,
                    "weather_icon": icon,
                    "wind_speed_max": wind[i] if i < len(wind) else None,
                }

                # Add AM/PM breakdown
                h = day_hourly.get(d, {})

                am_code = _dominant_weather(h.get("am_codes", []))
                am_desc, am_icon = WMO_CODES.get(am_code, ("Unknown", "cloud"))
                am_temps = h.get("am_temps", [])
                result["am_weather_code"] = am_code
                result["am_weather_description"] = am_desc
                result["am_weather_icon"] = am_icon
                result["am_temp"] = round(max(am_temps), 1) if am_temps else None
                result["am_precipitation_mm"] = round(h.get("am_precip", 0), 1)

                pm_code = _dominant_weather(h.get("pm_codes", []))
                pm_desc, pm_icon = WMO_CODES.get(pm_code, ("Unknown", "cloud"))
                pm_temps = h.get("pm_temps", [])
                result["pm_weather_code"] = pm_code
                result["pm_weather_description"] = pm_desc
                result["pm_weather_icon"] = pm_icon
                result["pm_temp"] = round(max(pm_temps), 1) if pm_temps else None
                result["pm_precipitation_mm"] = round(h.get("pm_precip", 0), 1)

                results.append(result)

            return results

    except Exception as e:
        import traceback
        logger.error(f"Failed to fetch weather from Open-Meteo: {e}\n{traceback.format_exc()}")
        return []


async def _get_cached_weather(site_id: str, start_date: str, end_date: str) -> tuple:
    """Check Supabase cache for weather data. Returns (dict keyed by date, location string)."""
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/weather_cache",
                headers={
                    "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}"
                },
                params={
                    "site_id": f"eq.{site_id}",
                    "and": f"(date.gte.{start_date},date.lte.{end_date})",
                    "select": "date,temperature_max,temperature_min,precipitation_mm,weather_code,weather_description,wind_speed_max,geocoded_location,am_weather_code,am_weather_description,am_temp,am_precipitation_mm,pm_weather_code,pm_weather_description,pm_temp,pm_precipitation_mm"
                }
            )
            if response.status_code == 200:
                rows = response.json()
                location = ""
                for r in rows:
                    if r.get("geocoded_location"):
                        location = r["geocoded_location"]
                return {r["date"]: r for r in rows}, location
    except Exception as e:
        logger.warning(f"Weather cache lookup failed: {e}")
    return {}, ""


async def _save_weather_to_cache(site_id: str, days: List[Dict[str, Any]], location: str = ""):
    """Save weather data to Supabase cache."""
    if not days:
        return
    try:
        rows = []
        for d in days:
            rows.append({
                "site_id": site_id,
                "date": d["date"],
                "temperature_max": d.get("temperature_max"),
                "temperature_min": d.get("temperature_min"),
                "precipitation_mm": d.get("precipitation_mm", 0),
                "weather_code": d.get("weather_code", 0),
                "weather_description": d.get("weather_description", ""),
                "wind_speed_max": d.get("wind_speed_max"),
                "geocoded_location": location,
                "am_weather_code": d.get("am_weather_code"),
                "am_weather_description": d.get("am_weather_description", ""),
                "am_temp": d.get("am_temp"),
                "am_precipitation_mm": d.get("am_precipitation_mm", 0),
                "pm_weather_code": d.get("pm_weather_code"),
                "pm_weather_description": d.get("pm_weather_description", ""),
                "pm_temp": d.get("pm_temp"),
                "pm_precipitation_mm": d.get("pm_precipitation_mm", 0),
            })

        async with httpx.AsyncClient(timeout=10.0) as client:
            # Upsert using Prefer header
            await client.post(
                f"{os.getenv('SUPABASE_URL')}/rest/v1/weather_cache",
                headers={
                    "apikey": os.getenv("SUPABASE_SERVICE_KEY"),
                    "Authorization": f"Bearer {os.getenv('SUPABASE_SERVICE_KEY')}",
                    "Content-Type": "application/json",
                    "Prefer": "resolution=merge-duplicates,return=minimal"
                },
                json=rows
            )
            logger.info(f"Cached weather for site={site_id}, {len(rows)} days")
    except Exception as e:
        logger.warning(f"Failed to cache weather (non-fatal): {e}")


async def get_weather_for_site(
    site_id: str, site_address: str, start_date: str, end_date: str,
    tenant_timezone: str = "",
) -> Dict[str, Dict[str, Any]]:
    """
    Get daily weather for a site, using cache where possible.

    Returns dict keyed by ISO date string:
    {
        "2026-03-24": {
            "temperature_max": 28.5,
            "temperature_min": 16.2,
            "precipitation_mm": 0.0,
            "weather_code": 1,
            "weather_description": "Mainly clear",
            "weather_icon": "sun",
            "wind_speed_max": 15.3
        }
    }
    """
    from datetime import date as date_type
    d_start = date_type.fromisoformat(start_date)
    d_end = date_type.fromisoformat(end_date)
    today = date_type.today()

    # Cap end date to yesterday — we only want actual observed weather, not forecasts
    # For today, the morning may be complete but afternoon not yet — include today
    # but it will be re-fetched next time once the day is complete
    effective_end = min(d_end, today)
    if effective_end < d_start:
        # Entire range is in the future — no weather to show
        return {"_meta": {"location": "", "source": ""}}

    effective_end_str = effective_end.isoformat()
    effective_start_str = d_start.isoformat()

    # Check cache first
    cached, cached_location = await _get_cached_weather(site_id, effective_start_str, effective_end_str)

    # For dates that include today or yesterday, always re-fetch
    # because cached data for recent days may have been forecast, not actual
    force_refetch = effective_end >= today - timedelta(days=1)

    # Figure out which dates we're missing
    missing_dates = []
    current = d_start
    while current <= effective_end:
        if current.isoformat() not in cached:
            missing_dates.append(current)
        current += timedelta(days=1)

    if not missing_dates and not force_refetch:
        # All cached — add icon fields from WMO codes
        for d_str, data in cached.items():
            code = data.get("weather_code", 0)
            _, icon = WMO_CODES.get(code, ("Unknown", "cloud"))
            data["weather_icon"] = icon
            # AM/PM icons
            am_code = data.get("am_weather_code", 0) or 0
            _, am_icon = WMO_CODES.get(am_code, ("Unknown", "cloud"))
            data["am_weather_icon"] = am_icon
            pm_code = data.get("pm_weather_code", 0) or 0
            _, pm_icon = WMO_CODES.get(pm_code, ("Unknown", "cloud"))
            data["pm_weather_icon"] = pm_icon
        cached["_meta"] = {"location": cached_location, "source": "cache"}
        return cached

    # Need to fetch from API — geocode the address first
    country_code = _country_from_timezone(tenant_timezone)
    geo = await _geocode_address(site_address, country_code=country_code)
    if not geo:
        logger.warning(f"Could not geocode address '{site_address}' - no weather data")
        cached["_meta"] = {"location": "Unable to locate", "source": ""}
        return cached  # Return whatever we have

    location_name = geo.get("name", "")

    # Fetch up to effective_end only (no future forecasts)
    api_data = await _fetch_weather_from_api(
        geo["latitude"], geo["longitude"], d_start, effective_end
    )

    if api_data:
        # Cache the new data (with location) — overwrites stale forecast data
        await _save_weather_to_cache(site_id, api_data, location=location_name)

        # Merge with any cached data
        result = dict(cached)
        for day in api_data:
            result[day["date"]] = day
        result["_meta"] = {"location": location_name, "source": "open-meteo"}
        return result

    cached["_meta"] = {"location": location_name, "source": ""}
    return cached
