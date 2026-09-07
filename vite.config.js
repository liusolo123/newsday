import { resolve } from 'node:path';
import { defineConfig } from 'vite';

function reloadJinjaTemplates() {
  const templatesDirectory = resolve(process.cwd(), 'app/templates');
  return {
    name: 'reload-jinja-templates',
    configureServer(server) {
      server.watcher.add(templatesDirectory);
      server.watcher.on('change', (file) => {
        if (file.startsWith(templatesDirectory) && file.endsWith('.html')) {
          server.ws.send({ type: 'full-reload' });
        }
      });
    },
  };
}

export default defineConfig({
  plugins: [reloadJinjaTemplates()],
  server: {
    host: '127.0.0.1',
    port: 5173,
    strictPort: true,
    cors: {
      origin: 'http://127.0.0.1:8000',
    },
  },
  build: {
    outDir: 'app/static/dist',
    emptyOutDir: true,
    manifest: true,
    rollupOptions: {
      input: resolve(process.cwd(), 'frontend/main.js'),
    },
  },
});
