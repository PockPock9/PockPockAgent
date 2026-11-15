import react from '@vitejs/plugin-react'
import { defineConfig } from 'vite'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  build: {
    // The lazy-loaded Three.js renderer is 130 kB gzipped; budget its isolated chunk explicitly.
    chunkSizeWarningLimit: 600,
    rolldownOptions: {
      output: {
        codeSplitting: {
          groups: [
            {
              name: 'three-core',
              test: /node_modules[\\/]three[\\/]/,
              priority: 20,
            },
            {
              name: 'fiber-runtime',
              test: /node_modules[\\/]@react-three[\\/]fiber[\\/]/,
              priority: 15,
            },
          ],
        },
      },
    },
  },
  server: {
    host: '127.0.0.1',
    proxy: {
      '/api': {
        target: 'http://127.0.0.1:8766',
        changeOrigin: true,
      },
    },
  },
})
