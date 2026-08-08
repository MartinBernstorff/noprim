from pydantic import BaseModel

from noprim_core.annotations import AnnotationText
from noprim_core.rules.code import RuleCode
from noprim_core.site import (
    ColumnNumber,
    Filename,
    LineNumber,
    Owner,
    Qualname,
    Surface,
)


class Violation(BaseModel):
    filename: Filename
    code: RuleCode
    line: LineNumber
    column: ColumnNumber
    surface: Surface
    qualname: Qualname
    annotation: AnnotationText
    # Carried through from the site so a rule can word its message for the framework
    # that dictated the annotation. Deliberately not part of the baseline key.
    owner: Owner = Owner.AUTHOR
