import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';

/** Permissão que cria e edita calendários e políticas e escolhe o SLA de cada categoria (ADR-017). */
export const SLA_MANAGE = 'service_desk.sla.manage';

export type SlaPriority = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW';
export const SLA_PRIORITIES: { code: SlaPriority; label: string }[] = [
  { code: 'CRITICAL', label: 'Crítica' },
  { code: 'HIGH', label: 'Alta' },
  { code: 'MEDIUM', label: 'Média' },
  { code: 'LOW', label: 'Baixa' }
];

/** O `sla` que acompanha cada chamado na API. */
export interface SlaInfo {
  state: 'NOT_APPLICABLE' | 'RUNNING' | 'PAUSED' | 'MET' | 'BREACHED';
  policy_name?: string | null;
  cycle?: number | null;
  priority?: string | null;
  first_response_due_at?: string | null;
  resolution_due_at?: string | null;
  first_response_at?: string | null;
  resolved_at?: string | null;
  paused?: boolean;
  breaches?: string[];
  /** Prazo pendente já vencido (antes de o job registrar a violação). */
  overdue?: boolean;
  /** Acima do % de alerta da política. */
  at_risk?: boolean;
}

/** Indicadores de SLA de um grupo (total, categoria ou prioridade); minutos úteis. */
export interface SlaGroup {
  key: string;
  label: string;
  met: number;
  breached: number;
  compliance_percent: number | null;
  avg_first_response_minutes: number | null;
  avg_resolution_minutes: number | null;
}

export interface SlaAttention {
  ticket_id: string;
  title: string;
  priority: string;
  kind: 'FIRST_RESPONSE' | 'RESOLUTION';
  due_at: string;
  overdue: boolean;
}

export interface SlaReport {
  total: SlaGroup;
  by_category: SlaGroup[];
  by_priority: SlaGroup[];
  open: number;
  at_risk: number;
  overdue: number;
  attention: SlaAttention[];
}

export interface TicketsReport {
  start: string | null;
  end: string | null;
  total_tickets: number;
  resolution_rate_percent: number;
  by_status: Record<string, number>;
  by_priority: Record<string, number>;
  by_category: { category: string; count: number }[];
  sla: SlaReport;
}

export interface SlaHoliday {
  day: string; // AAAA-MM-DD
  name: string;
}

export interface SlaCalendar {
  id: string;
  name: string;
  timezone: string;
  /** Dia da semana ("0" = segunda ... "6" = domingo) -> intervalos [["08:00", "18:00"], ...] */
  weekly_hours: Record<string, string[][]>;
  holidays: SlaHoliday[];
  policy_names: string[];
}

export type SlaCalendarInput = Omit<SlaCalendar, 'id' | 'policy_names'>;

export interface SlaTarget {
  priority: SlaPriority;
  first_response_minutes: number;
  resolution_minutes: number;
}

export interface SlaPolicy {
  id: string;
  name: string;
  description?: string | null;
  is_active: boolean;
  calendar_id: string;
  calendar_name: string;
  pause_statuses: string[];
  reopen_rule: 'RESTART' | 'CONTINUE';
  alert_percent: number;
  targets: SlaTarget[];
  category_names: string[];
}

export type SlaPolicyInput = Omit<SlaPolicy, 'id' | 'calendar_name' | 'category_names'>;

/** 90 -> "1 h 30 min"; 480 -> "8 h"; 30 -> "30 min". */
export function formatMinutes(minutes: number): string {
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${m} min`;
  return m ? `${h} h ${m} min` : `${h} h`;
}

@Injectable({ providedIn: 'root' })
export class SlaService {
  private http = inject(HttpClient);
  private apiUrl = '/api/v1/sla';

  listCalendars(): Observable<SlaCalendar[]> {
    return this.http.get<SlaCalendar[]>(`${this.apiUrl}/calendars`);
  }

  createCalendar(payload: SlaCalendarInput): Observable<SlaCalendar> {
    return this.http.post<SlaCalendar>(`${this.apiUrl}/calendars`, payload);
  }

  updateCalendar(id: string, payload: Partial<SlaCalendarInput>): Observable<SlaCalendar> {
    return this.http.patch<SlaCalendar>(`${this.apiUrl}/calendars/${id}`, payload);
  }

  deleteCalendar(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/calendars/${id}`);
  }

  listPolicies(): Observable<SlaPolicy[]> {
    return this.http.get<SlaPolicy[]>(`${this.apiUrl}/policies`);
  }

  createPolicy(payload: SlaPolicyInput): Observable<SlaPolicy> {
    return this.http.post<SlaPolicy>(`${this.apiUrl}/policies`, payload);
  }

  updatePolicy(id: string, payload: Partial<SlaPolicyInput>): Observable<SlaPolicy> {
    return this.http.patch<SlaPolicy>(`${this.apiUrl}/policies/${id}`, payload);
  }

  deletePolicy(id: string): Observable<void> {
    return this.http.delete<void>(`${this.apiUrl}/policies/${id}`);
  }

  /** Relatório de chamados; `start`/`end` em AAAA-MM-DD (o último dia entra). */
  ticketsReport(start?: string, end?: string): Observable<TicketsReport> {
    const params: Record<string, string> = {};
    if (start) params['start'] = start;
    if (end) params['end'] = end;
    return this.http.get<TicketsReport>('/api/v1/tickets/reports/summary', { params });
  }
}
