import httpx

# Check what models exist for Jeep 2013
r = httpx.get(
    'https://www.fueleconomy.gov/ws/rest/vehicle/menu/model',
    params={'year': '2013', 'make': 'Jeep'},
    headers={'Accept': 'application/json'}
)

print("Models for 2013 Jeep:")
print(r.json())


