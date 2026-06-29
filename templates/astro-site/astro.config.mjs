import { defineConfig } from 'astro/config';

export default defineConfig({
  site: '{{SITE_URL}}',
  base: '{{BASE_PATH}}' || undefined,
  output: 'static',
});
