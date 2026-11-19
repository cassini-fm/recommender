import os
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import FastAPI, HTTPException, Query
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

MIN_PLAYS = 3
DEFAULT_DAYS = 180

pool = ConnectionPool(os.environ["DATABASE_URL"], kwargs={"row_factory": dict_row}, open=False)

@asynccontextmanager
async def lifespan(app: FastAPI):
    pool.open()
    yield
    pool.close()

app = FastAPI(lifespan=lifespan)

SIMILARITY_QUERY = """
    with mine as (
        select distinct t.artist_id
        from engine.plays s join engine.tracks t on t.id = s.track_id
        where s.user_id = %(user_id)s
    ), neighbors as (
        select distinct s.user_id
        from engine.plays s join engine.tracks t on t.id = s.track_id
        where s.user_id <> %(user_id)s and t.artist_id in (select artist_id from mine)
    )

    select a.name as artist, t.title, t.mbid::text as mbid, count(distinct s.user_id) as listeners,
    (select count(*) from neighbors) as neighbors
    
    from engine.plays s
    join neighbors n on n.user_id = s.user_id
    join engine.tracks t on t.id = s.track_id
    join engine.artists a on a.id = t.artist_id
    where t.artist_id not in (select artist_id from mine)
    group by t.id, t.title, t.mbid, a.name
    order by listeners desc, t.title
    limit %(limit)s
"""

REDISCOVER_QUERY = """
    select a.name as artist, t.title, t.mbid::text as mbid, count(*) as plays
    from engine.plays s
    join engine.tracks t on t.id = s.track_id
    join engine.artists a on a.id = t.artist_id
    where s.user_id = %(user_id)s
    group by t.id, t.title, t.mbid, a.name
    having count(*) >= %(min_plays)s and max(s.played_at) < now() - make_interval(days => %(days)s)
    order by plays desc, t.title
    limit %(limit)s
"""

def item(row, score, reason):
    return { "artist": row["artist"], "title": row["title"], "album": None, "mbid": row["mbid"], "score": score, "reason": reason }

def similar(user, limit):
    with pool.connection() as connection:
        rows = connection.execute(SIMILARITY_QUERY, {"user_id": user, "limit": limit}).fetchall()
    return [
        item(row, row["listeners"] / row["neighbors"], f"Played by {row['listeners']} of {row['neighbors']} listeners who share artists with you")
        for row in rows
    ]

def rediscover(user_id, limit):
    params = {"user_id": user_id, "limit": limit, "min_plays": MIN_PLAYS, "days": DEFAULT_DAYS}
    with pool.connection() as connection:
        rows = connection.execute(REDISCOVER_QUERY, params).fetchall()
    most = rows[0]["plays"] if rows else 1
    return [
        item(row, row["plays"] / most, f"You played this {row['plays']} times, but not in the last {DEFAULT_DAYS} days")
        for row in rows
    ]

MODES = {
    "similar": similar,
    "rediscover": rediscover
}

@app.get("/modes")
def modes():
    return {"modes": list(MODES)}

@app.get("/recommendations")
def recommendations(user_id: UUID, mode: str, limit: int = Query(50, ge=1, le=100)):
    if mode not in MODES:
        raise HTTPException(status_code=400, detail="Unknown mode")
    return {"items": MODES[mode](user_id, limit)}

