import type { NextConfig } from "next";

// The frontend talks to FastAPI directly via NEXT_PUBLIC_API_URL
// (defaults to http://127.0.0.1:8000/api). We intentionally do NOT proxy
// /api/* through Next.js dev rewrites because long-running endpoints
// (lecture processing, streaming Q&A) exceed the dev proxy's socket timeout.
const nextConfig: NextConfig = {};

export default nextConfig;
