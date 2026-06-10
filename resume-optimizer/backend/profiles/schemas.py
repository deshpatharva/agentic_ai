from typing import Optional
from pydantic import BaseModel


class ExperienceEntry(BaseModel):
    company: str = ""
    title: str = ""
    dates: str = ""
    bullets: list[str] = []


class EducationEntry(BaseModel):
    institution: str = ""
    degree: str = ""
    dates: str = ""


class SectionsData(BaseModel):
    summary: str = ""
    experience: list[ExperienceEntry] = []
    education: list[EducationEntry] = []
    skills: list[str] = []


class ProfileCreate(BaseModel):
    label: str
    label_confirmed: bool = False
    raw_text: str = ""
    sections: SectionsData


class ProfileUpdate(BaseModel):
    label: Optional[str] = None
    label_confirmed: Optional[bool] = None
    sections: Optional[SectionsData] = None


class ParseProfileRequest(BaseModel):
    raw_text: str
