const API_BASE =
  process.env.NEXT_PUBLIC_API_URL || "http://127.0.0.1:8000/api";

async function request<T = any>(path: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, options);
  const data = await res.json();
  return data as T;
}

export interface LectureProcessResult {
  lecture_id: string;
  reused: boolean;
  message: string;
  source_url?: string;
  chunk_count?: number;
  error?: string;
}

export async function processLecture(formData: FormData): Promise<LectureProcessResult> {
  const res = await fetch(`${API_BASE}/lectures/process`, { method: "POST", body: formData });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.error || `Processing failed with status ${res.status}`);
  }
  return data;
}

export interface DashboardData {
  stats: { due_today: number; overdue: number; lectures_in_rotation: number; lecture_count: number };
  lectures: any[];
  study_next: any[];
  has_due_cards: boolean;
}

export async function fetchDashboard(): Promise<DashboardData> {
  return request("/lectures");
}

export async function deleteLecture(lectureId: string) {
  return request(`/lectures/${lectureId}`, { method: "DELETE" });
}

export interface QAInfo {
  lecture_id: string;
  has_chunks: boolean;
  lecture_meta: Record<string, any>;
}

export async function fetchQAInfo(lectureId: string): Promise<QAInfo> {
  return request(`/qa?lecture_id=${encodeURIComponent(lectureId)}`);
}

export async function askQuestion(formData: FormData) {
  const res = await fetch(`${API_BASE}/qa`, { method: "POST", body: formData });
  return res.json();
}

export function getStreamUrl(): string {
  return `${API_BASE}/qa/stream`;
}

export async function synthesizeSpeech(text: string, voice?: string): Promise<string> {
  const fd = new FormData();
  fd.set("text", text);
  if (voice) fd.set("voice", voice);
  const res = await fetch(`${API_BASE}/qa/tts`, { method: "POST", body: fd });
  if (!res.ok) {
    let message = `TTS failed (${res.status})`;
    try {
      const data = await res.json();
      if (data?.error) message = String(data.error);
    } catch {
      /* ignore non-JSON error bodies */
    }
    throw new Error(message);
  }
  const blob = await res.blob();
  return URL.createObjectURL(blob);
}

export interface SummaryData {
  lecture_id: string;
  title: string;
  content: string;
  mode: string;
  lecture_meta: Record<string, any>;
  error?: string;
}

export async function fetchSummary(lectureId: string): Promise<SummaryData> {
  return request(`/summary?lecture_id=${encodeURIComponent(lectureId)}`);
}

export async function fetchNotes(lectureId: string): Promise<SummaryData> {
  return request(`/notes?lecture_id=${encodeURIComponent(lectureId)}`);
}

export function getDownloadUrl(docType: string, lectureId: string): string {
  return `${API_BASE}/download/${docType}?lecture_id=${encodeURIComponent(lectureId)}`;
}

export interface QuizData {
  lecture_id: string;
  questions: any[];
  lecture_meta: Record<string, any>;
  coaching: Record<string, any>;
  error?: string;
}

export async function fetchQuiz(lectureId: string): Promise<QuizData> {
  return request(`/quiz?lecture_id=${encodeURIComponent(lectureId)}`);
}

export async function regenerateQuiz(lectureId: string): Promise<QuizData> {
  const formData = new FormData();
  formData.set("lecture_id", lectureId);
  const res = await fetch(`${API_BASE}/quiz/regenerate`, { method: "POST", body: formData });
  return res.json();
}

export interface QuizSubmitResult {
  lecture_id: string;
  results: any[];
  total_score: number;
  coaching: Record<string, any>;
  lecture_meta: Record<string, any>;
}

export async function submitQuiz(lectureId: string, answers: Record<string, any>): Promise<QuizSubmitResult> {
  const formData = new FormData();
  formData.set("lecture_id", lectureId);
  formData.set("answers", JSON.stringify(answers));
  const res = await fetch(`${API_BASE}/quiz/submit`, { method: "POST", body: formData });
  return res.json();
}

export interface FlashcardsData {
  dashboard: DashboardData;
  due_groups: any[];
  lecture_id: string;
  lecture_meta: Record<string, any>;
  lecture_summary: Record<string, any>;
  current_card: any;
  queue_cards: any[];
  coaching: Record<string, any>;
  error?: string;
}

export async function fetchFlashcards(lectureId?: string): Promise<FlashcardsData> {
  const query = lectureId ? `?lecture_id=${encodeURIComponent(lectureId)}` : "";
  return request(`/flashcards${query}`);
}

export async function reviewFlashcard(lectureId: string, cardId: string, rating: string) {
  const formData = new FormData();
  formData.set("lecture_id", lectureId);
  formData.set("card_id", cardId);
  formData.set("rating", rating);
  const res = await fetch(`${API_BASE}/flashcards/review`, { method: "POST", body: formData });
  return res.json();
}

export async function regenerateFlashcards(lectureId: string) {
  const formData = new FormData();
  formData.set("lecture_id", lectureId);
  const res = await fetch(`${API_BASE}/flashcards/regenerate`, { method: "POST", body: formData });
  return res.json();
}
