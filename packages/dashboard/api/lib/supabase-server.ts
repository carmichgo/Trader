import { createClient } from '@supabase/supabase-js';

const url = process.env.STORAGE_SUPABASE_URL || process.env.VITE_SUPABASE_URL || '';
const key = process.env.STORAGE_SUPABASE_SERVICE_ROLE_KEY || '';

export const supabase = createClient(url, key);
