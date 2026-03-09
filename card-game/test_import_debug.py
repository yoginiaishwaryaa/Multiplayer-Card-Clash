try:
    from backend.app.models import Message
    print("Import successful")
except ImportError as e:
    print(f"Import failed: {e}")
