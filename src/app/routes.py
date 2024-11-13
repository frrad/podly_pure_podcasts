import datetime
import re
from pathlib import Path
from typing import Any

import feedparser  # type: ignore[import-untyped]
import flask
import PyRSS2Gen  # type: ignore[import-untyped]
from flask import Blueprint, jsonify, request, send_file, url_for

from app import config, db, logger
from app.models import Feed, Post
from podcast_processor.podcast_processor import PodcastProcessor, PodcastProcessorTask
from shared.podcast_downloader import download_episode, find_audio_link

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index() -> flask.Response:
    feeds = Feed.query.all()

    return flask.make_response(flask.render_template("index.html", feeds=feeds), 200)


@main_bp.route("/v1/post/<string:p_guid>", methods=["GET"])
def download_post(p_guid: str) -> flask.Response:
    post = Post.query.filter_by(guid=p_guid).first()
    if post is None:
        return flask.make_response(("Post not found", 404))

    if config.require_episode_whitelist and not post.whitelisted:
        return flask.make_response(("Episode not whitelisted", 403))

    # Download the episode
    download_path = download_episode(
        post.feed.title,
        re.sub(r"[^a-zA-Z0-9\s]", "", post.title) + ".mp3",
        post.download_url,
    )
    if download_path is None:
        return flask.make_response(("Failed to download episode", 500))

    # Process the episode
    task = PodcastProcessorTask(post.title, download_path, post.title)
    processor = PodcastProcessor(config)
    output_path = processor.process(task)
    if output_path is None:
        return flask.make_response(("Failed to process episode", 500))

    try:
        return send_file(path_or_file=Path(output_path).resolve())
    except Exception as e:  # pylint: disable=broad-exception-caught
        logger.error(f"Error sending file: {e}")
        return flask.make_response(("Error sending file", 500))


def fetch_feed(url: str) -> feedparser.FeedParserDict:
    logger.info(f"Fetching feed from URL: {url}")
    return feedparser.parse(url)


def store_feed(feed_data: feedparser.FeedParserDict) -> Feed:
    logger.info(f"Storing feed: {feed_data.feed.title}")
    feed = Feed(
        title=feed_data.feed.title,
        description=feed_data.feed.get("description", ""),
        author=feed_data.feed.get("author", ""),
        rss_url=feed_data.href,
    )
    db.session.add(feed)
    db.session.commit()

    for entry in feed_data.entries:
        db.session.add(make_post(feed, entry))
    db.session.commit()
    logger.info(f"Feed stored with ID: {feed.id}")
    return feed


def refresh_feed(feed: Feed) -> None:
    logger.info(f"Refreshing feed with ID: {feed.id}")
    feed_data = fetch_feed(feed.rss_url)
    existing_posts = {post.guid for post in feed.posts}  # type: ignore[attr-defined]
    for entry in feed_data.entries:
        if entry.id not in existing_posts:
            logger.debug(f"found new podcast: {entry.title}")
            db.session.add(make_post(feed, entry))
    db.session.commit()
    logger.info(f"Feed with ID: {feed.id} refreshed")


def make_post(feed: Feed, entry: feedparser.FeedParserDict) -> Post:
    return Post(
        feed_id=feed.id,
        guid=entry.id,
        download_url=find_audio_link(entry),
        title=entry.title,
        description=entry.get("description", ""),
        release_date=(
            datetime.datetime(*entry.published_parsed[:6])
            if entry.get("published_parsed")
            else None
        ),
        duration=int(entry.get("itunes_duration", 0)),
    )


def generate_feed_xml(feed: Feed) -> Any:
    logger.info(f"Generating XML for feed with ID: {feed.id}")
    items = []
    for post in feed.posts:  # type: ignore[attr-defined]
        items.append(
            PyRSS2Gen.RSSItem(
                title=post.title,
                link=url_for("main.download_post", p_guid=post.guid, _external=True),
                description=post.description,
                guid=PyRSS2Gen.Guid(post.download_url),
                pubDate=(
                    post.release_date.strftime("%a, %d %b %Y %H:%M:%S %z")
                    if post.release_date
                    else None
                ),
            )
        )
    rss_feed = PyRSS2Gen.RSS2(
        title="[podly] " + feed.title,
        link=url_for("main.get_feed", f_id=feed.id, _external=True),
        description=feed.description,
        lastBuildDate=datetime.datetime.now(),
        items=items,
    )
    logger.info(f"XML generated for feed with ID: {feed.id}")
    return rss_feed.to_xml("utf-8")


@main_bp.route("/v1/feed", methods=["POST"])
def add_feed() -> flask.Response:
    data = request.form

    if not data or "url" not in data:
        logger.error("URL is required")
        return flask.make_response(jsonify({"error": "URL is required"}), 400)

    url = data["url"]
    feed_data = fetch_feed(url)
    if "title" not in feed_data.feed:
        logger.error("Invalid feed URL")
        return flask.make_response(jsonify({"error": "Invalid feed URL"}), 400)

    feed = Feed.query.filter_by(rss_url=url).first()
    if feed:
        refresh_feed(feed)
    else:
        feed = store_feed(feed_data)

    logger.info(f"Feed added with ID: {feed.id}")
    return flask.make_response(jsonify({"id": feed.id, "title": feed.title}), 201)


@main_bp.route("/v1/feed/<int:f_id>", methods=["GET"])
def get_feed(f_id: int) -> flask.Response:
    logger.info(f"Fetching feed with ID: {f_id}")
    feed = Feed.query.get_or_404(f_id)
    refresh_feed(feed)
    feed_xml = generate_feed_xml(feed)
    logger.info(f"Feed with ID: {f_id} fetched and XML generated")
    return flask.make_response(feed_xml, 200, {"Content-Type": "application/xml"})
