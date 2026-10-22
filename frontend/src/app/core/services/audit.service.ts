import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, map } from 'rxjs';

export interface AuditLogEntry {
  id: string;
  event_type: string;
  entity_type: string;
  entity_id: string;
  data: Record<string, unknown>;
  user_id: string | null;
  user_email: string | null;
  user_name: string | null;
  created_at: string;
}

export interface AuditFilters {
  event_type?: string;
  user?: string;
  /** AAAA-MM-DD (início do dia) */
  date_from?: string;
  /** AAAA-MM-DD (fim do dia) */
  date_to?: string;
}

export interface AuditPage {
  items: AuditLogEntry[];
  total: number;
}

@Injectable({ providedIn: 'root' })
export class AuditService {
  private http = inject(HttpClient);
  private baseUrl = '/api/v1/audit';

  list(filters: AuditFilters, limit: number, offset: number): Observable<AuditPage> {
    let params = new HttpParams().set('limit', limit).set('offset', offset);
    if (filters.event_type) params = params.set('event_type', filters.event_type);
    if (filters.user?.trim()) params = params.set('user', filters.user.trim());
    // datas locais do navegador convertidas para instantes UTC: o filtro cobre o dia inteiro do usuário
    if (filters.date_from) params = params.set('date_from', new Date(`${filters.date_from}T00:00:00`).toISOString());
    if (filters.date_to) params = params.set('date_to', new Date(`${filters.date_to}T23:59:59.999`).toISOString());
    return this.http
      .get<AuditLogEntry[]>(this.baseUrl, { params, observe: 'response' })
      .pipe(map((res) => ({ items: res.body ?? [], total: Number(res.headers.get('X-Total-Count') ?? res.body?.length ?? 0) })));
  }

  eventTypes(): Observable<string[]> {
    return this.http.get<string[]>(`${this.baseUrl}/event-types`);
  }
}
