from supabase import create_client, Client
from app.config import settings

# Inisialisasi Supabase Client tunggal (Singleton-like)
supabase: Client = create_client(settings.supabase_url, settings.supabase_key)