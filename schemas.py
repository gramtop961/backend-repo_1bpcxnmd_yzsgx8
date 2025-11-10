"""
Database Schemas for Vibe Ideas

Each Pydantic model represents a collection in MongoDB.
Collection name is lowercase of class name.
"""
from pydantic import BaseModel, Field, HttpUrl
from typing import Optional
from datetime import datetime

class Idea(BaseModel):
    title: str = Field(..., min_length=3, max_length=120, description="Idea title")
    description: str = Field(..., min_length=10, max_length=1000, description="What to build")
    link: Optional[HttpUrl] = Field(None, description="Optional reference link")
    votes_count: int = Field(0, ge=0, description="Number of votes")
    comments_count: int = Field(0, ge=0, description="Number of comments")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class Comment(BaseModel):
    post_id: str = Field(..., description="Related idea _id as string")
    author: str = Field(..., min_length=1, max_length=60, description="Display name")
    text: str = Field(..., min_length=1, max_length=500, description="Comment body")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

class Vote(BaseModel):
    post_id: str = Field(..., description="Related idea _id as string")
    ip: str = Field(..., description="Voter IP address")
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
