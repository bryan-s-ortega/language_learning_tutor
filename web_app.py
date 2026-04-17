from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
from pydantic import BaseModel
import logging

from core_logic import TutorService

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Language Learning Tutor Web App")

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize Tutor Service
tutor_service = TutorService()


# Models
class ChatRequest(BaseModel):
    user_id: str
    message: Optional[str] = None


class ConfigRequest(BaseModel):
    user_id: str
    language: Optional[str] = None
    difficulty: Optional[str] = None


class TaskRequest(BaseModel):
    user_id: str
    task_type: str


# Routes
@app.post("/api/start")
async def start_session(request: ChatRequest):
    """Initialize a session and get welcome message."""
    try:
        response = tutor_service.handle_start(request.user_id)
        return {"message": response}
    except Exception as e:
        logger.error(f"Error in start_session: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/newtask")
async def new_task(request: ChatRequest):
    """Start a new task selection process."""
    try:
        response = tutor_service.start_new_task(request.user_id)
        return response
    except Exception as e:
        logger.error(f"Error in new_task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/select_task")
async def select_task(request: TaskRequest):
    """Select a specific task type."""
    try:
        response = tutor_service.select_task_type(request.user_id, request.task_type)
        return response
    except Exception as e:
        logger.error(f"Error in select_task: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/chat")
async def chat(
    user_id: str = Form(...),
    message: Optional[str] = Form(None),
    voice: Optional[UploadFile] = File(None),
):
    """Handle user messages (text or voice)."""
    try:
        voice_bytes = None
        if voice:
            voice_bytes = await voice.read()

        response = tutor_service.process_answer(
            user_id=user_id, text_answer=message, voice_bytes=voice_bytes
        )
        return response
    except Exception as e:
        logger.error(f"Error in chat: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/progress")
async def get_progress(user_id: str):
    """Get user progress report."""
    try:
        response = tutor_service.handle_progress(user_id)
        return {"message": response}
    except Exception as e:
        logger.error(f"Error in get_progress: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/config")
async def update_config(request: ConfigRequest):
    """Update user configuration (language, difficulty)."""
    try:
        if request.language:
            tutor_service.set_language(request.user_id, request.language)
        if request.difficulty:
            tutor_service.set_difficulty(request.user_id, request.difficulty)
        return {"status": "success", "message": "Configuration updated"}
    except Exception as e:
        logger.error(f"Error in update_config: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/state")
async def get_state(user_id: str):
    """Get current user state (for debugging or UI sync)."""
    try:
        state = tutor_service.get_user_state(user_id)
        return state
    except Exception as e:
        logger.error(f"Error in get_state: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# Mount static files (Frontend)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
