/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  async rewrites() {
    const origin = process.env.REPOPILOT_API_ORIGIN;
    if (!origin) return [];
    const url = new URL(origin);
    if (url.protocol !== "https:" || url.username || url.password || url.pathname !== "/" || url.search || url.hash) {
      throw new Error("REPOPILOT_API_ORIGIN must be an HTTPS origin without credentials or a path");
    }
    return [{ source: "/api/:path*", destination: `${url.origin}/:path*` }];
  }
};

export default nextConfig;
