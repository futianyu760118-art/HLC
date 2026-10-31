// @ts-nocheck

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// 自定义插件：用于在终端打印前端错误
const errorLoggerPlugin = () => ({
  name: 'error-logger-plugin',
  configureServer(server) {
    server.middlewares.use('/log-error-from-frontend', (req, res) => {
      let body = '';
      req.on('data', chunk => { body += chunk; });
      req.on('end', () => {
        const error = JSON.parse(body);
        console.error(
          '[Browser Runtime Error]\n' +
          `Error: ${error.message}\n` +
          `Stack Trace:\n${error.stack}`
        );
        res.end('Error logged on server.');
      });
    });
  },
});

// https://vite.dev/config/
export default defineConfig(({ mode }) => ({
  plugins: [react(), mode === 'development' ? errorLoggerPlugin() : null,],
  server: {
    port: 15173,
    allowedHosts: true,
    hmr: {
      path: '/ws',
    }
    ,proxy: {
      '/api': {
        target: 'http://localhost:18888',
        changeOrigin: true,
        secure: false,
      },
      '/uploads': {
        target: 'http://localhost:18888',
        changeOrigin: true,
        secure: false,
      }
    }
  },
  build: {
    // 生成带内容哈希的文件名，确保每次构建都能破坏缓存
    chunkSizeWarningLimit: 1000,
    rollupOptions: {
      output: {
        // 为入口文件添加哈希
        entryFileNames: 'assets/[name]-[hash].js',
        // 为代码分割的chunk添加哈希
        chunkFileNames: 'assets/[name]-[hash].js',
        // 为静态资源添加哈希
        assetFileNames: 'assets/[name]-[hash].[ext]',
      }
    }
  }
}));
