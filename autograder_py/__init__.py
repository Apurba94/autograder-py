"""AutoGrader: grade Python assignments and compare submissions."""
from .core import Assignment, Test, feedback, fingerprints, grade, grade_folder, normalise, similarity, similarity_report, static_check, to_csv

__all__ = ["Assignment", "Test", "feedback", "fingerprints", "grade", "grade_folder", "normalise", "similarity", "similarity_report", "static_check", "to_csv"]
