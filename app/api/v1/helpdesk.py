from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlmodel import select, and_, or_
from sqlmodel.ext.asyncio.session import AsyncSession
from pydantic import BaseModel

from app.db.session import get_tenant_session
from app.api.v1.auth import get_current_user
from app.models.help import HelpArticle, HelpSearchLog
from app.models.user import User

router = APIRouter()


class HelpArticleCreate(BaseModel):
    slug: str
    title: str
    content_md: str
    language: str = "en"
    category: Optional[str] = None
    tags: Optional[str] = None
    is_published: bool = True
    is_featured: bool = False
    video_url: Optional[str] = None


@router.get("/articles")
async def list_articles(
    category: Optional[str] = Query(None),
    language: Optional[str] = Query("en"),
    is_featured: Optional[bool] = Query(None),
    search: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user)
):
    query = select(HelpArticle).where(HelpArticle.is_published == True)
    
    if category:
        query = query.where(HelpArticle.category == category)
    if language:
        query = query.where(HelpArticle.language == language)
    if is_featured is not None:
        query = query.where(HelpArticle.is_featured == is_featured)
    if search:
        query = query.where(
            or_(
                HelpArticle.title.ilike(f"%{search}%"),
                HelpArticle.content_md.ilike(f"%{search}%"),
                HelpArticle.tags.ilike(f"%{search}%")
            )
        )
    
    articles = (await session.exec(query.order_by(HelpArticle.view_count.desc(), HelpArticle.created_at.desc()))).all()
    
    # Log search if user is authenticated
    if current_user and search:
        log = HelpSearchLog(
            user_id=current_user.id,
            search_query=search,
            results_count=len(articles)
        )
        session.add(log)
        await session.commit()
    
    return [{"id": a.id, "slug": a.slug, "title": a.title, "category": a.category,
             "language": a.language, "view_count": a.view_count, "is_featured": a.is_featured} for a in articles]


@router.get("/articles/{slug}")
async def get_article(
    slug: str,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user)
):
    article = (await session.exec(
        select(HelpArticle).where(
            and_(
                HelpArticle.slug == slug,
                HelpArticle.is_published == True
            )
        )
    )).first()
    
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    # Increment view count
    article.view_count += 1
    await session.commit()
    await session.refresh(article)
    
    return {
        "id": article.id,
        "slug": article.slug,
        "title": article.title,
        "content_md": article.content_md,
        "content_html": article.content_html,
        "category": article.category,
        "tags": article.tags,
        "video_url": article.video_url,
        "view_count": article.view_count,
        "helpful_count": article.helpful_count
    }


@router.post("/articles/{article_id}/helpful")
async def mark_helpful(
    article_id: int,
    helpful: bool = True,
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user)
):
    article = await session.get(HelpArticle, article_id)
    if not article:
        raise HTTPException(status_code=404, detail="Article not found")
    
    if helpful:
        article.helpful_count += 1
    else:
        article.not_helpful_count += 1
    
    await session.commit()
    return {"status": "updated"}


@router.get("/search")
async def search_help(
    q: str = Query(...),
    category: Optional[str] = Query(None),
    language: str = Query("en"),
    session: AsyncSession = Depends(get_tenant_session),
    current_user: Optional[User] = Depends(get_current_user)
):
    """Natural language search for help articles"""
    query = select(HelpArticle).where(
        and_(
            HelpArticle.is_published == True,
            HelpArticle.language == language,
            or_(
                HelpArticle.title.ilike(f"%{q}%"),
                HelpArticle.content_md.ilike(f"%{q}%"),
                HelpArticle.tags.ilike(f"%{q}%")
            )
        )
    )
    
    if category:
        query = query.where(HelpArticle.category == category)
    
    articles = (await session.exec(query.order_by(HelpArticle.is_featured.desc(), HelpArticle.view_count.desc()))).all()
    
    # Log search
    if current_user:
        log = HelpSearchLog(
            user_id=current_user.id,
            search_query=q,
            results_count=len(articles)
        )
        session.add(log)
        await session.commit()
    
    return {
        "query": q,
        "results": [{"id": a.id, "slug": a.slug, "title": a.title, "category": a.category,
                    "snippet": a.content_md[:200] + "..." if len(a.content_md) > 200 else a.content_md} for a in articles],
        "count": len(articles)
    }


@router.get("/suggestions")
async def get_suggestions(
    context: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    session: AsyncSession = Depends(get_tenant_session)
):
    """Get context-aware help suggestions"""
    query = select(HelpArticle).where(HelpArticle.is_published == True)
    
    if category:
        query = query.where(HelpArticle.category == category)
    
    # Get featured articles or most viewed
    articles = (await session.exec(
        query.order_by(HelpArticle.is_featured.desc(), HelpArticle.view_count.desc())
        .limit(5)
    )).all()
    
    return [{"id": a.id, "slug": a.slug, "title": a.title, "category": a.category} for a in articles]


