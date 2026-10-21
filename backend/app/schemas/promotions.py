from datetime import date
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

Aspect = Literal["9:16", "16:9", "1:1"]


class PromotionInput(BaseModel):
    title: str = Field(min_length=1, max_length=180)
    product_ids: list[UUID] = Field(min_length=1, max_length=3)
    date_from: date
    date_to: date
    style: Literal["cinematic", "editorial", "detail"] = "cinematic"
    formats: list[Aspect] = Field(default_factory=lambda: ["9:16", "16:9", "1:1"], min_length=1, max_length=3)
    duration: Literal[15, 30] = 15
    hook: str = Field(default="Ο χώρος σου, αλλιώς.", min_length=1, max_length=100)
    cta: str = Field(default="Ανακάλυψέ το στο inde.gr", min_length=1, max_length=100)
    notes: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def validate_selection(self):
        if len(set(self.product_ids)) != len(self.product_ids) or len(set(self.formats)) != len(self.formats):
            raise ValueError("Duplicate products or formats.")
        if self.date_from > self.date_to or (self.date_to - self.date_from).days > 365:
            raise ValueError("Choose a report period of at most 366 days.")
        if not self.title.strip() or not self.hook.strip() or not self.cta.strip():
            raise ValueError("Title, hook and CTA are required.")
        return self


class PromotionReview(BaseModel):
    product_identity: Literal[True]
    cta_and_text: Literal[True]
    image_and_audio_rights: Literal[True]
    platform_format: Literal[True]
