from pydantic import BaseModel

from noprim_core.annotations import AnnotationText
from noprim_core.rules.code import RuleCode
from noprim_core.site import ColumnNumber, Filename, LineNumber, Qualname, Surface


class Violation(BaseModel):
    filename: Filename
    code: RuleCode
    line: LineNumber
    column: ColumnNumber
    surface: Surface
    qualname: Qualname
    annotation: AnnotationText
