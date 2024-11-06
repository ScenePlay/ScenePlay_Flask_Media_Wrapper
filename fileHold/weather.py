import requests
api_url = "https://api.open-meteo.com/v1/forecast?latitude=27.64&longitude=-80.36&hourly=temperature_2m,precipitation&temperature_unit=fahrenheit&windspeed_unit=mph&precipitation_unit=inch&timezone=America%2FNew_York"
response = requests.get(api_url)
print (response.json())
