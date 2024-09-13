from contextlib import asynccontextmanager
from typing import cast

from fastapi import Depends, FastAPI, HTTPException
from sqlmodel import Session, select

from mini_siem.models import Event, Source, create_database, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    create_database()
    yield


app = FastAPI(lifespan=lifespan)


def get_session():
    with Session(engine) as session:
        yield session


@app.post(
    "/sources/",
    tags=["source"],
    summary="Add a new source",
    response_description="Source added successfully",
    response_model=str,
)
async def add_source(source: Source, session: Session = Depends(get_session)):
    db_source = Event.model_validate(source)
    session.add(db_source)
    session.commit()
    return {"message": "Source added successfully"}


@app.get(
    "/sources",
    tags=["source"],
    summary="Get all sources",
    response_description="List of sources",
    response_model=list[Source],
)
def get_sources(session: Session = Depends(get_session)):
    sources = session.exec(select(Source)).all()
    return sources


@app.get(
    "/sources/{source_id}",
    tags=["source"],
    summary="Get a source by ID",
    response_description="Source details",
    response_model=Source,
)
def get_source(source_id: int, session: Session = Depends(get_session)):
    source = session.get(Source, source_id)
    if source is None:
        raise HTTPException(status_code=404, detail="Source not found")
    return source


@app.patch(
    "/sources/{source_id}",
    tags=["source"],
    summary="Update a source",
    response_description="Updated source",
    response_model=Source,
)
async def update_source(
    source_id: int,
    source: Source,
    session: Session = Depends(get_session),
):
    db_source = session.get(Source, source_id)
    if db_source is None:
        return {"error": "Log source not found"}
    source_data = source.model_dump(exclude_unset=True)
    db_source.sqlmodel_update(source_data)
    session.add(db_source)
    session.commit()
    session.refresh(db_source)
    return db_source


@app.post(
    "/events/",
    tags=["event"],
    summary="Add a new event or a list of events",
    response_description="Event added successfully",
    response_model=str,
)
async def add_event(
    events: Event | list[Event],
    session: Session = Depends(get_session),
):
    if not isinstance(events, list):
        events = cast(list[Event], [events])
    for event in events:
        db_event = Event.model_validate(event)
        session.add(db_event)
    session.commit()
    return {"message": "Event added successfully"}


@app.get(
    "/events/",
    tags=["event"],
    summary="Get all events",
    response_description="List of events",
    response_model=list[Event],
)
async def get_events(session: Session = Depends(get_session)):
    events = session.exec(select(Event)).all()
    return events


@app.get(
    "/events/search",
    tags=["event"],
    summary="Search events by query",
    response_description="List of matching events",
    response_model=list[Event] | None,
)
def search_events(
    query: str,
    session: Session = Depends(get_session),
):
    from .parser import generate_event_sql_query, parser

    tree = parser.parse(query)
    sql_query = generate_event_sql_query(tree)
    if sql_query is None:
        raise HTTPException(status_code=404, detail="Item not found")
    result = session.exec(sql_query).all()
    return result


@app.get(
    "/events/{event_id}",
    response_model=Event,
    tags=["event"],
    summary="Retrieve an event by ID",
    description="Get a single event by its unique ID",
    response_description="The retrieved event",
    responses={404: {"description": "Event not found"}},
)
def get_event(event_id: int, session: Session = Depends(get_session)):
    event = session.get(Event, event_id)
    if event is None:
        raise HTTPException(status_code=404, detail="Event not found")
    return event


def main():
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)


if __name__ == "__main__":
    main()
