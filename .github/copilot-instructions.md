# GitHub Copilot Instructions for Maritime Command OS

## Project Overview
This project is a Maritime Intelligence and Risk Analysis platform built with a Python backend (FastAPI, SQLAlchemy) and a frontend dashboard (Streamlit). 

## Code Style & Architecture
- **Language**: Python 3.10+
- **Backend Framework**: FastAPI. Use dependency injection for database sessions.
- **Database**: PostgreSQL with SQLAlchemy ORM and Alembic for migrations.
- **Frontend**: Streamlit. Prefer clean UI components, `st.columns`, `st.expander`, and native Streamlit interactive features. Custom HTML should use `unsafe_allow_html=True` carefully without empty newlines that break Markdown parsing.
- **Machine Learning**: `scikit-learn`, `pandas`, `numpy` for risk engine calculations. 

## Best Practices
1. **Typing**: Always use strict Python type hints (`from typing import List, Dict, Optional, Any`).
2. **Docstrings**: Use Google-style or standard descriptive docstrings for all functions and classes.
3. **Error Handling**: Use `try/except` blocks gracefully. In FastAPI, raise `HTTPException` with clear status codes and details.
4. **Security**: Never hardcode credentials. Use `.env` files and `python-dotenv`. Implement role-based access control (Admin, Operator, Public).
5. **Testing**: Write comprehensive unit tests using `pytest`. Place them in the `tests/` directory. Use fixtures for database connections.

## Workflow Rules
- When fixing UI issues in Streamlit, prefer native components or compact raw HTML strings.
- Always check `requirements.txt` for available libraries before suggesting new ones.
- Keep the `backend/`, `frontend/`, `database/`, and `ml/` layers cleanly separated. Do not mix database connection logic directly inside Streamlit frontend views; call the backend API or use isolated data services.
