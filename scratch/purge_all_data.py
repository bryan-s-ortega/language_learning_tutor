import os
from google.cloud import firestore
from app_core.config import config


def purge_collections():
    project_id = os.getenv("GCP_PROJECT_ID", config.database.project_id)
    print("--- DATABASE CLEANUP ---")
    print(f"Project ID: {project_id}")

    db = firestore.Client(project=project_id)
    collections = [
        config.database.firestore_collection,
        config.database.proficiency_collection,
        config.database.rate_limit_collection,
    ]

    for coll_name in collections:
        print(f"Purging collection: {coll_name}...")
        docs = db.collection(coll_name).list_documents()
        count = 0
        for doc in docs:
            doc.delete()
            count += 1
        print(f"Deleted {count} documents from {coll_name}.")


if __name__ == "__main__":
    confirm = input(
        "This will delete ALL data in the practice collections. Type 'YES' to confirm: "
    )
    if confirm == "YES":
        try:
            purge_collections()
            print("Cleanup complete.")
        except Exception as e:
            print(f"Error during cleanup: {e}")
            print(
                "\nMake sure you have set GOOGLE_APPLICATION_CREDENTIALS or are logged in with 'gcloud auth application-default login'."
            )
    else:
        print("Cleanup cancelled.")
