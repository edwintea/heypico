from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import httpx
import os
from dotenv import load_dotenv


load_dotenv()

app = FastAPI()

GOOGLE_MAPS_API_KEY = os.getenv("GOOGLE_MAPS_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("OPENAI_API_KEY not set")

MY_API_KEY = os.getenv("MY_API_KEY")

# Configure CORS origins (adjust as needed)
origins = [
    "http://localhost:3000",  # React app origin
    # Add other allowed origins here if needed
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Models
class UserPrompt(BaseModel):
    query: str
    location: str  # Only address/location name, no lat/lng

# Security dependency to check API key in header
async def verify_api_key(heypico_api_key: str = Header(...)):
    if heypico_api_key != MY_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid or missing API key")

# Helper function to call OpenAI to refine the query
async def query_llm(prompt: str) -> str:
    url = "https://api.openai.com/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENAI_API_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": "gpt-4",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": 50,
        "temperature": 0.7
    }
    async with httpx.AsyncClient() as client:
        response = await client.post(url, json=data, headers=headers)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"].strip()

# Helper function to geocode location string to lat,lng
async def geocode_location(location: str):
    geocode_url = (
        f"https://maps.googleapis.com/maps/api/geocode/json"
        f"?address={location}&key={GOOGLE_MAPS_API_KEY}"
    )

    print(geocode_url);
    async with httpx.AsyncClient() as client:
        geo_resp = await client.get(geocode_url)
        geo_resp.raise_for_status()
        geo_data = geo_resp.json()
        if geo_data["status"] != "OK" or not geo_data["results"]:
            raise HTTPException(status_code=400, detail="Invalid location")
        loc = geo_data["results"][0]["geometry"]["location"]
        return loc["lat"], loc["lng"]

# Helper function to search places using Google Maps Places API
async def search_places(query: str, lat: float, lng: float):
    places_url = (
        f"https://maps.googleapis.com/maps/api/place/nearbysearch/json"
        f"?location={lat},{lng}&radius=5000&keyword={query}&key={GOOGLE_MAPS_API_KEY}"
    )
    async with httpx.AsyncClient() as client:
        resp = await client.get(places_url)
        resp.raise_for_status()
        places_data = resp.json()
        if places_data["status"] != "OK":
            raise HTTPException(status_code=400, detail="Places API error")
        return places_data["results"]

@app.post("/search_places", dependencies=[Depends(verify_api_key)])
async def search_places_endpoint(user_prompt: UserPrompt):
    # Instead of refining the query with OpenAI, use the original query directly
    refined_query = user_prompt.query

    # Geocode the location string to lat,lng
    lat, lng = await geocode_location(user_prompt.location)

    # Search places with the original query and geocoded location
    places = await search_places(refined_query, lat, lng)

    results = []
    for place in places[:5]:  # limit to 5 results
        place_id = place["place_id"]
        name = place.get("name")
        address = place.get("vicinity")
        lat_p = place["geometry"]["location"]["lat"]
        lng_p = place["geometry"]["location"]["lng"]

        embed_url = (
            f"https://www.google.com/maps/embed/v1/place?key={GOOGLE_MAPS_API_KEY}"
            f"&q=place_id:{place_id}"
        )

        directions_url = (
            f"https://www.google.com/maps/dir/?api=1&destination={lat_p},{lng_p}"
        )

        results.append({
            "name": name,
            "address": address,
            "embed_map_url": embed_url,
            "directions_url": directions_url
        })

    return {"results": results}

