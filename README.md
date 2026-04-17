# Language Learning Tutor - Premium AI English Assistant

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-Modern-green.svg)](https://fastapi.tiangolo.com/)
[![Google Gemini AI](https://img.shields.io/badge/Google%20Gemini-AI-orange.svg)](https://deepmind.google/technologies/gemini/)

A premium, AI-powered English learning application with a modern minimalist web interface. Engage in hybrid learning through structured tasks or free-form conversation, all while tracking your progress with a gamified experience.

## 🚀 Quick Start

### Installation & Development
1. **Setup**: Use `uv` to install dependencies.
   ```bash
   uv sync
   ```
2. **Environment**: Export your API keys.
   ```bash
   export GEMINI_API_KEY="your-key"
   export GCP_PROJECT_ID="your-project"
   ```
3. **Run**: Start the development server.
   ```bash
   just run-web
   ```

## 🎯 Overview

This application provides a state-of-the-art language learning experience featuring:

- **🤖 Hybrid Learning**: Toggle between structured learning tasks and free-form conversation mode.
- **✨ Premium Web UI**: A minimalist, chat-centric interface with dark/light mode and glassmorphism.
- **🎮 Gamification Engine**: Daily streaks, XP tracking, and progress visualization.
- **🎙️ Multi-modal Feedback**: Record voice messages for pronunciation analysis or type your responses.
- **🧠 Adaptive SRS**: Spaced Repetition System that identifies your weak areas and reinforces them during conversation.
- **📊 Proficiency Analytics**: Visualize your mastery across grammar, vocabulary, and phrasal verbs with interactive charts.

## 🚀 Key Features

### Learning Modes
- **9 Structured Tasks**:
  - Error correction, Vocabulary matching, Idioms, Phrasal verbs, Writing, and more.
- **Free-form Conversation**: 
  - Chat naturally with the AI tutor. It provides separate "Tutor Notes" for corrections without breaking your flow.
  - **Adjustable Sensitivity**: Choose between Casual, Standard, or Strict correction thresholds.

### Technical Stack
- **Backend**: FastAPI & Python 3.12+
- **Frontend**: Vanilla JS, CSS, and HTML with Chart.js
- **Database**: Google Firestore
- **AI Engine**: Google Gemini (Pro & Flash) for generation, evaluation, and transcription.

## 🛠️ Project Structure
- `app_core/`: Central logic for AI interactions, database management, and utilities.
- `static/`: Frontend assets (styles, scripts, and views).
- `web_app.py`: FastAPI server implementation.
- `core_logic.py`: Main service layer bridging the UI and the engine.

---
*Built with ❤️ for language learners.*
