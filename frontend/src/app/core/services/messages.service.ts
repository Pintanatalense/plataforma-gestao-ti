import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpHeaders, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { GatewayCapabilities } from './notifications-admin.service';

/** Central de Mensagens (ADR-025 M3). */
export interface MessageTemplate {
  id: string;
  code: string;
  name: string;
  channels: string[];
  subject: string;
  body: string;
  is_active: boolean;
  variables: string[];
}

export interface TemplateInput {
  code: string;
  name: string;
  channels: string[];
  subject: string;
  body: string;
  is_active: boolean;
}

export interface RecipientOption {
  user_id: string;
  name: string;
  email: string;
  channels: string[];
}

export interface MessageDraft {
  channel: string;
  subject: string;
  body: string;
  variables: Record<string, string>;
  priority: 'low' | 'normal' | 'high';
  template_id: string | null;
  recipient_ids: string[];
}

export type RecipientOutcome = 'queued' | 'no_address' | 'out_of_scope' | 'inactive' | 'unknown';

export interface PreviewRecipient {
  user_id: string;
  email: string;
  name: string;
  outcome: RecipientOutcome;
  rendered?: { text?: string; html?: string; subject?: string; title?: string; note?: string | null };
}

export interface PreviewResponse {
  channel: string;
  capabilities: GatewayCapabilities;
  recipients: PreviewRecipient[];
  queued: number;
  skipped: number;
}

export interface OutboundMessage {
  id: string;
  kind: 'manual' | 'test';
  channel: string;
  subject: string;
  priority: string;
  status: 'QUEUED' | 'CANCELLED';
  queued_count: number;
  skipped_count: number;
  created_at: string;
  created_by: string | null;
  cancelled_at: string | null;
  deliveries: Record<string, number>;
}

export interface OutboundMessageDetail extends OutboundMessage {
  body: string;
  variables: Record<string, string>;
  template_id: string | null;
  recipients: (PreviewRecipient & {
    delivery: { delivery_id: string; status: string; provider_status: string | null; attempts: number; last_error: string | null } | null;
  })[];
}

@Injectable({ providedIn: 'root' })
export class MessagesService {
  private http = inject(HttpClient);
  private base = '/api/v1/notifications/messages';

  listTemplates(): Observable<{ items: MessageTemplate[]; builtin_variables: string[] }> {
    return this.http.get<{ items: MessageTemplate[]; builtin_variables: string[] }>(`${this.base}/templates`);
  }

  createTemplate(body: TemplateInput): Observable<MessageTemplate> {
    return this.http.post<MessageTemplate>(`${this.base}/templates`, body);
  }

  updateTemplate(id: string, body: TemplateInput): Observable<MessageTemplate> {
    return this.http.put<MessageTemplate>(`${this.base}/templates/${id}`, body);
  }

  deleteTemplate(id: string): Observable<void> {
    return this.http.delete<void>(`${this.base}/templates/${id}`);
  }

  searchRecipients(q: string): Observable<{ items: RecipientOption[]; reaches_everyone: boolean }> {
    const params = q.trim() ? new HttpParams().set('q', q.trim()) : undefined;
    return this.http.get<{ items: RecipientOption[]; reaches_everyone: boolean }>(`${this.base}/recipients`, { params });
  }

  preview(draft: MessageDraft): Observable<PreviewResponse> {
    return this.http.post<PreviewResponse>(`${this.base}/preview`, draft);
  }

  /** `idempotencyKey` é gerada uma vez por rascunho: reenviar (clique duplo, rede) devolve o mesmo envio. */
  send(draft: MessageDraft, idempotencyKey: string): Observable<OutboundMessage> {
    const headers = new HttpHeaders({ 'Idempotency-Key': idempotencyKey });
    return this.http.post<OutboundMessage>(this.base, draft, { headers });
  }

  sendTest(draft: MessageDraft): Observable<OutboundMessage> {
    return this.http.post<OutboundMessage>(`${this.base}/test`, draft);
  }

  list(filters: { channel?: string; kind?: string; limit?: number; offset?: number } = {}): Observable<{ total: number; items: OutboundMessage[] }> {
    let params = new HttpParams();
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== null && value !== '') params = params.set(key, String(value));
    }
    return this.http.get<{ total: number; items: OutboundMessage[] }>(this.base, { params });
  }

  get(id: string): Observable<OutboundMessageDetail> {
    return this.http.get<OutboundMessageDetail>(`${this.base}/${id}`);
  }

  cancel(id: string): Observable<OutboundMessage & { cancelled: number }> {
    return this.http.post<OutboundMessage & { cancelled: number }>(`${this.base}/${id}/cancel`, {});
  }
}
