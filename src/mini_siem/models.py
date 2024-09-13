"""This module defines the data models and database schema for an event-driven system.

It includes the following components:

* An `Action` enum representing possible actions that can be taken in response to an event.
* An `Event` model representing an event that occurred in the system.
* A `Source` model representing a source of events in the system.
* An `Alert` model representing an alert triggered by a rule.
* A `Rule` model representing a rule that triggers alerts based on events.
* A `create_database` function that creates a SQLite database with the specified file name and constructs the database engine.

The database schema is defined using SQLModel, and the `create_database` function creates all tables in the database based on the SQLModel metadata.
"""

from datetime import datetime
from enum import Enum

from sqlalchemy import JSON, TIMESTAMP, Column
from sqlmodel import Field, SQLModel, create_engine

# Define the SQLite database file name
_sqlite_file_name = "database.db"
# Construct the SQLite URL
_sqlite_url = f"sqlite:///{_sqlite_file_name}"

# Create a database engine with echo mode enabled
engine = create_engine(_sqlite_url, echo=True)


class Action(Enum):
    """Enum representing possible actions that can be taken in response to an event.

    Attributes:
    ALERT (str): Send an alert.
    RUN_SCRIPT (str): Run a script.

    """

    ALERT = "alert"
    RUN_SCRIPT = "run script"


class Status(Enum):
    OPEN = "open"
    CLOSED = "closed"
    RESOLVED = "resolved"


class Event(SQLModel, table=True):
    """Represents an event that occurred in the system.

    Attributes:
    id (int | None): Unique identifier for the event (primary key).
    timestamp (datetime): Timestamp when the event occurred.
    source_type (int): Foreign key referencing the source of the event.
    data (dict): Additional data associated with the event stored as JSON.

    """

    id: int | None = Field(primary_key=True, default=None)
    timestamp: datetime | None = Field(sa_column=Column(TIMESTAMP))
    source: int = Field(foreign_key="source.id")
    data: dict = Field(sa_column=Column(JSON))


class Source(SQLModel, table=True):
    """Represents a source of events in the system.

    Attributes:
    id (int | None): Unique identifier for the source (primary key).
    name (str): Name of the source.
    type (str): Type of the source.
    description (str): Description of the source.

    """

    id: int | None = Field(primary_key=True, default=None)
    name: str
    type: str
    description: str | None


class Alert(SQLModel, table=True):
    """Represents an alert triggered by a rule.

    Attributes:
    id (int | None): Unique identifier for the alert (primary key).
    timestamp (datetime): Timestamp when the alert was triggered.
    rule_id (int): Foreign key referencing the rule that triggered the alert.
    event_id (int): Foreign key referencing the event that triggered the alert.
    status (Literal["open", "closed", "resolved"]): Status of the alert.
    description (str): Description of the alert.

    """

    id: int | None = Field(primary_key=True, default=None)
    timestamp: datetime | None = Field(sa_column=Column(TIMESTAMP))
    rule_id: int = Field(foreign_key="rule.id")
    event_id: int = Field(foreign_key="event.id")
    status: Status
    description: str


class Rule(SQLModel, table=True):
    """Represents a rule that triggers alerts based on events.

    Attributes:
    id (int | None): Unique identifier for the rule (primary key).
    name (str): Name of the rule.
    description (str): Description of the rule.
    condition (str): Condition that triggers the rule.
    action (list[Action]): Action to take when the rule is triggered.
    enabled (bool): Whether the rule is enabled.

    """

    id: int | None = Field(primary_key=True, default=None)
    name: str
    description: str
    condition: str
    action: list[Action] = Field(sa_column=Column(JSON))
    enabled: bool


def create_database():
    # Create all tables in the database based on the SQLModel metadata
    SQLModel.metadata.create_all(engine)
