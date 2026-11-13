"""File names of a model artefact.

Kept apart from :mod:`muletrace.models.artifact` so that code which only moves artefacts around
(the promotion Lambda) does not import LightGBM.
"""

from typing import Final

MODEL_FILE: Final = "model.txt"
CALIBRATOR_FILE: Final = "calibrator.json"
METADATA_FILE: Final = "metadata.json"
ARTIFACT_FILES: Final = (MODEL_FILE, CALIBRATOR_FILE, METADATA_FILE)
