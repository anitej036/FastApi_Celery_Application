from fastapi import FastAPI, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, desc
from database import SessionLocal, engine, Base
from models import ReviewHistory, Category, AccessLog
from celery_config import create_access_log_task
import openai

# Initialize FastAPI app
app = FastAPI()

# Create database tables (only for local development, use Alembic for production)
Base.metadata.create_all(bind=engine)

# Dependency to get DB session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@app.get("/reviews/trends")
def get_review_trends(db: Session = Depends(get_db)):
    """Fetch the top 5 categories based on descending order of average stars."""

    # Fetch latest review per review_id
    subquery = (
        db.query(ReviewHistory.review_id, func.max(ReviewHistory.created_at).label("latest"))
        .group_by(ReviewHistory.review_id)
        .subquery()
    )

    # Join with ReviewHistory and Category to get required fields
    query = (
        db.query(
            Category.id,
            Category.name,
            Category.description,
            func.avg(ReviewHistory.stars).label("average_star"),
            func.count(ReviewHistory.id).label("total_reviews")
        )
        .join(ReviewHistory, Category.id == ReviewHistory.category_id)
        .join(subquery, (ReviewHistory.review_id == subquery.c.review_id) & (ReviewHistory.created_at == subquery.c.latest))
        .group_by(Category.id)
        .order_by(desc("average_star"))
        .limit(5)
    )

    result = query.all()

    # Asynchronously log access
    create_access_log_task.delay("GET /reviews/trends")
    
    return result

@app.get("/reviews/")
def get_reviews(category_id: int, page: int = Query(1, alias="page"), db: Session = Depends(get_db)):
    """Fetch all reviews for a particular category sorted by latest created_at, with pagination."""

    page_size = 15
    offset = (page - 1) * page_size

    # Fetch latest review per review_id in the given category
    subquery = (
        db.query(ReviewHistory.review_id, func.max(ReviewHistory.created_at).label("latest"))
        .filter(ReviewHistory.category_id == category_id)
        .group_by(ReviewHistory.review_id)
        .subquery()
    )

    query = (
        db.query(ReviewHistory)
        .join(subquery, (ReviewHistory.review_id == subquery.c.review_id) & (ReviewHistory.created_at == subquery.c.latest))
        .order_by(desc(ReviewHistory.created_at))
        .offset(offset)
        .limit(page_size)
    )
    
    reviews = query.all()
    
    for review in reviews:
        if review.tone is None or review.sentiment is None:
            review.tone, review.sentiment = fetch_tone_sentiment(review.text, review.stars)
            db.commit()
    
    # Log API access asynchronously
    create_access_log_task.delay(f"GET /reviews/?category_id={category_id}")
    
    return reviews

def fetch_tone_sentiment(text, stars):
    """Use OpenAI to fetch tone and sentiment"""
    response = openai.ChatCompletion.create(
        model="gpt-3.5-turbo",
        messages=[
            {"role": "system", "content": "Analyze the sentiment and tone of the following review."},
            {"role": "user", "content": f"Review: {text}\nStars: {stars}"},
        ]
    )
    analysis = response["choices"][0]["message"]["content"].strip()
    tone, sentiment = analysis.split("\n")[:2]  # Assuming output format
    return tone, sentiment
