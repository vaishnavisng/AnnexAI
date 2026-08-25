from fastapi import FastAPI


def register_routers(app: FastAPI) -> None:
    from app.api.flashcard_routes import router as flashcards_router
    from app.api.lecture_routes import router as lectures_router
    from app.api.library_routes import router as library_router
    from app.api.qa_routes import router as qa_router
    from app.api.quiz_routes import router as quiz_router
    from app.api.study_routes import router as study_router

    app.include_router(lectures_router, prefix="/api", tags=["lectures"])
    app.include_router(library_router, prefix="/api", tags=["library"])
    app.include_router(qa_router, prefix="/api", tags=["qa"])
    app.include_router(quiz_router, prefix="/api", tags=["quiz"])
    app.include_router(study_router, prefix="/api", tags=["study"])
    app.include_router(flashcards_router, prefix="/api", tags=["flashcards"])


__all__ = ["register_routers"]
