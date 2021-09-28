import os

from fastapi import FastAPI, Depends
from fastapi.staticfiles import StaticFiles
import feedparser
from sqlmodel import Session, create_engine, desc, func, select

from ptbmodels.models import Cluster, ClusterToLink

app = FastAPI()


def get_db_client():
    engine = create_engine(os.getenv("DB_CONNECTION_STRING"))
    db_session = Session(autocommit=False, autoflush=False, bind=engine)
    try:
        yield db_session
    finally:
        db_session.close()


@app.get("/feed")
def default_feed(rssUrl: str, limit: int):
    feed = feedparser.parse(rssUrl)
    feed["entries"] = feed["entries"][:limit]
    return feed


@app.get("/topics")
def topics(limit: int = 5, db_client: Session = Depends(get_db_client)):
    statement1 = select(ClusterToLink.cluster_id, func.count(ClusterToLink.article_id).label("size")). \
        group_by(ClusterToLink.cluster_id).order_by(desc("size")).limit(limit)
    sub1 = statement1.subquery("s1")
    statement2 = select(Cluster).join(sub1).order_by(desc("size"))
    clusters = db_client.exec(statement2).all()
    # sadly seem to need to manually include articles (and their sources) into the response

    clusters = [{**c.dict(), "articles": [{**a.dict(), "source": a.source} for a in c.articles]} for c in clusters]

    return clusters


# Path for all the static files (compiled JS/CSS, index.html, etc.)
app.mount("/", StaticFiles(directory="public", html=True), name="public")
