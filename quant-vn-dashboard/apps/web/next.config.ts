import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  reactStrictMode: true,
  experimental: {
    typedRoutes: true,
  },
  async rewrites() {
    // Optional convenience: proxy /api/* on the web origin to the FastAPI host.
    // Disable by setting NEXT_PUBLIC_API_BASE_URL to a full URL the browser
    // can reach directly.
    const target = process.env.NEXT_PUBLIC_API_BASE_URL;
    if (!target) return [];
    return [{ source: "/api/:path*", destination: `${target}/:path*` }];
  },
};

export default nextConfig;
