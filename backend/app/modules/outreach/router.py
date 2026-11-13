from fastapi import APIRouter

# Backend B adds call/report routes here without editing Backend A's module.
router = APIRouter(tags=["outreach"])
