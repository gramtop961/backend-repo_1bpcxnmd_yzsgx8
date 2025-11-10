import os
from datetime import datetime, timedelta, timezone
from typing import List, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import Idea, Comment, Vote

app = FastAPI(title="Vibe Ideas API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Utility to convert Mongo documents

def serialize_doc(doc):
    d = dict(doc)
    d["id"] = str(d.pop("_id"))
    # Ensure created_at/updated_at are isoformat strings
    if "created_at" in d and hasattr(d["created_at"], "isoformat"):
        d["created_at"] = d["created_at"].isoformat()
    if "updated_at" in d and hasattr(d["updated_at"], "isoformat"):
        d["updated_at"] = d["updated_at"].isoformat()
    return d

class CreateIdea(BaseModel):
    title: str = Field(..., min_length=3, max_length=120)
    description: str = Field(..., min_length=10, max_length=1000)
    link: Optional[str] = None

class CreateComment(BaseModel):
    post_id: str
    author: str = Field(..., min_length=1, max_length=60)
    text: str = Field(..., min_length=1, max_length=500)

@app.get("/")
async def root():
    return {"message": "Vibe Ideas API running"}

@app.get("/test")
async def test_database():
    info = {
        "backend": "running",
        "database": "not connected" if db is None else "connected",
        "collections": []
    }
    try:
        if db is not None:
            info["collections"] = db.list_collection_names()
    except Exception as e:
        info["error"] = str(e)
    return info

# Ideas Endpoints

@app.post("/api/ideas")
async def create_idea(payload: CreateIdea):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    idea = Idea(**payload.model_dump())
    idea_id = create_document("idea", idea)
    created = db["idea"].find_one({"_id": ObjectId(idea_id)})
    return serialize_doc(created)

@app.get("/api/ideas")
async def list_ideas(
    timeframe: str = "week",  # week, month, all
    sort: str = "votes",      # votes, comments, recent
    limit: int = 50
):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")

    filter_q = {}
    now = datetime.now(timezone.utc)
    if timeframe == "week":
        filter_q["created_at"] = {"$gte": now - timedelta(days=7)}
    elif timeframe == "month":
        filter_q["created_at"] = {"$gte": now - timedelta(days=30)}
    # else all time = no filter

    sort_map = {
        "votes": ("votes_count", -1),
        "comments": ("comments_count", -1),
        "recent": ("created_at", -1),
    }
    sort_field, sort_dir = sort_map.get(sort, ("votes_count", -1))

    cursor = db["idea"].find(filter_q).sort(sort_field, sort_dir).limit(limit)
    items = [serialize_doc(x) for x in cursor]
    return {"items": items}

@app.get("/api/ideas/{idea_id}")
async def get_idea(idea_id: str):
    doc = db["idea"].find_one({"_id": ObjectId(idea_id)})
    if not doc:
        raise HTTPException(status_code=404, detail="Idea not found")
    # Include comments
    comments = list(db["comment"].find({"post_id": idea_id}).sort("created_at", -1))
    return {"idea": serialize_doc(doc), "comments": [serialize_doc(c) for c in comments]}

@app.post("/api/comments")
async def add_comment(payload: CreateComment):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    # validate idea exists
    if not db["idea"].find_one({"_id": ObjectId(payload.post_id)}):
        raise HTTPException(status_code=404, detail="Idea not found")

    comment = Comment(**payload.model_dump())
    _id = create_document("comment", comment)
    # increment idea comments_count
    db["idea"].update_one({"_id": ObjectId(payload.post_id)}, {"$inc": {"comments_count": 1}})
    created = db["comment"].find_one({"_id": ObjectId(_id)})
    return serialize_doc(created)

@app.post("/api/ideas/{idea_id}/vote")
async def vote_idea(idea_id: str, request: Request):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")

    # capture client IP (respect x-forwarded-for)
    xff = request.headers.get("x-forwarded-for")
    ip = (xff.split(",")[0].strip() if xff else request.client.host) if request.client else (xff.split(",")[0].strip() if xff else "unknown")

    # ensure idea exists
    idea = db["idea"].find_one({"_id": ObjectId(idea_id)})
    if not idea:
        raise HTTPException(status_code=404, detail="Idea not found")

    # Single IP can vote for one single post only overall
    existing_vote = db["vote"].find_one({"ip": ip})
    if existing_vote:
        # if same post, idempotent success; else deny
        if existing_vote.get("post_id") == idea_id:
            return {"status": "already_voted", "ip": ip}
        raise HTTPException(status_code=403, detail="This IP has already voted for another idea")

    vote = Vote(post_id=idea_id, ip=ip)
    create_document("vote", vote)
    db["idea"].update_one({"_id": ObjectId(idea_id)}, {"$inc": {"votes_count": 1}})
    return {"status": "ok", "ip": ip}

# Seed some initial ideas if collection empty
@app.post("/api/seed")
async def seed():
    if db is None:
        raise HTTPException(status_code=500, detail="Database not available")
    count = db["idea"].count_documents({})
    if count > 0:
        return {"status": "skipped", "count": count}
    samples = [
        {
            "title": "AI-Powered Meeting Notetaker for Open-Source PRs",
            "description": "Summarize GitHub PR discussions and suggest action items with vibe coding agents.",
            "link": "https://github.com",
        },
        {
            "title": "Realtime Design Critique Bot",
            "description": "Drop a Figma link and get live critique + code-ready components.",
            "link": "https://figma.com",
        },
        {
            "title": "CLI to Full SaaS",
            "description": "Paste a CLI tool and generate a hosted SaaS with billing and dashboards.",
            "link": "https://example.com",
        },
    ]
    for s in samples:
        idea = Idea(**s)
        create_document("idea", idea)
    return {"status": "seeded", "count": len(samples)}

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
