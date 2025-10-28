import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  // 产出静态导出，便于由 FastAPI 直接托管静态文件
  output: "export",
};

export default nextConfig;
