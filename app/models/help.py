from datetime import datetime
from typing import Optional
from sqlmodel import SQLModel, Field


class HelpArticle(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    slug: str = Field(index=True)
    title: str
    content_md: str
    content_html: Optional[str] = None
    language: str = Field(default="en", index=True)
    category: Optional[str] = Field(default=None, index=True)  # reservations, front_desk, housekeeping, etc.
    tags: Optional[str] = None  # comma separated
    view_count: int = 0
    helpful_count: int = 0
    not_helpful_count: int = 0
    is_published: bool = Field(default=True, index=True)
    is_featured: bool = False
    video_url: Optional[str] = None
    interactive_guide_data: Optional[str] = None  # JSON for interactive guides
    property_specific: bool = False  # If True, only shown for specific properties
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)
    created_by: Optional[int] = Field(default=None, foreign_key="users.id")


class HelpSearchLog(SQLModel, table=True):
    id: Optional[int] = Field(default=None, primary_key=True)
    user_id: Optional[int] = Field(default=None, foreign_key="users.id", index=True)
    search_query: str = Field(index=True)
    results_count: int = 0
    clicked_article_id: Optional[int] = Field(default=None, foreign_key="helparticle.id")
    created_at: datetime = Field(default_factory=datetime.utcnow, index=True)



