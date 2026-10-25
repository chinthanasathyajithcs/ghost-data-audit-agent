"""Screenshots and PDFs: records come from the Stage 4A extractor (cached), observed at the capture time."""

from __future__ import annotations

import re
from pathlib import Path
from typing import Callable, Protocol

from deletion_audit.observations import Coverage, Observation, fields_text

DATE_SUFFIX = re.compile(r"_\d{8}(?:_\d+)?$")


class Extractor(Protocol):
    def extract_file(self, path: Path) -> tuple[dict, ...]: ...


def document_reader(extractor: Extractor) -> Callable[[Path, str, str], tuple[list[Observation], list[Coverage]]]:
    def read(path: Path, evidence_id: str, captured_at: str) -> tuple[list[Observation], list[Coverage]]:
        label = DATE_SUFFIX.sub("", Path(path).stem)
        observations = []
        for record in extractor.extract_file(path):  # records without a resource ID are kept for catalog aliases
            fields = dict(record["fields"])
            observations.append(Observation(
                evidence_id=evidence_id,
                captured_at=captured_at,
                observed_at=captured_at,
                system_id=None,
                resource_id=record["resource_id"],
                location=Path(path).name,
                label=label,
                fields=fields,
                text=fields_text(fields),
            ))
        return observations, []

    return read
