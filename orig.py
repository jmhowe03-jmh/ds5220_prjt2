import openmeteo_requests

import pandas as pd
import requests_cache
from retry_requests import retry
from datetime import datetime, timezone
import os



TABLE_NAME   = os.environ["DYNAMODB_TABLE"]
S3_BUCKET    = os.environ["S3_BUCKET"]
AWS_REGION   = os.environ.get("AWS_REGION", "us-east-1")



##########################
# Step 1 — Fetch current weather data from Open-Meteo
##########################
#https://open-meteo.com/en/docs/meteofrance-api?minutely_15=temperature_2m,relative_humidity_2m&current=temperature_2m,relative_humidity_2m
# Setup the Open-Meteo API client with cache and retry on error
cache_session = requests_cache.CachedSession('.cache', expire_after = 3600)
retry_session = retry(cache_session, retries = 5, backoff_factor = 0.2)
openmeteo = openmeteo_requests.Client(session = retry_session)

LATITUDE = 43.23
LONGITUDE = -76.14

# Make sure all required weather variables are listed here
# The order of variables in hourly or daily is important to assign them correctly below
url = "https://api.open-meteo.com/v1/forecast"
params = {
	"latitude": LATITUDE,
	"longitude": LONGITUDE,
	"hourly": "temperature_2m",
	"models": "meteofrance_seamless",
	"current": ["temperature_2m", "relative_humidity_2m"],
	"minutely_15": ["temperature_2m", "relative_humidity_2m"],
    "timezone": "auto",
}
responses = openmeteo.weather_api(url, params = params)

'''
# Process first location. Add a for-loop for multiple locations or weather models
response = responses[0]
print(f"Coordinates: {response.Latitude()}°N {response.Longitude()}°E")
print(f"Elevation: {response.Elevation()} m asl")
print(f"Timezone difference to GMT+0: {response.UtcOffsetSeconds()}s")

# Process current data. The order of variables needs to be the same as requested.
current = response.Current()
current_temperature_2m = current.Variables(0).Value()
current_relative_humidity_2m = current.Variables(1).Value()

print(f"\nCurrent time: {current.Time()}")
print(datetime.fromtimestamp(current.Time()))
print(f"Current temperature_2m: {current_temperature_2m}")
print(f"Current relative_humidity_2m: {current_relative_humidity_2m}")

'''

##########################
# Step 1 — Fetch current weather data from Open-Meteo
##########################


