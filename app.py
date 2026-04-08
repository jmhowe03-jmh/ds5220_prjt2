import io
import logging
import os
from datetime import datetime, timezone
from decimal import Decimal

import boto3
import matplotlib
import matplotlib.pyplot as plt
import openmeteo_requests
import pandas as pd
import requests_cache
import seaborn as sns
from boto3.dynamodb.conditions import Key
from retry_requests import retry

matplotlib.use("Agg")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
LATITUDE   = 43.23
LONGITUDE  = -76.14
LOCATION_ID = "OSWEGO_NY"  # logical key stored in DynamoDB

TABLE_NAME = os.environ["DYNAMODB_TABLE"]
S3_BUCKET  = os.environ["S3_BUCKET"]
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")

# Thresholds for weather-change alerts
TEMP_SPIKE_C   = Decimal("5.0")   # °C change in one interval flagged as a spike
HUMID_SPIKE_PCT = Decimal("20.0") # % RH change in one interval flagged as a spike


# ---------------------------------------------------------------------------
# Step 1 — Fetch current weather data from Open-Meteo
# ---------------------------------------------------------------------------
def fetch_weather() -> dict:
    """Return a DynamoDB-ready item with the current weather state."""
    cache_session = requests_cache.CachedSession(".cache", expire_after=900)  # 15-min cache
    retry_session = retry(cache_session, retries=5, backoff_factor=0.2)
    openmeteo    = openmeteo_requests.Client(session=retry_session)

    url    = "https://api.open-meteo.com/v1/forecast"
    params = {
        "latitude":    LATITUDE,
        "longitude":   LONGITUDE,
        "current":     ["temperature_2m", "relative_humidity_2m"],
        "minutely_15": ["temperature_2m", "relative_humidity_2m"],
        "models":      "meteofrance_seamless",
        "timezone":    "auto",
    }

    responses = openmeteo.weather_api(url, params=params)
    response  = responses[0]

    current = response.Current()
    temp_c  = current.Variables(0).Value()   # temperature_2m
    rh_pct  = current.Variables(1).Value()   # relative_humidity_2m

    log.info(
        "API | lat=%.4f lon=%.4f | temp=%.2f°C | rh=%.1f%%",
        response.Latitude(), response.Longitude(), temp_c, rh_pct,
    )

    return {
        "location_id":    LOCATION_ID,
        "timestamp":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "latitude":       Decimal(str(round(response.Latitude(),  6))),
        "longitude":      Decimal(str(round(response.Longitude(), 6))),
        "elevation_m":    Decimal(str(round(response.Elevation(), 1))),
        "temperature_c":  Decimal(str(round(temp_c, 2))),
        "humidity_pct":   Decimal(str(round(rh_pct, 1))),
        "utc_offset_sec": int(response.UtcOffsetSeconds()),
    }


# ---------------------------------------------------------------------------
# Step 2 — Query DynamoDB for the most recent previous entry
# ---------------------------------------------------------------------------
def get_previous(table) -> dict | None:
    """Return the latest stored item for this location, or None on first run."""
    resp = table.query(
        KeyConditionExpression=Key("location_id").eq(LOCATION_ID),
        ScanIndexForward=False,  # newest first
        Limit=1,
    )
    items = resp.get("Items", [])
    return items[0] if items else None


