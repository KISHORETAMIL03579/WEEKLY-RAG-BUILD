# backend/storage/exceptions.py
class RetrievalBackendError(RuntimeError):
    """Raised when the vector database or retrieval storage backend fails."""
    pass

