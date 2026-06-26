import fs from 'node:fs';
import path from 'node:path';
import YAML from 'yaml';

export type LinkMap = Record<string, string>;
export type SourceRef = { repo: string; category?: string };

export type ScoreEvidence = {
  source?: string;
  field?: string;
  detail?: string;
};

export type ScoreComponent = {
  value: number;
  available?: boolean;
  confidence?: string;
  explanation?: string;
  explanation_zh?: string;
  evidence?: ScoreEvidence[];
};

export type ScoreInfo = {
  total: number;
  read_first_score?: number;
  components?: Record<string, ScoreComponent>;
  applied_weights?: Record<string, number>;
  ranking_profile?: string;
  warnings?: string[];
  keyword_scores?: Record<string, number>;
  author_bonus?: number;
  passing_score?: number;
  is_qualified?: boolean;
};

export type AnalysisInfo = {
  innovations?: string[];
  methodology?: string;
  key_results?: string;
  limitations?: string[];
  tech_stack?: string[];
};

export type Paper = {
  id: string;
  title: string;
  year: number;
  venue: string;
  category?: string;
  paper_type?: string[] | string;
  tags: string[];
  representations?: string[];
  input_modalities?: string[];
  output_modalities?: string[];
  links: LinkMap;
  preview?: string;
  sources: SourceRef[];
  notes?: string;
  score?: ScoreInfo;
  tldr?: string;
  reasoning?: string;
  analysis?: AnalysisInfo;
  // Bilingual (Chinese) fields
  title_cn?: string;
  abstract_cn?: string;
  tldr_cn?: string;
  reasoning_cn?: string;
  analysis_cn?: AnalysisInfo;
};

export type Resource = {
  id: string;
  name: string;
  category?: string;
  type?: string;
  resource_type?: string;
  year?: number;
  language?: string[];
  kernel?: string[];
  description: string;
  tags: string[];
  links: LinkMap;
  sources: SourceRef[];
  notes?: string;
};

export type SurveyPaperRef = {
  id: string;
  title: string;
  year?: number;
  score?: number;
  url?: string;
};

export type SurveyTopic = {
  id: string;
  label: string;
  label_zh?: string;
  description?: string;
  description_zh?: string;
  paper_count: number;
  top_tags: string[];
  component_averages?: Record<string, number>;
  top_papers: SurveyPaperRef[];
  related_work_outline: string[];
  related_work_outline_zh?: string[];
};

export type SurveyIndex = {
  schema_version?: string;
  generated_at?: string;
  topics: SurveyTopic[];
};

function loadYaml<T>(relativePath: string): T[] {
  const file = path.join(process.cwd(), relativePath);
  if (!fs.existsSync(file)) {
    return [];
  }
  const raw = fs.readFileSync(file, 'utf-8');
  const parsed = YAML.parse(raw);
  return Array.isArray(parsed) ? parsed as T[] : [];
}

function loadYamlObject<T>(relativePath: string, fallback: T): T {
  const file = path.join(process.cwd(), relativePath);
  if (!fs.existsSync(file)) {
    return fallback;
  }
  const raw = fs.readFileSync(file, 'utf-8');
  const parsed = YAML.parse(raw);
  return parsed && typeof parsed === 'object' && !Array.isArray(parsed) ? parsed as T : fallback;
}

export function getPapers(): Paper[] {
  return loadYaml<Paper>('data/papers.yaml').sort((a, b) => b.year - a.year || a.title.localeCompare(b.title));
}

export function getPaper(id: string): Paper | undefined {
  return getPapers().find((p) => p.id === id);
}

export function paperTypeList(paper: Paper): string[] {
  const raw = paper.paper_type;
  const values = Array.isArray(raw) ? raw : raw ? [raw] : [];
  const fallback = paper.category ? [paper.category] : [];
  return uniq([...values, ...fallback].filter(Boolean));
}

export function paperTypeLabel(paper: Paper): string {
  const types = paperTypeList(paper);
  return types.length > 0 ? types.join(', ') : 'method';
}

export function paperTypeFilterValue(paper: Paper): string {
  const types = paperTypeList(paper);
  return types.length > 0 ? types.join('|') : 'method';
}

export function getDatasets(): Resource[] {
  return loadYaml<Resource>('data/datasets.yaml').sort((a, b) => (b.year || 0) - (a.year || 0) || a.name.localeCompare(b.name));
}

export function getTools(): Resource[] {
  return loadYaml<Resource>('data/tools.yaml').sort((a, b) => (a.type || '').localeCompare(b.type || '') || a.name.localeCompare(b.name));
}

export function getResources(): Resource[] {
  return loadYaml<Resource>('data/resources.yaml').sort((a, b) => (a.name || '').localeCompare(b.name || ''));
}

export function getSurveys(): SurveyTopic[] {
  const surveyIndex = loadYamlObject<SurveyIndex>('data/surveys.yaml', { topics: [] });
  return (surveyIndex.topics || []).sort((a, b) => b.paper_count - a.paper_count || a.label.localeCompare(b.label));
}

export function uniq<T>(arr: T[]): T[] {
  return Array.from(new Set(arr));
}

export function getStats() {
  const papers = getPapers();
  const datasets = getDatasets();
  const tools = getTools();
  let resources: Resource[] = [];
  try {
    resources = getResources();
  } catch {
    resources = [];
  }
  return {
    papers: papers.length,
    datasets: datasets.length,
    tools: tools.length,
    resources: resources.length,
    sources: uniq([...papers, ...datasets, ...tools, ...resources].flatMap((x: any) => (x.sources || []).map((s: SourceRef) => s.repo))).length,
    years: uniq(papers.map((p) => p.year)).sort((a, b) => b - a),
    categories: uniq(papers.flatMap((p) => paperTypeList(p))).sort()
  };
}