# ---------------------------------------------------------------------------
# Step 3 — Compare current readings to previous entry
# ---------------------------------------------------------------------------
def weather_analysis(
    current: dict,
    previous: dict | None,
) -> tuple[str, Decimal, Decimal]:
    """Return (trend_label, delta_temp_c, delta_humidity_pct).

    Trend labels:
      FIRST_ENTRY    — no prior data
      STABLE         — both metrics within normal variance
      WARMING        — temperature rising noticeably
      COOLING        — temperature dropping noticeably
      TEMP_SPIKE     — abrupt temperature jump >= TEMP_SPIKE_C (front passage)
      HUMID_SPIKE    — abrupt humidity jump >= HUMID_SPIKE_PCT
      WARMING_DRYING — getting warmer AND drier simultaneously
      COOLING_HUMID  — getting cooler AND more humid (precipitation likely)
    """
    if previous is None:
        return "FIRST_ENTRY", Decimal("0"), Decimal("0")

    delta_t = current["temperature_c"] - Decimal(str(previous["temperature_c"]))
    delta_h = current["humidity_pct"]  - Decimal(str(previous["humidity_pct"]))

    if abs(delta_t) >= TEMP_SPIKE_C:
        trend = "TEMP_SPIKE"
    elif abs(delta_h) >= HUMID_SPIKE_PCT:
        trend = "HUMID_SPIKE"
    elif delta_t > Decimal("0.5") and delta_h < Decimal("-2"):
        trend = "WARMING_DRYING"
    elif delta_t < Decimal("-0.5") and delta_h > Decimal("2"):
        trend = "COOLING_HUMID"
    elif delta_t > Decimal("0.5"):
        trend = "WARMING"
    elif delta_t < Decimal("-0.5"):
        trend = "COOLING"
    else:
        trend = "STABLE"

    return trend, delta_t, delta_h


# ---------------------------------------------------------------------------
# Step 4 — Fetch full history from DynamoDB for plotting
# ---------------------------------------------------------------------------
def fetch_history(table) -> pd.DataFrame:
    """Return all stored records as a DataFrame, sorted by timestamp.
    Handles DynamoDB pagination so the full history is always returned.
    """
    items, kwargs = [], dict(
        KeyConditionExpression=Key("location_id").eq(LOCATION_ID),
        ScanIndexForward=True,
    )
    while True:
        resp = table.query(**kwargs)
        items.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            break
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]

    if not items:
        return pd.DataFrame()

    df = pd.DataFrame(items)
    df["timestamp"]     = pd.to_datetime(df["timestamp"])
    df["temperature_c"] = df["temperature_c"].astype(float)
    df["humidity_pct"]  = df["humidity_pct"].astype(float)
    df["delta_temp_c"]  = df["delta_temp_c"].astype(float)
    df["delta_humid"]   = df["delta_humid"].astype(float)
    return df.sort_values("timestamp").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Step 5 — Render dual-axis temperature + humidity plot
