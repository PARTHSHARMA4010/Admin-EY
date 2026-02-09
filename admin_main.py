from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Optional
from bson import ObjectId
from datetime import datetime
import os
from dotenv import load_dotenv


load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME")

client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME]
admin_collection = db.service_centers

# 1. Initialize Independent App
app = FastAPI()

# 2. Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 3. Connect to Database
# REPLACE WITH YOUR ACTUAL MONGO STRING IF DIFFERENT
MONGO_URI = "mongodb+srv://jmdayushkumar_db_user:6oe935cfRww7fQZP@cluster0.iii0dcr.mongodb.net/?appName=Cluster0"
client = AsyncIOMotorClient(MONGO_URI)
db = client.auto_ai_db
admin_collection = db.service_centers

# --- 4. DATA MODELS ---

# A. Booking Sub-Model (Stored inside Service Center)
class Booking(BaseModel):
    booking_id: str
    vehicle_id: str
    issue: str              # e.g., "Brake Failure"
    part_required: Optional[str] = None # e.g., "Brake Pads Batch-404"
    date: str               # e.g., "2026-02-15"
    status: str = "SCHEDULED" # SCHEDULED, COMPLETED, CANCELLED

# B. Main Service Center Model
class ServiceCenter(BaseModel):
    centerId: str           # e.g., "SC-DEL-01"
    name: str               # e.g., "Hero Hub Delhi"
    location: str           # e.g., "Delhi"
    phone: str              # e.g., "9988776655"
    capacity: int           # e.g., 20
    
    # ✅ NEW FIELDS
    specializations: List[str] = [] # e.g., ["Engine", "EV Battery", "Body Shop"]
    bookings: List[Booking] = []    # Stores the list of vehicles booked here

    is_active: bool = True

# --- HELPER FUNCTION ---
def fix_id(document):
    document["_id"] = str(document["_id"])
    return document

# ==========================
# 5. ADMIN API ENDPOINTS
# ==========================

@app.get("/")
def home():
    return {"message": "Admin API is Online"}

# API 1: Register a Service Center (With Specialization)
@app.post("/register-center")
async def register_center(center: ServiceCenter):
    # Check if ID exists
    existing = await admin_collection.find_one({"centerId": center.centerId})
    if existing:
        raise HTTPException(status_code=400, detail="Center ID already exists")
    
    # Save
    new_center = center.dict()
    result = await admin_collection.insert_one(new_center)
    return {"message": "Registered Successfully", "id": str(result.inserted_id)}

# API 2: Add a Booking to a Center (Called by User App)
# @app.post("/book-slot/{center_id}")
# async def book_slot(center_id: str, booking: Booking):
#     # 1. Find the center
#     center = await admin_collection.find_one({"centerId": center_id})
#     if not center:
#         raise HTTPException(status_code=404, detail="Service Center Not Found")
    
#     # 2. Check Capacity (Simple Logic)
#     if len(center.get("bookings", [])) >= center["capacity"]:
#          raise HTTPException(status_code=400, detail="Center is Full for Today")

#     # 3. Add Booking to the list
#     new_booking = booking.dict()
#     await admin_collection.update_one(
#         {"centerId": center_id},
#         {"$push": {"bookings": new_booking}}
#     )

#     return {"message": "Slot Booked Successfully", "booking_id": booking.booking_id}

# API 3: Get All Centers (Admin View)
@app.get("/get-all-centers")
async def get_all_centers():
    centers = []
    cursor = admin_collection.find({})
    async for doc in cursor:
        centers.append(fix_id(doc))
    return centers

# API 4: Get Specific Center Details (Including Bookings)
@app.get("/get-center-details/{center_id}")
async def get_center_details(center_id: str):
    center = await admin_collection.find_one({"centerId": center_id})
    if center:
        return fix_id(center)
    raise HTTPException(status_code=404, detail="Center Not Found")