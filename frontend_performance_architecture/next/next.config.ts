import type { NextConfig } from 'next';

const config: NextConfig = {
  // 計測用コンテナからはネットワーク別名 next.test で来る
  allowedDevOrigins: ['next.test'],
};

export default config;
