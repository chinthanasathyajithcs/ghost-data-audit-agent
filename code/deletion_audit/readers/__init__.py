"""Evidence readers: each turns one file into Observations (and Coverage for snapshots)."""

from deletion_audit.readers.document_reader import document_reader
from deletion_audit.readers.handover_reader import read_handover
from deletion_audit.readers.json_reader import read_json
from deletion_audit.readers.log_reader import read_log
from deletion_audit.readers.sql_reader import read_sql

__all__ = ["document_reader", "read_handover", "read_json", "read_log", "read_sql"]
