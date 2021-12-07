import json

from dagster import solid
from sqlmodel import Session, desc, func, select

from etl.common import Context
from ptbmodels.models import ArticleCluster, ArticleClusterLink


@solid(required_resource_keys={"database_client"})
def get_latest_clusters(context: Context) -> list[ArticleCluster]:
    db_client: Session = context.resources.database_client

    statement1 = select(
        ArticleClusterLink.article_cluster_id,
        func.count(ArticleClusterLink.article_id).
            label("size")).group_by(ArticleClusterLink.article_cluster_id). \
        order_by(desc("size")).limit(10)
    sub1 = statement1.subquery("s1")
    sub2 = select(func.max(ArticleCluster.added_at)).scalar_subquery()
    statement2 = select(ArticleCluster).join(sub1).where(ArticleCluster.added_at == sub2).order_by(desc("size"))

    context.log.info(f"Attempting to execute: {statement2}")
    entities = db_client.exec(statement2).all()
    context.log.info(f"Got {len(entities)} rows of {ArticleCluster.__name__}")
    return entities


@solid
def prep_latest_clusters(context: Context, clusters: list[ArticleCluster]) -> dict:
    prepped_clusters = [
        {
            "topics": [{"term": k.term, "weight": k.weight} for k in c.keywords],
            "articles": [{"title": a.title, "url": a.url, "source": a.source.name, "date": a.published_at.strftime("%d-%m-%Y")} for a in c.articles]
        }
        for c in clusters
    ]

    return {
        "added_at": clusters[0].added_at,
        "clusters": prepped_clusters
    }


@solid
def write_to_bucket(context: Context, prepped_data: dict):
    # json.dumps(prepped_data)
    ...
