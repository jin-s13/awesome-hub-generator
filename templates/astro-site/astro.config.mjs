import { defineConfig } from 'astro/config';
import sitemap from '@astrojs/sitemap';

export default defineConfig({
  site: '{{SITE_URL}}',
  integrations: [sitemap()],
  output: 'static'
});