# ---------------------------------------------------------------------------
def generate_plot(df: pd.DataFrame) -> io.BytesIO | None:
    """Plot temperature and humidity over time, annotating weather events."""
    if df.empty or len(df) < 2:
        log.info("Not enough history to plot yet (%d point(s))", len(df))
        return None

    sns.set_theme(style="darkgrid", context="talk", font_scale=0.9)

    fig, ax1 = plt.subplots(figsize=(14, 6))
    ax2 = ax1.twinx()

    # --- Temperature line (left axis) ---
    sns.lineplot(
        data=df, x="timestamp", y="temperature_c",
        ax=ax1, color="#FF6B35", linewidth=2.5, zorder=2, label="Temp (°C)",
    )
    ax1.fill_between(
        df["timestamp"], df["temperature_c"],
        df["temperature_c"].min() - 1,
        alpha=0.10, color="#FF6B35",
    )

    # --- Humidity line (right axis) ---
    sns.lineplot(
        data=df, x="timestamp", y="humidity_pct",
        ax=ax2, color="#4FC3F7", linewidth=2.0, linestyle="--",
        zorder=2, label="Humidity (%)",
    )

    # --- Highlight weather events ---
    event_map = {
        "TEMP_SPIKE":  ("⚡", "#FFD700", "Temp spike"),
        "HUMID_SPIKE": ("💧", "#00BFFF", "Humid spike"),
        "COOLING_HUMID": ("🌧", "#90EE90", "Cooling + humid"),
        "WARMING_DRYING": ("☀️", "#FFA500", "Warming + drying"),
    }
    for event, (emoji, color, label) in event_map.items():
        subset = df[df["trend"] == event]
        if subset.empty:
            continue
        ax1.scatter(
            subset["timestamp"], subset["temperature_c"],
            color=color, s=120, zorder=4, label=f"{label} ({len(subset)})",
        )
        for _, row in subset.iterrows():
            ax1.annotate(
                emoji,
                xy=(row["timestamp"], row["temperature_c"]),
                xytext=(0, 14), textcoords="offset points",
                ha="center", fontsize=15, zorder=5,
            )

    # --- Labels & formatting ---
    ax1.set_title(
        f"Weather — {LOCATION_ID.replace('_', ' ').title()}\n"
        f"Last updated: {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}",
        fontsize=14, fontweight="bold", pad=14,
    )
    ax1.set_xlabel("Time (UTC)", labelpad=8)
    ax1.set_ylabel("Temperature (°C)", color="#FF6B35", labelpad=8)
    ax2.set_ylabel("Relative Humidity (%)", color="#4FC3F7", labelpad=8)
    ax1.tick_params(axis="y", labelcolor="#FF6B35")
    ax2.tick_params(axis="y", labelcolor="#4FC3F7")
    ax2.set_ylim(0, 105)

    # Merge legends from both axes
    lines1, labels1 = ax1.get_legend_handles_labels()
    lines2, labels2 = ax2.get_legend_handles_labels()
    ax1.legend(lines1 + lines2, labels1 + labels2,
               loc="upper left", fontsize=9, framealpha=0.85, edgecolor="#555555")
    ax2.get_legend().remove() if ax2.get_legend() else None

    sns.despine(ax=ax1, top=True)
    sns.despine(ax=ax2, top=True, left=True)
    fig.autofmt_xdate(rotation=25, ha="right")
    plt.tight_layout()

    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
    buf.seek(0)
    plt.close(fig)
    log.info("Plot generated (%d bytes, %d points)", len(buf.getvalue()), len(df))
    return buf


# ---------------------------------------------------------------------------
# Step 6 — Upload plot to S3
# ---------------------------------------------------------------------------
def push_plot(buf: io.BytesIO) -> None:
    s3 = boto3.client("s3", region_name=AWS_REGION)
    key = f"weather/{LOCATION_ID.lower()}-weather.png"
    s3.put_object(
        Bucket=S3_BUCKET,
        Key=key,
        Body=buf.getvalue(),
        ContentType="image/png",
    )
    log.info("Uploaded %s to s3://%s", key, S3_BUCKET)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    dynamodb = boto3.resource("dynamodb", region_name=AWS_REGION)
    table    = dynamodb.Table(TABLE_NAME)

    previous               = get_previous(table)
    entry                  = fetch_weather()
    trend, delta_t, delta_h = weather_analysis(entry, previous)

    entry["trend"]       = trend
    entry["delta_temp_c"] = delta_t
    entry["delta_humid"]  = delta_h

    table.put_item(Item=entry)

    if trend == "FIRST_ENTRY":
        log.info(
            "WEATHER | temp=%.2f°C | rh=%.1f%% | FIRST ENTRY",
            entry["temperature_c"], entry["humidity_pct"],
        )
    else:
        alert = "  *** WEATHER EVENT ***" if trend in (
            "TEMP_SPIKE", "HUMID_SPIKE", "COOLING_HUMID", "WARMING_DRYING"
        ) else ""
        log.info(
            "WEATHER | temp=%.2f°C (Δ%+.2f) | rh=%.1f%% (Δ%+.1f) | %-16s%s",
            entry["temperature_c"], delta_t,
            entry["humidity_pct"],  delta_h,
            trend, alert,
        )

    history  = fetch_history(table)
    plot_buf = generate_plot(history)
    if plot_buf:
        push_plot(plot_buf)


if __name__ == "__main__":
    main()