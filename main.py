from fastapi import FastAPI, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from motor.motor_asyncio import AsyncIOMotorClient
from typing import List, Optional, Dict
from bson import ObjectId
from datetime import datetime
import os
from dotenv import load_dotenv

load_dotenv()

MONGO_URI = os.getenv("MONGO_URI")
DB_NAME = os.getenv("DB_NAME", "auto_ai_db") 

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
client = AsyncIOMotorClient(MONGO_URI)
db = client[DB_NAME] 

# Collections
admin_collection = db.service_centers
vendor_collection = db.vendors          # ✅ NEW: Stores Vendor Profiles
batch_collection = db.batches           # ✅ NEW: Stores Supply Batches

# --- 4. DATA MODELS ---

# --- A. EXISTING MODELS (Service Center) ---
class Booking(BaseModel):
    booking_id: str
    vehicle_id: str
    issue: str              
    part_required: Optional[str] = None 
    date: str               
    status: str = "SCHEDULED" 
    
    # ✅ NEW: RCA Tracking Fields
    replaced_part_sku: Optional[str] = None      # e.g., "90919-01191"
    failure_type: Optional[str] = "NORMAL_WEAR"  # Options: "PREMATURE_FAILURE", "NORMAL_WEAR", "ACCIDENTAL"
    source_batch_id: Optional[str] = None        # e.g., "TOYOTA_202403A001" (Links failure to a batch)

class ServiceCenter(BaseModel):
    centerId: str           
    name: str               
    location: str           
    phone: str              
    capacity: int           
    specializations: List[str] = [] 
    bookings: List[Booking] = []    
    is_active: bool = True

# --- B. NEW MODELS (Vendor & Supply Chain) ---

class Vendor(BaseModel):
    vendor_id: str          # e.g., "V-DENSO-09"
    name: str               # e.g., "Denso Corporation"
    category: str           # e.g., "Electronics"
    contact: str
    # Performance is calculated dynamically, but we can store a snapshot
    durability_score: float = 100.0 

class BatchPart(BaseModel):
    part_sku: str           # e.g., "90919-01191"
    part_name: str
    quantity: int           # Total supplied
    failures_logged: int = 0 # Starts at 0, increases when we find bad parts!

class BatchAllocation(BaseModel):
    batch_allocation_id: str # e.g., "TOYOTA_202403A001"
    company_name: str
    vendor_details: Dict     # Stores snapshot of vendor info
    batch_info: Dict         # Stores dates/batch numbers
    parts_manifest: List[BatchPart] # The list of parts in this box

# --- HELPER FUNCTION ---
def fix_id(document):
    if document:
        document["_id"] = str(document["_id"])
    return document

# ==========================
# 5. ADMIN API ENDPOINTS
# ==========================

@app.get("/")
def home():
    return {"message": "Admin API with Vendor Tracing is Online"}

# --- EXISTING ENDPOINTS ---

@app.post("/register-center")
async def register_center(center: ServiceCenter):
    existing = await admin_collection.find_one({"centerId": center.centerId})
    if existing:
        raise HTTPException(status_code=400, detail="Center ID already exists")
    new_center = center.dict()
    result = await admin_collection.insert_one(new_center)
    return {"message": "Registered Successfully", "id": str(result.inserted_id)}

@app.get("/get-all-centers")
async def get_all_centers():
    centers = []
    cursor = admin_collection.find({})
    async for doc in cursor:
        centers.append(fix_id(doc))
    return centers

@app.get("/get-center-details/{center_id}")
async def get_center_details(center_id: str):
    center = await admin_collection.find_one({"centerId": center_id})
    if center:
        return fix_id(center)
    raise HTTPException(status_code=404, detail="Center Not Found")

@app.get("/get-center-by-name/{name}")
async def get_center_by_name(name: str):
    center = await admin_collection.find_one({"name": {"$regex": f"^{name}$", "$options": "i"}})
    if center:
        return fix_id(center)
    raise HTTPException(status_code=404, detail="Service Center with this name not found")

# --- ✅ NEW ENDPOINTS: VENDOR & RCA SYSTEM ---

# API 5: Register a Vendor (Supplier)
@app.post("/register-vendor")
async def register_vendor(vendor: Vendor):
    existing = await vendor_collection.find_one({"vendor_id": vendor.vendor_id})
    if existing:
        raise HTTPException(status_code=400, detail="Vendor ID already exists")
    
    result = await vendor_collection.insert_one(vendor.dict())
    return {"message": "Vendor Registered", "id": str(result.inserted_id)}

# API 6: Add a Batch (The JSON you provided)
@app.post("/add-batch")
async def add_batch(batch: BatchAllocation):
    # 1. Check if Batch ID exists
    existing = await batch_collection.find_one({"batch_allocation_id": batch.batch_allocation_id})
    if existing:
        raise HTTPException(status_code=400, detail="Batch ID already exists")
    
    # 2. Save the batch
    result = await batch_collection.insert_one(batch.dict())
    return {"message": "Batch Logged Successfully", "id": str(result.inserted_id)}

# API 7: Report a Failure (This updates the Vendor Score!)
# Usage: When a mechanic marks a job as "COMPLETED" and sees a broken part.
@app.post("/report-failure")
async def report_failure(
    batch_id: str = Body(..., embed=True), 
    part_sku: str = Body(..., embed=True)
):
    # 1. Find the Batch
    batch = await batch_collection.find_one({"batch_allocation_id": batch_id})
    if not batch:
        raise HTTPException(status_code=404, detail="Batch not found")

    # 2. Update the specific part in the batch (Increment failure count)
    result = await batch_collection.update_one(
        {"batch_allocation_id": batch_id, "parts_manifest.part_sku": part_sku},
        {"$inc": {"parts_manifest.$.failures_logged": 1}}
    )
    
    if result.modified_count == 0:
        raise HTTPException(status_code=400, detail="Part SKU not found in this batch")

    # 3. (Optional) Recalculate Vendor Score Logic here
    # For now, we just increment the failure counter.
    
    return {"message": "Failure Logged. Vendor Durability Score Impacted."}

# API 8: Get Vendor Analytics (The Traceability Dashboard)
@app.get("/vendor-analytics/{vendor_id}")
async def get_vendor_analytics(vendor_id: str):
    # 1. Get Vendor Info
    vendor = await vendor_collection.find_one({"vendor_id": vendor_id})
    if not vendor:
        raise HTTPException(status_code=404, detail="Vendor not found")
        
    # 2. Get All Batches from this Vendor
    # We search inside the 'vendor_details' object in the batch
    batches = []
    total_parts_supplied = 0
    total_failures = 0
    
    cursor = batch_collection.find({"vendor_details.vendor_id": vendor_id})
    async for batch in cursor:
        batches.append(fix_id(batch))
        for part in batch["parts_manifest"]:
            total_parts_supplied += part["quantity"]
            total_failures += part["failures_logged"]

    # 3. Calculate Real-World Durability Score
    # Score = Percentage of parts that survived
    score = 100.0
    if total_parts_supplied > 0:
        score = ((total_parts_supplied - total_failures) / total_parts_supplied) * 100

    return {
        "vendor_name": vendor["name"],
        "calculated_durability_score": round(score, 2),
        "total_parts_supplied": total_parts_supplied,
        "total_failures_detected": total_failures,
        "batches_analyzed": len(batches)
    }