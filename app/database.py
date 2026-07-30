from supabase import create_client, Client
from app.config import settings

# Inisialisasi Supabase Client tunggal menggunakan Service Role Key (Bypass RLS)
supabase: Client = create_client(settings.supabase_url, settings.supabase_service_role_key)