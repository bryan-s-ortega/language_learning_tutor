# Language Learning Tutor - AI-Powered English Learning Assistant

[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Google Cloud Functions](https://img.shields.io/badge/Google%20Cloud-Functions-orange.svg)](https://cloud.google.com/functions)
[![Telegram Bot](https://img.shields.io/badge/Telegram-Bot-blue.svg)](https://core.telegram.org/bots)

An intelligent, adaptive English learning tutor built with Google Cloud Functions, Telegram Bot API, and AI-powered task generation. The system provides personalized learning experiences through adaptive algorithms, spaced repetition, and comprehensive progress tracking.

## 🚀 Quick Start

### Usage

1. **Start Learning**: Send `/newtask` to your Telegram bot
2. **Check Progress**: Use `/progress` to see your learning statistics
3. **Practice**: Complete tasks and receive personalized feedback
4. **Voice Practice**: Send voice messages for pronunciation analysis

## 🎯 Overview

This project implements a sophisticated language learning system that:

- **🤖 AI-Powered Task Generation**: Uses Google's Gemini AI to create engaging, personalized English learning tasks
- **📱 Telegram Integration**: Delivers learning content through an intuitive Telegram bot interface
- **🧠 Adaptive Learning**: Implements intelligent algorithms that focus on user's weak areas
- **📊 Progress Tracking**: Comprehensive analytics and progress reporting
- **🔄 Spaced Repetition**: Optimizes learning intervals for better retention
- **🎙️ Voice Analysis**: Supports voice recording analysis for pronunciation practice
- **☁️ Cloud-Native**: Built on Google Cloud Functions for scalability and reliability

## 🚀 Features

### Core Learning Features
- **5 Task Types**: Error correction, vocabulary matching, idioms/phrasal verbs, word fluency, and voice recording analysis
- **Real-time Feedback**: Instant AI-powered evaluation and personalized feedback
- **Voice Support**: Speech-to-text transcription and pronunciation analysis
- **Interactive Interface**: Telegram keyboard buttons for seamless navigation

### Adaptive Learning System
- **Weak Area Detection**: Automatically identifies topics where users struggle
- **Personalized Tasks**: Generates content focused on improving weak areas
- **Smart Task Selection**: Recommends optimal task types based on performance
- **Spaced Repetition**: Reviews items at optimal intervals based on mastery levels
- **Progress Analytics**: Detailed reports with actionable recommendations

### Technical Features
- **Serverless Architecture**: Google Cloud Functions for automatic scaling
- **Secure Secrets Management**: Google Secret Manager for API keys and tokens
- **NoSQL Database**: Firestore for user data and progress tracking
- **AI Integration**: Google Gemini for intelligent content generation
- **Voice Processing**: Google Speech-to-Text for audio analysis

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