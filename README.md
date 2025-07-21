# Language Learning Tutor - AI-Powered English Learning Assistant

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Google Cloud Functions](https://img.shields.io/badge/Google%20Cloud-Functions-orange.svg)](https://cloud.google.com/functions)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-blue.svg)](https://core.telegram.org/bots)

An intelligent, adaptive English learning tutor built with Google Cloud Functions, Telegram Bot API, and AI-powered task generation. The system provides personalized learning experiences through adaptive algorithms, spaced repetition, and comprehensive progress tracking.

## 🚀 Quick Start

### Usage

1. **Start Learning**: Use `/start` to start interacting with the bot.
2. **Set language**: Use `/language` to choose language of responses.
3. **Set Difficulty**: Use `/difficulty` to choose your English learner level (beginner, intermediate, advanced).
4. **Practice**: Send `/newtask` to your Telegram bot to start learning and receive personalized feedback.
5. **Check Progress**: Use `/progress` to see your learning statistics.

## 🎯 Overview

This project implements a sophisticated language learning system that:

- **🤖 AI-Powered Task Generation**: Uses Google's Gemini AI to create engaging, personalized English learning tasks
- **📱 Telegram Integration**: Delivers learning content through an intuitive Telegram bot interface
- **🧠 Adaptive Learning**: Avoids repeating previously practiced main learning objectives for each task type, using user history
- **📊 Progress Tracking**: Comprehensive analytics and progress reporting
- **🎙️ Voice Analysis**: Supports voice recording analysis for pronunciation practice
- **☁️ Cloud-Native**: Built on Google Cloud Functions for scalability and reliability

## 🚀 Features

### Core Learning Features
- **9 Task Types**:
  - Error correction
  - Vocabulary matching
  - Idiom practice
  - Phrasal verb practice
  - Word fluency
  - Freestyle voice recording
  - Topic provided voice recording
  - Vocabulary
  - Writing
- **Difficulty Setting**: Users can set their English learner level (beginner, intermediate, advanced) with `/difficulty`. Vocabulary tasks adapt to this setting.
- **Real-time Feedback**: Instant AI-powered evaluation and personalized feedback.
- **Voice Support**: Multimodal llm for handling voice recordings.

### Adaptive Learning System
- **Personalized Tasks**: Ensures users always get new, unique learning content based on their own practice history.
- **Language Selection**: Users can set their preferred language for model responses using `/language`. The main learning objective (e.g., the word, idiom, or topic) is always in English, but all other instructions, explanations, and feedback will be in the selected language. The default is English, but users can change this at any time.
- **Progress Analytics**: Detailed reports with actionable recommendations

### Technical Features
- **Serverless Architecture**: Google Cloud Functions for automatic scaling
- **Secure Secrets Management**: Google Secret Manager for API keys and tokens
- **NoSQL Database**: Firestore for user data and progress tracking
- **AI Integration**: Google Gemini for intelligent content generation
- **Voice Processing**: Google multimodal llm for audio analysis

## 🛠️ Technology Stack

### Backend & Cloud Services
- **Google Cloud Functions**: Serverless compute platform
- **Google Firestore**: NoSQL database for user data
- **Google Secret Manager**: Secure secrets and API key management
- **Google Speech-to-Text**: Voice transcription service
- **Google Gemini AI**: Advanced AI for task generation and evaluation

### APIs & Integrations
- **Telegram Bot API**: User interface and interaction
- **Functions Framework**: Python runtime for Cloud Functions
- **Requests**: HTTP client for API calls

### Development Tools
- **Python 3.12+**: Primary programming language
- **Google Cloud CLI**: Deployment and management
- **UV**: Fast Python package manager

## Admin Commands

### Available Commands

| Command         | Description                                                                                 |
|----------------|---------------------------------------------------------------------------------------------|
| `/start`       | Welcome message and bot introduction                                                        |
| `/newtask`     | Start a new learning task                                                                   |
| `/progress`    | View your learning progress                                                                 |
| `/help`        | Show this help message                                                                      |
| `/difficulty`  | Set your English learner difficulty (beginner, intermediate, advanced)                      |
| `/language`    | Select your preferred language for model responses. The main learning objective is always in English, but all other instructions, explanations, and feedback will be in your chosen language. |

## Task Types & Difficulty

- **Error correction**: Fix grammatical errors in sentences
- **Vocabulary matching**: Match words with their definitions
- **Idiom practice**: Learn and practice English idioms
- **Phrasal verb practice**: Learn and practice English phrasal verbs
- **Word fluency**: Generate words starting with specific letters
- **Freestyle voice recording**: Practice pronunciation with any topic
- **Topic voice recording**: Practice pronunciation with a provided topic
- **Vocabulary**: Learn 5 words and use them in sentences
- **Writing**: Answer a thoughtful, open-ended question
