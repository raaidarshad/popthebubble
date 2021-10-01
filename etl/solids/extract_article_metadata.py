from dagster import Array, AssetMaterialization, Enum, EnumValue, Field, Output, String, solid

from requests.exceptions import HTTPError
from sqlalchemy.dialects.postgresql import insert
from sqlmodel import Session, select

from etl.common import Context, get_source_names, str_to_datetime
from etl.resources.rss_parser import RssParser
from ptbmodels.models import Article, RawFeed, RawFeedEntry, RssFeed, Source


# we want to restrict developer selection of source by name to only source names that we know of, so we use an Enum
SourceDenum = Enum("SourceDenum", [EnumValue("all")] + [EnumValue(n) for n in get_source_names()])

SourceDenumConfig = Field(
    config=Array(SourceDenum),
    # if no source names provided, we will simply ask for all sources
    default_value=["all"],
    is_required=False
)


@solid(required_resource_keys={"database_client"}, config_schema={"sources": SourceDenumConfig})
def get_sources(context: Context) -> list[Source]:
    db_client: Session = context.resources.database_client
    source_names = context.solid_config["sources"]
    if "all" in source_names:
        statement = select(Source)
    else:
        statement = select(Source).where(Source.name.in_(source_names))
    context.log.debug(f"Attempting to execute: {statement}")
    sources = db_client.exec(statement).all()
    context.log.debug(f"Got {len(sources)} sources")
    return sources


@solid(required_resource_keys={"database_client"}, config_schema={"sources": SourceDenumConfig})
def get_rss_feeds(context: Context) -> list[RssFeed]:
    db_client: Session = context.resources.database_client
    source_names = context.solid_config["sources"]
    if "all" in source_names:
        statement = select(RssFeed).where(RssFeed.is_okay)
    else:
        statement = select(RssFeed).join(Source, RssFeed.source_id == Source.id).where(Source.name.in_(source_names))
    context.log.debug(f"Attempting to execute: {statement}")
    feeds = db_client.exec(statement).all()
    context.log.debug(f"Got {len(feeds)} feeds")
    return feeds


@solid(required_resource_keys={"rss_parser"})
def get_raw_feeds(context: Context, rss_feeds: list[RssFeed]) -> list[RawFeed]:
    raw_feeds = [_get_raw_feed(context, rss_feed, context.resources.rss_parser) for rss_feed in rss_feeds]
    context.log.debug(f"Got {len(raw_feeds)} raw rss feeds")
    return raw_feeds


def _get_raw_feed(context: Context, rss_feed: RssFeed, parser: RssParser) -> RawFeed:
    raw = parser.parse(rss_feed.url)
    if raw.status == 200:
        entries = [RawFeedEntry(
            source_id=rss_feed.source_id,
            published_at=str_to_datetime(e.published),
            **e) for e in raw.entries]
        return RawFeed(
            entries=entries,
            source_id=rss_feed.source_id,
            **raw.feed
        )
    else:
        context.log.warning(f"RssFeed with url {rss_feed.url} not parsed, code: {raw.status}")


@solid
def get_new_raw_feed_entries(context: Context, raw_feeds: list[RawFeed]) -> list[RawFeedEntry]:
    ...


@solid
def transform_raw_feed_entries_to_articles(context: Context, raw_feed_entries: list[RawFeedEntry]) -> list[Article]:
    ...


@solid(required_resource_keys={"database_client"})
def load_articles(context: Context, articles: list[Article]):
    db_client: Session = context.resources.database_client
    # db_articles = [article.dict() for article in articles]
    context.log.debug(f"Attempting to add {len(articles)} rows to the Article table")
    article_count_before = db_client.query(Article).count()
    insert_statement = insert(Article).on_conflict_do_nothing(index_elements=["url"])
    db_client.exec(statement=insert_statement, params=articles)
    db_client.commit()
    article_count_after = db_client.query(Article).count()
    article_count_added = article_count_after - article_count_before
    context.log.debug(f"Added {article_count_added} articles to the Article table")
    if article_count_added > 0:
        yield AssetMaterialization(asset_key="article_table",
                                   description="New rows added to article table")
    yield Output(articles)
