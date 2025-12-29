import argparse
import concurrent
import os
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from openai import OpenAI
from .config import settings


class KnowledgeBase:
    def __init__(self):
        self.openai_client = OpenAI(api_key=settings.openai_api_key)
        self.vector_store_id = None

    def upload_single_file_to_vector_store(self, file_path: os.PathLike, vector_store_id: str):
        file_name = os.path.basename(file_path)

        try:
            file_response = self.openai_client.files.create(
                file=open(file_path, "rb"), purpose="assistants"
            )
            attach_response = self.openai_client.vector_stores.files.create(
                vector_store_id=vector_store_id, file_id=file_response.id
            )
            return {"file": file_name, "status": "success"}
        except Exception as e:
            print(f"Error uploading file {file_name}: {e}")
            return {"file": file_name, "status": "error", "error": str(e)}

    def upload_directory_to_vector_store(self, directory_path: os.PathLike, vector_store_id: str):
        files = [Path(directory_path) / Path(file) for file in os.listdir(directory_path)]
        stats = {
            "total_files": len(files),
            "successful_uploads": 0,
            "failed_uploads": 0,
            "errors": []
        }

        print(f"Uploading {stats['total_files']} files to vector store {vector_store_id}...")
        with concurrent.futures.ThreadPoolExecutor(max_workers=os.cpu_count() - 1) as executor:
            futures = {executor.submit(self.upload_single_file_to_vector_store, file_path, vector_store_id): file_path for file_path in files}
            for future in concurrent.futures.as_completed(futures):
                result = future.result()
                if result["status"] == "success":
                    stats["successful_uploads"] += 1
                    print(f"Uploaded file {result['file']}")
                else:
                    stats["failed_uploads"] += 1
                    stats["errors"].append(result)

        return stats

    def create_vector_store(self, vector_store_name: str) -> dict[str, Any]:
        try:
            vector_store = self.openai_client.vector_stores.create(name=vector_store_name)
            details = {
                "id": vector_store.id,
                "name": vector_store.name,
                "created_at": vector_store.created_at,
                "file_count": vector_store.file_counts.completed
            }
            print(f"Vector store {vector_store_name} created successfully: {details}")
            self.vector_store_id = details["id"]

            return details
        except Exception as e:
            print(f"Error creating vector store {vector_store_name}: {e}")
            return {}

    def create_and_initialize_vector_store(self, vector_store_name: str, directory_path: os.PathLike):
        vector_store = self.create_vector_store(vector_store_name)
        if not vector_store:
            raise ValueError("Failed to create vector store")

        stats = self.upload_directory_to_vector_store(directory_path, vector_store["id"])
        return stats

    def shut_down_vector_store(self):
        if self.vector_store_id:
            try:
                self.openai_client.vector_stores.delete(self.vector_store_id)
                print(f"Vector store {self.vector_store_id} deleted successfully")
            except Exception as e:
                print(f"Error deleting vector store {self.vector_store_id}: {e}")
        else:
            print("No vector store ID found")
