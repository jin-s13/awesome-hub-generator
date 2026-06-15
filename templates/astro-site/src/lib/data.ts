import fs from 'node:fs';
import path from 'node:path';
import YAML from 'yaml';

export type LinkMap = Record<string, string>;
export type SourceRef = { repo: string; category?: string };

export type Paper = {
  id: string;
  title: string;
  year: number;
  venue: string;
  category: string;
  tags: string[];
  representations?: string[];
  input_modalities?: string[];
  output_modalities?: string[];
  links: LinkMap;
  preview?: string;
  sources: SourceRef[];
  notes?: string;
};

export type Resource = {
  id: string;
  name: string;
  category?: string;
  type?: string;
  year?: number;
  language?: string[];
  kernel?: string[];
  description: string;
  tags: string[];
  links: LinkMap;
  sources: SourceRef[];
  notes?: string;
};

function loadYaml<T>(relativePath: string): T[] {
  const file = path.join(process.cwd(), relativePath);
  const raw = fs.readFileSync(file, 'utf-8');
  return YAML.parse(raw) as T[];
}

export function getPapers(): Paper[] {
  return loadYaml<Paper>('data/papers.yaml').sort((a, b) => b.year - a.year || a.title.localeCompare(b.title));
}

export function getDatasets(): Resource[] {
  return loadYaml<Resource>('data/datasets.yaml').sort((a, b) => (b.year || 0) - (a.year || 0) || a.name.localeCompare(b.name));
}

export function getTools(): Resource[] {
  return loadYaml<Resource>('data/tools.yaml').sort((a, b) => (a.type || '').localeCompare(b.type || '') || a.name.localeCompare(b.name));
}

export function uniq<T>(arr: T[]): T[] {
  return Array.from(new Set(arr));
}

export function getStats() {
  const papers = getPapers();
  const datasets = getDatasets();
  const tools = getTools();
  return {
    papers: papers.length,
    datasets: datasets.length,
    tools: tools.length,
    sources: uniq([...papers, ...datasets, ...tools].flatMap((x: any) => (x.sources || []).map((s: SourceRef) => s.repo))).length,
    years: uniq(papers.map((p) => p.year)).sort((a, b) => b - a),
    categories: uniq(papers.map((p) => p.category)).sort()
  };
}
