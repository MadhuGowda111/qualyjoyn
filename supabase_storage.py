import os
import uuid
from dotenv import load_dotenv
from supabase import create_client, Client

load_dotenv()

SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

if not SUPABASE_URL:
    raise Exception("SUPABASE_URL is missing in .env")

if not SUPABASE_KEY:
    raise Exception("SUPABASE_SERVICE_KEY is missing in .env")

supabase: Client = create_client(
    SUPABASE_URL,
    SUPABASE_KEY
)

BUCKET_NAME = "products"

def upload_product_image(product_id, image_file, display_order):
    """
    Upload one product image to Supabase Storage.

    Returns:
        Public URL
    """

    extension = image_file.filename.rsplit(".", 1)[1].lower()

    filename = f"{uuid.uuid4().hex}.{extension}"

    storage_path = f"{product_id}/{filename}"

    try:
        image_file.stream.seek(0)

        supabase.storage.from_(BUCKET_NAME).upload(
            path=storage_path,
            file=image_file.read(),
            file_options={
                "content-type": image_file.content_type,
                "upsert": "false"
            }
        )

        return supabase.storage.from_(BUCKET_NAME).get_public_url(storage_path)

    except Exception as e:
        print("Supabase Upload Error:", e)
        raise