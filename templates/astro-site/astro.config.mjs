import { defineConfig } from 'astro/config';

export default defineConfig({
  site: '{{SITE_URL}}',
  output: 'static',
  redirects: {
    '/': '/en/',
  },
});
